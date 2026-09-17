 # RUDP — Reliable UDP Data Transfer & Network Simulator

This MSc mini project demonstrates a custom reliable data-transfer protocol implemented over UDP. It transfers a real uploaded file through localhost UDP sender, gateway, network simulator, and receiver components.

## Features

- Binary packets (`!BBII32s`) with SHA-256 payload checksums.
- Selective Repeat-style sliding window, sequence numbers, ACKs, timeouts, retries, ordering, and duplicate handling.
- Configurable DATA loss, ACK loss, one-way network delay, packet corruption, packet size, and window size.
- Optional controlled first-transmission DATA loss for sequences 4, 9, 13, 18, 22, and 24 (available in API/test configuration).
- Real received-file size and SHA-256 verification before completion.
- SSE events drive the browser animations, metrics, and three graphs; the browser does not fabricate transfer data.
- Reset cancels the active UDP session and clears browser transfer state.

## Run

Requires Python 3.10+; there are no third-party runtime dependencies.

```powershell
python backend\web_bridge.py
```

Open `http://127.0.0.1:8000/`, choose a file, set network conditions, and select **Start Transfer**. The reconstructed file is saved in `backend/received_files`.

## Packet and transfer lifecycle

Each packet has version (1 byte), type (1 byte), sequence number (4 bytes), payload length (4 bytes), SHA-256 payload checksum (32 bytes), and payload. Sender and receiver exchange CONNECT/CONNECT_ACK, DATA/ACK, then FIN/FIN_ACK through the UDP gateway. The gateway applies configured loss, delay, and corruption before forwarding each real datagram.

## Verification

```powershell
python -m unittest discover -s backend\tests -v
```

The suite covers packet corruption detection, binary transfer, controlled loss and retransmission, ACK-loss duplicate recovery, corruption recovery, and cancellation.

## Limitations

This is a localhost educational simulator, not a replacement for TCP. It uses one receiver session per transfer and an in-memory receiver buffer, so very large files are constrained by process memory and the configured upload limit.
