import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from src.brc20.indexer import BRC20Indexer
from src.inscriptions.models import Inscription


def make_inscription(content: str, creator: str = "alice",
                     inscription_id: str = "tx:0", block: int = 1) -> Inscription:
    return Inscription(
        inscription_id=inscription_id,
        content_type="application/json",
        content=content,
        sat_number=hash(inscription_id) % 10**12,
        creator=creator,
        block_height=block,
    )


class TestDeploy(unittest.TestCase):
    def test_valid_deploy(self):
        idx = BRC20Indexer()
        insc = make_inscription(
            '{"p":"brc-20","op":"deploy","tick":"ordi","max":"21000000","lim":"1000"}'
        )
        idx.process_inscription(insc, 1, "tx:0")
        token = idx.get_token_info("ordi")
        self.assertIsNotNone(token)
        self.assertEqual(token.max_supply, 21_000_000)
        self.assertEqual(token.mint_limit, 1000)

    def test_duplicate_deploy(self):
        idx = BRC20Indexer()
        insc1 = make_inscription(
            '{"p":"brc-20","op":"deploy","tick":"ordi","max":"21000000","lim":"1000"}',
            inscription_id="tx1:0"
        )
        insc2 = make_inscription(
            '{"p":"brc-20","op":"deploy","tick":"ordi","max":"5000","lim":"100"}',
            inscription_id="tx2:0"
        )
        idx.process_inscription(insc1, 1, "tx1:0")
        idx.process_inscription(insc2, 2, "tx2:0")
        self.assertEqual(idx.get_token_info("ordi").max_supply, 21_000_000)

    def test_invalid_ticker_length(self):
        idx = BRC20Indexer()
        insc = make_inscription(
            '{"p":"brc-20","op":"deploy","tick":"ab","max":"1000","lim":"100"}'
        )
        idx.process_inscription(insc, 1, "tx:0")
        self.assertIsNone(idx.get_token_info("ab"))


class TestMint(unittest.TestCase):
    def setUp(self):
        self.idx = BRC20Indexer()
        deploy = make_inscription(
            '{"p":"brc-20","op":"deploy","tick":"test","max":"1000","lim":"100"}',
            inscription_id="deploy:0"
        )
        self.idx.process_inscription(deploy, 1, "deploy:0")

    def test_valid_mint(self):
        mint = make_inscription(
            '{"p":"brc-20","op":"mint","tick":"test","amt":"100"}',
            inscription_id="mint:0"
        )
        self.idx.process_inscription(mint, 2, "mint:0")
        bal = self.idx.get_address_balance("alice", "test")
        self.assertEqual(bal.overall, 100)

    def test_mint_over_limit(self):
        mint = make_inscription(
            '{"p":"brc-20","op":"mint","tick":"test","amt":"200"}',
            inscription_id="mint:0"
        )
        self.idx.process_inscription(mint, 2, "mint:0")
        bal = self.idx.get_address_balance("alice", "test")
        self.assertEqual(bal.overall, 0)  # rejected

    def test_mint_past_supply(self):
        for i in range(11):  # 11 * 100 = 1100 > 1000
            mint = make_inscription(
                '{"p":"brc-20","op":"mint","tick":"test","amt":"100"}',
                inscription_id=f"mint{i}:0"
            )
            self.idx.process_inscription(mint, 2 + i, f"mint{i}:0")
        token = self.idx.get_token_info("test")
        self.assertEqual(token.total_minted, 1000)

    def test_mint_nonexistent_token(self):
        mint = make_inscription(
            '{"p":"brc-20","op":"mint","tick":"fake","amt":"100"}',
            inscription_id="mint:0"
        )
        self.idx.process_inscription(mint, 2, "mint:0")
        bal = self.idx.get_address_balance("alice", "fake")
        self.assertEqual(bal.overall, 0)


class TestTransfer(unittest.TestCase):
    def setUp(self):
        self.idx = BRC20Indexer()
        deploy = make_inscription(
            '{"p":"brc-20","op":"deploy","tick":"test","max":"1000","lim":"100"}',
            inscription_id="deploy:0"
        )
        self.idx.process_inscription(deploy, 1, "deploy:0")
        mint = make_inscription(
            '{"p":"brc-20","op":"mint","tick":"test","amt":"100"}',
            inscription_id="mint:0"
        )
        self.idx.process_inscription(mint, 2, "mint:0")

    def test_transfer_inscribe(self):
        transfer = make_inscription(
            '{"p":"brc-20","op":"transfer","tick":"test","amt":"50"}',
            inscription_id="transfer:0"
        )
        self.idx.process_inscription(transfer, 3, "transfer:0")
        bal = self.idx.get_address_balance("alice", "test")
        self.assertEqual(bal.overall, 100)
        self.assertEqual(bal.transferable, 50)
        self.assertEqual(bal.available, 50)

    def test_transfer_send(self):
        transfer = make_inscription(
            '{"p":"brc-20","op":"transfer","tick":"test","amt":"50"}',
            inscription_id="transfer:0"
        )
        self.idx.process_inscription(transfer, 3, "transfer:0")
        self.idx.process_transfer_send("transfer:0", "bob", "newtx:0", 4)

        alice_bal = self.idx.get_address_balance("alice", "test")
        bob_bal = self.idx.get_address_balance("bob", "test")
        self.assertEqual(alice_bal.overall, 50)
        self.assertEqual(bob_bal.overall, 50)

    def test_transfer_insufficient_balance(self):
        transfer = make_inscription(
            '{"p":"brc-20","op":"transfer","tick":"test","amt":"200"}',
            inscription_id="transfer:0"
        )
        self.idx.process_inscription(transfer, 3, "transfer:0")
        bal = self.idx.get_address_balance("alice", "test")
        self.assertEqual(bal.transferable, 0)  # rejected


class TestCaseSensitivity(unittest.TestCase):
    def test_strict_normalizes_case(self):
        idx = BRC20Indexer(strict=True)
        deploy = make_inscription(
            '{"p":"brc-20","op":"deploy","tick":"ORDI","max":"1000","lim":"100"}',
            inscription_id="d:0"
        )
        idx.process_inscription(deploy, 1, "d:0")
        self.assertIsNotNone(idx.get_token_info("ordi"))
        self.assertIsNotNone(idx.get_token_info("ORDI"))

    def test_lenient_preserves_case(self):
        idx = BRC20Indexer(strict=False)
        deploy = make_inscription(
            '{"p":"brc-20","op":"deploy","tick":"ORDI","max":"1000","lim":"100"}',
            inscription_id="d:0"
        )
        idx.process_inscription(deploy, 1, "d:0")
        self.assertIsNotNone(idx.get_token_info("ORDI"))
        self.assertIsNone(idx.get_token_info("ordi"))


if __name__ == "__main__":
    unittest.main()
