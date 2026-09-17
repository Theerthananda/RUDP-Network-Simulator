# Protocol

Packets use network byte order and `!BBIII`: version, packet type, sequence, payload length, and a 4-byte CRC-32. CRC-32 is calculated over version, packet type, sequence, payload length, and payload (never the CRC field itself). Valid packet types are CONNECT, CONNECT_ACK, DATA, ACK, NACK, FIN, FIN_ACK, and ERROR.

CONNECT carries safe file metadata (name, byte size, chunk count, and file SHA-256). DATA sequences begin at 1. The sender may have `window_size` unacknowledged DATA packets in flight. Each packet is independently timed; only timed-out unacknowledged packets retransmit.

The receiver stores each sequence once, ACKs valid duplicates again, and reassembles chunks in sequence order. Every RUDP packet is CRC-32-validated even when simulated corruption is disabled. Corrupted packets fail validation, are rejected without a successful ACK, and their individual Selective Repeat timeout triggers retransmission. The final reconstructed file is independently checked with SHA-256. Completion requires all chunks, matching output size and SHA-256, FIN reception, and a FIN_ACK received by the sender. The receiver remains available after FIN to resend FIN_ACK if that acknowledgement was lost.
