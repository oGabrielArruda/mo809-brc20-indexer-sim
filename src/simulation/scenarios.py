from __future__ import annotations
import json
import csv
import os
import logging
from pathlib import Path

from .engine import SimulationEngine, SimulationConfig

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
RESULTS_DIR = DATA_DIR / "results"
LOGS_DIR = DATA_DIR / "logs"


def ensure_dirs():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def scenario_basic() -> dict:
    """Scenario 1: Basic flow - deploy, mint, transfer a single token."""
    logger.info("=== Scenario: Basic BRC-20 Flow ===")
    engine = SimulationEngine(SimulationConfig(miner_address="miner"))

    # fund addresses
    engine.mine_blocks(5)
    for addr in ["alice", "bob", "charlie"]:
        engine.transfer_btc("miner", addr, 100_000_000)

    # deploy token "ordi"
    logger.info("Deploying 'ordi' token...")
    deploy_result = engine.deploy_brc20("alice", "ordi", max_supply=21_000_000, mint_limit=1000)

    # mint tokens
    logger.info("Minting tokens...")
    mint_results = []
    for i in range(10):
        minter = ["alice", "bob", "charlie"][i % 3]
        result = engine.mint_brc20(minter, "ordi", 1000)
        mint_results.append(result)

    # transfer
    logger.info("Transferring tokens...")
    transfer_result = engine.transfer_brc20("alice", "bob", "ordi", 500)

    # collect final state
    engine.compare_indexers()

    return {
        "scenario": "basic",
        "final_block_height": engine.blockchain.height,
        "token_info": {
            "strict": _token_snapshot(engine.indexer_strict, "ordi"),
            "lenient": _token_snapshot(engine.indexer_lenient, "ordi"),
        },
        "balances": {
            "strict": _balance_snapshot(engine.indexer_strict, "ordi"),
            "lenient": _balance_snapshot(engine.indexer_lenient, "ordi"),
        },
        "metrics": engine.get_full_metrics(),
        "events_strict": [_event_to_dict(e) for e in engine.indexer_strict.events],
        "events_lenient": [_event_to_dict(e) for e in engine.indexer_lenient.events],
    }


def scenario_stress() -> dict:
    """Scenario 2: Multiple tokens, many mints, supply cap edge cases."""
    logger.info("=== Scenario: Stress Test ===")
    engine = SimulationEngine(SimulationConfig(miner_address="miner"))

    engine.mine_blocks(5)
    addresses = [f"user_{i:02d}" for i in range(10)]
    for addr in addresses:
        engine.transfer_btc("miner", addr, 500_000_000)

    # deploy multiple tokens
    tokens = [
        ("abcd", 10_000, 100),
        ("test", 5_000, 50),
        ("rare", 100, 10),
    ]
    for tick, max_s, lim in tokens:
        engine.deploy_brc20(addresses[0], tick, max_s, lim)

    # mass mint - including attempts past cap
    mint_count = {"valid": 0, "invalid": 0}
    for i in range(150):
        addr = addresses[i % len(addresses)]
        tick = tokens[i % len(tokens)][0]
        try:
            result = engine.mint_brc20(addr, tick, tokens[i % len(tokens)][2])
            # check if the last event was valid
            last_event = engine.indexer_strict.events[-1]
            if last_event.valid:
                mint_count["valid"] += 1
            else:
                mint_count["invalid"] += 1
        except Exception as e:
            mint_count["invalid"] += 1
            logger.debug(f"Mint failed: {e}")

    # transfers between users
    for i in range(5):
        try:
            engine.transfer_brc20(addresses[i], addresses[i + 5], "abcd", 10)
        except Exception:
            pass

    engine.compare_indexers()

    result = {
        "scenario": "stress",
        "final_block_height": engine.blockchain.height,
        "mint_counts": mint_count,
        "tokens": {},
        "metrics": engine.get_full_metrics(),
    }
    for tick, _, _ in tokens:
        result["tokens"][tick] = {
            "strict": _token_snapshot(engine.indexer_strict, tick),
            "lenient": _token_snapshot(engine.indexer_lenient, tick),
        }
    return result


def scenario_inconsistency() -> dict:
    """Scenario 3: Cases that cause divergence between strict and lenient indexers."""
    logger.info("=== Scenario: Indexer Inconsistency ===")
    engine = SimulationEngine(SimulationConfig(miner_address="miner"))

    engine.mine_blocks(5)
    for addr in ["alice", "bob"]:
        for _ in range(5):
            engine.transfer_btc("miner", addr, 1_000_000_000)

    # Case 1: Deploy with mixed-case ticker
    # strict normalizes to lowercase, lenient keeps as-is

    # Deploy "ORDI" (uppercase) - both indexers accept
    engine.deploy_brc20("alice", "ORDI", max_supply=21_000_000, mint_limit=1000)

    # Deploy "ordi" (lowercase)
    # strict: duplicate (normalizes to "ordi" which already exists) -> rejected
    # lenient: new token "ordi" (case-sensitive, different from "ORDI") -> accepted
    engine.deploy_brc20("bob", "ordi", max_supply=10_000_000, mint_limit=500)

    # Mint on "ordi":
    # strict: mints on the existing "ordi" token (from first deploy, limit=1000)
    # lenient: mints on "ordi" (from second deploy, limit=500)
    for _ in range(5):
        engine.mint_brc20("alice", "ordi", 500)

    # Mint on "ORDI":
    # strict: mints on "ordi" (normalized, same token)
    # lenient: mints on "ORDI" (first deploy, limit=1000)
    for _ in range(5):
        engine.mint_brc20("bob", "ORDI", 1000)

    # Case 2: Transfer to show balance divergence
    try:
        engine.transfer_brc20("alice", "bob", "ordi", 200)
    except Exception:
        pass

    # Force a comparison at multiple points
    divergences = engine.compare_indexers()

    return {
        "scenario": "inconsistency",
        "final_block_height": engine.blockchain.height,
        "divergences": engine.comparator.summary(),
        "strict_snapshot": engine.indexer_strict.snapshot(),
        "lenient_snapshot": engine.indexer_lenient.snapshot(),
        "events_strict": [_event_to_dict(e) for e in engine.indexer_strict.events],
        "events_lenient": [_event_to_dict(e) for e in engine.indexer_lenient.events],
        "metrics": engine.get_full_metrics(),
    }


def scenario_sat_tracking() -> dict:
    """Scenario 4: Track specific sats through multiple transactions."""
    logger.info("=== Scenario: Sat Tracking ===")
    engine = SimulationEngine(SimulationConfig(miner_address="miner"))

    engine.mine_blocks(3)

    # track the first sat of block 0 (mythic) and first sat of block 1 (uncommon)
    from src.ordinals.sat import block_sat_range, classify_rarity

    tracked_sats = []
    for h in range(3):
        start, end = block_sat_range(h)
        rarity = classify_rarity(start)
        tracked_sats.append({
            "sat_number": start,
            "mined_in_block": h,
            "rarity": rarity.value,
        })

    # do some transfers that move sats around
    engine.transfer_btc("miner", "alice", 1_000_000_000)
    engine.transfer_btc("alice", "bob", 500_000_000)
    engine.transfer_btc("bob", "charlie", 250_000_000)

    # find where tracked sats ended up
    for sat_info in tracked_sats:
        location = engine.ordinal_tracker.find_sat(sat_info["sat_number"])
        sat_info["final_location"] = location
        history = engine.ordinal_tracker.trace_sat_history(
            sat_info["sat_number"], engine.blockchain.blocks
        )
        sat_info["history"] = history

    return {
        "scenario": "sat_tracking",
        "final_block_height": engine.blockchain.height,
        "tracked_sats": tracked_sats,
        "ordinal_metrics": engine.ordinal_tracker.metrics,
        "blockchain_metrics": engine.blockchain.metrics,
    }


def scenario_edge_cases() -> dict:
    """Scenario 5: Invalid operations, malformed data, edge cases."""
    logger.info("=== Scenario: Edge Cases ===")
    engine = SimulationEngine(SimulationConfig(miner_address="miner"))

    engine.mine_blocks(5)
    engine.transfer_btc("miner", "alice", 500_000_000)
    engine.transfer_btc("miner", "bob", 500_000_000)

    cases = []

    # Case 1: Deploy with invalid ticker length
    r = engine.deploy_brc20("alice", "ab", max_supply=1000, mint_limit=100)
    cases.append({"case": "short_ticker", "inscription": r.get("inscription") is not None})

    # Case 2: Deploy with valid ticker
    engine.deploy_brc20("alice", "good", max_supply=1000, mint_limit=100)

    # Case 3: Duplicate deploy
    r = engine.deploy_brc20("bob", "good", max_supply=2000, mint_limit=200)
    cases.append({"case": "duplicate_deploy", "inscription_created": r.get("inscription") is not None})

    # Case 4: Mint non-existent token
    r = engine.mint_brc20("alice", "fake", 100)
    cases.append({"case": "mint_nonexistent", "inscription_created": r.get("inscription") is not None})

    # Case 5: Mint exceeding limit
    r = engine.mint_brc20("alice", "good", 200)  # limit is 100
    cases.append({"case": "mint_over_limit", "inscription_created": r.get("inscription") is not None})

    # Case 6: Valid mints up to supply
    for i in range(11):  # 11 * 100 = 1100 > 1000 cap
        engine.mint_brc20("alice", "good", 100)

    # Case 7: Transfer more than available
    try:
        engine.transfer_brc20("alice", "bob", "good", 99999)
        cases.append({"case": "transfer_over_balance", "error": False})
    except Exception as e:
        cases.append({"case": "transfer_over_balance", "error": str(e)})

    engine.compare_indexers()

    return {
        "scenario": "edge_cases",
        "final_block_height": engine.blockchain.height,
        "cases": cases,
        "strict_events": [_event_to_dict(e) for e in engine.indexer_strict.events],
        "strict_snapshot": engine.indexer_strict.snapshot(),
        "metrics": engine.get_full_metrics(),
    }


def run_all_scenarios() -> dict:
    ensure_dirs()
    all_results = {}

    scenarios = [
        ("basic", scenario_basic),
        ("stress", scenario_stress),
        ("inconsistency", scenario_inconsistency),
        ("sat_tracking", scenario_sat_tracking),
        ("edge_cases", scenario_edge_cases),
    ]

    for name, func in scenarios:
        logger.info(f"\n{'='*60}")
        logger.info(f"Running scenario: {name}")
        logger.info(f"{'='*60}")
        try:
            result = func()
            all_results[name] = result
            _save_result(name, result)
            logger.info(f"Scenario {name} completed successfully")
        except Exception as e:
            logger.error(f"Scenario {name} failed: {e}", exc_info=True)
            all_results[name] = {"error": str(e)}

    # save combined results
    summary_path = RESULTS_DIR / "all_results.json"
    with open(summary_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    logger.info(f"All results saved to {summary_path}")

    return all_results


def _save_result(name: str, result: dict):
    path = RESULTS_DIR / f"scenario_{name}.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    # save blockchain metrics as CSV
    metrics = result.get("metrics", {}).get("blockchain", [])
    if metrics:
        csv_path = RESULTS_DIR / f"scenario_{name}_blockchain.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=metrics[0].keys())
            writer.writeheader()
            writer.writerows(metrics)


def _token_snapshot(indexer, tick) -> dict:
    info = indexer.get_token_info(tick)
    if info is None:
        return {"exists": False}
    return {
        "exists": True,
        "max_supply": info.max_supply,
        "total_minted": info.total_minted,
        "remaining": info.remaining_supply,
    }


def _balance_snapshot(indexer, tick) -> dict:
    balances = indexer.get_all_balances(tick)
    return {
        addr: {
            "overall": b.overall,
            "transferable": b.transferable,
            "available": b.available,
        }
        for addr, b in balances.items()
    }


def _event_to_dict(event) -> dict:
    return {
        "block": event.block_height,
        "type": event.event_type,
        "tick": event.tick,
        "valid": event.valid,
        "error": event.error,
    }
