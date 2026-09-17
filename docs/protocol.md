# Protocol

Packets use network byte order and `!BBII32s`: version, packet type, sequence, payload length, and the 32-byte SHA-256 digest of the payload. Valid packet types are CONNECT, CONNECT_ACK, DATA, ACK, NACK, FIN, FIN_ACK, and ERROR.

CONNECT carries safe file metadata (name, byte size, chunk count, and file SHA-256). DATA sequences begin at 1. The sender may have `window_size` unacknowledged DATA packets in flight. Each packet is independently timed; only timed-out unacknowledged packets retransmit.

The receiver stores each sequence once, ACKs valid duplicates again, and reassembles chunks in sequence order. Corrupted packets fail checksum validation and are not accepted. Completion requires all chunks, matching output size and SHA-256, FIN reception, and a FIN_ACK received by the sender. The receiver remains available after FIN to resend FIN_ACK if that acknowledgement was lost.
