"""Cancellable Selective Repeat file-transfer session over real UDP sockets."""

from __future__ import annotations

import hashlib
import json
import random
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from protocol.packet import Packet, PacketIntegrityError


DEFAULT_TIMEOUT_SECONDS = 2.0
MAX_RETRIES = 5
CONTROLLED_LOSS_SEQUENCES = {4, 9, 13, 18, 22, 24}


@dataclass(frozen=True)
class TransferConfig:
    protocol: str = "RUDP"
    data_loss: float = 0.0
    ack_loss: float = 0.0
    delay_ms: int = 100
    corruption: float = 0.0
    packet_size: int = 1024
    window_size: int = 3
    send_batch_size: int = 3
    controlled_loss: bool = False
    # Test/demo hook: corrupt each listed DATA sequence once. This is not a UI
    # setting; normal simulation continues to use corruption_rate.
    forced_corruption_sequences: frozenset[int] = field(default_factory=frozenset)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_request(cls, data: dict) -> "TransferConfig":
        def percentage(name: str) -> float:
            value = float(data.get(name, 0))
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
            return value / 100

        protocol = str(data.get("protocol", "RUDP")).upper()
        if protocol not in {"RUDP", "UDP"}:
            raise ValueError("protocol must be RUDP or UDP")
        delay_ms = int(data.get("networkDelay", 100))
        packet_size = int(data.get("packetSize", 1024))
        window_size = int(data.get("windowSize", 3))
        send_batch_size = int(data.get("sendBatchSize", 3))
        if not 0 <= delay_ms <= 10_000:
            raise ValueError("networkDelay must be between 0 and 10000 ms")
        if not 1 <= packet_size <= Packet.MAX_PAYLOAD_SIZE:
            raise ValueError(f"packetSize must be between 1 and {Packet.MAX_PAYLOAD_SIZE}")
        if not 1 <= window_size <= 128:
            raise ValueError("windowSize must be between 1 and 128")
        if not 1 <= send_batch_size <= 128:
            raise ValueError("sendBatchSize must be between 1 and 128")
        return cls(
            protocol=protocol,
            data_loss=percentage("packetLoss"),
            ack_loss=percentage("ackLoss") if protocol == "RUDP" else 0.0,
            delay_ms=delay_ms,
            corruption=percentage("corruptionRate"),
            packet_size=packet_size,
            window_size=window_size,
            send_batch_size=send_batch_size,
            controlled_loss=bool(data.get("controlledLoss", False)),
        )


@dataclass
class TransferMetrics:
    packets_sent: int = 0
    total_transmissions: int = 0
    packets_received: int = 0
    packets_lost: int = 0
    retransmissions: int = 0
    packets_corrupted: int = 0
    checksum_errors: int = 0
    integrity_retransmissions: int = 0
    duplicates: int = 0
    acks_received: int = 0
    acks_lost: int = 0
    received_payload_bytes: int = 0
    rtts_ms: list[float] = field(default_factory=list)
    started_at: float | None = None

    def snapshot(self) -> dict:
        elapsed = max(0.001, time.monotonic() - self.started_at) if self.started_at else 0.0
        return {
            "packets_sent": self.packets_sent,
            "total_transmissions": self.total_transmissions,
            "packets_received": self.packets_received,
            "packets_lost": self.packets_lost,
            "retransmissions": self.retransmissions,
            "packets_corrupted": self.packets_corrupted,
            "checksum_errors": self.checksum_errors,
            "integrity_retransmissions": self.integrity_retransmissions,
            "duplicates": self.duplicates,
            "acks_received": self.acks_received,
            "acks_lost": self.acks_lost,
            "average_rtt_ms": round(sum(self.rtts_ms) / len(self.rtts_ms), 2) if self.rtts_ms else None,
            "throughput_bps": round(self.received_payload_bytes / elapsed, 2),
        }


class TransferCancelled(Exception):
    pass


class RUDPTransferSession:
    """Owns sender, gateway and receiver UDP endpoints for one transfer."""

    def __init__(self, source: Path, output_directory: Path, config: TransferConfig,
                 emit: Callable[[dict], None], cancel_event: threading.Event | None = None):
        self.source = Path(source)
        self.output_directory = Path(output_directory)
        self.config = config
        self.emit_callback = emit
        self.cancel_event = cancel_event or threading.Event()
        self.metrics = TransferMetrics()
        self.metrics_lock = threading.Lock()
        self.forced_loss_done: set[int] = set()
        self.forced_corruption_done: set[int] = set()
        self.received_chunks: dict[int, bytes] = {}
        self.receiver_metadata: dict | None = None
        self.integrity_ok = False
        self.receiver_done = threading.Event()
        self.sockets: list[socket.socket] = []
        self.gateway_thread: threading.Thread | None = None
        self.receiver_thread: threading.Thread | None = None
        self.sender_address: tuple[str, int] | None = None
        self.receiver_address: tuple[str, int] | None = None
        # DATA sequence numbers deliberately damaged in transit and awaiting
        # their individual Selective Repeat timeout/retransmission.
        self.pending_integrity_failures: set[int] = set()

    def _emit(self, event_type: str, message: str, **extra) -> None:
        with self.metrics_lock:
            metrics = self.metrics.snapshot()
        self.emit_callback({"type": event_type, "message": message, "metrics": metrics, **extra})

    def _socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(0.1)
        self.sockets.append(sock)
        return sock

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise TransferCancelled()

    def _close_sockets(self) -> None:
        for sock in self.sockets:
            try:
                sock.close()
            except OSError:
                pass

    def _network_deliver(self, data: bytes, packet: Packet, callback: Callable[[bytes], None]) -> None:
        """Simulate the link after the gateway has received a real UDP datagram."""
        if self.cancel_event.wait(self.config.delay_ms / 1000):
            return
        is_ack = packet.packet_type in {"ACK", "CONNECT_ACK", "FIN_ACK", "NACK"}
        if (self.config.protocol == "RUDP" and packet.packet_type == "DATA"
                and self.config.controlled_loss
                and packet.sequence_number in CONTROLLED_LOSS_SEQUENCES
                and packet.sequence_number not in self.forced_loss_done):
            self.forced_loss_done.add(packet.sequence_number)
            with self.metrics_lock:
                self.metrics.packets_lost += 1
            self._emit("packet_lost", "Controlled first-transmission DATA loss", packet_type="DATA", sequence_number=packet.sequence_number, direction="sender_to_receiver", reason="controlled")
            return
        loss_rate = self.config.ack_loss if self.config.protocol == "RUDP" and is_ack else self.config.data_loss
        if random.random() < loss_rate:
            with self.metrics_lock:
                if is_ack:
                    self.metrics.acks_lost += 1
                elif packet.packet_type == "DATA":
                    self.metrics.packets_lost += 1
            self._emit("packet_lost", "Packet lost by configured network condition", packet_type=packet.packet_type, sequence_number=packet.sequence_number, direction="receiver_to_sender" if is_ack else "sender_to_receiver")
            return
        forced_data_corruption = (
            packet.packet_type == "DATA"
            and packet.sequence_number in self.config.forced_corruption_sequences
            and packet.sequence_number not in self.forced_corruption_done
        )
        if forced_data_corruption:
            self.forced_corruption_done.add(packet.sequence_number)
        if forced_data_corruption or random.random() < self.config.corruption:
            data = Packet.corrupt_for_simulation(data, packet.packet_type)
            with self.metrics_lock:
                self.metrics.packets_corrupted += 1
                if self.config.protocol == "RUDP" and packet.packet_type == "DATA":
                    self.pending_integrity_failures.add(packet.sequence_number)
            self._emit("packet_corrupted", "Packet corrupted by network simulator", packet_type=packet.packet_type, sequence_number=packet.sequence_number, direction="receiver_to_sender" if is_ack else "sender_to_receiver")
        callback(data)
        self._emit("packet_delivered", "Packet delivered by UDP gateway", packet_type=packet.packet_type, sequence_number=packet.sequence_number, direction="receiver_to_sender" if is_ack else "sender_to_receiver")

    def _gateway_loop(self, gateway: socket.socket) -> None:
        self._emit("gateway_started", "UDP gateway started", port=gateway.getsockname()[1])
        while not self.cancel_event.is_set():
            try:
                data, address = gateway.recvfrom(65535)
                packet = Packet.deserialize(data)
            except socket.timeout:
                continue
            except (OSError, ValueError) as error:
                if not self.cancel_event.is_set():
                    self._emit("gateway_rejected_packet", "Gateway rejected malformed packet", error=str(error))
                continue
            if packet.packet_type in {"CONNECT", "DATA", "FIN"}:
                self.sender_address = address
                target = self.receiver_address
            else:
                target = self.sender_address
            if target is None:
                continue
            threading.Thread(target=self._network_deliver, args=(data, packet, lambda payload, target=target: gateway.sendto(payload, target)), daemon=True).start()

    def _send_from_receiver(self, receiver: socket.socket, packet_type: str, sequence_number: int = 0) -> None:
        if self.cancel_event.is_set():
            return
        packet = Packet(Packet.VERSION, packet_type, sequence_number, b"")
        receiver.sendto(packet.serialize(), self.gateway_address)
        self._emit("ack_sent", f"{packet_type} #{sequence_number} sent", packet_type=packet_type, sequence_number=sequence_number, direction="receiver_to_sender")

    def _receiver_loop(self, receiver: socket.socket) -> None:
        self._emit("receiver_started", "RUDP receiver started", port=receiver.getsockname()[1])
        expected_total = None
        fin_completed = False
        while not self.cancel_event.is_set():
            try:
                data, _ = receiver.recvfrom(65535)
                packet = Packet.deserialize(data)
            except socket.timeout:
                continue
            except PacketIntegrityError as error:
                if not self.cancel_event.is_set():
                    packet_type, sequence_number = Packet.identify(data)
                    identity = f"{packet_type} #{sequence_number}" if packet_type is not None else "Packet"
                    with self.metrics_lock:
                        self.metrics.checksum_errors += 1
                    self._emit("checksum_failed", f"{identity} CRC-32 verification failed", packet_type=packet_type, sequence_number=sequence_number, error=str(error))
                    self._emit("packet_rejected", f"{identity} rejected due to integrity error", packet_type=packet_type, sequence_number=sequence_number, error=str(error))
                continue
            except (OSError, ValueError) as error:
                if not self.cancel_event.is_set():
                    self._emit("packet_corrupted", "Receiver rejected corrupted packet", error=str(error))
                continue
            if packet.packet_type == "CONNECT":
                try:
                    metadata = json.loads(packet.payload.decode("utf-8"))
                    required = {"filename", "file_size", "total_chunks", "file_checksum"}
                    if not required.issubset(metadata) or int(metadata["total_chunks"]) < 0:
                        raise ValueError("missing or invalid transfer metadata")
                    self.receiver_metadata = metadata
                    expected_total = int(metadata["total_chunks"])
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    self._emit("transfer_failed", "Receiver rejected CONNECT metadata", error=str(error))
                    continue
                self._emit("metadata_received", "Receiver accepted file metadata", filename=metadata["filename"], file_size=metadata["file_size"], total_packets=expected_total)
                self._send_from_receiver(receiver, "CONNECT_ACK")
                self._emit("connection_established", "RUDP connection established")
            elif packet.packet_type == "DATA" and self.receiver_metadata is not None:
                if not 1 <= packet.sequence_number <= expected_total:
                    continue
                if packet.sequence_number in self.received_chunks:
                    with self.metrics_lock:
                        self.metrics.duplicates += 1
                    self._emit("duplicate_packet", "Duplicate DATA packet received", packet_type="DATA", sequence_number=packet.sequence_number)
                else:
                    self.received_chunks[packet.sequence_number] = packet.payload
                    with self.metrics_lock:
                        self.metrics.packets_received += 1
                        self.metrics.received_payload_bytes += len(packet.payload)
                    self._emit("packet_received", f"DATA #{packet.sequence_number} received and stored", packet_type="DATA", sequence_number=packet.sequence_number, payload_size=len(packet.payload), received_packets=len(self.received_chunks), total_packets=expected_total)
                self._send_from_receiver(receiver, "ACK", packet.sequence_number)
            elif packet.packet_type == "FIN" and self.receiver_metadata is not None:
                if fin_completed:
                    # A FIN_ACK may have been lost; acknowledge the sender's FIN retry.
                    self._send_from_receiver(receiver, "FIN_ACK")
                    continue
                if len(self.received_chunks) != expected_total:
                    self._emit("transfer_failed", "FIN received before all DATA packets", received_packets=len(self.received_chunks), total_packets=expected_total)
                    continue
                self._emit("fin_received", "Receiver received FIN", packet_type="FIN")
                self._write_and_verify_file()
                self._send_from_receiver(receiver, "FIN_ACK")
                self.receiver_done.set()
                fin_completed = True

    def _write_and_verify_file(self) -> None:
        assert self.receiver_metadata is not None
        self.output_directory.mkdir(parents=True, exist_ok=True)
        filename = Path(str(self.receiver_metadata["filename"])).name
        output = self.output_directory / filename
        payload = b"".join(self.received_chunks[number] for number in sorted(self.received_chunks))
        output.write_bytes(payload)
        expected_size = int(self.receiver_metadata["file_size"])
        expected_hash = str(self.receiver_metadata["file_checksum"])
        actual_hash = hashlib.sha256(payload).hexdigest()
        self.integrity_ok = len(payload) == expected_size and actual_hash == expected_hash
        self._emit("checksum_calculated", "Receiver calculated file SHA-256", filename=filename, actual_checksum=actual_hash)
        self._emit("integrity_verified" if self.integrity_ok else "integrity_failed", "File integrity verified" if self.integrity_ok else "File integrity verification failed", filename=filename, expected_size=expected_size, received_size=len(payload), expected_checksum=expected_hash, actual_checksum=actual_hash)

    def _await_control_packet(self, sender: socket.socket, packet_type: str, sequence_number: int, payload: bytes = b"") -> None:
        packet = Packet(Packet.VERSION, packet_type, sequence_number, payload)
        expected = "CONNECT_ACK" if packet_type == "CONNECT" else "FIN_ACK"
        for attempt in range(1, MAX_RETRIES + 1):
            self._check_cancelled()
            sender.sendto(packet.serialize(), self.gateway_address)
            self._emit("packet_sent", f"{packet_type} sent", packet_type=packet_type, sequence_number=sequence_number, attempt=attempt)
            deadline = time.monotonic() + self.config.timeout_seconds
            while time.monotonic() < deadline:
                self._check_cancelled()
                try:
                    data, _ = sender.recvfrom(65535)
                    response = Packet.deserialize(data)
                    if response.packet_type == expected:
                        self._emit("ack_received", f"{expected} received", packet_type=expected, sequence_number=sequence_number)
                        return
                except socket.timeout:
                    pass
                except PacketIntegrityError as error:
                    with self.metrics_lock:
                        self.metrics.checksum_errors += 1
                    self._emit("checksum_failed", "Sender rejected control response with invalid CRC-32", packet_type=expected, error=str(error))
                except ValueError as error:
                    self._emit("packet_corrupted", "Sender rejected corrupted control response", packet_type=expected, error=str(error))
            self._emit("timeout", f"{packet_type} timed out", packet_type=packet_type, sequence_number=sequence_number, attempt=attempt)
        raise RuntimeError(f"{packet_type} failed after {MAX_RETRIES} attempts")

    def _send_data(self, sender: socket.socket, chunks: list[bytes]) -> None:
        total = len(chunks)
        base, next_sequence = 1, 1
        acked: set[int] = set()
        sent_at: dict[int, float] = {}
        retries: dict[int, int] = {}
        while base <= total:
            self._check_cancelled()
            while next_sequence <= total and next_sequence < base + self.config.window_size:
                sequence = next_sequence
                sender.sendto(Packet(Packet.VERSION, "DATA", sequence, chunks[sequence - 1]).serialize(), self.gateway_address)
                sent_at[sequence] = time.monotonic()
                retries[sequence] = 0
                with self.metrics_lock:
                    self.metrics.packets_sent += 1
                    self.metrics.total_transmissions += 1
                self._emit("packet_sent", "DATA sent", packet_type="DATA", sequence_number=sequence, payload_size=len(chunks[sequence - 1]), retransmission=False, retry=0)
                next_sequence += 1
            try:
                data, _ = sender.recvfrom(65535)
                response = Packet.deserialize(data)
                if response.packet_type == "ACK" and response.sequence_number in sent_at:
                    sequence = response.sequence_number
                    if sequence not in acked:
                        acked.add(sequence)
                        with self.metrics_lock:
                            self.metrics.acks_received += 1
                            self.metrics.rtts_ms.append((time.monotonic() - sent_at[sequence]) * 1000)
                        self._emit("ack_received", f"ACK #{sequence} received", packet_type="ACK", sequence_number=sequence)
                        while base in acked:
                            base += 1
                        self._emit("window_moved", "Selective Repeat window advanced", base=base, window_size=self.config.window_size)
            except socket.timeout:
                pass
            except PacketIntegrityError as error:
                with self.metrics_lock:
                    self.metrics.checksum_errors += 1
                self._emit("checksum_failed", "Sender rejected ACK with invalid CRC-32", packet_type="ACK", error=str(error))
            except ValueError as error:
                self._emit("packet_corrupted", "Sender rejected corrupted ACK", packet_type="ACK", error=str(error))
            now = time.monotonic()
            for sequence in range(base, next_sequence):
                if sequence in acked or now - sent_at[sequence] < self.config.timeout_seconds:
                    continue
                retries[sequence] += 1
                if retries[sequence] > MAX_RETRIES:
                    raise RuntimeError(f"DATA #{sequence} failed after {MAX_RETRIES} retries")
                self._emit("timeout", f"DATA #{sequence} acknowledgement timed out", packet_type="DATA", sequence_number=sequence, retry=retries[sequence])
                sender.sendto(Packet(Packet.VERSION, "DATA", sequence, chunks[sequence - 1]).serialize(), self.gateway_address)
                sent_at[sequence] = time.monotonic()
                with self.metrics_lock:
                    self.metrics.total_transmissions += 1
                    self.metrics.retransmissions += 1
                    integrity_retry = sequence in self.pending_integrity_failures
                    if integrity_retry:
                        self.metrics.integrity_retransmissions += 1
                        self.pending_integrity_failures.discard(sequence)
                self._emit("retransmission", f"DATA #{sequence} retransmitted after integrity failure" if integrity_retry else f"DATA #{sequence} retransmitted", packet_type="DATA", sequence_number=sequence, payload_size=len(chunks[sequence - 1]), retransmission=True, retry=retries[sequence], reason="integrity_failure" if integrity_retry else "timeout")

    def run(self) -> dict:
        sender = gateway = receiver = None
        try:
            raw = self.source.read_bytes()
            chunks = [raw[index:index + self.config.packet_size] for index in range(0, len(raw), self.config.packet_size)] or [b""]
            checksum = hashlib.sha256(raw).hexdigest()
            with self.metrics_lock:
                self.metrics.started_at = time.monotonic()
            sender, gateway, receiver = self._socket(), self._socket(), self._socket()
            self.gateway_address = gateway.getsockname()
            self.receiver_address = receiver.getsockname()
            self.gateway_thread = threading.Thread(target=self._gateway_loop, args=(gateway,), daemon=True)
            self.receiver_thread = threading.Thread(target=self._receiver_loop, args=(receiver,), daemon=True)
            self.gateway_thread.start()
            self.receiver_thread.start()
            self._emit("transfer_started", "Real RUDP transfer started", filename=self.source.name, file_size=len(raw), total_packets=len(chunks), window_size=self.config.window_size)
            metadata = json.dumps({"filename": self.source.name, "file_size": len(raw), "total_chunks": len(chunks), "file_checksum": checksum}).encode()
            self._await_control_packet(sender, "CONNECT", 0, metadata)
            self._send_data(sender, chunks)
            self._await_control_packet(sender, "FIN", 0)
            if not self.receiver_done.wait(self.config.timeout_seconds) or not self.integrity_ok:
                raise RuntimeError("Receiver did not complete verified file reconstruction")
            self._emit("transfer_complete", "RUDP transfer completed and integrity was verified", filename=self.source.name, file_size=len(raw), total_packets=len(chunks), integrity_verified=True)
            return {"success": True, "metrics": self.metrics.snapshot()}
        except TransferCancelled:
            self._emit("transfer_cancelled", "Transfer cancelled and UDP session closed")
            return {"success": False, "cancelled": True}
        except Exception as error:
            self._emit("transfer_failed", "RUDP transfer failed", error=str(error))
            return {"success": False, "error": str(error)}
        finally:
            self.cancel_event.set()
            self._close_sockets()
            self._emit("session_closed", "UDP sender, gateway and receiver session closed")


class UDPTransferSession(RUDPTransferSession):
    """Unreliable UDP transfer using the existing gateway network conditions.

    This deliberately has no acknowledgements, timers, retransmissions, or
    control packets.  Its batch size only yields between sender bursts.
    """

    def _receiver_loop(self, receiver: socket.socket) -> None:
        self._emit("receiver_started", "UDP receiver started", port=receiver.getsockname()[1])
        while not self.cancel_event.is_set():
            try:
                data, _ = receiver.recvfrom(65535)
                packet = Packet.deserialize(data)
            except socket.timeout:
                continue
            except (OSError, ValueError) as error:
                if not self.cancel_event.is_set():
                    self._emit("packet_corrupted", "UDP receiver rejected corrupted packet", error=str(error))
                continue
            if packet.packet_type != "DATA" or not 1 <= packet.sequence_number <= self.udp_total_packets:
                continue
            if packet.sequence_number in self.received_chunks:
                with self.metrics_lock:
                    self.metrics.duplicates += 1
                continue
            self.received_chunks[packet.sequence_number] = packet.payload
            with self.metrics_lock:
                self.metrics.packets_received += 1
                self.metrics.received_payload_bytes += len(packet.payload)
            self._emit("packet_received", "UDP receiver stored DATA packet", packet_type="DATA", sequence_number=packet.sequence_number, payload_size=len(packet.payload), received_packets=len(self.received_chunks), total_packets=self.udp_total_packets)
            if len(self.received_chunks) == self.udp_total_packets:
                self.udp_receive_complete.set()

    def run(self) -> dict:
        sender = gateway = receiver = None
        try:
            raw = self.source.read_bytes()
            chunks = [raw[index:index + self.config.packet_size] for index in range(0, len(raw), self.config.packet_size)] or [b""]
            self.udp_total_packets = len(chunks)
            self.udp_receive_complete = threading.Event()
            with self.metrics_lock:
                self.metrics.started_at = time.monotonic()
            sender, gateway, receiver = self._socket(), self._socket(), self._socket()
            # A UDP burst can otherwise overflow localhost socket queues before
            # the receiver thread drains them.  This is transport buffering, not
            # simulated packet loss.
            gateway.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            self.gateway_address = gateway.getsockname()
            self.receiver_address = receiver.getsockname()
            self.gateway_thread = threading.Thread(target=self._gateway_loop, args=(gateway,), daemon=True)
            self.receiver_thread = threading.Thread(target=self._receiver_loop, args=(receiver,), daemon=True)
            self.gateway_thread.start()
            self.receiver_thread.start()
            self._emit("transfer_started", "UDP transfer started", filename=self.source.name, file_size=len(raw), total_packets=len(chunks), send_batch_size=self.config.send_batch_size)
            for start in range(0, len(chunks), self.config.send_batch_size):
                self._check_cancelled()
                for offset, chunk in enumerate(chunks[start:start + self.config.send_batch_size], start + 1):
                    sender.sendto(Packet(Packet.VERSION, "DATA", offset, chunk).serialize(), self.gateway_address)
                    with self.metrics_lock:
                        self.metrics.packets_sent += 1
                        self.metrics.total_transmissions += 1
                    self._emit("packet_sent", "UDP DATA sent", packet_type="DATA", sequence_number=offset, payload_size=len(chunk), retransmission=False)
                # Pace bursts so localhost queues can be drained without adding
                # reliability behavior to UDP.
                if self.cancel_event.wait(0.002):
                    raise TransferCancelled()
            # Finish as soon as every expected packet is received.  With actual
            # configured loss/corruption, stop after a bounded delivery grace.
            receive_timeout = max(1.0, self.config.delay_ms / 1000 * 2 + 0.5)
            if self.udp_receive_complete.wait(receive_timeout):
                complete = True
            elif self.cancel_event.is_set():
                raise TransferCancelled()
            else:
                complete = False
            if complete:
                self.output_directory.mkdir(parents=True, exist_ok=True)
                (self.output_directory / self.source.name).write_bytes(
                    b"".join(self.received_chunks[number] for number in range(1, len(chunks) + 1))
                )
            self._emit("transfer_complete", "UDP transfer completed" if complete else "UDP transfer completed with missing packets", filename=self.source.name, file_size=len(raw), total_packets=len(chunks), integrity_verified=complete)
            return {"success": True, "metrics": self.metrics.snapshot(), "integrity_verified": complete}
        except TransferCancelled:
            self._emit("transfer_cancelled", "UDP transfer cancelled and session closed")
            return {"success": False, "cancelled": True}
        except Exception as error:
            self._emit("transfer_failed", "UDP transfer failed", error=str(error))
            return {"success": False, "error": str(error)}
        finally:
            self.cancel_event.set()
            self._close_sockets()
            self._emit("session_closed", "UDP sender, gateway and receiver session closed")
