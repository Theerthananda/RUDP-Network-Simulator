import struct
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from checksum import calculate_checksum, verify_checksum


class PacketIntegrityError(ValueError):
    """Raised when a packet's received CRC-32 does not match its contents."""


class Packet:
    """Binary RUDP packet with CRC-32 over framing fields and payload."""

    # Version (1), type (1), sequence (4), payload length (4), CRC-32 (4).
    HEADER_FORMAT = "!BBIII"
    PROTECTED_HEADER_FORMAT = "!BBII"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    VERSION = 1
    MAX_PAYLOAD_SIZE = 60 * 1024

    PACKET_TYPES = {
        "CONNECT": 1, "CONNECT_ACK": 2, "DATA": 3, "ACK": 4,
        "NACK": 5, "FIN": 6, "FIN_ACK": 7, "ERROR": 8,
    }
    PACKET_TYPE_NAMES = {value: key for key, value in PACKET_TYPES.items()}

    def __init__(self, version, packet_type, sequence_number, payload):
        if version != self.VERSION:
            raise ValueError("Unsupported packet version")
        if packet_type not in self.PACKET_TYPES:
            raise ValueError("Unknown packet type")
        if not isinstance(sequence_number, int) or not 0 <= sequence_number <= 0xFFFFFFFF:
            raise ValueError("Invalid sequence number")
        self.version = version
        self.packet_type = packet_type
        self.sequence_number = sequence_number
        self.payload = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        self.length = len(self.payload)
        if self.length > self.MAX_PAYLOAD_SIZE:
            raise ValueError("Payload exceeds maximum packet size")
        self.checksum = calculate_checksum(self._protected_bytes())

    def _protected_bytes(self):
        return struct.pack(
            self.PROTECTED_HEADER_FORMAT, self.version,
            self.PACKET_TYPES[self.packet_type], self.sequence_number, self.length,
        ) + self.payload

    def serialize(self):
        return struct.pack(
            self.HEADER_FORMAT, self.version, self.PACKET_TYPES[self.packet_type],
            self.sequence_number, self.length, self.checksum,
        ) + self.payload

    @staticmethod
    def deserialize(data):
        if len(data) < Packet.HEADER_SIZE:
            raise ValueError("Packet corrupted: data is smaller than header")
        version, packet_type_code, sequence_number, length, checksum = struct.unpack(
            Packet.HEADER_FORMAT, data[:Packet.HEADER_SIZE]
        )
        payload = data[Packet.HEADER_SIZE:]
        protected = struct.pack(
            Packet.PROTECTED_HEADER_FORMAT, version, packet_type_code, sequence_number, length,
        ) + payload
        # Verify before interpreting version/type so altered framing is an
        # integrity failure, rather than a valid but changed packet.
        if not verify_checksum(protected, checksum):
            raise PacketIntegrityError("Packet corrupted: CRC-32 verification failed")
        if len(payload) != length:
            raise ValueError("Packet corrupted: payload length mismatch")
        if version != Packet.VERSION:
            raise ValueError("Unsupported packet version")
        if packet_type_code not in Packet.PACKET_TYPE_NAMES:
            raise ValueError("Unknown packet type")
        if length > Packet.MAX_PAYLOAD_SIZE:
            raise ValueError("Packet payload exceeds maximum size")
        return Packet(version, Packet.PACKET_TYPE_NAMES[packet_type_code], sequence_number, payload)

    @staticmethod
    def corrupt_for_simulation(data, packet_type):
        """Flip one CRC-protected bit without recalculating the CRC.

        DATA payload is preferred so its sequence remains available for the
        receiver event log and Selective Repeat retransmission visualization.
        """
        mutable = bytearray(data)
        if not mutable:
            return data
        index = Packet.HEADER_SIZE if packet_type == "DATA" and len(mutable) > Packet.HEADER_SIZE else 0
        mutable[index] ^= 0x01
        return bytes(mutable)

    @staticmethod
    def identify(data):
        """Best-effort identity for logging a rejected wire packet."""
        if len(data) < Packet.HEADER_SIZE:
            return None, None
        _, type_code, sequence_number, _, _ = struct.unpack(
            Packet.HEADER_FORMAT, data[:Packet.HEADER_SIZE]
        )
        return Packet.PACKET_TYPE_NAMES.get(type_code), sequence_number

    def __repr__(self):
        return (f"Packet(version={self.version}, type={self.packet_type}, "
                f"sequence={self.sequence_number}, length={self.length}, "
                f"crc32=0x{self.checksum:08x})")
