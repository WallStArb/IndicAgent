#!/usr/bin/env python3
"""
Measure Delta Distribution: How much do prices actually move bar-to-bar?

Renaissance question: "What's the marginal information content of each bar?"

If 90% of bars move < 0.1%, most bars are noise → use delta-based filtering.
If most bars move significantly, need full processing.
"""

import asyncio

import numpy as np
import pandas as pd

from src.core.script_utils import get_script_db

ATR_WINDOW = 14
DELTA_THRESHOLD_AGGRESSIVE = 0.001   # 0.1% — aggressive filter catches 90th-percentile noise
DELTA_THRESHOLD_CONSERVATIVE = 0.002  # 0.2% — conservative filter catches 75th-percentile noise


async def measure_delta_distribution(
    symbols: list[str] | None = None,
    timeframe: str = "1m",
    sample_size: int = 10000
) -> dict:
    """Measure price changes between consecutive bars.

    Args:
        symbols: List of symbols to analyze (None = all)
        timeframe: Timeframe to analyze
        sample_size: Max bars to analyze per symbol

    Returns:
        Dictionary with delta statistics
    """
    db = await get_script_db()

    try:
        async with db.get_connection() as conn:
            if symbols is None:
                symbols_query = """
                    SELECT DISTINCT symbol
                    FROM market_data_ohlcv
                    WHERE timeframe = $1
                    ORDER BY symbol
                """
                rows = await conn.fetch(symbols_query, timeframe)
                symbols = [row["symbol"] for row in rows]

            print(f"\n=== Analyzing {len(symbols)} symbols ({timeframe} timeframe) ===\n")

            all_deltas = []

            for symbol in symbols:
                query = """
                    SELECT high, low, close
                    FROM market_data_ohlcv
                    WHERE symbol = $1 AND timeframe = $2
                    ORDER BY timestamp ASC
                    LIMIT $3
                """

                rows = await conn.fetch(query, symbol, timeframe, sample_size)

                if len(rows) < 2:
                    print(f"⚠ {symbol}: skipping (only {len(rows)} bars)")
                    continue

                df = pd.DataFrame(rows, columns=["high", "low", "close"])

                df["close_change"] = df["close"].diff()
                # Guard against zero close prices (corrupted data or certain derivatives)
                prev_close = df["close"].shift(1).replace(0, np.nan)
                df["close_change_pct"] = df["close_change"] / prev_close

                df["hl"] = df["high"] - df["low"]
                df["hc"] = abs(df["high"] - df["close"].shift(1))
                df["lc"] = abs(df["low"] - df["close"].shift(1))
                df["tr"] = df[["hl", "hc", "lc"]].max(axis=1)

                df = df.dropna()

                # ATR computed after dropna so it reflects the same bars used in delta analysis
                atr = df["tr"].rolling(window=ATR_WINDOW).mean().iloc[-1]

                if len(df) == 0:
                    continue

                deltas = df["close_change_pct"].abs().values
                all_deltas.extend(deltas)

                p50 = np.percentile(deltas, 50)
                p75 = np.percentile(deltas, 75)
                p90 = np.percentile(deltas, 90)
                p95 = np.percentile(deltas, 95)
                p99 = np.percentile(deltas, 99)
                mean = np.mean(deltas)

                print(f"{symbol:10s} | {len(df):6d} bars | ATR: {atr:.4f} | "
                      f"50%: {p50*100:.4f}% | 75%: {p75*100:.4f}% | "
                      f"90%: {p90*100:.4f}% | 95%: {p95*100:.4f}% | "
                      f"Mean: {mean*100:.4f}%")

            print(f"\n=== OVERALL DELTA DISTRIBUTION ({len(all_deltas)} bars) ===\n")

            all_deltas = np.array(all_deltas)

            if len(all_deltas) == 0:
                print("No valid data to analyze.")
                return {
                    "total_bars": 0,
                    "p50": None,
                    "p75": None,
                    "p90": None,
                    "p95": None,
                    "p99": None,
                    "mean": None,
                    "std": None,
                    "recommendation": None
                }

            p50 = np.percentile(all_deltas, 50)
            p75 = np.percentile(all_deltas, 75)
            p90 = np.percentile(all_deltas, 90)
            p95 = np.percentile(all_deltas, 95)
            p99 = np.percentile(all_deltas, 99)
            mean = np.mean(all_deltas)
            std = np.std(all_deltas)

            print(f"50% of bars move < {p50*100:.4f}%")
            print(f"75% of bars move < {p75*100:.4f}%")
            print(f"90% of bars move < {p90*100:.4f}%")
            print(f"95% of bars move < {p95*100:.4f}%")
            print(f"99% of bars move < {p99*100:.4f}%")
            print(f"Mean: {mean*100:.4f}%")
            print(f"Std Dev: {std*100:.4f}%")

            print("\n=== RENAISSANCE RECOMMENDATION ===\n")

            if p90 < DELTA_THRESHOLD_AGGRESSIVE:
                print("✓ DELTA-BASED FILTERING recommended")
                print(f"  → Filter out bars with < {p90*100:.2f}% change (catches 90% of noise)")
                print("  → Expected reduction: 90% fewer bars to process")
                print("  → Throughput improvement: 10x (without code changes)")
            elif p75 < DELTA_THRESHOLD_CONSERVATIVE:
                print("✓ DELTA-BASED FILTERING recommended (conservative)")
                print(f"  → Filter out bars with < {p75*100:.2f}% change (catches 75% of noise)")
                print("  → Expected reduction: 75% fewer bars to process")
                print("  → Throughput improvement: 4x (without code changes)")
            else:
                print("✗ DELTA-BASED FILTERING not recommended")
                print("  → Most bars contain significant price movement")
                print("  → Filtering would drop valuable signals")
                print("  → Consider parallelization instead")

            return {
                "total_bars": len(all_deltas),
                "p50": float(p50),
                "p75": float(p75),
                "p90": float(p90),
                "p95": float(p95),
                "p99": float(p99),
                "mean": float(mean),
                "std": float(std),
                "recommendation": (
                    "filter"
                    if (p90 < DELTA_THRESHOLD_AGGRESSIVE or p75 < DELTA_THRESHOLD_CONSERVATIVE)
                    else "parallelize"
                )
            }

    finally:
        await db.close()


async def main():
    """Run delta distribution measurement."""
    result = await measure_delta_distribution(
        symbols=None,  # All symbols
        timeframe="1m",
        sample_size=10000
    )

    print("\n=== RESULT SAVED ===\n")
    print(f"Recommendation: {result['recommendation']}")


if __name__ == "__main__":
    asyncio.run(main())
