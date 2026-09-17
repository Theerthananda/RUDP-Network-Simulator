# Viva notes

**Why UDP?** UDP is lightweight and exposes the reliability work this project demonstrates.

**What makes it reliable?** Sequence numbers, checksums, ACKs, individual timers, retransmissions, a sliding window, ordering, and duplicate handling.

**What is Selective Repeat here?** A lost or unacknowledged DATA sequence is retried individually; acknowledged packets are not resent.

**Why SHA-256?** The 32-byte digest detects changed payload bytes before a receiver stores them; a whole-file SHA-256 verifies final reconstruction.

**How are loss and corruption demonstrated?** The gateway’s simulator applies the configured probabilities on real packet forwarding. Controlled loss drops only the first send of listed DATA sequences.

**How are RTT and throughput calculated?** RTT is sender transmit-to-corresponding-ACK time. Throughput is successfully stored payload bytes divided by transfer duration.

**What happens on Reset?** The bridge signals cancellation, the session closes UDP sockets and delayed work, the browser closes/reopens its old SSE stream, clears metrics/graphs/animations, and can start a new transfer.

**Limitations and future work?** This is a localhost demonstration with an in-memory receiver buffer. Future work could add streaming output, adaptive timeouts, persistent sessions, congestion control, and authenticated peers.
