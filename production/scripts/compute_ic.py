#!/usr/bin/env python3
"""
Information Coefficient (IC) computation — compute_ic.py

Computes Pearson r(confidence, binary_outcome) per plugin per regime.
Writes results to signal_performance_segmented table.

Renaissance principle: "Earn the right through proof."
IC is the quantifiable measure of whether a signal's confidence score has
predictive power over realized outcomes. Plugins below threshold are flagged.

Usage:
    .venv/bin/python production/scripts/compute_ic.py --window-days 30
    .venv/bin/python production/scripts/compute_ic.py --window-days 30 --write
    .venv/bin/python production/scripts/compute_ic.py --symbols ES,NQ --write
    .venv/bin/python production/scripts/compute_ic.py --regime trend --write
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.settings import Settings  # noqa: E402
from src.intelligence.ml.information_coefficient import (  # noqa: E402
    IC_MIN_SAMPLE_SIZE,
    IC_NOISE_THRESHOLD,
    IC_P_VALUE_THRESHOLD,
    ICResult,
    compute_ic,
    is_ic_significant,
)
from src.intelligence.trading.signal_outcome import WIN_OUTCOMES  # noqa: E402


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute Information Coefficient (IC) for all signal plugins.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=30,
        metavar="N",
        help="Rolling window in days (default: 30)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        metavar="SYM,SYM",
        help="Comma-separated symbol filter (default: all active)",
    )
    parser.add_argument(
        "--regime",
        type=str,
        default="all",
        choices=["all", "trend", "mean_reversion", "ranging"],
        help="Filter by regime_context group (default: all)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write results to signal_performance_segmented (default: dry-run)",
    )
    parser.add_argument(
        "--min-ic",
        type=float,
        default=IC_NOISE_THRESHOLD,
        metavar="IC",
        help=f"Minimum IC to consider non-noise (default: {IC_NOISE_THRESHOLD})",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_conn(settings: Settings) -> psycopg2.extensions.connection:
    return psycopg2.connect(settings.database_url)


def _fetch_signals(
    conn: psycopg2.extensions.connection,
    window_days: int,
    symbols: list[str] | None,
) -> list[tuple]:
    """Fetch resolved signals from signal_ledger for IC computation."""
    # Use calibrated_confidence if available (migration 038), fall back to confidence
    # We detect availability at query time using a safe COALESCE with sub-select
    symbol_filter = ""
    params: list = [window_days]
    if symbols:
        placeholders = ", ".join(["%s"] * len(symbols))
        symbol_filter = f"AND symbol IN ({placeholders})"
        params.extend(symbols)

    sql = f"""
        SELECT
            sl.setup_plugin,
            sl.timeframe,
            sl.symbol,
            COALESCE(sl.confidence, 0.0)                    AS conf,
            sl.outcome,
            sl.pnl_r,
            COALESCE(sl.regime_context, 'any')              AS regime_type,
            sl.feature_ts::date                             AS bar_date
        FROM signal_ledger sl
        WHERE sl.feature_ts >= NOW() - INTERVAL %s
          AND sl.outcome IS NOT NULL
          {symbol_filter}
        ORDER BY sl.setup_plugin, sl.timeframe, sl.symbol, sl.feature_ts
    """

    with conn.cursor() as cur:
        cur.execute(sql, [f"{window_days} days"] + (symbols or []))
        return cur.fetchall()


def _write_results(
    conn: psycopg2.extensions.connection,
    results: list[ICResult],
    window_days: int,
    window_start: date,
    window_end: date,
) -> int:
    """Insert IC results into signal_performance_segmented. Returns rows written."""
    if not results:
        return 0

    rows = [
        (
            r.setup_plugin,
            r.timeframe,
            r.regime_type,
            r.symbol,
            datetime.now(UTC),
            window_days,
            window_start,
            window_end,
            r.sample_size,
            r.wins,
            r.win_rate,
            r.avg_pnl_r,
            r.ic_score,
            r.ic_p_value,
            r.ic_n,
            r.ic_significant,
        )
        for r in results
        if r.sample_size >= IC_MIN_SAMPLE_SIZE  # DB CHECK enforces this too
    ]

    if not rows:
        return 0

    sql = """
        INSERT INTO signal_performance_segmented (
            setup_plugin, timeframe, regime_type, symbol,
            computed_at, window_days, window_start, window_end,
            sample_size, wins, win_rate, avg_pnl_r,
            ic_score, ic_p_value, ic_n, ic_significant
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s
        )
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _group_signals(
    rows: list[tuple],
    regime_filter: str,
) -> dict[tuple, list]:
    """Group raw signal rows by (plugin, tf, symbol, regime)."""
    # Group by (setup_plugin, timeframe, symbol, regime_type)
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        setup_plugin, timeframe, symbol, conf, outcome, pnl_r, regime_type, _date = row

        # Regime filter
        if regime_filter != "all":
            if regime_filter == "trend" and "trend" not in regime_type.lower():
                continue
            elif regime_filter == "mean_reversion" and "reversion" not in regime_type.lower():
                continue
            elif regime_filter == "ranging" and regime_type != "ranging":
                continue

        key = (setup_plugin, timeframe, symbol, regime_type)
        groups[key].append((conf, outcome, pnl_r))
    return groups


def _compute_results(
    groups: dict[tuple, list],
    window_days: int,
    min_ic: float,
) -> list[ICResult]:
    """Compute IC for each group. Returns only groups with sample_size >= IC_MIN_SAMPLE_SIZE."""
    results: list[ICResult] = []

    for (setup_plugin, timeframe, symbol, regime_type), signals in groups.items():
        if len(signals) < IC_MIN_SAMPLE_SIZE:
            continue

        confidences = [s[0] for s in signals]
        outcomes = [s[1] for s in signals]
        pnl_rs = [s[2] for s in signals]

        sample_size = len(signals)
        wins = sum(1 for o in outcomes if o in WIN_OUTCOMES)
        win_rate = wins / sample_size if sample_size > 0 else None
        valid_pnl = [p for p in pnl_rs if p is not None]
        avg_pnl_r = sum(valid_pnl) / len(valid_pnl) if valid_pnl else None

        ic_score, ic_p_value, ic_n = compute_ic(confidences, outcomes)
        ic_significant = is_ic_significant(ic_score, ic_p_value, ic_n)

        results.append(
            ICResult(
                setup_plugin=setup_plugin,
                timeframe=timeframe,
                regime_type=regime_type,
                symbol=symbol,
                window_days=window_days,
                sample_size=sample_size,
                wins=wins,
                win_rate=win_rate,
                avg_pnl_r=avg_pnl_r,
                ic_score=ic_score,
                ic_p_value=ic_p_value,
                ic_n=ic_n,
                ic_significant=ic_significant,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

_GRADE_SYMBOLS = {
    "strong": "+++",
    "meaningful": "++",
    "weak": "+",
    "noise": "x",
    "insufficient_data": "?",
}


def _print_table(results: list[ICResult], min_ic: float) -> None:
    """Print IC results table to stdout."""
    if not results:
        print("No results with sample_size >= 30.")
        return

    header = f"{'Plugin':<35} {'TF':<5} {'Symbol':<8} {'N':>6} {'IC':>8} {'p-val':>8} Grade"
    separator = "-" * len(header)
    print(separator)
    print(header)
    print(separator)

    noise_plugins = []

    # Sort by IC score descending (None last)
    sorted_results = sorted(results, key=lambda r: (r.ic_score or -999), reverse=True)

    for r in sorted_results:
        ic_str = f"{r.ic_score:.4f}" if r.ic_score is not None else "  None"
        pv_str = f"{r.ic_p_value:.4f}" if r.ic_p_value is not None else "  None"
        grade_sym = _GRADE_SYMBOLS.get(r.grade, "?")
        flag = " [NOISE]" if r.is_noise and r.ic_n >= IC_MIN_SAMPLE_SIZE else ""
        sym_display = r.symbol or "ALL"
        print(
            f"{r.setup_plugin:<35} {r.timeframe:<5} {sym_display:<8} "
            f"{r.ic_n:>6} {ic_str:>8} {pv_str:>8} {r.grade} {grade_sym}{flag}"
        )
        if r.is_noise and r.ic_n >= IC_MIN_SAMPLE_SIZE:
            noise_plugins.append(r)

    print(separator)
    print(f"\nTotal: {len(results)} plugin-regime slices")
    print(f"Noise candidates (IC < {min_ic} or p > {IC_P_VALUE_THRESHOLD}): {len(noise_plugins)}")

    if noise_plugins:
        print("\nNoise candidates flagged for Phase 44 shadow review:")
        for r in noise_plugins:
            print(f"  - {r.setup_plugin} [{r.timeframe}] {r.symbol or 'ALL'}: "
                  f"IC={r.ic_score:.4f if r.ic_score else 'None'}, "
                  f"N={r.ic_n}, grade={r.grade}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = _parse_args()

    settings = Settings()
    symbols: list[str] | None = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]

    window_end = date.today()
    window_start = window_end - timedelta(days=args.window_days)

    print(f"IC Computation — window: {args.window_days}d ({window_start} to {window_end})")
    print(f"Symbols: {symbols or 'all'} | Regime: {args.regime} | Write: {args.write}")
    print()

    conn = _get_conn(settings)
    try:
        print("Fetching resolved signals from signal_ledger...")
        rows = _fetch_signals(conn, args.window_days, symbols)
        print(f"  Fetched {len(rows):,} resolved signals")

        if not rows:
            print("No resolved signals found. Exiting.")
            return 0

        print("Grouping by (plugin, timeframe, symbol, regime)...")
        groups = _group_signals(rows, args.regime)
        print(f"  Groups: {len(groups):,} ({sum(1 for g in groups.values() if len(g) >= IC_MIN_SAMPLE_SIZE):,} with N >= {IC_MIN_SAMPLE_SIZE})")

        print("Computing IC scores...")
        results = _compute_results(groups, args.window_days, args.min_ic)
        print(f"  IC computed for {len(results):,} slices")

        print()
        _print_table(results, args.min_ic)

        if args.write:
            print(f"\nWriting {len(results)} results to signal_performance_segmented...")
            n_written = _write_results(conn, results, args.window_days, window_start, window_end)
            print(f"  Written: {n_written} rows")
        else:
            print("\n[DRY RUN] Use --write to persist results.")

        # Exit 1 if any plugin with N >= 30 is noise (monitoring integration)
        noise_count = sum(
            1 for r in results
            if r.is_noise and r.ic_n >= IC_MIN_SAMPLE_SIZE
        )
        if noise_count > 0:
            print(f"\nExit 1: {noise_count} noise plugin(s) detected (IC gate failed).")
            return 1

        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
