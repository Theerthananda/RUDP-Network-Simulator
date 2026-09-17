"""HTTP/SSE bridge for the RUDP simulator."""
from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from transfer.session import RUDPTransferSession, TransferConfig, UDPTransferSession

ROOT = Path(__file__).resolve().parent
TEMP_DIRECTORY, RECEIVED_DIRECTORY = ROOT / "temp_uploads", ROOT / "received_files"
FRONTEND_DIRECTORY = ROOT.parent / "frontend"
HOST, PORT, MAX_UPLOAD_BYTES = "127.0.0.1", 8000, 20 * 1024 * 1024


class TransferManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.subscribers: set = set()
        self.active_thread: threading.Thread | None = None
        self.cancel_event: threading.Event | None = None
        self.session_id: str | None = None

    def broadcast(self, event: dict) -> None:
        event = {"timestamp": time.time(), "session_id": self.session_id, **event}
        encoded = f"data: {json.dumps(event)}\n\n".encode("utf-8")
        with self.lock:
            subscribers = list(self.subscribers)
        for stream in subscribers:
            try:
                stream.write(encoded)
                stream.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                with self.lock:
                    self.subscribers.discard(stream)

    def start(self, source: Path, config: TransferConfig) -> str:
        with self.lock:
            if self.active_thread and self.active_thread.is_alive():
                raise RuntimeError("A transfer is already running")
            self.cancel_event, self.session_id = threading.Event(), uuid.uuid4().hex
            session_id = self.session_id

            def worker() -> None:
                session_class = UDPTransferSession if config.protocol == "UDP" else RUDPTransferSession
                session_class(source, RECEIVED_DIRECTORY, config, self.broadcast, self.cancel_event).run()
                with self.lock:
                    self.active_thread = self.cancel_event = None

            self.active_thread = threading.Thread(target=worker, name="rudp-transfer", daemon=True)
            self.active_thread.start()
            return session_id

    def cancel(self) -> bool:
        with self.lock:
            if not self.active_thread or not self.active_thread.is_alive() or not self.cancel_event:
                return False
            self.cancel_event.set()
            return True


manager = TransferManager()
TEMP_DIRECTORY.mkdir(parents=True, exist_ok=True)
RECEIVED_DIRECTORY.mkdir(parents=True, exist_ok=True)


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *args) -> None:
        return

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _request_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_UPLOAD_BYTES * 2:
            raise ValueError("Request is empty or too large")
        body = json.loads(self.rfile.read(length).decode())
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        return body

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self._static_file(FRONTEND_DIRECTORY / "index.html", "text/html; charset=utf-8")
            return
        if self.path.startswith("/js/") or self.path.startswith("/css/"):
            relative = Path(self.path.lstrip("/"))
            target = (FRONTEND_DIRECTORY / relative).resolve()
            if FRONTEND_DIRECTORY.resolve() not in target.parents:
                self._json(404, {"success": False, "message": "File not found"})
                return
            content_type = "application/javascript; charset=utf-8" if target.suffix == ".js" else "text/css; charset=utf-8"
            self._static_file(target, content_type)
            return
        if self.path != "/api/events":
            self._json(404, {"success": False, "message": "Endpoint not found"})
            return
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        with manager.lock:
            manager.subscribers.add(self.wfile)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                time.sleep(10)
                self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with manager.lock:
                manager.subscribers.discard(self.wfile)

    def _static_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self._json(404, {"success": False, "message": "File not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        if self.path == "/api/transfer":
            self._transfer()
        elif self.path == "/api/transfer/cancel":
            self._json(200, {"success": True, "cancelled": manager.cancel()})
        elif self.path == "/api/event":
            try:
                manager.broadcast(self._request_json())
                self._json(200, {"success": True})
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {"success": False, "message": str(error)})
        else:
            self._json(404, {"success": False, "message": "Endpoint not found"})

    def _transfer(self) -> None:
        try:
            request = self._request_json()
            filename, encoded = Path(str(request.get("filename", ""))).name, request.get("data")
            if not filename or not isinstance(encoded, str):
                raise ValueError("filename and Base64 file data are required")
            payload = base64.b64decode(encoded, validate=True)
            if not payload:
                raise ValueError("Empty files are not supported")
            if len(payload) > MAX_UPLOAD_BYTES:
                raise ValueError("File exceeds the 20 MB upload limit")
            config = TransferConfig.from_request(request.get("config", {}))
            target = TEMP_DIRECTORY / f"{uuid.uuid4().hex}_{filename}"
            target.write_bytes(payload)
            self._json(202, {"success": True, "session_id": manager.start(target, config), "filename": filename})
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"success": False, "message": str(error)})
        except RuntimeError as error:
            self._json(409, {"success": False, "message": str(error)})
        except Exception as error:
            self._json(500, {"success": False, "message": str(error)})


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), BridgeHandler)
    print(f"RUDP Web Bridge running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        manager.cancel()
    finally:
        server.server_close()
