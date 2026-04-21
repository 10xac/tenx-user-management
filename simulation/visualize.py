"""
Simulation Results Visualizer
=============================
Generates charts and summary tables from simulation JSON results.

Usage:
    # Visualize the latest run
    python -m simulation.visualize

    # Visualize a specific run
    python -m simulation.visualize --file simulation/results/simulation_20240101_120000.json

    # Export charts as PNG files
    python -m simulation.visualize --export-dir simulation/results/charts/

Output:
    - Latency vs Tier (per endpoint)
    - Throughput vs Tier (per endpoint)
    - Error Rate vs Tier
    - P95 Latency Heatmap
    - Response Time Distribution
    - Summary table (console)
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

from simulation.config import RESULTS_DIR


# ============================================================================
# Data loading
# ============================================================================

def load_latest_result() -> tuple[dict, Path]:
    """Load the most recent simulation result JSON."""
    files = sorted(RESULTS_DIR.glob("simulation_*.json"), reverse=True)
    if not files:
        print("No simulation results found in", RESULTS_DIR)
        sys.exit(1)
    path = files[0]
    print(f"Loading: {path.name}")
    with open(path) as f:
        return json.load(f), path


def load_result(filepath: str) -> tuple[dict, Path]:
    path = Path(filepath)
    with open(path) as f:
        return json.load(f), path


# ============================================================================
# Chart builders
# ============================================================================

COLORS = {
    "single": "#2196F3",
    "admin_single": "#4CAF50",
    "batch": "#FF9800",
    "webhook": "#9C27B0",
    "env_check": "#607D8B",
    "env_refresh": "#E91E63",
}


def _group_by_endpoint(results: list[dict]) -> dict:
    """Group results by endpoint name."""
    groups = {}
    for r in results:
        ep = r["endpoint"]
        groups.setdefault(ep, []).append(r)
    return groups


def chart_latency_vs_tier(results: list[dict], export_dir: Path | None = None):
    """Line chart: P50, P95, P99 latency vs user tier for each endpoint."""
    groups = _group_by_endpoint(results)

    fig, axes = plt.subplots(2, 3, figsize=(18, 10), sharey=False)
    fig.suptitle("Response Latency vs User Tier", fontsize=16, fontweight="bold")
    axes = axes.flatten()

    for idx, (ep, data) in enumerate(sorted(groups.items())):
        if idx >= len(axes):
            break
        ax = axes[idx]
        data_sorted = sorted(data, key=lambda x: x["tier"])
        tiers = [d["tier"] for d in data_sorted]
        p50 = [d["latency_ms"]["median"] for d in data_sorted]
        p95 = [d["latency_ms"]["p95"] for d in data_sorted]
        p99 = [d["latency_ms"]["p99"] for d in data_sorted]

        color = COLORS.get(ep, "#333")
        ax.plot(tiers, p50, "o-", label="P50 (median)", color=color, alpha=0.6)
        ax.plot(tiers, p95, "s--", label="P95", color=color, alpha=0.85)
        ax.plot(tiers, p99, "^:", label="P99", color=color, alpha=1.0)
        ax.fill_between(tiers, p50, p95, alpha=0.1, color=color)

        ax.set_title(ep.replace("_", " ").title(), fontweight="bold")
        ax.set_xlabel("User Tier")
        ax.set_ylabel("Latency (ms)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(ticker.ScalarFormatter())

    # Hide unused subplots
    for idx in range(len(groups), len(axes)):
        axes[idx].set_visible(False)

    plt.tight_layout()
    if export_dir:
        export_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(export_dir / "latency_vs_tier.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ Latency vs Tier chart")


def chart_throughput_vs_tier(results: list[dict], export_dir: Path | None = None):
    """Bar chart: Throughput (RPS) vs user tier per endpoint."""
    groups = _group_by_endpoint(results)

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.suptitle("Throughput (Requests/sec) vs User Tier", fontsize=16, fontweight="bold")

    endpoints = sorted(groups.keys())
    all_tiers = sorted(set(r["tier"] for r in results))
    x = np.arange(len(all_tiers))
    width = 0.8 / max(len(endpoints), 1)

    for i, ep in enumerate(endpoints):
        data_sorted = sorted(groups[ep], key=lambda d: d["tier"])
        tier_map = {d["tier"]: d["throughput_rps"] for d in data_sorted}
        rps_values = [tier_map.get(t, 0) for t in all_tiers]
        offset = (i - len(endpoints) / 2 + 0.5) * width
        ax.bar(x + offset, rps_values, width, label=ep.replace("_", " ").title(),
               color=COLORS.get(ep, "#999"), alpha=0.85)

    ax.set_xlabel("User Tier")
    ax.set_ylabel("Requests / Second")
    ax.set_xticks(x)
    ax.set_xticklabels([str(t) for t in all_tiers])
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    if export_dir:
        fig.savefig(export_dir / "throughput_vs_tier.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ Throughput vs Tier chart")


def chart_error_rate(results: list[dict], export_dir: Path | None = None):
    """Line chart: Error rate (%) vs tier per endpoint."""
    groups = _group_by_endpoint(results)

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.suptitle("Error Rate (%) vs User Tier", fontsize=16, fontweight="bold")

    for ep in sorted(groups.keys()):
        data_sorted = sorted(groups[ep], key=lambda d: d["tier"])
        tiers = [d["tier"] for d in data_sorted]
        error_rates = [d["error_rate_pct"] for d in data_sorted]
        ax.plot(tiers, error_rates, "o-", label=ep.replace("_", " ").title(),
                color=COLORS.get(ep, "#333"), linewidth=2)

    ax.set_xlabel("User Tier")
    ax.set_ylabel("Error Rate (%)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(ticker.ScalarFormatter())
    ax.set_ylim(bottom=-1)

    plt.tight_layout()
    if export_dir:
        fig.savefig(export_dir / "error_rate_vs_tier.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ Error Rate vs Tier chart")


def chart_p95_heatmap(results: list[dict], export_dir: Path | None = None):
    """Heatmap: P95 latency across endpoints × tiers."""
    groups = _group_by_endpoint(results)
    endpoints = sorted(groups.keys())
    all_tiers = sorted(set(r["tier"] for r in results))

    matrix = []
    for ep in endpoints:
        tier_map = {d["tier"]: d["latency_ms"]["p95"] for d in groups[ep]}
        row = [tier_map.get(t, 0) for t in all_tiers]
        matrix.append(row)

    fig, ax = plt.subplots(figsize=(12, 5))
    im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto")

    ax.set_xticks(range(len(all_tiers)))
    ax.set_xticklabels([str(t) for t in all_tiers])
    ax.set_yticks(range(len(endpoints)))
    ax.set_yticklabels([e.replace("_", " ").title() for e in endpoints])

    # Annotate cells
    for i in range(len(endpoints)):
        for j in range(len(all_tiers)):
            val = matrix[i][j]
            ax.text(j, i, f"{val:.0f}", ha="center", va="center",
                    fontsize=9, color="black" if val < max(max(r) for r in matrix) * 0.6 else "white")

    fig.colorbar(im, label="P95 Latency (ms)")
    fig.suptitle("P95 Latency Heatmap (Endpoint × Tier)", fontsize=14, fontweight="bold")

    plt.tight_layout()
    if export_dir:
        fig.savefig(export_dir / "p95_heatmap.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ P95 Latency Heatmap")


def chart_response_distribution(results: list[dict], export_dir: Path | None = None):
    """Histogram: Response time distribution for each endpoint (all tiers combined)."""
    groups = _group_by_endpoint(results)

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("Response Time Distribution per Endpoint", fontsize=16, fontweight="bold")
    axes = axes.flatten()

    for idx, (ep, data) in enumerate(sorted(groups.items())):
        if idx >= len(axes):
            break
        ax = axes[idx]
        all_times = []
        for d in data:
            all_times.extend([r["elapsed_ms"] for r in d["requests"]])

        if all_times:
            ax.hist(all_times, bins=50, color=COLORS.get(ep, "#999"),
                    alpha=0.75, edgecolor="white")
            ax.axvline(np.median(all_times), color="red", linestyle="--",
                       label=f"Median: {np.median(all_times):.0f}ms")
            p95 = np.percentile(all_times, 95)
            ax.axvline(p95, color="orange", linestyle=":",
                       label=f"P95: {p95:.0f}ms")

        ax.set_title(ep.replace("_", " ").title(), fontweight="bold")
        ax.set_xlabel("Response Time (ms)")
        ax.set_ylabel("Count")
        ax.legend(fontsize=8)

    for idx in range(len(groups), len(axes)):
        axes[idx].set_visible(False)

    plt.tight_layout()
    if export_dir:
        fig.savefig(export_dir / "response_distribution.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ Response Time Distribution chart")


def chart_success_vs_failure(results: list[dict], export_dir: Path | None = None):
    """Stacked bar: Success vs Failure counts per tier."""
    all_tiers = sorted(set(r["tier"] for r in results))
    successes = []
    failures = []
    for t in all_tiers:
        tier_results = [r for r in results if r["tier"] == t]
        successes.append(sum(r["successful"] for r in tier_results))
        failures.append(sum(r["failed"] for r in tier_results))

    fig, ax = plt.subplots(figsize=(12, 6))
    x = range(len(all_tiers))
    ax.bar(x, successes, label="Successful", color="#4CAF50", alpha=0.85)
    ax.bar(x, failures, bottom=successes, label="Failed", color="#F44336", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels([str(t) for t in all_tiers])
    ax.set_xlabel("User Tier")
    ax.set_ylabel("Request Count")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("Success vs Failure per Tier", fontsize=14, fontweight="bold")

    plt.tight_layout()
    if export_dir:
        fig.savefig(export_dir / "success_vs_failure.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ Success vs Failure chart")


# ============================================================================
# Console summary table
# ============================================================================

def print_summary_table(data: dict):
    """Print a formatted summary to the console."""
    meta = data["metadata"]
    summary = data.get("summary", {})

    print("\n" + "=" * 90)
    print(f"  SIMULATION RESULTS SUMMARY")
    run_id = meta.get("run_id", "unknown")
    base_url = meta.get("base_url", "unknown")
    timestamp = meta.get("timestamp", "unknown")
    run_stage = meta.get("run_stage", "unknown")
    print(f"  Run ID: {run_id}    Target: {base_url}")
    print(f"  Timestamp: {timestamp}    Run Stage: {run_stage}")
    print("=" * 90)

    if summary:
        print(f"\n  Overall: {summary['total_requests']} requests, "
              f"{summary['total_successful']} ok, {summary['total_failed']} err "
              f"({summary['overall_error_rate_pct']}% error rate)")
        lat = summary.get("overall_latency_ms", {})
        print(f"  Latency: mean={lat.get('mean', 0)}ms, "
              f"median={lat.get('median', 0)}ms, "
              f"p95={lat.get('p95', 0)}ms, p99={lat.get('p99', 0)}ms")

    # Per-endpoint-tier table
    print(f"\n  {'Endpoint':<18} {'Tier':>6} {'Reqs':>6} {'OK':>6} {'Err':>5} "
          f"{'ErrRate':>8} {'P50ms':>8} {'P95ms':>8} {'P99ms':>8} {'RPS':>8}")
    print("  " + "-" * 95)

    for r in sorted(data.get("results", []), key=lambda x: (x["endpoint"], x["tier"])):
        lat = r["latency_ms"]
        print(f"  {r['endpoint']:<18} {r['tier']:>6} {r['total_requests']:>6} "
              f"{r['successful']:>6} {r['failed']:>5} "
              f"{r['error_rate_pct']:>7.1f}% "
              f"{lat['median']:>8.1f} {lat['p95']:>8.1f} {lat['p99']:>8.1f} "
              f"{r['throughput_rps']:>8.1f}")

    print()


# ============================================================================
# Main visualize
# ============================================================================

def visualize(filepath: str | None = None, export_dir: str | None = None):
    """Generate all charts and print summary."""
    if filepath:
        data, path = load_result(filepath)
    else:
        data, path = load_latest_result()

    results = data.get("results", [])
    if not results:
        print("No results to visualize.")
        return

    export = Path(export_dir) if export_dir else RESULTS_DIR / "charts"

    print(f"\nGenerating visualizations → {export}/")
    chart_latency_vs_tier(results, export)
    chart_throughput_vs_tier(results, export)
    chart_error_rate(results, export)
    chart_p95_heatmap(results, export)
    chart_response_distribution(results, export)
    chart_success_vs_failure(results, export)

    print_summary_table(data)
    print(f"  Charts saved to: {export}/\n")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Visualize simulation results")
    parser.add_argument("--file", type=str, help="Path to specific simulation JSON")
    parser.add_argument("--export-dir", type=str, help="Directory to export charts")
    args = parser.parse_args()

    visualize(filepath=args.file, export_dir=args.export_dir)


if __name__ == "__main__":
    main()
