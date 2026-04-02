#!/usr/bin/env python3
"""Thread pool throughput benchmark for intelligence pipeline.

Measures bars/sec throughput at various ThreadPoolExecutor pool sizes
using synthetic plugin workloads. Does not require live Kafka or DB.

Results depend on hardware (24-core system), GIL behavior, and plugin
I/O vs CPU mix. Re-run after significant plugin count changes.

Usage:
    .venv/bin/python production/scripts/benchmark_thread_pool.py

Output: CSV to stdout + summary table to stderr.
"""

import asyncio
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor

POOL_SIZES = [28, 48, 64, 96, 128]
NUM_PLUGINS = 27  # Match TIER_I1 count
NUM_BARS = 200  # Bars to process per pool size
PLUGIN_SLEEP_MS = 1.0  # Simulated per-plugin latency (1ms)


def _synthetic_plugin_work() -> dict:
    """Simulate a single plugin execution with realistic I/O-like latency."""
    time.sleep(PLUGIN_SLEEP_MS / 1000)
    return {"value": 1.0, "signal": False}


async def _benchmark_pool_size(pool_size: int, num_bars: int) -> dict:
    """Benchmark a single pool size by processing num_bars bars.

    For each bar, submits NUM_PLUGINS tasks concurrently via asyncio.gather
    + run_in_executor — matching the pattern in IntelligencePipelineAgent._run_i1.

    Args:
        pool_size: ThreadPoolExecutor max_workers to test.
        num_bars: Number of bars to process.

    Returns:
        Dict with pool_size, bars_per_sec, total_sec, avg_bar_ms.
    """
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="bench") as executor:
        start = time.perf_counter()
        for _ in range(num_bars):
            await asyncio.gather(
                *[
                    loop.run_in_executor(executor, _synthetic_plugin_work)
                    for _ in range(NUM_PLUGINS)
                ]
            )
        elapsed = time.perf_counter() - start

    bars_per_sec = num_bars / elapsed
    avg_bar_ms = (elapsed / num_bars) * 1000

    return {
        "pool_size": pool_size,
        "bars_per_sec": round(bars_per_sec, 2),
        "total_sec": round(elapsed, 3),
        "avg_bar_ms": round(avg_bar_ms, 2),
    }


async def _amain() -> None:
    """Run benchmark across all pool sizes and emit CSV to stdout."""
    print("# Starting thread pool benchmark...", file=sys.stderr)
    print(
        f"# Configuration: {len(POOL_SIZES)} pool sizes, "
        f"{NUM_PLUGINS} plugins/bar, {NUM_BARS} bars/size, "
        f"{PLUGIN_SLEEP_MS}ms simulated plugin latency",
        file=sys.stderr,
    )
    print("", file=sys.stderr)

    results = []
    for pool_size in POOL_SIZES:
        print(f"  Testing pool_size={pool_size}...", file=sys.stderr, end="", flush=True)
        result = await _benchmark_pool_size(pool_size, NUM_BARS)
        results.append(result)
        print(
            f" {result['bars_per_sec']:.1f} bars/sec "
            f"({result['avg_bar_ms']:.1f}ms/bar)",
            file=sys.stderr,
        )

    # CSV output to stdout
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=["pool_size", "bars_per_sec", "total_sec", "avg_bar_ms"],
    )
    writer.writeheader()
    writer.writerows(results)

    # Summary table to stderr
    best = max(results, key=lambda r: r["bars_per_sec"])
    print("", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("RESULTS SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(
        f"{'pool_size':>10}  {'bars_per_sec':>14}  {'avg_bar_ms':>12}",
        file=sys.stderr,
    )
    print("-" * 44, file=sys.stderr)
    for r in results:
        marker = " <-- BEST" if r["pool_size"] == best["pool_size"] else ""
        print(
            f"{r['pool_size']:>10}  {r['bars_per_sec']:>14.2f}  {r['avg_bar_ms']:>12.2f}{marker}",
            file=sys.stderr,
        )
    print("", file=sys.stderr)
    print(
        f"Recommended pool size: {best['pool_size']} "
        f"({best['bars_per_sec']:.1f} bars/sec)",
        file=sys.stderr,
    )
    print(
        f"Set INTELLIGENCE_THREAD_POOL_WORKERS={best['pool_size']} in .env",
        file=sys.stderr,
    )


if __name__ == "__main__":
    asyncio.run(_amain())
