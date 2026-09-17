import sys
from pathlib import Path

sys.path.append(
    str(Path(__file__).resolve().parent)
)

from transfer.file_splitter import split_file


# ==============================
# CREATE TEST FILE
# ==============================

test_file = Path(
    "backend/transfer_test.txt"
)

test_file.write_text(
    "This is a test file for RUDP file transfer. "
    "We are splitting this file into multiple chunks "
    "before sending it through the network.",
    encoding="utf-8"
)


# ==============================
# SPLIT FILE
# ==============================

chunks = list(
    split_file(
        test_file,
        chunk_size=20
    )
)


# ==============================
# DISPLAY CHUNKS
# ==============================

print(
    f"Total chunks: {len(chunks)}\n"
)

for sequence_number, chunk in chunks:

    print(
        f"Chunk #{sequence_number}: "
        f"{len(chunk)} bytes → {chunk!r}"
    )


# ==============================
# VERIFY
# ==============================

if len(chunks) > 1:

    print(
        "\n✅ File successfully split "
        "into multiple chunks"
    )

else:

    print(
        "\n❌ File was not split "
        "into multiple chunks"
    )