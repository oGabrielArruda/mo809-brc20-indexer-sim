from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Optional
from src.inscriptions.models import Inscription

logger = logging.getLogger(__name__)


@dataclass
class TokenInfo:
    tick: str
    max_supply: int
    mint_limit: int
    total_minted: int = 0
    deploy_inscription_id: str = ""
    deploy_block: int = 0

    @property
    def remaining_supply(self) -> int:
        return self.max_supply - self.total_minted

    @property
    def is_fully_minted(self) -> bool:
        return self.total_minted >= self.max_supply


@dataclass
class AddressBalance:
    overall: int = 0
    transferable: int = 0

    @property
    def available(self) -> int:
        return self.overall - self.transferable


@dataclass
class TransferEntry:
    inscription_id: str
    tick: str
    amount: int
    owner: str
    utxo_outpoint: str
    used: bool = False


@dataclass
class BRC20Event:
    block_height: int
    event_type: str  # "deploy", "mint", "transfer_inscribe", "transfer_send", "invalid"
    tick: str
    data: dict
    valid: bool
    error: str = ""


class BRC20Indexer:
    def __init__(self, name: str = "default", strict: bool = True):
        self.name = name
        self.strict = strict
        self.tokens: dict[str, TokenInfo] = {}  # tick (lowercase) -> TokenInfo
        self.balances: dict[str, dict[str, AddressBalance]] = {}  # address -> tick -> balance
        self.pending_transfers: dict[str, TransferEntry] = {}  # inscription_id -> TransferEntry
        self.events: list[BRC20Event] = []
        self.metrics: list[dict] = []

    def _normalize_tick(self, tick: str) -> str:
        if self.strict:
            return tick.lower()
        return tick  # lenient: case-sensitive

    def _get_balance(self, address: str, tick: str) -> AddressBalance:
        if address not in self.balances:
            self.balances[address] = {}
        if tick not in self.balances[address]:
            self.balances[address][tick] = AddressBalance()
        return self.balances[address][tick]

    def _parse_amount(self, value) -> Optional[int]:
        try:
            if isinstance(value, str):
                n = int(value)
            elif isinstance(value, (int, float)):
                if self.strict:
                    if isinstance(value, float):
                        return None
                n = int(value)
            else:
                return None
            return n if n > 0 else None
        except (ValueError, TypeError):
            return None

    def process_inscription(self, inscription: Inscription, block_height: int,
                            utxo_outpoint: str):
        if not inscription.is_brc20:
            return

        data = inscription.brc20_data
        if data is None:
            return

        op = data.get("op", "")
        if op == "deploy":
            self._process_deploy(inscription, data, block_height)
        elif op == "mint":
            self._process_mint(inscription, data, block_height)
        elif op == "transfer":
            self._process_transfer_inscribe(inscription, data, block_height, utxo_outpoint)
        else:
            self._log_event(block_height, "invalid", data.get("tick", ""), data, False,
                           f"Unknown operation: {op}")

    def _process_deploy(self, inscription: Inscription, data: dict, block_height: int):
        tick_raw = data.get("tick", "")
        tick = self._normalize_tick(tick_raw)

        if self.strict and len(tick_raw) != 4:
            self._log_event(block_height, "deploy", tick, data, False,
                           f"Ticker must be exactly 4 characters: '{tick_raw}'")
            return

        if tick in self.tokens:
            self._log_event(block_height, "deploy", tick, data, False,
                           f"Token '{tick}' already deployed")
            return

        max_supply = self._parse_amount(data.get("max"))
        if max_supply is None:
            self._log_event(block_height, "deploy", tick, data, False,
                           f"Invalid max supply: {data.get('max')}")
            return

        lim = data.get("lim", data.get("max"))
        mint_limit = self._parse_amount(lim)
        if mint_limit is None:
            self._log_event(block_height, "deploy", tick, data, False,
                           f"Invalid mint limit: {lim}")
            return

        if mint_limit > max_supply:
            mint_limit = max_supply

        self.tokens[tick] = TokenInfo(
            tick=tick,
            max_supply=max_supply,
            mint_limit=mint_limit,
            deploy_inscription_id=inscription.inscription_id,
            deploy_block=block_height,
        )

        self._log_event(block_height, "deploy", tick, data, True)

    def _process_mint(self, inscription: Inscription, data: dict, block_height: int):
        tick_raw = data.get("tick", "")
        tick = self._normalize_tick(tick_raw)

        if tick not in self.tokens:
            self._log_event(block_height, "mint", tick, data, False,
                           f"Token '{tick}' not deployed")
            return

        token = self.tokens[tick]

        if token.is_fully_minted:
            self._log_event(block_height, "mint", tick, data, False,
                           f"Token '{tick}' fully minted")
            return

        amt = self._parse_amount(data.get("amt"))
        if amt is None:
            self._log_event(block_height, "mint", tick, data, False,
                           f"Invalid amount: {data.get('amt')}")
            return

        if amt > token.mint_limit:
            if self.strict:
                self._log_event(block_height, "mint", tick, data, False,
                               f"Amount {amt} exceeds mint limit {token.mint_limit}")
                return
            else:
                amt = token.mint_limit

        actual_mint = min(amt, token.remaining_supply)
        token.total_minted += actual_mint

        balance = self._get_balance(inscription.creator, tick)
        balance.overall += actual_mint

        self._log_event(block_height, "mint", tick, {**data, "actual_mint": actual_mint}, True)

    def _process_transfer_inscribe(self, inscription: Inscription, data: dict,
                                    block_height: int, utxo_outpoint: str):
        tick_raw = data.get("tick", "")
        tick = self._normalize_tick(tick_raw)

        if tick not in self.tokens:
            self._log_event(block_height, "transfer_inscribe", tick, data, False,
                           f"Token '{tick}' not deployed")
            return

        amt = self._parse_amount(data.get("amt"))
        if amt is None:
            self._log_event(block_height, "transfer_inscribe", tick, data, False,
                           f"Invalid amount: {data.get('amt')}")
            return

        balance = self._get_balance(inscription.creator, tick)
        if balance.available < amt:
            self._log_event(block_height, "transfer_inscribe", tick, data, False,
                           f"Insufficient available balance: have {balance.available}, need {amt}")
            return

        balance.transferable += amt

        self.pending_transfers[inscription.inscription_id] = TransferEntry(
            inscription_id=inscription.inscription_id,
            tick=tick,
            amount=amt,
            owner=inscription.creator,
            utxo_outpoint=utxo_outpoint,
        )

        self._log_event(block_height, "transfer_inscribe", tick, data, True)

    def process_transfer_send(self, inscription_id: str, new_owner: str,
                               new_outpoint: str, block_height: int):
        transfer = self.pending_transfers.get(inscription_id)
        if transfer is None or transfer.used:
            return

        tick = transfer.tick
        amt = transfer.amount
        old_owner = transfer.owner

        sender_balance = self._get_balance(old_owner, tick)
        sender_balance.overall -= amt
        sender_balance.transferable -= amt

        if new_owner != old_owner:
            receiver_balance = self._get_balance(new_owner, tick)
            receiver_balance.overall += amt

        transfer.used = True
        transfer.owner = new_owner
        transfer.utxo_outpoint = new_outpoint

        self._log_event(block_height, "transfer_send", tick, {
            "from": old_owner,
            "to": new_owner,
            "amt": amt,
            "inscription_id": inscription_id,
        }, True)

    def _log_event(self, block_height: int, event_type: str, tick: str,
                   data: dict, valid: bool, error: str = ""):
        event = BRC20Event(
            block_height=block_height,
            event_type=event_type,
            tick=tick,
            data=data,
            valid=valid,
            error=error,
        )
        self.events.append(event)
        if not valid:
            logger.debug(f"[{self.name}] INVALID {event_type} at block {block_height}: {error}")

    def get_token_info(self, tick: str) -> Optional[TokenInfo]:
        return self.tokens.get(self._normalize_tick(tick))

    def get_address_balance(self, address: str, tick: str) -> AddressBalance:
        return self._get_balance(address, self._normalize_tick(tick))

    def get_all_balances(self, tick: str) -> dict[str, AddressBalance]:
        tick = self._normalize_tick(tick)
        result = {}
        for addr, ticks in self.balances.items():
            if tick in ticks and ticks[tick].overall > 0:
                result[addr] = ticks[tick]
        return result

    def collect_metrics(self, block_height: int):
        valid_events = [e for e in self.events if e.block_height == block_height and e.valid]
        invalid_events = [e for e in self.events if e.block_height == block_height and not e.valid]

        self.metrics.append({
            "height": block_height,
            "total_tokens": len(self.tokens),
            "valid_operations": len(valid_events),
            "invalid_operations": len(invalid_events),
            "event_types": {
                t: len([e for e in valid_events if e.event_type == t])
                for t in ["deploy", "mint", "transfer_inscribe", "transfer_send"]
            },
        })

    def snapshot(self) -> dict:
        return {
            "tokens": {
                tick: {
                    "max_supply": t.max_supply,
                    "total_minted": t.total_minted,
                    "mint_limit": t.mint_limit,
                }
                for tick, t in self.tokens.items()
            },
            "balances": {
                addr: {
                    tick: {"overall": b.overall, "transferable": b.transferable, "available": b.available}
                    for tick, b in ticks.items()
                    if b.overall > 0
                }
                for addr, ticks in self.balances.items()
                if any(b.overall > 0 for b in ticks.values())
            },
        }
