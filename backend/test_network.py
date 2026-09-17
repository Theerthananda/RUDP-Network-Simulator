import sys
from pathlib import Path

# Allow Python to find backend modules
sys.path.append(str(Path(__file__).resolve().parent))

from network.simulator import NetworkSimulator


class TestPacket:

    def __init__(self, sequence_number):
        self.sequence_number = sequence_number


network = NetworkSimulator(
    min_delay=0.1,
    max_delay=1.0
)


for sequence_number in range(1, 6):

    packet = TestPacket(sequence_number)

    network.transmit(packet)


# Give network threads time to finish
import time
time.sleep(2)