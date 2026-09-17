# Architecture

The web bridge serves the frontend and exposes `POST /api/transfer`, `GET /api/events`, and `POST /api/transfer/cancel`. It starts one cancellable `RUDPTransferSession` per upload.

`Frontend → Web Bridge → Sender UDP socket → Gateway UDP socket → Network simulator → Receiver UDP socket`

ACKs and FIN_ACKs return through the same gateway and simulator in reverse. The gateway receives and forwards actual localhost UDP datagrams; the simulator sits on that forwarding path and can delay, drop, or corrupt them. RUDP packets carry CRC-32 over their interpretable header fields and payload; a simulated corruption flips protected bytes without updating that CRC, so the receiver rejects the datagram and Selective Repeat times out only that sequence. SHA-256 remains the separate final reconstructed-file verification. The session emits authoritative events and metric snapshots to the bridge SSE stream. The frontend uses those events for its log, visualization, metrics, and three graphs.

Cancellation sets the session cancellation event and closes all three UDP sockets. It also stops delayed deliveries, preventing packets from leaking into a later transfer.
