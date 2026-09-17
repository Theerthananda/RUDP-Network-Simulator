from pathlib import Path


class FileReassembler:

    def __init__(self, output_path):

        self.output_path = Path(output_path)

        self.chunks = {}


    def add_chunk(self, sequence_number, data):

        self.chunks[sequence_number] = data


    def is_complete(self, total_chunks):

        return len(self.chunks) == total_chunks


    def write_file(self):

        with open(self.output_path, "wb") as file:

            for sequence_number in sorted(self.chunks):

                file.write(
                    self.chunks[sequence_number]
                )


        return self.output_path