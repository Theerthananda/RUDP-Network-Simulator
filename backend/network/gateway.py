import socket
import sys
import json
import urllib.request

from pathlib import Path


sys.path.append(
    str(Path(__file__).resolve().parents[1])
)


from protocol.packet import Packet
from network.simulator import NetworkSimulator


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
    **extra
):
    """
    Send a live gateway event to the Web Bridge.

    Event reporting must never interrupt
    the actual RUDP transfer.
    """

    event = {
        "type": event_type,
        "message": message,
    }


    if packet_type is not None:

        event["packet_type"] = (
            packet_type
        )


    if sequence_number is not None:

        event["sequence_number"] = (
            sequence_number
        )


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

        # Live event reporting must NEVER
        # break the actual RUDP network.
        pass


# ==============================
# CONFIGURATION
# ==============================

LISTEN_HOST = "127.0.0.1"

LISTEN_PORT = 6000

RECEIVER_HOST = "127.0.0.1"

RECEIVER_PORT = 5000


# ==============================
# NETWORK SIMULATOR
# ==============================

network = NetworkSimulator(
    min_delay=0.1,
    max_delay=0.5,
    loss_rate=0.0,
    corruption_rate=0.0,
    forced_loss_sequences={
        4,
        9,
        13,
        18,
        22,
        24
    }
)


# ==============================
# CREATE GATEWAY SOCKET
# ==============================

gateway_socket = socket.socket(
    socket.AF_INET,
    socket.SOCK_DGRAM
)


gateway_socket.bind(
    (
        LISTEN_HOST,
        LISTEN_PORT
    )
)


sender_address = None


# ==============================
# GATEWAY STATUS
# ==============================

print(
    f"Network Gateway running on "
    f"{LISTEN_HOST}:{LISTEN_PORT}"
)

print(
    f"Forwarding to receiver "
    f"{RECEIVER_HOST}:{RECEIVER_PORT}"
)

print(
    "Forced DATA loss sequences: "
    "{4, 9, 13, 18, 22, 24} (once)"
)

print()


report_event(
    "gateway_started",
    (
        f"Network Gateway running on "
        f"{LISTEN_HOST}:{LISTEN_PORT}"
    ),
    host=LISTEN_HOST,
    port=LISTEN_PORT,
    receiver_host=RECEIVER_HOST,
    receiver_port=RECEIVER_PORT
)


# ==============================
# DELIVERY FUNCTIONS
# ==============================

def deliver_to_receiver(data):

    gateway_socket.sendto(
        data,
        (
            RECEIVER_HOST,
            RECEIVER_PORT
        )
    )


def deliver_to_sender(data):

    if sender_address is not None:

        gateway_socket.sendto(
            data,
            sender_address
        )


# ==============================
# MAIN GATEWAY LOOP
# ==============================

while True:

    data, source_address = (
        gateway_socket.recvfrom(
            65535
        )
    )


    # ==============================
    # DECODE PACKET
    # ==============================

    try:

        packet = Packet.deserialize(
            data
        )

    except ValueError as error:

        print(
            f"Gateway rejected packet: "
            f"{error}"
        )


        report_event(
            "gateway_rejected_packet",
            (
                f"Gateway rejected packet: "
                f"{error}"
            ),
            error=str(error)
        )


        continue


    packet_type = (
        packet.packet_type
    )

    sequence_number = (
        packet.sequence_number
    )


    print(
        f"Gateway received "
        f"{packet_type} "
        f"#{sequence_number}"
    )


    report_event(
        "gateway_received",
        (
            f"Gateway received "
            f"{packet_type} "
            f"#{sequence_number}"
        ),
        packet_type=packet_type,
        sequence_number=sequence_number,
        source_address=(
            f"{source_address[0]}:"
            f"{source_address[1]}"
        )
    )


    # ==============================
    # SENDER → RECEIVER
    # ==============================

    if packet_type in (
        "CONNECT",
        "DATA",
        "FIN"
    ):

        sender_address = (
            source_address
        )


        report_event(
            "gateway_forwarding",
            (
                f"Gateway forwarding "
                f"{packet_type} "
                f"#{sequence_number} "
                f"to receiver"
            ),
            packet_type=packet_type,
            sequence_number=sequence_number,
            direction="sender_to_receiver"
        )


        network.transmit(
            data,
            packet,
            deliver_to_receiver
        )


    # ==============================
    # RECEIVER → SENDER
    # ==============================

    elif packet_type in (
        "CONNECT_ACK",
        "ACK",
        "FIN_ACK"
    ):

        report_event(
            "gateway_forwarding",
            (
                f"Gateway forwarding "
                f"{packet_type} "
                f"#{sequence_number} "
                f"to sender"
            ),
            packet_type=packet_type,
            sequence_number=sequence_number,
            direction="receiver_to_sender"
        )


        network.transmit(
            data,
            packet,
            deliver_to_sender
        )


    # ==============================
    # UNKNOWN PACKET
    # ==============================

    else:

        print(
            f"Unknown packet type: "
            f"{packet_type}"
        )


        report_event(
            "unknown_packet",
            (
                f"Unknown packet type: "
                f"{packet_type}"
            ),
            packet_type=packet_type,
            sequence_number=sequence_number
        )