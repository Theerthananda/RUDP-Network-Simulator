import hashlib
import random
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol.packet import Packet, PacketIntegrityError
from transfer.session import RUDPTransferSession, TransferConfig, UDPTransferSession


class RUDPTransferSessionTests(unittest.TestCase):
    def run_session(self, payload, config):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.bin", root / "received"
            source.write_bytes(payload)
            events = []
            result = RUDPTransferSession(source, output, config, events.append).run()
            received = output / "source.bin"
            return result, events, received.read_bytes() if received.exists() else None

    def test_binary_packet_round_trip_and_rejects_corruption(self):
        packet = Packet(1, "DATA", 7, b"\x00\xffbinary")
        self.assertEqual(Packet.deserialize(packet.serialize()).payload, b"\x00\xffbinary")
        corrupted = bytearray(packet.serialize())
        corrupted[-1] ^= 1
        with self.assertRaises(ValueError):
            Packet.deserialize(bytes(corrupted))

    def test_crc_rejects_interpretable_header_corruption(self):
        packet = Packet(1, "DATA", 7, b"header-protected")
        corrupted = bytearray(packet.serialize())
        # Alter the sequence-number field but leave the transmitted CRC intact.
        corrupted[5] ^= 1
        with self.assertRaises(PacketIntegrityError):
            Packet.deserialize(bytes(corrupted))

    def test_real_transfer_preserves_binary_file(self):
        payload = bytes(range(256)) * 10
        result, events, received = self.run_session(payload, TransferConfig(delay_ms=2, timeout_seconds=0.15, packet_size=256))
        self.assertTrue(result["success"])
        self.assertEqual(received, payload)
        self.assertIn("integrity_verified", [event["type"] for event in events])
        self.assertEqual(result["metrics"]["checksum_errors"], 0)
        self.assertEqual(result["metrics"]["integrity_retransmissions"], 0)

    def test_controlled_first_transmission_loss_recovers(self):
        payload = b"x" * (30 * 64)
        result, events, received = self.run_session(payload, TransferConfig(delay_ms=1, timeout_seconds=0.08, packet_size=64, controlled_loss=True))
        types = [event["type"] for event in events]
        self.assertTrue(result["success"])
        self.assertEqual(received, payload)
        self.assertGreaterEqual(result["metrics"]["packets_lost"], 6)
        self.assertGreaterEqual(result["metrics"]["retransmissions"], 6)
        self.assertIn("packet_lost", types)

    def test_ack_loss_creates_duplicates_but_completes(self):
        random.seed(21)
        payload = b"ack-loss" * 200
        result, events, received = self.run_session(payload, TransferConfig(delay_ms=1, timeout_seconds=0.06, packet_size=80, ack_loss=0.15))
        self.assertTrue(result["success"])
        self.assertEqual(received, payload)
        self.assertGreater(result["metrics"]["acks_lost"], 0)
        self.assertIn("duplicate_packet", [event["type"] for event in events])

    def test_corruption_is_detected_and_transfer_recovers(self):
        random.seed(7)
        payload = b"corruption-check" * 400
        result, events, received = self.run_session(payload, TransferConfig(delay_ms=1, timeout_seconds=0.06, packet_size=100, corruption=0.08))
        self.assertTrue(result["success"])
        self.assertEqual(hashlib.sha256(received).digest(), hashlib.sha256(payload).digest())
        self.assertGreater(result["metrics"]["packets_corrupted"], 0)
        self.assertIn("packet_corrupted", [event["type"] for event in events])

    def test_window_retransmits_only_crc_rejected_packet(self):
        payload = b"selective-repeat" * 200
        config = TransferConfig(
            delay_ms=1, timeout_seconds=0.06, packet_size=100, window_size=5,
            forced_corruption_sequences=frozenset({3}),
        )
        result, events, received = self.run_session(payload, config)
        retransmitted = [event["sequence_number"] for event in events if event["type"] == "retransmission"]
        self.assertTrue(result["success"])
        self.assertEqual(received, payload)
        self.assertEqual(retransmitted, [3])
        self.assertEqual(result["metrics"]["packets_corrupted"], 1)
        self.assertEqual(result["metrics"]["checksum_errors"], 1)
        self.assertEqual(result["metrics"]["integrity_retransmissions"], 1)
        self.assertIn("checksum_failed", [event["type"] for event in events])
        self.assertIn("packet_rejected", [event["type"] for event in events])

    def test_combined_corruption_loss_and_ack_loss_recovers(self):
        random.seed(101)
        payload = b"combined-network-conditions" * 100
        config = TransferConfig(
            delay_ms=1, timeout_seconds=0.08, packet_size=100, window_size=5,
            data_loss=0.03, ack_loss=0.03, corruption=0.02,
            forced_corruption_sequences=frozenset({3}),
        )
        result, _, received = self.run_session(payload, config)
        self.assertTrue(result["success"])
        self.assertEqual(received, payload)
        self.assertGreaterEqual(result["metrics"]["checksum_errors"], 1)

    def test_cancellation_closes_active_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "large.bin"
            source.write_bytes(b"z" * 100_000)
            events, cancelled = [], threading.Event()
            session = RUDPTransferSession(source, root / "received", TransferConfig(delay_ms=100, timeout_seconds=0.2, packet_size=1024), events.append, cancelled)
            thread = threading.Thread(target=session.run)
            thread.start()
            time.sleep(0.05)
            cancelled.set()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertIn("transfer_cancelled", [event["type"] for event in events])

    def test_udp_transfer_uses_shared_network_conditions_without_reliability(self):
        payload = b"udp-data" * 100
        config = TransferConfig(protocol="UDP", delay_ms=1, packet_size=80, send_batch_size=3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.bin", root / "received"
            source.write_bytes(payload)
            events = []
            result = UDPTransferSession(source, output, config, events.append).run()
        self.assertTrue(result["success"])
        self.assertTrue(result["integrity_verified"])
        self.assertEqual(result["metrics"]["acks_received"], 0)
        self.assertEqual(result["metrics"]["acks_lost"], 0)
        self.assertEqual(result["metrics"]["retransmissions"], 0)
        self.assertIsNone(result["metrics"]["average_rtt_ms"])
        self.assertNotIn("ack_sent", [event["type"] for event in events])
        self.assertNotIn("timeout", [event["type"] for event in events])

    def test_udp_data_loss_is_measured_without_retransmission(self):
        random.seed(4)
        payload = b"loss" * 250
        config = TransferConfig(protocol="UDP", data_loss=0.5, delay_ms=1, packet_size=40, send_batch_size=4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(payload)
            events = []
            result = UDPTransferSession(source, root / "received", config, events.append).run()
        self.assertTrue(result["success"])
        self.assertGreater(result["metrics"]["packets_lost"], 0)
        self.assertEqual(result["metrics"]["retransmissions"], 0)
        self.assertNotIn("timeout", [event["type"] for event in events])

    def test_udp_one_megabyte_localhost_transfer_has_no_unconfigured_loss(self):
        payload = bytes(range(256)) * 4096
        config = TransferConfig(protocol="UDP", data_loss=0, delay_ms=0, corruption=0,
                                packet_size=1024, send_batch_size=3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "one-megabyte.bin", root / "received"
            source.write_bytes(payload)
            events = []
            result = UDPTransferSession(source, output, config, events.append).run()
            received = (output / source.name).read_bytes()
        metrics = result["metrics"]
        self.assertTrue(result["success"])
        self.assertTrue(result["integrity_verified"])
        self.assertEqual(metrics["packets_sent"], 1024)
        self.assertEqual(metrics["packets_received"], metrics["packets_sent"])
        self.assertEqual(metrics["packets_lost"], 0)
        self.assertEqual(metrics["acks_received"], 0)
        self.assertEqual(metrics["retransmissions"], 0)
        self.assertEqual(received, payload)


if __name__ == "__main__":
    unittest.main()
