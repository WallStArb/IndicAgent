"""Backtest macro factors (yield curve, flight-to-quality) on historical data.

Uses the same validation infrastructure as backtest_i6_plugin.py (Plan 64-00).
Queries rate futures (ZT, ZB) and equity/bond ETFs (TLT, SPY) from market_data_ohlcv,
computes macro factors via rolling window, joins to signal_ledger for pnl_r outcomes.

D-25 validation gate: IC > 0.05 AND p < 0.01 (Bonferroni-corrected) AND N >= 30.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import pandas as pd

from src.config.settings import Settings
from src.intelligence.macro.flight_to_quality import compute_flight_to_quality
from src.intelligence.macro.yield_curve import compute_yield_curve_slope
from tools.validate_i6_backtest import ValidationResults, validate_backtest_results

# Lookback window size (bars) — matches macro factor defaults
_LOOKBACK = 10

# Minimum bars needed per symbol to compute yield curve
_YC_REQUIRED_SYMBOLS = {"ZT", "ZB"}

# Minimum bars needed per symbol to compute FTQ
_FTQ_REQUIRED_SYMBOLS = {"TLT", "SPY"}


async def _load_ohlcv(
    conn: asyncpg.Connection,
    symbols: frozenset[str],
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Load OHLCV bars from market_data_ohlcv for the given symbols.

    NOTE: market_data_ohlcv primary time column is 'timestamp' (not 'ts').
    Renames to 'ts' internally for consistency with backtest tooling.
    """
    symbol_list = list(symbols)
    rows = await conn.fetch(
        """
        SELECT timestamp AS ts, symbol, timeframe AS tf,
               open, high, low, close, volume
        FROM market_data_ohlcv
        WHERE timestamp BETWEEN $1 AND $2
          AND symbol = ANY($3::text[])
        ORDER BY timestamp, symbol
        """,
        start_date,
        end_date,
        symbol_list,
    )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        rows,
        columns=["ts", "symbol", "tf", "open", "high", "low", "close", "volume"],
    )


async def _load_signal_outcomes(
    conn: asyncpg.Connection,
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Load pnl_r outcomes and hmm_regime from signal_ledger + intelligence_features.

    Joins signal_ledger to intelligence_features for hmm_regime context.
    Only includes signals with exit_at populated (closed trades with known outcomes).
    """
    rows = await conn.fetch(
        """
        SELECT
            sl.feature_ts,
            sl.pnl_r,
            COALESCE(
                (ic.i4::jsonb->>'hmm_regime')::int,
                0
            ) AS hmm_regime
        FROM signal_ledger sl
        LEFT JOIN intelligence_features ic ON (
            sl.symbol = ic.symbol
            AND sl.feature_ts = ic.ts
            AND sl.feature_tf = ic.tf
        )
        WHERE sl.feature_ts BETWEEN $1 AND $2
          AND sl.exit_at IS NOT NULL
          AND sl.pnl_r IS NOT NULL
        ORDER BY sl.feature_ts
        """,
        start_date,
        end_date,
    )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=["feature_ts", "pnl_r", "hmm_regime"])


def _build_rolling_windows(
    df: pd.DataFrame,
    required_symbols: set[str],
    compute_fn: Any,
    output_field: str,
    lookback: int = _LOOKBACK,
) -> pd.DataFrame:
    """Apply a macro factor compute function over a rolling window of OHLCV data.

    Slides a window of `lookback` rows per symbol pair across the sorted DataFrame.
    Only emits a result when all required symbols have at least `lookback` bars in
    the window — prevents look-ahead bias (window uses only past bars).

    Args:
        df: OHLCV DataFrame (ts, symbol, tf, open, high, low, close, volume)
        required_symbols: Symbols that must be present (e.g., {"ZT", "ZB"})
        compute_fn: Macro factor function — compute_fn(bars, lookback) -> dict
        output_field: Primary numeric output field name (e.g., "yield_curve_slope")
        lookback: Rolling window size

    Returns:
        DataFrame with columns: ts, {output_field}, {output_field}_regime
    """
    results = []

    # Group by timestamp — each unique timestamp is a bar boundary
    timestamps = sorted(df["ts"].unique())

    # Build per-symbol deques (rolling buffer)
    symbol_deques: dict[str, deque] = {sym: deque(maxlen=lookback + 1) for sym in required_symbols}

    for ts in timestamps:
        # Add bars at this timestamp to each symbol's deque
        ts_bars = df[df["ts"] == ts]
        for _, row in ts_bars.iterrows():
            sym = row["symbol"]
            if sym in symbol_deques:
                symbol_deques[sym].append(row.to_dict())

        # Only compute once all required symbols have enough bars
        if not all(len(symbol_deques[sym]) >= lookback for sym in required_symbols):
            continue

        try:
            result = compute_fn(symbol_deques, lookback=lookback)
        except Exception:
            continue

        # Extract regime field name from result (convention: {output_field}_regime)
        regime_field = next(
            (k for k in result if k.endswith("_regime")),
            output_field + "_regime",
        )

        results.append(
            {
                "ts": ts,
                output_field: result.get(output_field, 0.0),
                regime_field: result.get(regime_field, "unknown"),
            }
        )

    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results)


def _merge_with_outcomes(
    factor_df: pd.DataFrame,
    outcomes_df: pd.DataFrame,
    output_field: str,
) -> pd.DataFrame:
    """Merge factor time-series with signal outcomes using asof join.

    Matches each macro factor observation to the nearest signal in time
    (within 1-bar tolerance of 1 minute). Rows without a pnl_r match are dropped.

    Args:
        factor_df: DataFrame with ts and {output_field} columns
        outcomes_df: DataFrame with feature_ts, pnl_r, hmm_regime columns
        output_field: Field name for the macro factor value

    Returns:
        Merged DataFrame suitable for validate_backtest_results()
    """
    if factor_df.empty or outcomes_df.empty:
        return pd.DataFrame()

    # Ensure datetime types for merge_asof
    factor_df = factor_df.copy()
    outcomes_df = outcomes_df.copy()
    factor_df["ts"] = pd.to_datetime(factor_df["ts"], utc=True)
    outcomes_df["feature_ts"] = pd.to_datetime(outcomes_df["feature_ts"], utc=True)

    merged = pd.merge_asof(
        factor_df.sort_values("ts"),
        outcomes_df.sort_values("feature_ts"),
        left_on="ts",
        right_on="feature_ts",
        direction="nearest",
        tolerance=pd.Timedelta("1min"),
    )

    # Keep only rows with pnl_r outcome (closed signals)
    valid = merged.dropna(subset=["pnl_r"])
    if valid.empty:
        return pd.DataFrame()

    # Return only the columns needed for validate_backtest_results
    cols = [output_field, "pnl_r", "hmm_regime"]
    available = [c for c in cols if c in valid.columns]
    return valid[available].reset_index(drop=True)


async def backtest_yield_curve(
    start_date: datetime,
    end_date: datetime,
) -> tuple[pd.DataFrame, ValidationResults | None]:
    """Backtest yield curve factor on historical rate futures data.

    Loads ZT + ZB bars from market_data_ohlcv, runs compute_yield_curve_slope()
    over rolling windows, joins to signal_ledger for pnl_r outcomes, and
    validates IC/p-value via validate_backtest_results().

    Args:
        start_date: Backtest start date (UTC)
        end_date: Backtest end date (UTC)

    Returns:
        Tuple of (merged_df, ValidationResults or None if insufficient data)
    """
    settings = Settings()
    output_field = "yield_curve_slope"

    async with asyncpg.create_pool(settings.database_url, min_size=1, max_size=3) as pool:
        async with pool.acquire() as conn:
            print(f"  Loading ZT+ZB bars from {start_date.date()} to {end_date.date()}...")
            ohlcv_df = await _load_ohlcv(
                conn,
                frozenset(_YC_REQUIRED_SYMBOLS),
                start_date,
                end_date,
            )

            if ohlcv_df.empty:
                print("  WARNING: No ZT/ZB data found in market_data_ohlcv for this period")
                return pd.DataFrame(), None

            print(f"  Loaded {len(ohlcv_df)} bars ({ohlcv_df['symbol'].nunique()} symbols)")

            print("  Loading signal outcomes from signal_ledger...")
            outcomes_df = await _load_signal_outcomes(conn, start_date, end_date)
            print(f"  Found {len(outcomes_df)} closed signals with pnl_r outcomes")

    # Compute rolling yield curve slope
    print(f"  Computing yield curve slope (lookback={_LOOKBACK})...")
    factor_df = _build_rolling_windows(
        ohlcv_df,
        _YC_REQUIRED_SYMBOLS,
        compute_yield_curve_slope,
        output_field,
        lookback=_LOOKBACK,
    )

    if factor_df.empty:
        print("  WARNING: No yield curve observations computed (insufficient ZT/ZB data)")
        return pd.DataFrame(), None

    print(f"  Computed {len(factor_df)} yield curve observations")

    # Merge with signal outcomes
    merged_df = _merge_with_outcomes(factor_df, outcomes_df, output_field)

    if merged_df.empty or len(merged_df) < 30:
        print(f"  WARNING: Only {len(merged_df)} matched observations (need >= 30)")
        return merged_df, None

    # Validate
    validation = validate_backtest_results(merged_df, output_field)
    return merged_df, validation


async def backtest_ftq(
    start_date: datetime,
    end_date: datetime,
) -> tuple[pd.DataFrame, ValidationResults | None]:
    """Backtest flight-to-quality factor on historical TLT/SPY data.

    Loads TLT + SPY bars from market_data_ohlcv, runs compute_flight_to_quality()
    over rolling windows, joins to signal_ledger for pnl_r outcomes, and
    validates IC/p-value via validate_backtest_results().

    Args:
        start_date: Backtest start date (UTC)
        end_date: Backtest end date (UTC)

    Returns:
        Tuple of (merged_df, ValidationResults or None if insufficient data)
    """
    settings = Settings()
    output_field = "ftq_score"

    async with asyncpg.create_pool(settings.database_url, min_size=1, max_size=3) as pool:
        async with pool.acquire() as conn:
            print(f"  Loading TLT+SPY bars from {start_date.date()} to {end_date.date()}...")
            ohlcv_df = await _load_ohlcv(
                conn,
                frozenset(_FTQ_REQUIRED_SYMBOLS),
                start_date,
                end_date,
            )

            if ohlcv_df.empty:
                print("  WARNING: No TLT/SPY data found in market_data_ohlcv for this period")
                return pd.DataFrame(), None

            print(f"  Loaded {len(ohlcv_df)} bars ({ohlcv_df['symbol'].nunique()} symbols)")

            print("  Loading signal outcomes from signal_ledger...")
            outcomes_df = await _load_signal_outcomes(conn, start_date, end_date)
            print(f"  Found {len(outcomes_df)} closed signals with pnl_r outcomes")

    # Compute rolling FTQ score
    print(f"  Computing flight-to-quality score (lookback={_LOOKBACK})...")
    factor_df = _build_rolling_windows(
        ohlcv_df,
        _FTQ_REQUIRED_SYMBOLS,
        compute_flight_to_quality,
        output_field,
        lookback=_LOOKBACK,
    )

    if factor_df.empty:
        print("  WARNING: No FTQ observations computed (insufficient TLT/SPY data)")
        return pd.DataFrame(), None

    print(f"  Computed {len(factor_df)} FTQ observations")

    # Merge with signal outcomes
    merged_df = _merge_with_outcomes(factor_df, outcomes_df, output_field)

    if merged_df.empty or len(merged_df) < 30:
        print(f"  WARNING: Only {len(merged_df)} matched observations (need >= 30)")
        return merged_df, None

    # Validate
    validation = validate_backtest_results(merged_df, output_field)
    return merged_df, validation


def _print_factor_result(
    name: str,
    output_field: str,
    df: pd.DataFrame,
    validation: ValidationResults | None,
) -> None:
    """Print backtest result for one macro factor."""
    print(f"\n{'=' * 60}")
    print(f"{name} Factor")
    print(f"{'=' * 60}")

    if df.empty:
        print("  SKIPPED: No data available")
        return

    print(f"  Matched observations: {len(df)}")

    if validation is None:
        print("  SKIPPED: Insufficient data for validation (need >= 30 matched signals)")
        return

    print(f"  IC        = {validation.ic:.4f}")
    print(f"  p-value   = {validation.p_value:.4f}")
    print(f"  N         = {validation.n}")
    print(f"  Decision  : {validation.decision}")

    if validation.regime_results:
        print("  Regime breakdown:")
        for regime_name, regime_result in validation.regime_results.items():
            status = "PASS" if regime_result.passed else "FAIL"
            print(
                f"    {regime_name}: IC={regime_result.ic:.4f}, "
                f"p={regime_result.p_value:.4f}, N={regime_result.n} [{status}]"
            )


async def _amain() -> int:
    """Async main entry point."""
    start_date = datetime(2025, 10, 1, tzinfo=UTC)
    end_date = datetime(2026, 4, 1, tzinfo=UTC)
    output_dir = Path("/tmp")

    print("Phase 64: Macro Factor Backtest Validation")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print("Validation gate: IC > 0.05, p < 0.01 (Bonferroni), N >= 30")

    # --- Yield Curve Backtest ---
    print("\n\nRunning Yield Curve backtest...")
    yc_df, yc_validation = await backtest_yield_curve(start_date, end_date)

    if not yc_df.empty:
        csv_path = output_dir / "yield_curve_backtest.csv"
        yc_df.to_csv(csv_path, index=False)
        print(f"  Saved: {csv_path}")

    _print_factor_result("Yield Curve", "yield_curve_slope", yc_df, yc_validation)

    # --- Flight-to-Quality Backtest ---
    print("\n\nRunning Flight-to-Quality backtest...")
    ftq_df, ftq_validation = await backtest_ftq(start_date, end_date)

    if not ftq_df.empty:
        csv_path = output_dir / "ftq_backtest.csv"
        ftq_df.to_csv(csv_path, index=False)
        print(f"  Saved: {csv_path}")

    _print_factor_result("Flight-to-Quality", "ftq_score", ftq_df, ftq_validation)

    # --- Feature Selection Summary ---
    print(f"\n\n{'=' * 60}")
    print("MACRO FACTOR FEATURE SELECTION (D-25)")
    print(f"{'=' * 60}")

    all_validations = {
        "Yield Curve (yield_curve_slope)": yc_validation,
        "Flight-to-Quality (ftq_score)": ftq_validation,
    }

    validated_count = 0
    for factor_name, val in all_validations.items():
        if val is None:
            print(f"  {factor_name}: SKIP (insufficient data)")
            continue
        ic = val.ic
        decision_label = val.decision
        print(f"  {factor_name}: {decision_label} (IC={ic:.4f}, p={val.p_value:.4f})")
        if val.passed:
            validated_count += 1

    print()
    if validated_count >= 1:
        print("RECOMMENDATION: Deploy validated factors to shadow mode")
        print("  Monitor shadow performance for 2 weeks minimum before production")
    else:
        print("RECOMMENDATION: Tweak or abandon macro factors per Renaissance discipline")
        print("  Consider expanding data window if near-miss on N or IC")

    return 0


def main() -> int:
    """CLI entry point."""
    return asyncio.run(_amain())


if __name__ == "__main__":
    import sys

    sys.exit(main())
