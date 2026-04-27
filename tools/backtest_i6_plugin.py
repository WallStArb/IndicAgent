"""Backtest tool for I6 plugins on historical market data.

This tool replays any I6 plugin on historical market data from TimescaleDB,
enabling scientific validation before production deployment (Renaissance discipline).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any

import argparse
import asyncpg
import pandas as pd
from tqdm import tqdm

from src.config.settings import Settings


async def backtest_i6_plugin(
    plugin_class: type,
    start_date: datetime,
    end_date: datetime,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> pd.DataFrame:
    """Backtest I6 plugin on historical data.

    Args:
        plugin_class: I6 plugin class (e.g., CrossTimeframeConfluencePlugin)
        start_date: Backtest start date (UTC)
        end_date: Backtest end date (UTC)
        symbols: Optional symbol filter (default: all active contracts)
        timeframes: Optional timeframe filter (default: _STANDARD_TFS)

    Returns:
        DataFrame with columns:
        - ts (timestamp)
        - symbol (str)
        - tf (str)
        - {output_field}_value for each plugin output
        - pnl_r (float, from signal_ledger JOIN)
        - hmm_regime (int, from intelligence_features)

    Raises:
        ValueError: If plugin_class doesn't have compute_full() method
    """
    # Validate plugin interface
    if not hasattr(plugin_class, "compute_full"):
        raise ValueError(f"Plugin {plugin_class.__name__} must have compute_full() method")

    # Default timeframes
    if timeframes is None:
        timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]

    # Run async backtest
    return await _backtest_async(plugin_class, start_date, end_date, symbols, timeframes)


async def _backtest_async(
    plugin_class: type,
    start_date: datetime,
    end_date: datetime,
    symbols: list[str] | None,
    timeframes: list[str],
) -> pd.DataFrame:
    """Async implementation of backtest."""
    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)

    try:
        # Query intelligence_features for I1-I5 inputs
        query = """
            SELECT
                ts,
                symbol,
                tf,
                i2_events,
                i3_patterns,
                i4_context,
                i5_patterns,
                hmm_regime
            FROM intelligence_features
            WHERE ts BETWEEN $1 AND $2
        """
        params = [start_date, end_date]

        if symbols:
            query += " AND symbol = ANY($3)"
            params.append(symbols)

        if timeframes:
            query += " AND tf = ANY($4)"
            params.append(timeframes)

        query += " ORDER BY ts, symbol, tf"

        rows = await conn.fetch(query, *params)

        if not rows:
            print(f"WARNING: No data found in intelligence_features for date range")
            return pd.DataFrame()

        # Load outcomes from signal_ledger
        outcomes_query = """
            SELECT
                sl.feature_ts,
                sl.feature_tf,
                sl.symbol,
                sl.pnl_r
            FROM signal_ledger sl
            WHERE sl.exit_at IS NOT NULL
              AND sl.feature_ts BETWEEN $1 AND $2
        """
        outcomes_params = [start_date, end_date]

        if symbols:
            outcomes_query += " AND sl.symbol = ANY($3)"
            outcomes_params.append(symbols)

        if timeframes:
            outcomes_query += " AND sl.feature_tf = ANY($4)"
            outcomes_params.append(timeframes)

        outcome_rows = await conn.fetch(outcomes_query, *outcomes_params)

        # Build outcome lookup dict
        outcomes = {}
        for row in outcome_rows:
            key = (row["feature_ts"], row["feature_tf"], row["symbol"])
            outcomes[key] = row["pnl_r"]

        # Instantiate plugin (handle both class and instance)
        try:
            plugin = plugin_class()
        except TypeError:
            # Already an instance
            plugin = plugin_class

        results = []

        # Process each bar with progress bar
        for row in tqdm(rows, desc="Backtesting", unit="bars"):
            try:
                # Build frames dict
                frames = {
                    "ts": row["ts"],
                    "symbol": row["symbol"],
                    "timeframe": row["tf"],
                    "features": {},  # Could populate from I1 if needed
                    "intel_i2": row.get("i2_events", {}),
                    "intel_i3": row.get("i3_patterns", {}),
                    "intel_i4": row.get("i4_context", {}),
                    "intel_i5": row.get("i5_patterns", {}),
                }

                # Call plugin compute_full
                outputs = plugin.compute_full(frames)

                if not outputs:
                    continue

                # Build result row
                result_row = {
                    "ts": row["ts"],
                    "symbol": row["symbol"],
                    "tf": row["tf"],
                    "hmm_regime": row.get("hmm_regime"),
                }

                # Add plugin outputs
                for key, value in outputs.items():
                    result_row[key] = value

                # Look up pnl_r from signal_ledger
                pnl_key = (row["ts"], row["tf"], row["symbol"])
                result_row["pnl_r"] = outcomes.get(pnl_key)

                results.append(result_row)

            except Exception as e:
                # Log error and skip this bar
                print(f"ERROR processing bar {row['ts']} {row['symbol']} {row['tf']}: {e}")
                continue

        # Convert to DataFrame
        df = pd.DataFrame(results)

        if df.empty:
            print("WARNING: No valid backtest results generated")
            return df

        # Reorder columns for readability
        col_order = ["ts", "symbol", "tf", "hmm_regime", "pnl_r"]
        output_cols = [col for col in df.columns if col not in col_order]
        df = df[col_order + output_cols]

        return df

    finally:
        await conn.close()


def main():
    """CLI interface for backtest tool."""
    parser = argparse.ArgumentParser(
        description="Backtest I6 plugin on historical market data"
    )
    parser.add_argument(
        "--plugin",
        type=str,
        required=True,
        help="Plugin class name (e.g., CrossTimeframeConfluencePlugin)",
    )
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="*",
        default=None,
        help="Symbols to backtest (default: all)",
    )
    parser.add_argument(
        "--timeframes",
        type=str,
        nargs="*",
        default=None,
        help="Timeframes to backtest (default: all)",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output CSV path",
    )

    args = parser.parse_args()

    # Parse dates
    start_date = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end_date = datetime.fromisoformat(args.end).replace(tzinfo=UTC)

    # Import plugin class (simplified - assumes plugin is importable)
    # In production, would need more sophisticated plugin discovery
    try:
        from src.intelligence.confluence.cross_timeframe import (
            CrossTimeframeConfluencePlugin,
        )

        plugin_map = {
            "CrossTimeframeConfluencePlugin": CrossTimeframeConfluencePlugin,
        }
    except ImportError:
        plugin_map = {}

    plugin_class = plugin_map.get(args.plugin)

    if plugin_class is None:
        print(f"ERROR: Unknown plugin {args.plugin}")
        print(f"Available plugins: {list(plugin_map.keys())}")
        return 1

    # Run backtest
    print(f"Backtesting {args.plugin} from {args.start} to {args.end}")
    df = asyncio.run(
        backtest_i6_plugin(
            plugin_class=plugin_class,
            start_date=start_date,
            end_date=end_date,
            symbols=args.symbols,
            timeframes=args.timeframes,
        )
    )

    # Save results
    df.to_csv(args.output, index=False)
    print(f"Results saved to {args.output}")
    print(f"Total bars: {len(df)}")

    return 0


if __name__ == "__main__":
    exit(main())
