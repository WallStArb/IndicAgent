#!/usr/bin/env python3
"""
Data Quality Audit Script — Measures and reports data quality across the intelligence pipeline.

Checks:
1. NULL rates in signal_ledger (cis_score, confidence)
2. Intelligence features staleness per (symbol, timeframe)
3. Pipeline lag P50/P95 from signal_ledger.pipeline_lag_ms
4. OHLCV bar completeness (today's RTH session)
5. IC health from signal_performance_segmented

Critical thresholds (exits 1 if violated during market hours):
  - null_cis_rate > 1%   — data corruption in CIS scoring
  - intelligence_stale > 900s  — intelligence pipeline down
  - pipeline_lag_p95 > 500ms  — pipeline severely lagging

Output: human-readable audit report + Prometheus text file at /tmp/data_quality_metrics.prom
Scheduling: Run every 15 minutes via indicagent-data-quality.timer systemd timer.

Usage:
    INDICAGENT_ENV=development .venv/bin/python production/scripts/data_quality_check.py
    .venv/bin/python production/scripts/data_quality_check.py --symbols ES,NQ
    .venv/bin/python production/scripts/data_quality_check.py --dry-run
    .venv/bin/python production/scripts/data_quality_check.py --help

Design rationale (Renaissance principles):
- "Instrument everything": data quality is observable state, not assumed correctness
- "Degrade gracefully, adapt automatically": surface degradation before it compounds
- "Never drop data": document violations, don't suppress them
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from prometheus_client import REGISTRY, write_to_textfile

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.observability.data_quality_metrics import (
    DQ_IC_SCORE,
    DQ_IC_SIGNIFICANT_FRACTION,
    DQ_INTELLIGENCE_STALENESS_SECONDS,
    DQ_NULL_CIS_RATE,
    DQ_NULL_CONFIDENCE_RATE,
    DQ_OHLCV_CHUNK_COUNT,
    DQ_OHLCV_MISSING_BARS_DAILY,
    DQ_PIPELINE_LAG_P50_MS,
    DQ_PIPELINE_LAG_P95_MS,
    DQ_SIGNAL_STALENESS_SECONDS,
)

# ---------------------------------------------------------------------------
# Critical thresholds
# ---------------------------------------------------------------------------

CRITICAL_NULL_CIS_RATE = 0.01  # > 1% null CIS score = data corruption
CRITICAL_STALENESS_S = 900  # > 15 min stale intelligence = pipeline down
CRITICAL_LAG_P95_MS = 500  # > 500ms P95 lag = pipeline lagging

# Expected 1m RTH bars per full session (09:30-16:00 ET = 390 minutes)
RTH_BARS_EXPECTED = 390

# Timeframes to check staleness for
TIMEFRAMES = ["1m", "5m", "15m", "1h"]

# Prometheus text file path
PROM_OUTPUT = "/tmp/data_quality_metrics.prom"


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------


def connect_db(settings: Settings) -> Any:
    """Create a synchronous psycopg2 connection from Settings."""
    return psycopg2.connect(settings.database_url)


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def check_null_rates(
    conn: Any, symbols: list[str]
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """Query signal_ledger for NULL cis_score and confidence rates per symbol.

    Returns:
        (cis_null_rates, confidence_null_rates, critical_symbols)
        where rates are fractions (0.0–1.0) and critical_symbols has null_cis > threshold.
    """
    cis_rates: dict[str, float] = {}
    confidence_rates: dict[str, float] = {}
    critical_syms: list[str] = []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                symbol,
                COUNT(*) AS total,
                SUM(CASE WHEN cis_score IS NULL THEN 1 ELSE 0 END) AS null_cis,
                SUM(CASE WHEN confidence IS NULL THEN 1 ELSE 0 END) AS null_confidence
            FROM signal_ledger
            WHERE symbol = ANY(%s)
            GROUP BY symbol
            """,
            (symbols,),
        )
        rows = cur.fetchall()

    seen: set[str] = {row["symbol"] for row in rows}
    for row in rows:
        symbol = row["symbol"]
        total = row["total"]
        cis_rate = float(row["null_cis"]) / total if total > 0 else 0.0
        conf_rate = float(row["null_confidence"]) / total if total > 0 else 0.0
        cis_rates[symbol] = cis_rate
        confidence_rates[symbol] = conf_rate
        DQ_NULL_CIS_RATE.labels(symbol=symbol).set(cis_rate)
        DQ_NULL_CONFIDENCE_RATE.labels(symbol=symbol).set(conf_rate)
        if cis_rate > CRITICAL_NULL_CIS_RATE:
            critical_syms.append(symbol)

    # Symbols with no rows in signal_ledger — treat as 0% null
    for symbol in symbols:
        if symbol not in seen:
            cis_rates[symbol] = 0.0
            confidence_rates[symbol] = 0.0

    return cis_rates, confidence_rates, critical_syms


def check_intelligence_staleness(
    conn: Any, symbols: list[str], timeframes: list[str]
) -> tuple[dict[tuple[str, str], float], list[tuple[str, str]]]:
    """Query intelligence_features for seconds-since-last-write per (symbol, tf).

    Returns:
        (staleness_map, critical_pairs)
        where staleness_map maps (symbol, tf) -> seconds, critical_pairs exceed threshold.
    """
    staleness: dict[tuple[str, str], float] = {}
    critical_pairs: list[tuple[str, str]] = []
    now = datetime.now(UTC)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT symbol, tf, MAX(ts) AS last_ts
            FROM intelligence_features
            WHERE symbol = ANY(%s)
              AND tf = ANY(%s)
              AND ts > NOW() - INTERVAL '24 hours'
            GROUP BY symbol, tf
            """,
            (symbols, timeframes),
        )
        rows = cur.fetchall()

    seen: set[tuple[str, str]] = set()
    for row in rows:
        sym = row["symbol"]
        tf = row["tf"]
        last_ts = row["last_ts"]
        if last_ts:
            age_s = (now - last_ts).total_seconds()
        else:
            age_s = float("inf")
        staleness[(sym, tf)] = age_s
        seen.add((sym, tf))
        DQ_INTELLIGENCE_STALENESS_SECONDS.labels(symbol=sym, timeframe=tf).set(age_s)
        if age_s > CRITICAL_STALENESS_S:
            critical_pairs.append((sym, tf))

    # Mark missing (symbol, tf) combos as infinite staleness
    for sym in symbols:
        for tf in timeframes:
            if (sym, tf) not in seen:
                staleness[(sym, tf)] = float("inf")
                DQ_INTELLIGENCE_STALENESS_SECONDS.labels(symbol=sym, timeframe=tf).set(99999)

    # Check signal_ledger staleness too (per symbol)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT symbol, MAX(timestamp) AS last_ts
            FROM signal_ledger
            WHERE symbol = ANY(%s)
              AND timestamp > NOW() - INTERVAL '24 hours'
            GROUP BY symbol
            """,
            (symbols,),
        )
        sig_rows = cur.fetchall()

    for row in sig_rows:
        sym = row["symbol"]
        last_ts = row["last_ts"]
        if last_ts:
            age_s = (now - last_ts).total_seconds()
        else:
            age_s = float("inf")
        DQ_SIGNAL_STALENESS_SECONDS.labels(symbol=sym).set(age_s)

    return staleness, critical_pairs


def check_pipeline_lag(
    conn: Any, symbols: list[str]
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float], list[tuple[str, str]]]:
    """Query signal_ledger.pipeline_lag_ms for P50/P95 per (symbol, tf) over last 1 hour.

    Returns:
        (p50_map, p95_map, critical_pairs)
    """
    p50_map: dict[tuple[str, str], float] = {}
    p95_map: dict[tuple[str, str], float] = {}
    critical_pairs: list[tuple[str, str]] = []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                symbol,
                timeframe,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY pipeline_lag_ms) AS p50,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY pipeline_lag_ms) AS p95
            FROM signal_ledger
            WHERE symbol = ANY(%s)
              AND pipeline_lag_ms IS NOT NULL
              AND timestamp > NOW() - INTERVAL '1 hour'
            GROUP BY symbol, timeframe
            """,
            (symbols,),
        )
        rows = cur.fetchall()

    for row in rows:
        sym = row["symbol"]
        tf = row["timeframe"]
        p50 = float(row["p50"]) if row["p50"] is not None else 0.0
        p95 = float(row["p95"]) if row["p95"] is not None else 0.0
        p50_map[(sym, tf)] = p50
        p95_map[(sym, tf)] = p95
        DQ_PIPELINE_LAG_P50_MS.labels(symbol=sym, timeframe=tf).set(p50)
        DQ_PIPELINE_LAG_P95_MS.labels(symbol=sym, timeframe=tf).set(p95)
        if p95 > CRITICAL_LAG_P95_MS:
            critical_pairs.append((sym, tf))

    return p50_map, p95_map, critical_pairs


def check_ohlcv_completeness(conn: Any, symbols: list[str]) -> tuple[dict[str, int], int]:
    """Check today's RTH 1m bar completeness and hypertable chunk count.

    Returns:
        (missing_bars_per_symbol, chunk_count)
    """
    missing: dict[str, int] = {}

    # Today's RTH session in ET (handles EST/EDT automatically via zoneinfo)
    now_et = datetime.now(_ET)
    rth_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    rth_close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_et < rth_open_et:
        # Before RTH open — use yesterday's session
        rth_open_et -= timedelta(days=1)
        rth_close_et -= timedelta(days=1)
    today_start = rth_open_et.astimezone(UTC)
    today_end = rth_close_et.astimezone(UTC)
    now_utc = now_et.astimezone(UTC)

    # Cap to current time if market hasn't closed yet
    if now_utc < today_end:
        session_duration = (now_utc - today_start).total_seconds()
        expected_bars = max(1, int(session_duration / 60))
    else:
        expected_bars = RTH_BARS_EXPECTED

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT symbol, COUNT(*) AS bar_count
            FROM market_data_ohlcv
            WHERE symbol = ANY(%s)
              AND timeframe = '1m'
              AND timestamp >= %s
              AND timestamp < %s
            GROUP BY symbol
            """,
            (symbols, today_start, today_end),
        )
        rows = cur.fetchall()

    bar_counts = {row["symbol"]: int(row["bar_count"]) for row in rows}
    for symbol in symbols:
        actual = bar_counts.get(symbol, 0)
        missing_bars = max(0, expected_bars - actual)
        missing[symbol] = missing_bars
        DQ_OHLCV_MISSING_BARS_DAILY.labels(symbol=symbol).set(missing_bars)

    # Hypertable chunk count
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS chunk_count
            FROM timescaledb_information.chunks
            WHERE hypertable_name = 'market_data_ohlcv'
              AND hypertable_schema = 'public'
            """
        )
        row = cur.fetchone()
        chunk_count = int(row[0]) if row else 0

    DQ_OHLCV_CHUNK_COUNT.set(chunk_count)
    return missing, chunk_count


def check_ic_health(conn: Any) -> tuple[dict[tuple[str, str], float], float]:
    """Read signal_performance_segmented for latest IC scores per (plugin, tf).

    NOTE: Table dropped in migration 050 (never used in production).
    IC health tracking is deferred until Renaissance observability phase.
    Returns empty dict and 0.0 when table doesn't exist.

    Returns:
        (ic_scores, significant_fraction)
        ic_scores maps (plugin, tf) -> ic_score
        significant_fraction = fraction of N>=30 plugins with ic_p_value < 0.05
    """
    ic_scores: dict[tuple[str, str], float] = {}
    total_eligible = 0
    total_significant = 0

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Get latest IC per (setup_plugin, timeframe) — use max(computed_at) per group
            cur.execute(
                """
                SELECT DISTINCT ON (setup_plugin, timeframe)
                    setup_plugin,
                    timeframe,
                    ic_score,
                    ic_p_value,
                    ic_n,
                    ic_significant,
                    sample_size
                FROM signal_performance_segmented
                WHERE ic_score IS NOT NULL
                ORDER BY setup_plugin, timeframe, computed_at DESC
                """
            )
            rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        # Table dropped in migration 050 - IC health not available
        DQ_IC_SIGNIFICANT_FRACTION.set(0.0)
        return {}, 0.0

    for row in rows:
        plugin = row["setup_plugin"]
        tf = row["timeframe"]
        ic = float(row["ic_score"]) if row["ic_score"] is not None else 0.0
        ic_scores[(plugin, tf)] = ic
        DQ_IC_SCORE.labels(setup_plugin=plugin, timeframe=tf).set(ic)

        # Count towards significant fraction if N >= 30
        if row["ic_n"] is not None and row["ic_n"] >= 30:
            total_eligible += 1
            if row["ic_p_value"] is not None and row["ic_p_value"] < 0.05:
                total_significant += 1

    frac = (total_significant / total_eligible) if total_eligible > 0 else 0.0
    DQ_IC_SIGNIFICANT_FRACTION.set(frac)

    return ic_scores, frac


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_rate(rate: float, threshold: float) -> str:
    pct = rate * 100
    status = "CRIT" if rate > threshold else "ok"
    return f"{pct:.1f}% {status}"


def _fmt_seconds(s: float) -> str:
    if s == float("inf") or s > 86400:
        return "N/A"
    if s > CRITICAL_STALENESS_S:
        return f"{s:.0f}s CRIT"
    return f"{s:.0f}s ok"


def _fmt_lag(ms: float) -> str:
    if ms > CRITICAL_LAG_P95_MS:
        return f"{ms:.0f}ms CRIT"
    return f"{ms:.0f}ms ok"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IndicAgent data quality audit — measures null rates, staleness, and pipeline lag",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0  All thresholds pass (or --dry-run)
  1  One or more CRITICAL thresholds violated (null_cis > 1%%, stale > 15min, lag_p95 > 500ms)

Thresholds:
  null_cis_rate    > 1%%   -> CRITICAL (data corruption)
  intelligence_stale > 900s -> CRITICAL (pipeline down)
  pipeline_lag_p95 > 500ms  -> CRITICAL (pipeline lagging)
        """,
    )
    parser.add_argument("--symbols", help="Comma-separated symbols to check (default: all active)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run checks but do not write Prometheus text file",
    )
    parser.add_argument(
        "--output",
        default=PROM_OUTPUT,
        help=f"Prometheus text file path (default: {PROM_OUTPUT})",
    )
    args = parser.parse_args()

    settings = Settings()
    conn = connect_db(settings)

    try:
        # Resolve symbols
        if args.symbols:
            symbols = [s.strip() for s in args.symbols.split(",")]
        else:
            from src.config.settings import get_active_symbols

            symbols = get_active_symbols(settings)

        now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"\n[DATA QUALITY AUDIT] {now_str}")
        print(f"Symbols: {', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}")
        print("-" * 60)

        critical_violations: list[str] = []

        # --- NULL RATES ---
        cis_rates, conf_rates, crit_syms = check_null_rates(conn, symbols)
        print("\nNULL RATES")
        for sym in symbols:
            cis_pct = cis_rates.get(sym, 0.0) * 100
            conf_pct = conf_rates.get(sym, 0.0) * 100
            cis_flag = "CRIT" if cis_rates.get(sym, 0.0) > CRITICAL_NULL_CIS_RATE else "ok"
            print(f"  {sym:<10} cis_score: {cis_pct:5.1f}% {cis_flag:<4}  confidence: {conf_pct:5.1f}%")
        if crit_syms:
            for sym in crit_syms:
                critical_violations.append(
                    f"NULL cis_score rate {cis_rates[sym]*100:.1f}% > {CRITICAL_NULL_CIS_RATE*100:.0f}% for {sym}"
                )

        # --- STALENESS ---
        staleness_map, crit_stale = check_intelligence_staleness(conn, symbols, TIMEFRAMES)
        print("\nINTELLIGENCE STALENESS (seconds since last write)")
        for sym in symbols[:5]:  # Show first 5 to keep output readable
            parts = []
            for tf in TIMEFRAMES:
                age = staleness_map.get((sym, tf), float("inf"))
                parts.append(f"{tf}:{_fmt_seconds(age)}")
            print(f"  {sym:<10} {' | '.join(parts)}")
        if len(symbols) > 5:
            print(f"  ... and {len(symbols)-5} more symbols")
        if crit_stale:
            for sym, tf in crit_stale:
                age = staleness_map.get((sym, tf), 0)
                critical_violations.append(
                    f"Intelligence stale {age:.0f}s > {CRITICAL_STALENESS_S}s for {sym}/{tf}"
                )

        # --- PIPELINE LAG ---
        p50_map, p95_map, crit_lag = check_pipeline_lag(conn, symbols)
        print("\nPIPELINE LAG (last 1h window)")
        if p50_map:
            # Group by symbol, show 1m and 5m
            shown_syms: set[str] = set()
            for (sym, tf), p95 in sorted(p95_map.items()):
                if tf not in ("1m", "5m"):
                    continue
                if sym not in shown_syms:
                    shown_syms.add(sym)
                p50 = p50_map.get((sym, tf), 0.0)
                lag_flag = "CRIT" if p95 > CRITICAL_LAG_P95_MS else "ok"
                print(
                    f"  {sym:<10}/{tf:<3} P50={p50:.0f}ms  P95={p95:.0f}ms {lag_flag}"
                )
        else:
            print("  No pipeline_lag_ms data in last 1h (services may be idle)")
        if crit_lag:
            for sym, tf in crit_lag:
                p95 = p95_map.get((sym, tf), 0)
                critical_violations.append(
                    f"Pipeline lag P95={p95:.0f}ms > {CRITICAL_LAG_P95_MS}ms for {sym}/{tf}"
                )

        # --- OHLCV COMPLETENESS ---
        missing_bars, chunk_count = check_ohlcv_completeness(conn, symbols)
        chunk_flag = "CRIT" if chunk_count > 5000 else "ok"
        print("\nOHLCV COMPLETENESS")
        print(f"  Chunk count: {chunk_count:,} {chunk_flag} (target < 200 after rebuild)")
        total_missing = sum(missing_bars.values())
        if total_missing > 0:
            top_missing = sorted(missing_bars.items(), key=lambda x: -x[1])[:5]
            for sym, n in top_missing:
                print(f"  {sym}: {n} missing 1m bars today")
        else:
            print("  All symbols: 0 missing 1m bars today (or pre-market)")

        # --- IC HEALTH ---
        ic_scores, sig_frac = check_ic_health(conn)
        total_ic_plugins = len(ic_scores)
        sig_pct = sig_frac * 100
        print("\nIC HEALTH")
        if total_ic_plugins == 0:
            print("  IC health tracking disabled (table dropped, see migration 050)")
        else:
            print(f"  Plugins with IC computed: {total_ic_plugins}")
            print(f"  Significant (p<0.05, N>=30): {sig_pct:.0f}%")

        # --- RESULT ---
        print("\n" + "-" * 60)
        if critical_violations:
            print(f"RESULT: FAIL — {len(critical_violations)} critical violation(s)")
            for v in critical_violations:
                print(f"  [CRIT] {v}")
        else:
            print("RESULT: PASS (exit 0)")

        # Write Prometheus text file
        if not args.dry_run:
            write_to_textfile(args.output, REGISTRY)
            print(f"\nPrometheus metrics written to: {args.output}")

        if critical_violations:
            sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
