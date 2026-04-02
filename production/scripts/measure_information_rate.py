#!/usr/bin/env python3
"""
Measure Information Rate: How often do plugin outputs actually change?

Renaissance question: "What's the marginal information content of each plugin output?"

If a plugin's output only changes 20% of the time, use incremental computation (cache 80%).
If outputs change frequently, need full processing.
"""

import asyncio

import pandas as pd

from src.core.script_utils import get_script_db

INTELLIGENCE_TIERS = ["i1", "i2", "i3", "i4", "i5", "i6", "i7"]
CHANGE_RATE_THRESHOLD = 0.30  # below this → incremental computation (caching) is worthwhile


async def measure_information_rate(
    symbols: list[str] | None = None,
    timeframe: str = "1m",
    sample_size: int = 5000
) -> dict:
    """Measure how often plugin outputs change between consecutive bars.

    Args:
        symbols: List of symbols to analyze (None = all)
        timeframe: Timeframe to analyze
        sample_size: Max bars to analyze per symbol

    Returns:
        Dictionary with change frequency per plugin
    """
    db = await get_script_db()

    try:
        async with db.get_connection() as conn:
            if symbols is None:
                symbols_query = """
                    SELECT DISTINCT symbol
                    FROM intelligence_features
                    WHERE tf = $1
                    ORDER BY symbol
                """
                rows = await conn.fetch(symbols_query, timeframe)
                symbols = [row["symbol"] for row in rows]

            print(f"\n=== Analyzing {len(symbols)} symbols ({timeframe} timeframe) ===\n")

            tier_plugins = {tier: [] for tier in INTELLIGENCE_TIERS}

            for symbol in symbols:
                query = """
                    SELECT ts, symbol, tf,
                           i1, i2, i3, i4, i5, i6, i7
                    FROM intelligence_features
                    WHERE symbol = $1 AND tf = $2
                    ORDER BY ts ASC
                    LIMIT $3
                """

                rows = await conn.fetch(query, symbol, timeframe, sample_size)

                if len(rows) < 2:
                    print(f"⚠ {symbol}: skipping (only {len(rows)} feature records)")
                    continue

                print(f"\n{symbol}: {len(rows)} feature records")

                for tier in INTELLIGENCE_TIERS:
                    prev_output = None
                    change_count = 0
                    total_count = 0

                    for row in rows:
                        current_output = row[tier]

                        if current_output is None:
                            continue

                        total_count += 1

                        if prev_output is not None and prev_output != current_output:
                            change_count += 1

                        prev_output = current_output

                    if total_count > 0:
                        change_rate = change_count / total_count
                        tier_plugins[tier].append({
                            "symbol": symbol,
                            "changes": change_count,
                            "total": total_count,
                            "change_rate": change_rate
                        })

                        if tier == "i1":  # Only print I1 details
                            print(f"  {tier.upper()}: {change_count}/{total_count} changes "
                                  f"({change_rate*100:.1f}%)")

            print("\n=== INFORMATION RATE BY TIER ===\n")

            tier_stats = {}

            for tier in INTELLIGENCE_TIERS:
                if not tier_plugins[tier]:
                    continue

                df = pd.DataFrame(tier_plugins[tier])

                weighted_rate = (df["change_rate"] * df["total"]).sum() / df["total"].sum()
                p50 = df["change_rate"].median()
                p75 = df["change_rate"].quantile(0.75)
                p90 = df["change_rate"].quantile(0.90)

                tier_stats[tier] = {
                    "weighted_change_rate": float(weighted_rate),
                    "median_change_rate": float(p50),
                    "p75_change_rate": float(p75),
                    "p90_change_rate": float(p90),
                    "total_bars": int(df["total"].sum()),
                    "total_changes": int(df["changes"].sum()),
                }

                print(f"{tier.upper()}: {weighted_rate*100:.1f}% change rate "
                      f"(median: {p50*100:.1f}%, P75: {p75*100:.1f}%, P90: {p90*100:.1f}%)")

            print("\n=== RENAISSANCE RECOMMENDATION ===\n")

            i1_rate = tier_stats.get("i1", {}).get("weighted_change_rate", 1.0)
            i7_rate = tier_stats.get("i7", {}).get("weighted_change_rate", 1.0)

            if i1_rate < CHANGE_RATE_THRESHOLD:
                print("✓ INCREMENTAL COMPUTATION recommended for I1")
                print(f"  → Cache I1 outputs (only {i1_rate*100:.1f}% change rate)")
                print(f"  → Expected cache hit rate: {100 - i1_rate*100:.1f}%")
                improvement = 1 / (1 - i1_rate * 0.7)
                print(f"  → Throughput improvement: {improvement:.1f}x (without parallelization)")
            else:
                print("✗ INCREMENTAL COMPUTATION not recommended for I1")
                print(f"  → I1 outputs change frequently ({i1_rate*100:.1f}% rate)")
                print("  → Caching would have low hit rate")

            if i7_rate < CHANGE_RATE_THRESHOLD:
                print("\n✓ INCREMENTAL COMPUTATION recommended for I7")
                print(f"  → Cache I7 outputs (only {i7_rate*100:.1f}% change rate)")
                print(f"  → Expected cache hit rate: {100 - i7_rate*100:.1f}%")
            else:
                print("\n✗ INCREMENTAL COMPUTATION not recommended for I7")
                print(f"  → I7 outputs change frequently ({i7_rate*100:.1f}% rate)")

            print("\n=== OVERALL STRATEGY ===\n")

            if i1_rate < CHANGE_RATE_THRESHOLD or i7_rate < CHANGE_RATE_THRESHOLD:
                print("RECOMMENDATION: Incremental computation")
                print("→ Implement output caching for low-change-rate tiers")
                print("→ Defer parallelization until caching is proven insufficient")
            else:
                print("RECOMMENDATION: Parallelization")
                print("→ Outputs change too frequently for caching to help")
                print("→ Proceed with I1/I7 parallelization design")

            return tier_stats

    finally:
        await db.close()


async def main():
    """Run information rate measurement."""
    result = await measure_information_rate(
        symbols=None,  # All symbols
        timeframe="1m",
        sample_size=5000
    )

    print("\n=== RESULT SAVED ===\n")
    print(f"I1 change rate: {result.get('i1', {}).get('weighted_change_rate', 0)*100:.1f}%")
    print(f"I7 change rate: {result.get('i7', {}).get('weighted_change_rate', 0)*100:.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
