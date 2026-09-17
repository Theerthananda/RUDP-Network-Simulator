import socket
import sys
import json
import urllib.request

from pathlib import Path


sys.path.append(
    str(Path(__file__).resolve().parents[1])
)


from protocol.packet import Packet
from protocol.file_checksum import calculate_file_checksum
from transfer.file_reassembler import FileReassembler


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
    Send a live receiver event to the Web Bridge.

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
        # break the actual RUDP receiver.
        pass


# ==============================
# CONFIGURATION
# ==============================

HOST = "0.0.0.0"

PORT = 5000

OUTPUT_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "received_files"
)


OUTPUT_DIRECTORY.mkdir(
    parents=True,
    exist_ok=True
)


# ==============================
# CREATE SOCKET
# ==============================

receiver_socket = socket.socket(
    socket.AF_INET,
    socket.SOCK_DGRAM
)


receiver_socket.bind(
    (
        HOST,
        PORT
    )
)


print(
    f"RUDP Receiver started on port {PORT}..."
)

print(
    "Waiting for file transfer...\n"
)


report_event(
    "receiver_started",
    (
        f"RUDP Receiver started "
        f"on port {PORT}"
    ),
    host=HOST,
    port=PORT
)


# ==============================
# WAIT FOR CONNECT
# ==============================

while True:

    data, sender_address = (
        receiver_socket.recvfrom(
            65535
        )
    )


    # ==============================
    # DESERIALIZE CONNECT
    # ==============================

    try:

        packet = Packet.deserialize(
            data
        )

    except ValueError as error:

        print(
            f"❌ Corrupted packet rejected: "
            f"{error}"
        )


        report_event(
            "packet_corrupted",
            (
                f"❌ Corrupted packet rejected: "
                f"{error}"
            ),
            error=str(error)
        )


        continue


    # ==============================
    # CHECK CONNECT
    # ==============================

    if packet.packet_type == "CONNECT":

        # ==============================
        # READ METADATA
        # ==============================

        try:

            metadata = json.loads(
                packet.payload.decode(
                    "utf-8"
                )
            )

        except (
            UnicodeDecodeError,
            json.JSONDecodeError
        ):

            print(
                "❌ Invalid CONNECT metadata"
            )


            report_event(
                "transfer_failed",
                "❌ Invalid CONNECT metadata",
                packet_type="CONNECT",
                sequence_number=0
            )


            continue


        # ==============================
        # EXTRACT METADATA
        # ==============================

        filename = metadata[
            "filename"
        ]

        file_size = metadata[
            "file_size"
        ]

        chunk_size = metadata[
            "chunk_size"
        ]

        total_chunks = metadata[
            "total_chunks"
        ]

        expected_file_checksum = (
            metadata[
                "file_checksum"
            ]
        )


        # ==============================
        # DISPLAY METADATA
        # ==============================

        print(
            "📋 File metadata received:"
        )

        print(
            f"   Filename: {filename}"
        )

        print(
            f"   File size: {file_size} bytes"
        )

        print(
            f"   Chunk size: {chunk_size} bytes"
        )

        print(
            f"   Total chunks: {total_chunks}"
        )

        print(
            f"   Expected SHA-256: "
            f"{expected_file_checksum}"
        )

        print()


        report_event(
            "metadata_received",
            (
                f"📋 File metadata received: "
                f"{filename}"
            ),
            packet_type="CONNECT",
            sequence_number=0,
            filename=filename,
            file_size=file_size,
            chunk_size=chunk_size,
            total_packets=total_chunks,
            expected_checksum=(
                expected_file_checksum
            )
        )


        # ==============================
        # SEND CONNECT ACK
        # ==============================

        connect_ack = Packet(
            version=1,
            packet_type="CONNECT_ACK",
            sequence_number=0,
            payload=b""
        )


        receiver_socket.sendto(
            connect_ack.serialize(),
            sender_address
        )


        print(
            "📤 CONNECT_ACK sent"
        )

        print(
            "✅ Ready to receive file\n"
        )


        report_event(
            "ack_sent",
            "📤 CONNECT_ACK sent",
            packet_type="CONNECT_ACK",
            sequence_number=0
        )


        report_event(
            "receiver_ready",
            "✅ Ready to receive file",
            filename=filename,
            total_packets=total_chunks
        )


        break


# ==============================
# FILE REASSEMBLER
# ==============================

output_file = (
    OUTPUT_DIRECTORY / filename
)


reassembler = FileReassembler(
    output_file
)


received_sequences = set()


# ==============================
# RECEIVE DATA
# ==============================

while True:

    data, sender_address = (
        receiver_socket.recvfrom(
            65535
        )
    )


    # ==============================
    # DESERIALIZE PACKET
    # ==============================

    try:

        packet = Packet.deserialize(
            data
        )

    except ValueError as error:

        print(
            f"❌ Corrupted packet rejected: "
            f"{error}\n"
        )


        report_event(
            "packet_corrupted",
            (
                f"❌ Corrupted DATA rejected: "
                f"{error}"
            ),
            packet_type="DATA",
            error=str(error)
        )


        continue


    # ==============================
    # IGNORE NON-DATA PACKETS
    # ==============================

    if packet.packet_type != "DATA":

        continue


    sequence_number = (
        packet.sequence_number
    )


    print(
        f"📥 Received DATA "
        f"#{sequence_number}"
    )


    report_event(
        "packet_received",
        (
            f"📥 Received DATA "
            f"#{sequence_number}"
        ),
        packet_type="DATA",
        sequence_number=sequence_number,
        payload_size=len(
            packet.payload
        )
    )


    # ==============================
    # STORE CHUNK
    # ==============================

    if (
        sequence_number
        in received_sequences
    ):

        print(
            f"⚠️ DUPLICATE: "
            f"Packet #{sequence_number}"
        )


        report_event(
            "duplicate_packet",
            (
                f"⚠️ DUPLICATE: "
                f"Packet #{sequence_number}"
            ),
            packet_type="DATA",
            sequence_number=sequence_number
        )


    else:

        received_sequences.add(
            sequence_number
        )


        reassembler.add_chunk(
            sequence_number,
            packet.payload
        )


        print(
            f"✅ Chunk "
            f"#{sequence_number} stored"
        )


        report_event(
            "chunk_stored",
            (
                f"✅ Chunk "
                f"#{sequence_number} stored"
            ),
            packet_type="DATA",
            sequence_number=sequence_number,
            received_packets=len(
                received_sequences
            ),
            total_packets=total_chunks,
            payload_size=len(
                packet.payload
            )
        )


    # ==============================
    # SEND ACK
    # ==============================

    ack_packet = Packet(
        version=1,
        packet_type="ACK",
        sequence_number=sequence_number,
        payload=b""
    )


    receiver_socket.sendto(
        ack_packet.serialize(),
        sender_address
    )


    print(
        f"📤 ACK "
        f"#{sequence_number} sent\n"
    )


    report_event(
        "ack_sent",
        (
            f"📤 ACK "
            f"#{sequence_number} sent"
        ),
        packet_type="ACK",
        sequence_number=sequence_number
    )


    # ==============================
    # CHECK COMPLETION
    # ==============================

    if reassembler.is_complete(
        total_chunks
    ):

        # ==============================
        # WRITE FILE
        # ==============================

        reassembler.write_file()


        print(
            "🎉 File received completely!"
        )

        print(
            f"📁 Output: {output_file}"
        )


        report_event(
            "file_received",
            "🎉 File received completely!",
            filename=filename,
            file_size=file_size,
            total_packets=total_chunks,
            received_packets=len(
                received_sequences
            )
        )


        # ==============================
        # VERIFY FILE SIZE
        # ==============================

        received_file_size = (
            output_file.stat().st_size
        )


        print(
            f"📏 Expected file size: "
            f"{file_size} bytes"
        )

        print(
            f"📏 Received file size: "
            f"{received_file_size} bytes"
        )


        if (
            received_file_size
            == file_size
        ):

            print(
                "✅ File size verified"
            )


            report_event(
                "file_size_verified",
                "✅ File size verified",
                filename=filename,
                expected_size=file_size,
                received_size=(
                    received_file_size
                )
            )

        else:

            print(
                "❌ File size verification failed"
            )


            report_event(
                "file_size_failed",
                (
                    "❌ File size "
                    "verification failed"
                ),
                filename=filename,
                expected_size=file_size,
                received_size=(
                    received_file_size
                )
            )


        # ==============================
        # CALCULATE RECEIVED CHECKSUM
        # ==============================

        actual_file_checksum = (
            calculate_file_checksum(
                output_file
            )
        )


        print(
            "\n🔐 Expected SHA-256:"
        )

        print(
            expected_file_checksum
        )


        print(
            "\n🔐 Received SHA-256:"
        )

        print(
            actual_file_checksum
        )


        report_event(
            "checksum_calculated",
            "🔐 Received SHA-256 calculated.",
            filename=filename,
            expected_checksum=(
                expected_file_checksum
            ),
            actual_checksum=(
                actual_file_checksum
            )
        )


        # ==============================
        # VERIFY FILE INTEGRITY
        # ==============================

        integrity_verified = (
            received_file_size
            == file_size
            and actual_file_checksum
            == expected_file_checksum
        )


        if integrity_verified:

            print(
                "\n✅ FILE INTEGRITY VERIFIED"
            )

            print(
                "✅ Source and received files "
                "are identical"
            )


            report_event(
                "integrity_verified",
                (
                    "✅ FILE INTEGRITY VERIFIED"
                ),
                filename=filename,
                file_size=file_size,
                expected_checksum=(
                    expected_file_checksum
                ),
                actual_checksum=(
                    actual_file_checksum
                ),
                verified=True
            )


        else:

            print(
                "\n❌ FILE INTEGRITY CHECK FAILED"
            )

            print(
                "⚠️ Received file does not "
                "match the source file"
            )


            report_event(
                "integrity_failed",
                (
                    "❌ FILE INTEGRITY CHECK FAILED"
                ),
                filename=filename,
                file_size=file_size,
                expected_checksum=(
                    expected_file_checksum
                ),
                actual_checksum=(
                    actual_file_checksum
                ),
                verified=False
            )


        # ==============================
        # WAIT FOR FIN
        # ==============================

        print(
            "\n⏳ Waiting for FIN from sender..."
        )


        report_event(
            "waiting_for_fin",
            "⏳ Waiting for FIN from sender...",
            filename=filename
        )


        while True:

            fin_data, fin_sender_address = (
                receiver_socket.recvfrom(
                    65535
                )
            )


            # ==============================
            # DESERIALIZE FIN
            # ==============================

            try:

                fin_packet = (
                    Packet.deserialize(
                        fin_data
                    )
                )

            except ValueError as error:

                print(
                    f"❌ Corrupted packet rejected: "
                    f"{error}"
                )


                report_event(
                    "packet_corrupted",
                    (
                        f"❌ Corrupted FIN rejected: "
                        f"{error}"
                    ),
                    packet_type="FIN",
                    error=str(error)
                )


                continue


            # ==============================
            # CHECK FIN
            # ==============================

            if (
                fin_packet.packet_type
                != "FIN"
            ):

                continue


            print(
                "📥 FIN received"
            )


            report_event(
                "fin_received",
                "📥 FIN received",
                packet_type="FIN",
                sequence_number=0
            )


            # ==============================
            # SEND FIN_ACK
            # ==============================

            fin_ack = Packet(
                version=1,
                packet_type="FIN_ACK",
                sequence_number=0,
                payload=b""
            )


            receiver_socket.sendto(
                fin_ack.serialize(),
                fin_sender_address
            )


            print(
                "📤 FIN_ACK sent"
            )

            print(
                "✅ Transfer session closed"
            )


            report_event(
                "ack_sent",
                "📤 FIN_ACK sent",
                packet_type="FIN_ACK",
                sequence_number=0
            )


            report_event(
                "session_closed",
                "✅ Transfer session closed",
                filename=filename
            )


            # ==============================
            # REAL TRANSFER COMPLETION
            # ==============================

            if integrity_verified:

                report_event(
                    "transfer_complete",
                    (
                        "🎉 RUDP transfer "
                        "completed successfully."
                    ),
                    filename=filename,
                    file_size=file_size,
                    total_packets=total_chunks,
                    received_packets=len(
                        received_sequences
                    ),
                    integrity_verified=True,
                    expected_checksum=(
                        expected_file_checksum
                    ),
                    actual_checksum=(
                        actual_file_checksum
                    )
                )

            else:

                report_event(
                    "transfer_failed",
                    (
                        "❌ RUDP transfer "
                        "failed file integrity verification."
                    ),
                    filename=filename,
                    file_size=file_size,
                    total_packets=total_chunks,
                    received_packets=len(
                        received_sequences
                    ),
                    integrity_verified=False,
                    expected_checksum=(
                        expected_file_checksum
                    ),
                    actual_checksum=(
                        actual_file_checksum
                    )
                )


            break


        # ==============================
        # END DATA LOOP
        # ==============================

        break


# ==============================
# CLOSE SOCKET
# ==============================

receiver_socket.close()


print(
    "\n🔌 Receiver socket closed."
)