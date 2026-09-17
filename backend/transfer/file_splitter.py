from pathlib import Path


DEFAULT_CHUNK_SIZE = 1024


def split_file(file_path, chunk_size=DEFAULT_CHUNK_SIZE):

    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"File not found: {file_path}"
        )

    if not file_path.is_file():
        raise ValueError(
            f"Not a file: {file_path}"
        )

    with open(file_path, "rb") as file:

        sequence_number = 1

        while True:

            chunk = file.read(chunk_size)

            if not chunk:
                break

            yield sequence_number, chunk

            sequence_number += 1