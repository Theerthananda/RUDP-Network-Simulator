import socket
import sys
import json
import time
import urllib.request

from pathlib import Path


sys.path.append(
    str(Path(__file__).resolve().parents[1])
)


from protocol.packet import Packet
from protocol.file_checksum import calculate_file_checksum
from transfer.file_splitter import split_file


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
    Send a live event to the Web Bridge.

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
        # break the actual RUDP transfer.

        pass


# ==============================
# CONFIGURATION
# ==============================

GATEWAY_HOST = "127.0.0.1"

GATEWAY_PORT = 6000

WINDOW_SIZE = 3

TIMEOUT = 2

MAX_RETRIES = 3


if len(sys.argv) < 2:

    print(
        "❌ No file path provided."
    )

    report_event(
        "transfer_failed",
        "No file path provided."
    )

    sys.exit(1)


FILE_PATH = Path(
    sys.argv[1]
).resolve()


if not FILE_PATH.is_file():

    print(
        f"❌ File not found: {FILE_PATH}"
    )

    report_event(
        "transfer_failed",
        f"File not found: {FILE_PATH}"
    )

    sys.exit(1)


CHUNK_SIZE = 1024


# ==============================
# READ FILE
# ==============================

chunks = list(
    split_file(
        FILE_PATH,
        chunk_size=CHUNK_SIZE
    )
)


total_packets = len(chunks)


file_size = FILE_PATH.stat().st_size


file_checksum = (
    calculate_file_checksum(
        FILE_PATH
    )
)


# ==============================
# DISPLAY FILE INFORMATION
# ==============================

print(
    f"📁 File: {FILE_PATH}"
)

print(
    f"📏 File size: {file_size} bytes"
)

print(
    f"📦 Chunk size: {CHUNK_SIZE} bytes"
)

print(
    f"📦 Total packets: {total_packets}"
)

print(
    f"🔐 File SHA-256: {file_checksum}"
)

print()


# ==============================
# LIVE TRANSFER METADATA
# ==============================

report_event(
    "transfer_metadata",
    (
        f"Preparing RUDP transfer "
        f"for {FILE_PATH.name}"
    ),
    filename=FILE_PATH.name,
    file_size=file_size,
    chunk_size=CHUNK_SIZE,
    total_packets=total_packets,
    file_checksum=file_checksum,
    window_size=WINDOW_SIZE
)


# ==============================
# CREATE UDP SOCKET
# ==============================

sender_socket = socket.socket(
    socket.AF_INET,
    socket.SOCK_DGRAM
)


# ==============================
# CONNECT HANDSHAKE
# ==============================

metadata = {
    "filename": FILE_PATH.name,
    "file_size": file_size,
    "chunk_size": CHUNK_SIZE,
    "total_chunks": total_packets,
    "file_checksum": file_checksum
}


metadata_payload = json.dumps(
    metadata
).encode("utf-8")


connect_packet = Packet(
    version=1,
    packet_type="CONNECT",
    sequence_number=0,
    payload=metadata_payload
)


connect_attempt = 0


# CONNECT uses the normal timeout.

sender_socket.settimeout(
    TIMEOUT
)


while True:

    sender_socket.sendto(
        connect_packet.serialize(),
        (
            GATEWAY_HOST,
            GATEWAY_PORT
        )
    )


    connect_attempt += 1


    print(
        f"📤 CONNECT sent "
        f"(attempt {connect_attempt})"
    )


    report_event(
        "packet_sent",
        (
            f"📤 CONNECT sent "
            f"(attempt {connect_attempt})"
        ),
        packet_type="CONNECT",
        sequence_number=0,
        attempt=connect_attempt
    )


    try:

        data, sender_address = (
            sender_socket.recvfrom(
                65535
            )
        )


        # ==============================
        # DESERIALIZE RESPONSE
        # ==============================

        try:

            response_packet = (
                Packet.deserialize(
                    data
                )
            )

        except ValueError as error:

            print(
                f"⚠️ Corrupted CONNECT_ACK: "
                f"{error}"
            )

            print(
                "Ignoring corrupted CONNECT_ACK...\n"
            )


            report_event(
                "packet_corrupted",
                (
                    "⚠️ Corrupted CONNECT_ACK "
                    "rejected"
                ),
                packet_type="CONNECT_ACK",
                sequence_number=0,
                error=str(error)
            )


            continue


        # ==============================
        # CHECK CONNECT_ACK
        # ==============================

        if (
            response_packet.packet_type
            == "CONNECT_ACK"
        ):

            print(
                "📥 CONNECT_ACK received"
            )

            print(
                "✅ File metadata accepted\n"
            )


            report_event(
                "ack_received",
                "📥 CONNECT_ACK received",
                packet_type="CONNECT_ACK",
                sequence_number=0
            )


            report_event(
                "connection_established",
                "✅ File metadata accepted"
            )


            break


    except socket.timeout:

        if connect_attempt >= MAX_RETRIES:

            print(
                "❌ CONNECT failed: "
                "maximum retries exceeded"
            )


            report_event(
                "transfer_failed",
                (
                    "❌ CONNECT failed: "
                    "maximum retries exceeded"
                ),
                packet_type="CONNECT",
                sequence_number=0,
                attempts=connect_attempt
            )


            sender_socket.close()

            sys.exit(1)


        print(
            "⏱️ CONNECT timeout"
        )

        print(
            "🔄 Retrying CONNECT...\n"
        )


        report_event(
            "timeout",
            "⏱️ CONNECT timeout",
            packet_type="CONNECT",
            sequence_number=0,
            attempt=connect_attempt
        )


# ==============================
# SELECTIVE REPEAT STATE
# ==============================

base = 1

next_sequence = 1

acked = set()

retry_count = {}

sent_time = {}

packet_data = {}


# ==============================
# PREPARE DATA PACKETS
# ==============================

for sequence_number, chunk in chunks:

    packet = Packet(
        version=1,
        packet_type="DATA",
        sequence_number=sequence_number,
        payload=chunk
    )


    packet_data[
        sequence_number
    ] = packet.serialize()


# ==============================
# START SELECTIVE REPEAT
# ==============================

print(
    "🚀 Starting Selective Repeat transfer...\n"
)


report_event(
    "data_transfer_started",
    "🚀 Starting Selective Repeat transfer",
    total_packets=total_packets,
    window_size=WINDOW_SIZE
)


# Small socket timeout allows the sender
# to frequently check individual timers.

sender_socket.settimeout(
    0.05
)


# ==============================
# DATA TRANSFER LOOP
# ==============================

while base <= total_packets:

    # ==============================
    # SEND NEW PACKETS
    # ==============================

    while (
        next_sequence <= total_packets
        and next_sequence < (
            base + WINDOW_SIZE
        )
    ):

        sender_socket.sendto(
            packet_data[next_sequence],
            (
                GATEWAY_HOST,
                GATEWAY_PORT
            )
        )


        # Start individual timer.

        sent_time[
            next_sequence
        ] = time.monotonic()


        # First transmission = retry 0.

        retry_count.setdefault(
            next_sequence,
            0
        )


        payload_size = len(
            chunks[
                next_sequence - 1
            ][1]
        )


        print(
            f"📤 Sent DATA "
            f"#{next_sequence}"
        )


        report_event(
            "packet_sent",
            (
                f"📤 Sent DATA "
                f"#{next_sequence}"
            ),
            packet_type="DATA",
            sequence_number=next_sequence,
            payload_size=payload_size,
            retransmission=False,
            retry=0
        )


        next_sequence += 1


    # ==============================
    # WAIT FOR ACK
    # ==============================

    try:

        data, sender_address = (
            sender_socket.recvfrom(
                65535
            )
        )


        # ==============================
        # DESERIALIZE ACK
        # ==============================

        try:

            response_packet = (
                Packet.deserialize(
                    data
                )
            )

        except ValueError as error:

            print(
                f"⚠️ Corrupted ACK: "
                f"{error}"
            )

            print(
                "Ignoring corrupted ACK...\n"
            )


            report_event(
                "packet_corrupted",
                "⚠️ Corrupted ACK rejected",
                packet_type="ACK",
                error=str(error)
            )


            continue


        # ==============================
        # ONLY PROCESS ACK PACKETS
        # ==============================

        if (
            response_packet.packet_type
            != "ACK"
        ):

            continue


        ack_number = (
            response_packet.sequence_number
        )


        # ==============================
        # VALIDATE ACK NUMBER
        # ==============================

        if (
            ack_number < base
            or ack_number > total_packets
        ):

            print(
                f"⚠️ Ignoring unexpected "
                f"ACK #{ack_number}"
            )


            report_event(
                "unexpected_ack",
                (
                    f"⚠️ Ignoring unexpected "
                    f"ACK #{ack_number}"
                ),
                packet_type="ACK",
                sequence_number=ack_number
            )


            continue


        # ==============================
        # RECORD ACK
        # ==============================

        if ack_number in acked:

            print(
                f"⚠️ Duplicate ACK "
                f"#{ack_number}"
            )


            report_event(
                "duplicate_ack",
                (
                    f"⚠️ Duplicate ACK "
                    f"#{ack_number}"
                ),
                packet_type="ACK",
                sequence_number=ack_number
            )


        else:

            acked.add(
                ack_number
            )


            # Stop timer for this packet.

            sent_time.pop(
                ack_number,
                None
            )


            print(
                f"📥 Received ACK "
                f"#{ack_number}"
            )


            report_event(
                "ack_received",
                (
                    f"📥 Received ACK "
                    f"#{ack_number}"
                ),
                packet_type="ACK",
                sequence_number=ack_number,
                acknowledged_packets=len(
                    acked
                ),
                total_packets=total_packets
            )


        # ==============================
        # MOVE WINDOW
        # ==============================

        old_base = base


        while base in acked:

            base += 1


        if base != old_base:

            print(
                f"➡️ Window moved: "
                f"#{old_base} → #{base}\n"
            )


            report_event(
                "window_moved",
                (
                    f"➡️ Window moved: "
                    f"#{old_base} → #{base}"
                ),
                old_base=old_base,
                new_base=base
            )


    # ==============================
    # SOCKET POLLING TIMEOUT
    # ==============================

    except socket.timeout:

        # This 0.05 second timeout does NOT
        # mean a DATA packet timed out.
        #
        # It only allows us to check the
        # individual packet timers.


        current_time = (
            time.monotonic()
        )


        # ==============================
        # CHECK EVERY PACKET TIMER
        # ==============================

        for sequence_number in range(
            base,
            next_sequence
        ):

            # Already acknowledged?

            if sequence_number in acked:

                continue


            # Does this packet have a timer?

            if sequence_number not in sent_time:

                continue


            elapsed = (
                current_time
                - sent_time[
                    sequence_number
                ]
            )


            # Timer has not expired.

            if elapsed < TIMEOUT:

                continue


            # ==============================
            # PACKET TIMEOUT
            # ==============================

            print(
                f"⏱️ TIMEOUT: "
                f"DATA #{sequence_number}"
            )


            report_event(
                "timeout",
                (
                    f"⏱️ TIMEOUT: "
                    f"DATA #{sequence_number}"
                ),
                packet_type="DATA",
                sequence_number=sequence_number,
                elapsed=elapsed
            )


            # Increase retry count.

            retry_count[
                sequence_number
            ] += 1


            # ==============================
            # CHECK MAX RETRIES
            # ==============================

            if (
                retry_count[
                    sequence_number
                ] > MAX_RETRIES
            ):

                print(
                    f"❌ FAILED: Packet "
                    f"#{sequence_number} "
                    f"exceeded "
                    f"{MAX_RETRIES} retries"
                )


                report_event(
                    "transfer_failed",
                    (
                        f"❌ FAILED: Packet "
                        f"#{sequence_number} "
                        f"exceeded "
                        f"{MAX_RETRIES} retries"
                    ),
                    packet_type="DATA",
                    sequence_number=sequence_number,
                    retries=retry_count[
                        sequence_number
                    ]
                )


                sender_socket.close()

                sys.exit(1)


            # ==============================
            # RETRANSMIT ONLY THIS PACKET
            # ==============================

            sender_socket.sendto(
                packet_data[
                    sequence_number
                ],
                (
                    GATEWAY_HOST,
                    GATEWAY_PORT
                )
            )


            # Restart only this packet's timer.

            sent_time[
                sequence_number
            ] = time.monotonic()


            retry = retry_count[
                sequence_number
            ]


            print(
                f"🔄 Retransmitting DATA "
                f"#{sequence_number} "
                f"(retry {retry})"
            )

            print()


            report_event(
                "retransmission",
                (
                    f"🔄 Retransmitting DATA "
                    f"#{sequence_number} "
                    f"(retry {retry})"
                ),
                packet_type="DATA",
                sequence_number=sequence_number,
                retransmission=True,
                retry=retry
            )


# ==============================
# ALL DATA ACKNOWLEDGED
# ==============================

print(
    "📤 All DATA packets acknowledged"
)

print(
    "Preparing to close transfer...\n"
)


report_event(
    "all_data_acknowledged",
    "📤 All DATA packets acknowledged",
    acknowledged_packets=len(acked),
    total_packets=total_packets
)


# ==============================
# SEND FIN
# ==============================

fin_packet = Packet(
    version=1,
    packet_type="FIN",
    sequence_number=0,
    payload=b""
)


fin_attempt = 0


# FIN uses normal timeout.

sender_socket.settimeout(
    TIMEOUT
)


while True:

    sender_socket.sendto(
        fin_packet.serialize(),
        (
            GATEWAY_HOST,
            GATEWAY_PORT
        )
    )


    fin_attempt += 1


    print(
        f"📤 FIN sent "
        f"(attempt {fin_attempt})"
    )


    report_event(
        "packet_sent",
        (
            f"📤 FIN sent "
            f"(attempt {fin_attempt})"
        ),
        packet_type="FIN",
        sequence_number=0,
        attempt=fin_attempt
    )


    try:

        data, sender_address = (
            sender_socket.recvfrom(
                65535
            )
        )


        # ==============================
        # DESERIALIZE FIN_ACK
        # ==============================

        try:

            response_packet = (
                Packet.deserialize(
                    data
                )
            )

        except ValueError as error:

            print(
                f"⚠️ Corrupted FIN_ACK: "
                f"{error}"
            )

            print(
                "Ignoring corrupted FIN_ACK...\n"
            )


            report_event(
                "packet_corrupted",
                "⚠️ Corrupted FIN_ACK rejected",
                packet_type="FIN_ACK",
                sequence_number=0,
                error=str(error)
            )


            continue


        # ==============================
        # CHECK FIN_ACK
        # ==============================

        if (
            response_packet.packet_type
            == "FIN_ACK"
        ):

            print(
                "📥 FIN_ACK received"
            )

            print(
                "✅ Transfer session closed"
            )


            report_event(
                "ack_received",
                "📥 FIN_ACK received",
                packet_type="FIN_ACK",
                sequence_number=0
            )


            report_event(
                "session_closed",
                "✅ Transfer session closed"
            )


            break


    except socket.timeout:

        if fin_attempt >= MAX_RETRIES:

            print(
                "❌ FIN failed: "
                "maximum retries exceeded"
            )


            report_event(
                "transfer_failed",
                (
                    "❌ FIN failed: "
                    "maximum retries exceeded"
                ),
                packet_type="FIN",
                sequence_number=0,
                attempts=fin_attempt
            )


            sender_socket.close()

            sys.exit(1)


        print(
            "⏱️ FIN timeout"
        )

        print(
            "🔄 Retrying FIN...\n"
        )


        report_event(
            "timeout",
            "⏱️ FIN timeout",
            packet_type="FIN",
            sequence_number=0,
            attempt=fin_attempt
        )


# ==============================
# TRANSFER COMPLETE
# ==============================

sender_socket.close()


print(
    "\n🎉 File transfer completed successfully!"
)

print(
    f"📁 Source file: {FILE_PATH}"
)

print(
    f"🔐 SHA-256: {file_checksum}"
)


report_event(
    "sender_complete",
    "🎉 Sender completed file transfer.",
    filename=FILE_PATH.name,
    file_size=file_size,
    total_packets=total_packets,
    file_checksum=file_checksum
)