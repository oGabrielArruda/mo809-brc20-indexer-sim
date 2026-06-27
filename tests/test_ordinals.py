import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from src.ordinals.sat import (
    SatRange, classify_rarity, Rarity, block_sat_range, sat_to_block_and_offset,
)
from src.ordinals.tracker import OrdinalTracker
from src.utxo.blockchain import Blockchain


class TestSatRange(unittest.TestCase):
    def test_count(self):
        r = SatRange(0, 100)
        self.assertEqual(r.count, 100)

    def test_contains(self):
        r = SatRange(10, 20)
        self.assertTrue(r.contains(10))
        self.assertTrue(r.contains(19))
        self.assertFalse(r.contains(20))

    def test_split(self):
        r = SatRange(0, 100)
        left, right = r.split_at(30)
        self.assertEqual(left, SatRange(0, 30))
        self.assertEqual(right, SatRange(30, 100))


class TestRarity(unittest.TestCase):
    def test_mythic(self):
        self.assertEqual(classify_rarity(0), Rarity.MYTHIC)

    def test_uncommon_first_sat_of_block(self):
        start, _ = block_sat_range(1)
        self.assertEqual(classify_rarity(start), Rarity.UNCOMMON)

    def test_common(self):
        self.assertEqual(classify_rarity(1), Rarity.COMMON)

    def test_block_sat_range(self):
        start, end = block_sat_range(0)
        self.assertEqual(start, 0)
        self.assertEqual(end, 50 * 100_000_000)


class TestSatToBlock(unittest.TestCase):
    def test_genesis_sat(self):
        block, offset = sat_to_block_and_offset(0)
        self.assertEqual(block, 0)
        self.assertEqual(offset, 0)

    def test_second_block_first_sat(self):
        block, offset = sat_to_block_and_offset(50 * 100_000_000)
        self.assertEqual(block, 1)
        self.assertEqual(offset, 0)


class TestOrdinalTracker(unittest.TestCase):
    def test_coinbase_sat_assignment(self):
        bc = Blockchain()
        tracker = OrdinalTracker()

        block = bc.mine_block("miner")
        tracker.process_block(block)

        coinbase_out = block.coinbase_tx.outputs[0]
        ranges = tracker.get_sat_ranges(coinbase_out.outpoint)
        self.assertTrue(len(ranges) > 0)
        total = sum(r.count for r in ranges)
        self.assertEqual(total, 50 * 100_000_000)

    def test_fifo_transfer(self):
        bc = Blockchain()
        tracker = OrdinalTracker()

        block = bc.mine_block("miner")
        tracker.process_block(block)

        tx = bc.create_transaction("miner", [("alice", 1_000_000_000)], fee=0)
        block2 = bc.mine_block("miner", [tx])
        tracker.process_block(block2)

        alice_utxos = bc.utxo_set.get_utxos_for_address("alice")
        self.assertTrue(len(alice_utxos) > 0)
        alice_ranges = tracker.get_sat_ranges(alice_utxos[0].outpoint)
        total = sum(r.count for r in alice_ranges)
        self.assertEqual(total, 1_000_000_000)

    def test_find_sat(self):
        bc = Blockchain()
        tracker = OrdinalTracker()

        block = bc.mine_block("miner")
        tracker.process_block(block)

        location = tracker.find_sat(0)
        self.assertIsNotNone(location)


if __name__ == "__main__":
    unittest.main()
