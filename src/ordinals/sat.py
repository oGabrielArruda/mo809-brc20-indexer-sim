from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from src.utxo.blockchain import HALVING_INTERVAL, compute_subsidy


DIFFICULTY_ADJUSTMENT_INTERVAL = 2016
SATS_PER_BTC = 100_000_000


class Rarity(Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"
    MYTHIC = "mythic"


def classify_rarity(sat_number: int) -> Rarity:
    if sat_number == 0:
        return Rarity.MYTHIC

    block_height, offset = sat_to_block_and_offset(sat_number)

    is_block_start = (offset == 0)
    is_difficulty_adj = (block_height % DIFFICULTY_ADJUSTMENT_INTERVAL == 0)
    is_halving = (block_height % HALVING_INTERVAL == 0) and block_height > 0

    if is_block_start and is_halving and is_difficulty_adj:
        return Rarity.LEGENDARY
    if is_block_start and is_halving:
        return Rarity.EPIC
    if is_block_start and is_difficulty_adj:
        return Rarity.RARE
    if is_block_start:
        return Rarity.UNCOMMON
    return Rarity.COMMON


def sat_to_block_and_offset(sat_number: int) -> tuple[int, int]:
    total = 0
    height = 0
    while True:
        subsidy = compute_subsidy(height)
        if subsidy == 0:
            break
        if total + subsidy > sat_number:
            return height, sat_number - total
        total += subsidy
        height += 1
    return height, sat_number - total


def block_sat_range(height: int) -> tuple[int, int]:
    start = 0
    for h in range(height):
        start += compute_subsidy(h)
    subsidy = compute_subsidy(height)
    return start, start + subsidy


@dataclass(frozen=True)
class SatRange:
    start: int  # inclusive
    end: int    # exclusive

    @property
    def count(self) -> int:
        return self.end - self.start

    def contains(self, sat: int) -> bool:
        return self.start <= sat < self.end

    def split_at(self, amount: int) -> tuple[SatRange, SatRange]:
        if amount <= 0 or amount >= self.count:
            raise ValueError(f"Cannot split range of {self.count} at {amount}")
        mid = self.start + amount
        return SatRange(self.start, mid), SatRange(mid, self.end)

    def __repr__(self) -> str:
        return f"[{self.start}..{self.end})"
