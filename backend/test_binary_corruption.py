import sys
from pathlib import Path

sys.path.append(
    str(Path(__file__).resolve().parent)
)

from protocol.packet import Packet


data = bytes([
    0,
    1,
    2,
    3,
    10,
    13,
    124,
    255
])


packet = Packet(
    version=1,
    packet_type="DATA",
    sequence_number=1,
    payload=data
)


serialized = bytearray(
    packet.serialize()
)


# Corrupt one payload byte

serialized[-1] ^= 1


try:

    Packet.deserialize(
        bytes(serialized)
    )

    print(
        "❌ ERROR: Corruption was not detected"
    )

except ValueError as error:

    print(
        f"✅ Corruption detected: {error}"
    )