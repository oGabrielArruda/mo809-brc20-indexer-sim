from __future__ import annotations
from dataclasses import dataclass, field
from src.utxo.models import Block, Transaction, TransactionOutput
from src.utxo.blockchain import Blockchain
from .sat import SatRange, block_sat_range, classify_rarity, Rarity


@dataclass
class OrdinalUTXO:
    outpoint: str
    sat_ranges: list[SatRange]
    address: str

    @property
    def total_sats(self) -> int:
        return sum(r.count for r in self.sat_ranges)


class OrdinalTracker:
    def __init__(self):
        self._utxo_sats: dict[str, list[SatRange]] = {}
        self.metrics: list[dict] = []
        self._total_sats_mined = 0
        self._rarity_counts: dict[str, int] = {r.value: 0 for r in Rarity}

    def process_block(self, block: Block):
        coinbase_tx = block.coinbase_tx
        if coinbase_tx is None:
            return

        sat_start, sat_end = block_sat_range(block.height)
        subsidy = sat_end - sat_start

        if subsidy > 0:
            first_sat_rarity = classify_rarity(sat_start)
            self._rarity_counts[first_sat_rarity.value] += 1
            if first_sat_rarity == Rarity.COMMON:
                self._rarity_counts[Rarity.COMMON.value] += subsidy - 1
            else:
                self._rarity_counts[Rarity.COMMON.value] += subsidy - 1

        self._total_sats_mined += subsidy

        # process non-coinbase transactions first (FIFO transfer)
        for tx in block.transactions:
            if tx.is_coinbase:
                continue
            self._transfer_sats(tx)

        # assign new sats to coinbase outputs
        if subsidy > 0:
            remaining_fees_sats = self._collect_fee_sats(block)
            coinbase_ranges = [SatRange(sat_start, sat_end)] + remaining_fees_sats
            self._distribute_to_outputs(coinbase_tx, coinbase_ranges)

        self._collect_metrics(block)

    def _transfer_sats(self, tx: Transaction):
        input_ranges: list[SatRange] = []
        for inp in tx.inputs:
            outpoint = inp.outpoint
            ranges = self._utxo_sats.pop(outpoint, [])
            input_ranges.extend(ranges)

        self._distribute_to_outputs(tx, input_ranges)

    def _collect_fee_sats(self, block: Block) -> list[SatRange]:
        fee_ranges: list[SatRange] = []
        for tx in block.transactions:
            if tx.is_coinbase:
                continue
            input_total = 0
            input_ranges: list[SatRange] = []
            for inp in tx.inputs:
                outpoint = inp.outpoint
                if outpoint in self._utxo_sats:
                    for r in self._utxo_sats[outpoint]:
                        input_ranges.append(r)
                        input_total += r.count

            output_total = tx.total_output_value
            fee = input_total - output_total
            if fee > 0:
                pass  # fees already consumed during _transfer_sats
        return fee_ranges

    def _distribute_to_outputs(self, tx: Transaction, sat_ranges: list[SatRange]):
        flat_ranges = list(sat_ranges)
        range_idx = 0
        current_offset = 0

        for out in tx.outputs:
            needed = out.value
            output_ranges: list[SatRange] = []

            while needed > 0 and range_idx < len(flat_ranges):
                r = flat_ranges[range_idx]
                available = r.count - current_offset

                if available <= needed:
                    if current_offset > 0:
                        output_ranges.append(SatRange(r.start + current_offset, r.end))
                    else:
                        output_ranges.append(r)
                    needed -= available
                    range_idx += 1
                    current_offset = 0
                else:
                    start = r.start + current_offset
                    output_ranges.append(SatRange(start, start + needed))
                    current_offset += needed
                    needed = 0

            outpoint = out.outpoint
            self._utxo_sats[outpoint] = output_ranges

    def get_sat_ranges(self, outpoint: str) -> list[SatRange]:
        return self._utxo_sats.get(outpoint, [])

    def find_sat(self, sat_number: int) -> str | None:
        for outpoint, ranges in self._utxo_sats.items():
            for r in ranges:
                if r.contains(sat_number):
                    return outpoint
        return None

    def trace_sat_history(self, sat_number: int, blocks: list[Block]) -> list[dict]:
        history = []
        temp_tracker = OrdinalTracker()
        for block in blocks:
            temp_tracker.process_block(block)
            location = temp_tracker.find_sat(sat_number)
            if location:
                history.append({
                    "block": block.height,
                    "outpoint": location,
                })
        return history

    def _collect_metrics(self, block: Block):
        self.metrics.append({
            "height": block.height,
            "total_sats_mined": self._total_sats_mined,
            "tracked_utxos": len(self._utxo_sats),
            "rarity_counts": dict(self._rarity_counts),
        })
