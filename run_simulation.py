#!/usr/bin/env python3
"""Run all BRC-20 indexer simulation scenarios and generate data."""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.simulation.scenarios import run_all_scenarios

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "data" / "logs" / "simulation.log"),
    ],
)

if __name__ == "__main__":
    results = run_all_scenarios()
    print("\n" + "=" * 60)
    print("SIMULATION COMPLETE")
    print("=" * 60)

    for name, result in results.items():
        if "error" in result:
            print(f"  [{name}] FAILED: {result['error']}")
        else:
            height = result.get("final_block_height", "?")
            print(f"  [{name}] OK - final block height: {height}")

    print(f"\nResults saved to: data/results/")
