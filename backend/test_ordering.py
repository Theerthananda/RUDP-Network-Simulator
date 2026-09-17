import time


class Packet:
    def __init__(self, sequence_number):
        self.sequence_number = sequence_number


# Simulated arrival order from our network simulator
arrival_order = [1, 4, 5, 3, 2]


expected_sequence = 1
buffer = {}


print("Receiver ordering test started...\n")


for sequence_number in arrival_order:

    packet = Packet(sequence_number)

    print(f"📦 Received packet #{sequence_number}")

    # Packet arrived in the correct order
    if sequence_number == expected_sequence:

        print(
            f"✅ Packet #{sequence_number} accepted"
        )

        expected_sequence += 1

        # Check whether the next expected packets
        # are already waiting in the buffer
        while expected_sequence in buffer:

            print(
                f"📦 Buffered packet #{expected_sequence} "
                f"is now accepted"
            )

            del buffer[expected_sequence]

            expected_sequence += 1

    # Packet arrived too early
    elif sequence_number > expected_sequence:

        buffer[sequence_number] = packet

        print(
            f"⚠️ Out of order: Packet #{sequence_number} "
            f"expected #{expected_sequence}"
        )

        print(
            f"📦 Packet #{sequence_number} stored in buffer"
        )

    # Packet arrived too late / duplicate
    else:

        print(
            f"⚠️ Duplicate or already processed: "
            f"Packet #{sequence_number}"
        )

    print()


print("========== RESULT ==========")
print(f"Next expected packet: #{expected_sequence}")

if buffer:
    print(
        f"Packets still in buffer: "
        f"{list(buffer.keys())}"
    )
else:
    print("Buffer is empty ✅")

print("\nOrdering test completed.")