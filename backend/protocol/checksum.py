"""Non-cryptographic integrity helpers used by the RUDP packet format."""

import zlib


def calculate_checksum(data):
    """
    Calculate an unsigned IEEE CRC-32 for packet data.

    CRC-32 detects accidental wire corruption. It is intentionally separate
    from the SHA-256 digest used to verify the complete reconstructed file.
    """
    return zlib.crc32(data) & 0xFFFFFFFF


def verify_checksum(data, expected_checksum):
    """
    Verify whether the data matches the expected checksum.
    """
    return calculate_checksum(data) == expected_checksum
