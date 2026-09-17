import random
import threading
import time
import json
import urllib.request


# ==============================
# LIVE EVENT BRIDGE
# ==============================

EVENT_ENDPOINT = (
    "http://127.0.0.1:8000/api/event"
)


def report_event(
    event_type,
    message,
    packet_type=None,
    sequence_number=None,
    direction=None,
    **extra
):
    """
    Send a network event to the Web Bridge.

    Event reporting must never interrupt
    the actual RUDP network simulation.
    """

    event = {
        "type": event_type,
        "message": message,
    }

    if packet_type is not None:
        event["packet_type"] = packet_type

    if sequence_number is not None:
        event["sequence_number"] = (
            sequence_number
        )

    if direction is not None:
        event["direction"] = direction

    event.update(extra)

    try:

        request_data = json.dumps(
            event
        ).encode("utf-8")

        request = urllib.request.Request(
            EVENT_ENDPOINT,
            data=request_data,
            headers={
                "Content-Type":
                    "application/json"
            },
            method="POST"
        )

        with urllib.request.urlopen(
            request,
            timeout=0.2
        ):
            pass

    except Exception:
        # Live browser reporting must NEVER
        # break the actual network transfer.
        pass


# ==============================
# NETWORK SIMULATOR
# ==============================

class NetworkSimulator:

    def __init__(
        self,
        min_delay=0.1,
        max_delay=0.5,
        loss_rate=0.0,
        corruption_rate=0.0,
        forced_loss_sequences=None
    ):

        self.min_delay = min_delay

        self.max_delay = max_delay

        self.loss_rate = loss_rate

        self.corruption_rate = (
            corruption_rate
        )

        # Packets that should be deliberately lost.
        #
        # Example:
        # {2} means DATA #2 will be lost.

        self.forced_loss_sequences = (
            forced_loss_sequences or set()
        )

        # Remember packets already deliberately
        # lost.
        #
        # This makes forced loss happen only once.

        self.forced_loss_done = set()


    # ==============================
    # TRANSMIT PACKET
    # ==============================

    def transmit(
        self,
        data,
        packet,
        deliver_callback
    ):

        delay = random.uniform(
            self.min_delay,
            self.max_delay
        )

        thread = threading.Thread(
            target=self._deliver_packet,
            args=(
                data,
                packet,
                delay,
                deliver_callback
            )
        )

        thread.start()


    # ==============================
    # DELIVER PACKET
    # ==============================

    def _deliver_packet(
        self,
        data,
        packet,
        delay,
        deliver_callback
    ):

        packet_type = (
            packet.packet_type
        )

        sequence_number = (
            packet.sequence_number
        )


        # ==============================
        # NETWORK DELAY
        # ==============================

        print(
            f"🌐 Network: "
            f"{packet_type} "
            f"#{sequence_number} "
            f"delayed by {delay:.2f}s"
        )

        report_event(
            "network_delay",
            (
                f"Network delaying "
                f"{packet_type} "
                f"#{sequence_number} "
                f"by {delay:.2f}s"
            ),
            packet_type=packet_type,
            sequence_number=sequence_number,
            delay=delay
        )


        time.sleep(delay)


        # ==============================
        # FORCED DATA LOSS
        # ==============================

        if (
            packet_type == "DATA"
            and sequence_number
            in self.forced_loss_sequences
            and sequence_number
            not in self.forced_loss_done
        ):

            self.forced_loss_done.add(
                sequence_number
            )

            message = (
                f"❌ FORCED NETWORK LOSS: "
                f"{packet_type} "
                f"#{sequence_number}"
            )

            print(
                f"{message}\n"
            )

            report_event(
                "packet_lost",
                message,
                packet_type=packet_type,
                sequence_number=sequence_number,
                loss_type="forced"
            )

            return


        # ==============================
        # RANDOM PACKET LOSS
        # ==============================

        if (
            random.random()
            < self.loss_rate
        ):

            message = (
                f"❌ NETWORK LOSS: "
                f"{packet_type} "
                f"#{sequence_number}"
            )

            print(
                f"{message}\n"
            )

            report_event(
                "packet_lost",
                message,
                packet_type=packet_type,
                sequence_number=sequence_number,
                loss_type="random"
            )

            return


        # ==============================
        # PACKET CORRUPTION
        # ==============================

        if (
            random.random()
            < self.corruption_rate
        ):

            corrupted_data = (
                self._corrupt_data(
                    data
                )
            )

            message = (
                f"⚠️ NETWORK CORRUPTION: "
                f"{packet_type} "
                f"#{sequence_number}"
            )

            print(
                f"{message}\n"
            )

            report_event(
                "packet_corrupted",
                message,
                packet_type=packet_type,
                sequence_number=sequence_number
            )

            deliver_callback(
                corrupted_data
            )

            return


        # ==============================
        # NORMAL DELIVERY
        # ==============================

        deliver_callback(
            data
        )

        message = (
            f"📦 Network delivered "
            f"{packet_type} "
            f"#{sequence_number}"
        )

        print(
            f"{message}\n"
        )

        report_event(
            "packet_delivered",
            message,
            packet_type=packet_type,
            sequence_number=sequence_number
        )


    # ==============================
    # CORRUPT DATA
    # ==============================

    def _corrupt_data(
        self,
        data
    ):

        data = bytearray(
            data
        )

        if len(data) == 0:
            return bytes(data)

        index = random.randrange(
            len(data)
        )

        data[index] ^= 1

        return bytes(data)