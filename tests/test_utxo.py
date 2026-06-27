import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from src.utxo.models import TransactionOutput, TransactionInput, Transaction, UTXOSet
from src.utxo.blockchain import Blockchain, compute_subsidy


class TestUTXOSet(unittest.TestCase):
    def test_add_and_get(self):
        utxo_set = UTXOSet()
        out = TransactionOutput(value=1000, address="alice", tx_id="tx1", index=0)
        utxo_set.add(out)
        self.assertEqual(utxo_set.get("tx1:0").value, 1000)

    def test_spend(self):
        utxo_set = UTXOSet()
        out = TransactionOutput(value=1000, address="alice", tx_id="tx1", index=0)
        utxo_set.add(out)
        utxo_set.spend("tx1:0")
        self.assertFalse(utxo_set.is_unspent("tx1:0"))

    def test_double_spend(self):
        utxo_set = UTXOSet()
        out = TransactionOutput(value=1000, address="alice", tx_id="tx1", index=0)
        utxo_set.add(out)
        utxo_set.spend("tx1:0")
        with self.assertRaises(ValueError):
            utxo_set.spend("tx1:0")

    def test_balance(self):
        utxo_set = UTXOSet()
        utxo_set.add(TransactionOutput(value=500, address="alice", tx_id="tx1", index=0))
        utxo_set.add(TransactionOutput(value=300, address="alice", tx_id="tx2", index=0))
        utxo_set.add(TransactionOutput(value=200, address="bob", tx_id="tx3", index=0))
        self.assertEqual(utxo_set.get_balance("alice"), 800)
        self.assertEqual(utxo_set.get_balance("bob"), 200)


class TestBlockchain(unittest.TestCase):
    def test_mine_genesis(self):
        bc = Blockchain()
        block = bc.mine_block("miner")
        self.assertEqual(block.height, 0)
        self.assertEqual(bc.height, 1)
        self.assertEqual(bc.utxo_set.get_balance("miner"), 50 * 100_000_000)

    def test_transfer(self):
        bc = Blockchain()
        bc.mine_block("miner")
        tx = bc.create_transaction("miner", [("alice", 1_000_000_000)], fee=0)
        bc.mine_block("miner", [tx])
        self.assertEqual(bc.utxo_set.get_balance("alice"), 1_000_000_000)

    def test_insufficient_funds(self):
        bc = Blockchain()
        bc.mine_block("miner")
        with self.assertRaises(ValueError):
            bc.create_transaction("alice", [("bob", 100)])

    def test_subsidy_halving(self):
        self.assertEqual(compute_subsidy(0), 50 * 100_000_000)
        self.assertEqual(compute_subsidy(210_000), 25 * 100_000_000)
        self.assertEqual(compute_subsidy(420_000), 12.5 * 100_000_000)


class TestValidation(unittest.TestCase):
    def test_double_spend_detection(self):
        bc = Blockchain()
        bc.mine_block("miner")
        tx1 = bc.create_transaction("miner", [("alice", 1_000_000_000)], fee=0)
        bc.mine_block("miner", [tx1])

        # try to spend the same UTXO in a new tx
        fake_input = TransactionInput(
            prev_tx_id=tx1.inputs[0].prev_tx_id,
            prev_index=tx1.inputs[0].prev_index,
            address="miner",
        )
        fake_tx = Transaction(
            inputs=[fake_input],
            outputs=[TransactionOutput(value=1_000_000_000, address="evil")],
        )
        result = bc.validate_transaction(fake_tx)
        self.assertFalse(result.valid)


if __name__ == "__main__":
    unittest.main()
