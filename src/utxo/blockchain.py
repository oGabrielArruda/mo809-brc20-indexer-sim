from __future__ import annotations
from dataclasses import dataclass, field
from .models import Block, Transaction, TransactionInput, TransactionOutput, UTXOSet

HALVING_INTERVAL = 210_000
INITIAL_SUBSIDY = 50 * 100_000_000  # 50 BTC in sats


def compute_subsidy(height: int) -> int:
    halvings = height // HALVING_INTERVAL
    if halvings >= 64:
        return 0
    return INITIAL_SUBSIDY >> halvings


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


class Blockchain:
    def __init__(self):
        self.blocks: list[Block] = []
        self.utxo_set = UTXOSet()
        self.metrics: list[dict] = []

    @property
    def height(self) -> int:
        return len(self.blocks)

    def create_coinbase_tx(self, miner_address: str, height: int, extra_reward: int = 0) -> Transaction:
        subsidy = compute_subsidy(height)
        coinbase_input = TransactionInput(
            prev_tx_id="0" * 64,
            prev_index=0xFFFFFFFF,
            address="coinbase",
        )
        coinbase_output = TransactionOutput(
            value=subsidy + extra_reward,
            address=miner_address,
        )
        return Transaction(
            inputs=[coinbase_input],
            outputs=[coinbase_output],
            is_coinbase=True,
        )

    def create_transaction(
        self,
        sender: str,
        recipients: list[tuple[str, int]],
        fee: int = 0,
    ) -> Transaction:
        total_needed = sum(amount for _, amount in recipients) + fee
        utxos = self.utxo_set.get_utxos_for_address(sender)
        utxos.sort(key=lambda u: u.value)

        selected = []
        collected = 0
        for utxo in utxos:
            selected.append(utxo)
            collected += utxo.value
            if collected >= total_needed:
                break

        if collected < total_needed:
            raise ValueError(
                f"Insufficient funds for {sender}: have {collected}, need {total_needed}"
            )

        inputs = [
            TransactionInput(
                prev_tx_id=utxo.tx_id,
                prev_index=utxo.index,
                address=sender,
            )
            for utxo in selected
        ]

        outputs = [
            TransactionOutput(value=amount, address=addr)
            for addr, amount in recipients
        ]

        change = collected - total_needed
        if change > 0:
            outputs.append(TransactionOutput(value=change, address=sender))

        return Transaction(inputs=inputs, outputs=outputs)

    def validate_transaction(self, tx: Transaction) -> ValidationResult:
        errors = []

        if tx.is_coinbase:
            return ValidationResult(valid=True)

        if not tx.inputs:
            errors.append("Transaction has no inputs")
            return ValidationResult(valid=False, errors=errors)

        if not tx.outputs:
            errors.append("Transaction has no outputs")
            return ValidationResult(valid=False, errors=errors)

        total_in = 0
        for inp in tx.inputs:
            utxo = self.utxo_set.get(inp.outpoint)
            if utxo is None:
                errors.append(f"Input {inp.outpoint} references non-existent UTXO")
                continue
            if utxo.spent:
                errors.append(f"Input {inp.outpoint} is already spent (double-spend)")
                continue
            if utxo.address != inp.address:
                errors.append(
                    f"Input {inp.outpoint} address mismatch: "
                    f"UTXO owned by {utxo.address}, spent by {inp.address}"
                )
                continue
            total_in += utxo.value

        total_out = tx.total_output_value

        if total_out > total_in:
            errors.append(
                f"Output value ({total_out}) exceeds input value ({total_in})"
            )

        for out in tx.outputs:
            if out.value <= 0:
                errors.append(f"Output has non-positive value: {out.value}")

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def add_block(self, block: Block) -> ValidationResult:
        if block.height != self.height:
            return ValidationResult(
                valid=False,
                errors=[f"Invalid height: expected {self.height}, got {block.height}"],
            )

        if not block.transactions:
            return ValidationResult(valid=False, errors=["Block has no transactions"])

        if not block.transactions[0].is_coinbase:
            return ValidationResult(valid=False, errors=["First transaction must be coinbase"])

        all_errors = []
        for i, tx in enumerate(block.transactions):
            result = self.validate_transaction(tx)
            if not result.valid:
                all_errors.extend([f"tx[{i}]: {e}" for e in result.errors])

        if all_errors:
            return ValidationResult(valid=False, errors=all_errors)

        # apply: spend inputs, create outputs
        for tx in block.transactions:
            if not tx.is_coinbase:
                for inp in tx.inputs:
                    self.utxo_set.spend(inp.outpoint)
            for out in tx.outputs:
                self.utxo_set.add(out)

        self.blocks.append(block)
        self._collect_metrics(block)

        return ValidationResult(valid=True)

    def mine_block(
        self,
        miner_address: str,
        transactions: list[Transaction] | None = None,
    ) -> Block:
        height = self.height
        txs = transactions or []

        fees = 0
        for tx in txs:
            for inp in tx.inputs:
                utxo = self.utxo_set.get(inp.outpoint)
                if utxo:
                    fees += utxo.value
            fees -= tx.total_output_value

        coinbase = self.create_coinbase_tx(miner_address, height, extra_reward=fees)
        block = Block(height=height, transactions=[coinbase] + txs)

        result = self.add_block(block)
        if not result.valid:
            raise ValueError(f"Failed to mine block: {result.errors}")

        return block

    def _collect_metrics(self, block: Block):
        self.metrics.append({
            "height": block.height,
            "num_transactions": len(block.transactions),
            "utxo_set_size": self.utxo_set.unspent_count,
            "total_utxo_value": self.utxo_set.total_value,
        })
