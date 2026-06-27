from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


@dataclass
class TransactionOutput:
    value: int  # satoshis
    address: str
    tx_id: str = ""
    index: int = 0
    spent: bool = False
    script_type: str = "P2PKH"

    @property
    def outpoint(self) -> str:
        return f"{self.tx_id}:{self.index}"


@dataclass
class TransactionInput:
    prev_tx_id: str
    prev_index: int
    address: str  # simplified: who is spending (replaces unlocking script)

    @property
    def outpoint(self) -> str:
        return f"{self.prev_tx_id}:{self.prev_index}"


@dataclass
class Transaction:
    inputs: list[TransactionInput]
    outputs: list[TransactionOutput]
    tx_id: str = ""
    is_coinbase: bool = False
    witness_data: Optional[dict] = None  # used later for inscriptions

    def __post_init__(self):
        if not self.tx_id:
            self.tx_id = self._compute_id()
        for i, out in enumerate(self.outputs):
            out.tx_id = self.tx_id
            out.index = i

    def _compute_id(self) -> str:
        content = json.dumps({
            "inputs": [(inp.prev_tx_id, inp.prev_index) for inp in self.inputs],
            "outputs": [(out.value, out.address) for out in self.outputs],
            "coinbase": self.is_coinbase,
        }, sort_keys=True)
        return _sha256(content)

    @property
    def total_input_value(self) -> int:
        return 0  # resolved externally by blockchain

    @property
    def total_output_value(self) -> int:
        return sum(out.value for out in self.outputs)


@dataclass
class Block:
    height: int
    transactions: list[Transaction] = field(default_factory=list)
    subsidy: int = 50 * 100_000_000  # 50 BTC in sats (initial reward)

    @property
    def coinbase_tx(self) -> Optional[Transaction]:
        if self.transactions and self.transactions[0].is_coinbase:
            return self.transactions[0]
        return None

    def total_fees(self, utxo_set: dict[str, TransactionOutput]) -> int:
        total = 0
        for tx in self.transactions:
            if tx.is_coinbase:
                continue
            input_val = sum(
                utxo_set[inp.outpoint].value
                for inp in tx.inputs
                if inp.outpoint in utxo_set
            )
            total += input_val - tx.total_output_value
        return total


class UTXOSet:
    def __init__(self):
        self._utxos: dict[str, TransactionOutput] = {}
        self._spent: set[str] = set()

    def add(self, utxo: TransactionOutput):
        self._utxos[utxo.outpoint] = utxo

    def get(self, outpoint: str) -> Optional[TransactionOutput]:
        return self._utxos.get(outpoint)

    def spend(self, outpoint: str) -> TransactionOutput:
        utxo = self._utxos.get(outpoint)
        if utxo is None:
            raise ValueError(f"UTXO {outpoint} not found")
        if utxo.spent:
            raise ValueError(f"UTXO {outpoint} already spent (double-spend)")
        utxo.spent = True
        self._spent.add(outpoint)
        return utxo

    def is_unspent(self, outpoint: str) -> bool:
        utxo = self._utxos.get(outpoint)
        return utxo is not None and not utxo.spent

    @property
    def unspent_count(self) -> int:
        return sum(1 for u in self._utxos.values() if not u.spent)

    @property
    def total_value(self) -> int:
        return sum(u.value for u in self._utxos.values() if not u.spent)

    def get_utxos_for_address(self, address: str) -> list[TransactionOutput]:
        return [
            u for u in self._utxos.values()
            if u.address == address and not u.spent
        ]

    def get_balance(self, address: str) -> int:
        return sum(u.value for u in self.get_utxos_for_address(address))
