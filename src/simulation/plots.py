"""Generate plots from simulation results for the LaTeX report."""
from __future__ import annotations
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

RESULTS_DIR = Path(__file__).parent.parent.parent / "data" / "results"
FIGURES_DIR = Path(__file__).parent.parent.parent / "report" / "figures"


def ensure_dirs():
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)


def load_scenario(name: str) -> dict:
    path = RESULTS_DIR / f"scenario_{name}.json"
    with open(path) as f:
        return json.load(f)


def plot_utxo_growth():
    """Plot UTXO set growth over blocks (basic scenario)."""
    data = load_scenario("basic")
    metrics = data["metrics"]["blockchain"]

    heights = [m["height"] for m in metrics]
    utxo_sizes = [m["utxo_set_size"] for m in metrics]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(heights, utxo_sizes, "b-", linewidth=1.5)
    ax.set_xlabel("Block Height")
    ax.set_ylabel("UTXO Set Size")
    ax.set_title("UTXO Set Growth Over Blocks")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "utxo_growth.pdf")
    plt.close(fig)


def plot_brc20_events():
    """Plot BRC-20 operation distribution (basic scenario)."""
    data = load_scenario("basic")
    events = data["events_strict"]

    valid_types = {}
    invalid_count = 0
    for e in events:
        if e["valid"]:
            t = e["type"]
            valid_types[t] = valid_types.get(t, 0) + 1
        else:
            invalid_count += 1

    labels = list(valid_types.keys()) + (["invalid"] if invalid_count else [])
    values = list(valid_types.values()) + ([invalid_count] if invalid_count else [])
    colors = ["#2ecc71", "#3498db", "#e67e22", "#9b59b6", "#e74c3c"]

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(labels, values, color=colors[:len(labels)])
    ax.set_ylabel("Count")
    ax.set_title("BRC-20 Operations Distribution")
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                str(val), ha="center", va="bottom", fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "brc20_events.pdf")
    plt.close(fig)


def plot_indexer_divergence():
    """Plot indexer divergence comparison (inconsistency scenario)."""
    data = load_scenario("inconsistency")
    divs = data["divergences"]["divergences"]

    categories = {}
    for d in divs:
        cat = d["category"]
        categories[cat] = categories.get(cat, 0) + 1

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    # Left: divergence counts by category
    ax = axes[0]
    cats = list(categories.keys())
    counts = list(categories.values())
    colors = ["#e74c3c", "#f39c12", "#3498db"]
    ax.bar(cats, counts, color=colors[:len(cats)])
    ax.set_ylabel("Number of Divergences")
    ax.set_title("Divergences by Category")
    for i, (c, v) in enumerate(zip(cats, counts)):
        ax.text(i, v + 0.1, str(v), ha="center", fontweight="bold")

    # Right: per-token balance comparison (shows where divergence really is)
    strict_bal = data["strict_snapshot"]["balances"]
    lenient_bal = data["lenient_snapshot"]["balances"]

    # Build (address, token) -> balance for each indexer
    labels = []
    strict_vals = []
    lenient_vals = []

    all_addresses = sorted(set(list(strict_bal.keys()) + list(lenient_bal.keys())))
    all_ticks = set()
    for addr in all_addresses:
        if addr in strict_bal:
            all_ticks.update(strict_bal[addr].keys())
        if addr in lenient_bal:
            all_ticks.update(lenient_bal[addr].keys())
    all_ticks = sorted(all_ticks)

    for addr in all_addresses:
        for tick in all_ticks:
            s_val = strict_bal.get(addr, {}).get(tick, {}).get("overall", 0)
            l_val = lenient_bal.get(addr, {}).get(tick, {}).get("overall", 0)
            if s_val > 0 or l_val > 0:
                labels.append(f"{addr}\n\"{tick}\"")
                strict_vals.append(s_val)
                lenient_vals.append(l_val)

    ax = axes[1]
    x = range(len(labels))
    width = 0.35
    ax.bar([i - width/2 for i in x], strict_vals, width, label="Strict Indexer", color="#2ecc71")
    ax.bar([i + width/2 for i in x], lenient_vals, width, label="Lenient Indexer", color="#e74c3c")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Token Balance")
    ax.set_title("Per-Token Balance: Strict vs Lenient")
    ax.legend()

    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "indexer_divergence.pdf")
    plt.close(fig)


def plot_supply_evolution():
    """Plot token supply evolution from the stress scenario."""
    data = load_scenario("stress")

    # Extract per-token minted supply over time from events
    tokens_info = data["tokens"]
    token_names = list(tokens_info.keys())

    # Build cumulative valid/invalid counts from indexer metrics
    events = data["metrics"]["indexer_strict"]
    cum_valid = []
    cum_invalid = []
    heights = []
    cv, ci = 0, 0
    for m in events:
        cv += m["valid_operations"]
        ci += m["invalid_operations"]
        cum_valid.append(cv)
        cum_invalid.append(ci)
        heights.append(m["height"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))

    # Left: final supply state per token
    ticks = []
    minted = []
    remaining = []
    for tick in token_names:
        info = tokens_info[tick]["strict"]
        if info["exists"]:
            ticks.append(f'"{tick}"')
            minted.append(info["total_minted"])
            remaining.append(info["max_supply"] - info["total_minted"])

    x = range(len(ticks))
    ax1.bar(x, minted, color="#2ecc71", label="Minted")
    ax1.bar(x, remaining, bottom=minted, color="#bdc3c7", label="Remaining")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(ticks)
    ax1.set_ylabel("Token Supply")
    ax1.set_title("Token Supply: Minted vs Remaining")
    ax1.legend()
    for i, (m, r) in enumerate(zip(minted, remaining)):
        ax1.text(i, m/2, str(m), ha="center", va="center", fontweight="bold", fontsize=9)
        if r > 0:
            ax1.text(i, m + r/2, str(r), ha="center", va="center", fontsize=8, color="gray")

    # Right: cumulative valid vs invalid operations
    ax2.plot(heights, cum_valid, "g-", linewidth=2, label=f"Valid ({cum_valid[-1]})")
    ax2.plot(heights, cum_invalid, "r-", linewidth=2, label=f"Invalid ({cum_invalid[-1]})")
    ax2.set_xlabel("Block Height")
    ax2.set_ylabel("Cumulative Operations")
    ax2.set_title("Cumulative BRC-20 Operations")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "supply_evolution.pdf")
    plt.close(fig)


def plot_sat_tracking():
    """Plot sat tracking - show the concept of sat ranges in UTXOs."""
    data = load_scenario("sat_tracking")
    tracked = data["tracked_sats"]
    blockchain_metrics = data["blockchain_metrics"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))

    # Left: sat journey through blocks (those that have history)
    colors_map = {
        "mythic": "#9b59b6",
        "uncommon": "#3498db",
        "common": "#95a5a6",
    }
    sats_with_history = [s for s in tracked if len(s.get("history", [])) > 1]
    if not sats_with_history:
        sats_with_history = tracked

    for i, sat_info in enumerate(sats_with_history):
        history = sat_info.get("history", [])
        if not history:
            continue
        blocks = [h["block"] for h in history]
        y_vals = [i] * len(blocks)
        rarity = sat_info["rarity"]
        color = colors_map.get(rarity, "#2ecc71")

        # show each outpoint change as a different marker
        outpoints = [h["outpoint"][:8] + "..." for h in history]
        unique_outpoints = []
        for op in outpoints:
            if op not in unique_outpoints:
                unique_outpoints.append(op)

        ax1.scatter(blocks, y_vals, c=color, s=100, zorder=3)
        ax1.plot(blocks, y_vals, c=color, alpha=0.4, linewidth=2)

        # annotate outpoint changes
        prev_op = None
        for b, op in zip(blocks, outpoints):
            if op != prev_op:
                ax1.annotate(op, (b, i), textcoords="offset points",
                            xytext=(0, 10), fontsize=6, ha="center", rotation=30)
                prev_op = op

    sat_labels = [f"Sat {s['sat_number']}\n({s['rarity']})" for s in sats_with_history]
    ax1.set_xlabel("Block Height")
    ax1.set_yticks(range(len(sats_with_history)))
    ax1.set_yticklabels(sat_labels, fontsize=8)
    ax1.set_title("Sat Movement Across Transactions")
    ax1.grid(True, alpha=0.3)

    # Right: rarity distribution table as a bar chart
    rarity_data = {
        "Mythic\n(sat 0)": 1,
        "Uncommon\n(1st sat/block)": len([s for s in tracked if s["rarity"] == "uncommon"]),
        "Common\n(all others)": max(0, len(tracked) - 1 -
                                    len([s for s in tracked if s["rarity"] == "uncommon"])),
    }
    # use the ordinal metrics rarity counts if available
    ord_metrics = data.get("ordinal_metrics", [])
    if ord_metrics:
        last = ord_metrics[-1]
        rc = last.get("rarity_counts", {})
        rarity_data = {}
        for rarity_name in ["mythic", "uncommon", "common"]:
            count = rc.get(rarity_name, 0)
            if count > 0:
                rarity_data[rarity_name.capitalize()] = count

    colors = ["#9b59b6", "#3498db", "#95a5a6", "#e74c3c", "#f39c12"]
    bars = ax2.bar(list(rarity_data.keys()), list(rarity_data.values()),
                   color=colors[:len(rarity_data)])
    ax2.set_ylabel("Count (first sats)")
    ax2.set_title(f"Sat Rarity Distribution ({len(blockchain_metrics)} blocks)")
    for bar, val in zip(bars, rarity_data.values()):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                str(val), ha="center", fontweight="bold")
    ax2.set_yscale("log")

    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "sat_tracking.pdf")
    plt.close(fig)


def plot_edge_cases():
    """Plot edge case validation results."""
    data = load_scenario("edge_cases")
    events = data["strict_events"]

    valid_count = sum(1 for e in events if e["valid"])
    invalid_count = sum(1 for e in events if not e["valid"])

    # Group invalids by error type
    error_types = {}
    for e in events:
        if not e["valid"]:
            err = e["error"]
            if "already deployed" in err:
                key = "Duplicate Deploy"
            elif "not deployed" in err:
                key = "Token Not Found"
            elif "exceeds mint limit" in err:
                key = "Exceeds Limit"
            elif "fully minted" in err:
                key = "Supply Exhausted"
            elif "Insufficient" in err:
                key = "Insufficient Balance"
            elif "Ticker must be" in err:
                key = "Invalid Ticker"
            else:
                key = "Other"
            error_types[key] = error_types.get(key, 0) + 1

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))

    ax1.bar(["Valid", "Invalid"], [valid_count, invalid_count],
            color=["#2ecc71", "#e74c3c"])
    ax1.set_title("Operation Validation Results")
    ax1.set_ylabel("Count")
    for i, v in enumerate([valid_count, invalid_count]):
        ax1.text(i, v + 0.2, str(v), ha="center", fontweight="bold")

    if error_types:
        labels = list(error_types.keys())
        sizes = list(error_types.values())
        ax2.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90,
                colors=["#e74c3c", "#f39c12", "#e67e22", "#d35400", "#c0392b", "#8e44ad"])
        ax2.set_title("Invalid Operations by Reason")

    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "edge_cases.pdf")
    plt.close(fig)


def generate_all_plots():
    ensure_dirs()
    print("Generating plots...")

    plot_utxo_growth()
    print("  - utxo_growth.pdf")

    plot_brc20_events()
    print("  - brc20_events.pdf")

    plot_indexer_divergence()
    print("  - indexer_divergence.pdf")

    plot_supply_evolution()
    print("  - supply_evolution.pdf")

    plot_sat_tracking()
    print("  - sat_tracking.pdf")

    plot_edge_cases()
    print("  - edge_cases.pdf")

    print(f"All plots saved to {FIGURES_DIR}")


if __name__ == "__main__":
    generate_all_plots()
