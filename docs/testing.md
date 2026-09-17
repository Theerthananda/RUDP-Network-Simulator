# Testing

Run `python -m unittest discover -s backend\tests -v`.

The automated suite verifies binary serialization and corruption rejection, normal binary transfer with file reconstruction, controlled first-send loss with retries, ACK-loss duplicate handling, corruption detection/recovery, and cancellation during an active transfer.

The HTTP acceptance check posts a binary file to `/api/transfer` with network settings, waits for completion, and compares the reconstructed file hash. Reset uses `/api/transfer/cancel`; a delayed large transfer is cancelled before completion. The frontend is served by the same bridge and its JavaScript is syntax-checked with Node.
