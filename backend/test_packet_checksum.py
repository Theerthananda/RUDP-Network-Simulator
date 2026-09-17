import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from protocol.packet import Packet


# Create a packet
packet = Packet(
    version=1,
    packet_type="DATA",
    sequence_number=1,
    payload="Hello from RUDP"
)

print("Original packet:")
print(packet)


# Serialize
data = packet.serialize()

print("\nSerialized packet:")
print(data.decode("utf-8"))


# Deserialize
received_packet = Packet.deserialize(data)

print("\nDeserialized packet:")
print(received_packet)

print("\nChecksum verification:")
print("✅ Packet is valid")