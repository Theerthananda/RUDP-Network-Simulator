import sys
from pathlib import Path

# Allow Python to find backend modules
sys.path.append(str(Path(__file__).resolve().parent))

from protocol.checksum import calculate_checksum, verify_checksum


data = b"Hello from RUDP"

checksum = calculate_checksum(data)

print("Original data:")
print(data)

print("\nChecksum:")
print(checksum)

print("\nVerification with original data:")

if verify_checksum(data, checksum):
    print("✅ Checksum valid")
else:
    print("❌ Checksum invalid")


# Simulate corruption
corrupted_data = b"Hello from RUDX"

print("\nCorrupted data:")
print(corrupted_data)

print("\nVerification with corrupted data:")

if verify_checksum(corrupted_data, checksum):
    print("✅ Checksum valid")
else:
    print("❌ Checksum invalid — DATA CORRUPTED")