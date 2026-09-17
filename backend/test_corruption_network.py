import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from protocol.packet import Packet
from network.simulator import NetworkSimulator


network = NetworkSimulator(
    min_delay=0.1,
    max_delay=0.5,
    corruption_rate=0.50
)


for sequence_number in range(1, 11):

    packet = Packet(
        version=1,
        packet_type="DATA",
        sequence_number=sequence_number,
        payload=f"Hello from packet {sequence_number}"
    )

    network.transmit(packet)


# Give all network threads time to finish
time.sleep(1)