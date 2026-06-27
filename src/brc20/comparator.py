from __future__ import annotations
from dataclasses import dataclass, field
from .indexer import BRC20Indexer


@dataclass
class Divergence:
    block_height: int
    category: str  # "token_existence", "balance_mismatch", "supply_mismatch"
    detail: str
    indexer_a_value: str
    indexer_b_value: str


class IndexerComparator:
    def __init__(self, indexer_a: BRC20Indexer, indexer_b: BRC20Indexer):
        self.indexer_a = indexer_a
        self.indexer_b = indexer_b
        self.divergences: list[Divergence] = []

    def compare(self, block_height: int) -> list[Divergence]:
        new_divergences = []

        new_divergences.extend(self._compare_tokens(block_height))
        new_divergences.extend(self._compare_balances(block_height))

        self.divergences.extend(new_divergences)
        return new_divergences

    def _compare_tokens(self, block_height: int) -> list[Divergence]:
        divs = []
        all_ticks = set(self.indexer_a.tokens.keys()) | set(self.indexer_b.tokens.keys())

        for tick in all_ticks:
            a_has = tick in self.indexer_a.tokens
            b_has = tick in self.indexer_b.tokens

            if a_has != b_has:
                divs.append(Divergence(
                    block_height=block_height,
                    category="token_existence",
                    detail=f"Token '{tick}'",
                    indexer_a_value="exists" if a_has else "missing",
                    indexer_b_value="exists" if b_has else "missing",
                ))
                continue

            if a_has and b_has:
                ta = self.indexer_a.tokens[tick]
                tb = self.indexer_b.tokens[tick]
                if ta.total_minted != tb.total_minted:
                    divs.append(Divergence(
                        block_height=block_height,
                        category="supply_mismatch",
                        detail=f"Token '{tick}' total_minted",
                        indexer_a_value=str(ta.total_minted),
                        indexer_b_value=str(tb.total_minted),
                    ))

        return divs

    def _compare_balances(self, block_height: int) -> list[Divergence]:
        divs = []

        all_addresses = set()
        for addr in self.indexer_a.balances:
            all_addresses.add(addr)
        for addr in self.indexer_b.balances:
            all_addresses.add(addr)

        all_ticks = set(self.indexer_a.tokens.keys()) | set(self.indexer_b.tokens.keys())

        for addr in all_addresses:
            for tick in all_ticks:
                bal_a = self.indexer_a.get_address_balance(addr, tick)
                bal_b = self.indexer_b.get_address_balance(addr, tick)

                if bal_a.overall != bal_b.overall:
                    divs.append(Divergence(
                        block_height=block_height,
                        category="balance_mismatch",
                        detail=f"'{tick}' balance of {addr}",
                        indexer_a_value=f"overall={bal_a.overall}",
                        indexer_b_value=f"overall={bal_b.overall}",
                    ))
                elif bal_a.transferable != bal_b.transferable:
                    divs.append(Divergence(
                        block_height=block_height,
                        category="balance_mismatch",
                        detail=f"'{tick}' transferable of {addr}",
                        indexer_a_value=f"transferable={bal_a.transferable}",
                        indexer_b_value=f"transferable={bal_b.transferable}",
                    ))

        return divs

    def summary(self) -> dict:
        by_category = {}
        for d in self.divergences:
            by_category.setdefault(d.category, []).append(d)

        return {
            "total_divergences": len(self.divergences),
            "by_category": {cat: len(divs) for cat, divs in by_category.items()},
            "first_divergence_block": min((d.block_height for d in self.divergences), default=None),
            "divergences": [
                {
                    "block": d.block_height,
                    "category": d.category,
                    "detail": d.detail,
                    "a": d.indexer_a_value,
                    "b": d.indexer_b_value,
                }
                for d in self.divergences
            ],
        }
