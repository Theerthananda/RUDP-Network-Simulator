import sys
from pathlib import Path

sys.path.append(
    str(Path(__file__).resolve().parent)
)

from protocol.packet import Packet


# ==============================
# TEXT PAYLOAD TEST
# ==============================

text_packet = Packet(
    version=1,
    packet_type="DATA",
    sequence_number=1,
    payload="Hello from RUDP"
)

serialized = text_packet.serialize()

print("Serialized packet:")
print(serialized)

print("\nOriginal packet:")
print(text_packet)


deserialized = Packet.deserialize(
    serialized
)

print("\nDeserialized packet:")
print(deserialized)


# ==============================
# BINARY PAYLOAD TEST
# ==============================

binary_data = bytes([
    0,
    1,
    2,
    3,
    10,
    13,
    124,
    255
])


binary_packet = Packet(
    version=1,
    packet_type="DATA",
    sequence_number=2,
    payload=binary_data
)


serialized_binary = binary_packet.serialize()

deserialized_binary = Packet.deserialize(
    serialized_binary
)


print("\nBinary packet:")
print(deserialized_binary)


# ==============================
# VERIFY BINARY DATA
# ==============================

if deserialized_binary.payload == binary_data:

    print(
        "\n✅ Binary payload preserved correctly"
    )

else:

    print(
        "\n❌ Binary payload changed"
    )