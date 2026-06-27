from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Inscription:
    inscription_id: str  # reveal_tx_id:output_index
    content_type: str    # e.g. "application/json", "text/plain", "image/png"
    content: str         # the raw content
    sat_number: int      # which sat this is inscribed on
    creator: str         # address of who inscribed it
    block_height: int    # when it was revealed

    @property
    def is_brc20(self) -> bool:
        if self.content_type != "application/json":
            return False
        try:
            data = json.loads(self.content)
            return data.get("p") == "brc-20"
        except (json.JSONDecodeError, AttributeError):
            return False

    @property
    def brc20_data(self) -> Optional[dict]:
        if not self.is_brc20:
            return None
        return json.loads(self.content)


@dataclass
class CommitRevealPair:
    commit_tx_id: str
    reveal_tx_id: str
    inscription: Inscription
    committed: bool = False
    revealed: bool = False


class InscriptionRegistry:
    def __init__(self):
        self._inscriptions: dict[str, Inscription] = {}  # inscription_id -> Inscription
        self._by_sat: dict[int, str] = {}  # sat_number -> inscription_id
        self._pending_commits: dict[str, dict] = {}  # commit_tx_id -> commit data
        self.metrics: list[dict] = []
        self._total_inscriptions = 0
        self._total_brc20_inscriptions = 0

    def create_commit(self, commit_tx_id: str, content_type: str, content: str,
                      creator: str) -> str:
        self._pending_commits[commit_tx_id] = {
            "content_type": content_type,
            "content": content,
            "creator": creator,
        }
        return commit_tx_id

    def create_reveal(self, commit_tx_id: str, reveal_tx_id: str,
                      output_index: int, sat_number: int,
                      block_height: int) -> Optional[Inscription]:
        commit_data = self._pending_commits.pop(commit_tx_id, None)
        if commit_data is None:
            return None

        inscription_id = f"{reveal_tx_id}:{output_index}"

        if sat_number in self._by_sat:
            return None

        inscription = Inscription(
            inscription_id=inscription_id,
            content_type=commit_data["content_type"],
            content=commit_data["content"],
            sat_number=sat_number,
            creator=commit_data["creator"],
            block_height=block_height,
        )

        self._inscriptions[inscription_id] = inscription
        self._by_sat[sat_number] = inscription_id
        self._total_inscriptions += 1
        if inscription.is_brc20:
            self._total_brc20_inscriptions += 1

        return inscription

    def get_inscription(self, inscription_id: str) -> Optional[Inscription]:
        return self._inscriptions.get(inscription_id)

    def get_inscription_by_sat(self, sat_number: int) -> Optional[Inscription]:
        insc_id = self._by_sat.get(sat_number)
        if insc_id:
            return self._inscriptions.get(insc_id)
        return None

    def get_all_brc20_inscriptions(self) -> list[Inscription]:
        return [i for i in self._inscriptions.values() if i.is_brc20]

    def collect_metrics(self, block_height: int):
        self.metrics.append({
            "height": block_height,
            "total_inscriptions": self._total_inscriptions,
            "total_brc20_inscriptions": self._total_brc20_inscriptions,
            "pending_commits": len(self._pending_commits),
        })
