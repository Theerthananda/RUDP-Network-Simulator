import sys
from pathlib import Path

sys.path.append(
    str(Path(__file__).resolve().parent)
)

from transfer.file_reassembler import FileReassembler


# ==============================
# TEST DATA
# ==============================

chunks = [
    (1, b"This is "),
    (2, b"a RUDP "),
    (3, b"file transfer "),
    (4, b"test.")
]


# ==============================
# CREATE REASSEMBLER
# ==============================

output_file = Path(
    "backend/reassembled_test.txt"
)

reassembler = FileReassembler(
    output_file
)


# ==============================
# ADD CHUNKS OUT OF ORDER
# ==============================

reassembler.add_chunk(
    3,
    chunks[2][1]
)

reassembler.add_chunk(
    1,
    chunks[0][1]
)

reassembler.add_chunk(
    4,
    chunks[3][1]
)

reassembler.add_chunk(
    2,
    chunks[1][1]
)


# ==============================
# CHECK COMPLETION
# ==============================

if reassembler.is_complete(4):

    print(
        "✅ All chunks received"
    )

    reassembler.write_file()

else:

    print(
        "❌ Missing chunks"
    )


# ==============================
# VERIFY FILE
# ==============================

expected = (
    b"This is "
    b"a RUDP "
    b"file transfer "
    b"test."
)


actual = output_file.read_bytes()


if actual == expected:

    print(
        "✅ File reassembled correctly"
    )

    print(
        f"Output: {output_file}"
    )

else:

    print(
        "❌ Reassembled file is incorrect"
    )