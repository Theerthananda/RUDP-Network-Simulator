import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from protocol.packet import Packet


# Create a valid packet
packet = Packet(
    version=1,
    packet_type="DATA",
    sequence_number=1,
    payload="Hello from RUDP"
)

# Serialize the packet
data = packet.serialize()

print("Original serialized packet:")
print(data.decode("utf-8"))


# Corrupt the payload
corrupted_data = data.decode("utf-8").replace(
    "Hello from RUDP",
    "Hello from RUDX"
).encode("utf-8")


print("\nCorrupted serialized packet:")
print(corrupted_data.decode("utf-8"))


# Try to deserialize corrupted packet
print("\nChecking corrupted packet...")

try:

    Packet.deserialize(corrupted_data)

    print("❌ ERROR: Corrupted packet was accepted")

except ValueError as error:

    print(f"❌ CORRUPTION DETECTED: {error}")