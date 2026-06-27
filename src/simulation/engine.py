from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from src.utxo.models import Transaction, TransactionInput, TransactionOutput
from src.utxo.blockchain import Blockchain
from src.ordinals.tracker import OrdinalTracker
from src.ordinals.sat import SatRange
from src.inscriptions.models import InscriptionRegistry, Inscription
from src.brc20.indexer import BRC20Indexer
from src.brc20.comparator import IndexerComparator

logger = logging.getLogger(__name__)


@dataclass
class SimulationConfig:
    num_blocks: int = 100
    miner_address: str = "miner_01"
    enable_ordinals: bool = True
    enable_inscriptions: bool = True
    enable_dual_indexer: bool = True


class SimulationEngine:
    def __init__(self, config: SimulationConfig | None = None):
        self.config = config or SimulationConfig()
        self.blockchain = Blockchain()
        self.ordinal_tracker = OrdinalTracker()
        self.inscription_registry = InscriptionRegistry()
        self.indexer_strict = BRC20Indexer(name="strict", strict=True)
        self.indexer_lenient = BRC20Indexer(name="lenient", strict=False)
        self.comparator = IndexerComparator(self.indexer_strict, self.indexer_lenient)
        self._inscription_queue: list[dict] = []
        self._pending_commit_txs: dict[str, dict] = {}  # commit_tx_id -> data

    def mine_empty_block(self) -> None:
        block = self.blockchain.mine_block(self.config.miner_address)
        if self.config.enable_ordinals:
            self.ordinal_tracker.process_block(block)

    def mine_blocks(self, count: int) -> None:
        for _ in range(count):
            self.mine_empty_block()

    def transfer_btc(self, sender: str, recipient: str, amount: int,
                     fee: int = 1000) -> Transaction:
        tx = self.blockchain.create_transaction(sender, [(recipient, amount)], fee=fee)
        block = self.blockchain.mine_block(self.config.miner_address, [tx])
        if self.config.enable_ordinals:
            self.ordinal_tracker.process_block(block)
        return tx

    def deploy_brc20(self, deployer: str, tick: str, max_supply: int,
                     mint_limit: int, fee: int = 1000) -> dict:
        brc20_json = json.dumps({
            "p": "brc-20",
            "op": "deploy",
            "tick": tick,
            "max": str(max_supply),
            "lim": str(mint_limit),
        })
        return self._inscribe(deployer, "application/json", brc20_json, fee)

    def mint_brc20(self, minter: str, tick: str, amount: int,
                   fee: int = 1000) -> dict:
        brc20_json = json.dumps({
            "p": "brc-20",
            "op": "mint",
            "tick": tick,
            "amt": str(amount),
        })
        return self._inscribe(minter, "application/json", brc20_json, fee)

    def transfer_brc20(self, sender: str, recipient: str, tick: str,
                       amount: int, fee: int = 1000) -> dict:
        brc20_json = json.dumps({
            "p": "brc-20",
            "op": "transfer",
            "tick": tick,
            "amt": str(amount),
        })
        result = self._inscribe(sender, "application/json", brc20_json, fee)

        if result.get("inscription") is None:
            return result

        inscription_id = result["inscription"].inscription_id
        reveal_tx = result["reveal_tx"]
        reveal_outpoint = f"{reveal_tx.tx_id}:{0}"

        send_tx = self._send_inscription_utxo(sender, recipient, reveal_outpoint, fee)
        if send_tx:
            block_height = self.blockchain.height - 1
            new_outpoint = f"{send_tx.tx_id}:{0}"
            self.indexer_strict.process_transfer_send(
                inscription_id, recipient, new_outpoint, block_height)
            if self.config.enable_dual_indexer:
                self.indexer_lenient.process_transfer_send(
                    inscription_id, recipient, new_outpoint, block_height)
            result["send_tx"] = send_tx

        return result

    def _inscribe(self, creator: str, content_type: str, content: str,
                  fee: int) -> dict:
        # Phase 1: Commit transaction
        commit_tx = self.blockchain.create_transaction(
            creator, [(creator, 10000)], fee=fee
        )
        commit_block = self.blockchain.mine_block(
            self.config.miner_address, [commit_tx]
        )
        if self.config.enable_ordinals:
            self.ordinal_tracker.process_block(commit_block)

        self.inscription_registry.create_commit(
            commit_tx.tx_id, content_type, content, creator
        )

        # Phase 2: Reveal transaction
        commit_outpoint = f"{commit_tx.tx_id}:0"
        reveal_input = TransactionInput(
            prev_tx_id=commit_tx.tx_id,
            prev_index=0,
            address=creator,
        )
        reveal_output = TransactionOutput(value=9000, address=creator)
        reveal_tx = Transaction(
            inputs=[reveal_input],
            outputs=[reveal_output],
            witness_data={"content_type": content_type, "content": content},
        )

        reveal_block = self.blockchain.mine_block(
            self.config.miner_address, [reveal_tx]
        )
        if self.config.enable_ordinals:
            self.ordinal_tracker.process_block(reveal_block)

        # determine which sat gets the inscription (first unoccupied sat in the output)
        reveal_outpoint = f"{reveal_tx.tx_id}:0"
        sat_ranges = self.ordinal_tracker.get_sat_ranges(reveal_outpoint)
        sat_number = None
        if sat_ranges:
            for r in sat_ranges:
                for s in range(r.start, r.end):
                    if s not in self.inscription_registry._by_sat:
                        sat_number = s
                        break
                if sat_number is not None:
                    break
        if sat_number is None:
            sat_number = hash(reveal_tx.tx_id) % (2**48)
            while sat_number in self.inscription_registry._by_sat:
                sat_number += 1

        inscription = self.inscription_registry.create_reveal(
            commit_tx.tx_id, reveal_tx.tx_id, 0, sat_number, reveal_block.height
        )

        if inscription:
            self.inscription_registry.collect_metrics(reveal_block.height)
            self.indexer_strict.process_inscription(
                inscription, reveal_block.height, reveal_outpoint)
            self.indexer_strict.collect_metrics(reveal_block.height)
            if self.config.enable_dual_indexer:
                self.indexer_lenient.process_inscription(
                    inscription, reveal_block.height, reveal_outpoint)
                self.indexer_lenient.collect_metrics(reveal_block.height)

        return {
            "commit_tx": commit_tx,
            "reveal_tx": reveal_tx,
            "inscription": inscription,
            "sat_number": sat_number,
        }

    def _send_inscription_utxo(self, sender: str, recipient: str,
                                utxo_outpoint: str, fee: int) -> Optional[Transaction]:
        utxo = self.blockchain.utxo_set.get(utxo_outpoint)
        if utxo is None or utxo.spent:
            return None

        parts = utxo_outpoint.split(":")
        send_input = TransactionInput(
            prev_tx_id=parts[0],
            prev_index=int(parts[1]),
            address=sender,
        )
        send_output = TransactionOutput(value=utxo.value - fee, address=recipient)
        send_tx = Transaction(inputs=[send_input], outputs=[send_output])

        block = self.blockchain.mine_block(self.config.miner_address, [send_tx])
        if self.config.enable_ordinals:
            self.ordinal_tracker.process_block(block)

        return send_tx

    def compare_indexers(self) -> list:
        block_height = self.blockchain.height - 1
        return self.comparator.compare(block_height)

    def get_full_metrics(self) -> dict:
        return {
            "blockchain": self.blockchain.metrics,
            "ordinals": self.ordinal_tracker.metrics,
            "inscriptions": self.inscription_registry.metrics,
            "indexer_strict": self.indexer_strict.metrics,
            "indexer_lenient": self.indexer_lenient.metrics,
            "comparator": self.comparator.summary(),
        }
