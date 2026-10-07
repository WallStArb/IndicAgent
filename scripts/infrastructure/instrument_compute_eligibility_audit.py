#!/usr/bin/env python3
"""Phase 174 (174-02, D-07 Task 1): does `instruments.is_active=true` really mean
compute-ready for every existing row, or are some symbols mid-onboarding?

Plan 185-41 moved the answer from a bookkeeping flag to computed truth: a symbol is
compute-ready when every required `bar_integrity` verdict D7 writes is passed and fresh
(`src/intelligence/bars/verdict_gate.py`, data layer integrity design sections 6 and 8).
This audit measures, per active symbol, the tradeable row counts of the compute timeframes
and what each gate says today (how many names fail which check, and which currently promoted
names would no longer qualify). It writes nothing.

Read-only, no writes, exit code always 0 (a measurement tool, not a gate) -- the ONLY
non-zero exit path is an unrecoverable query failure.

Query shape is load-bearing, not incidental (RESEARCH.md review finding): a bare
`SELECT symbol, timeframe, count(*), min(timestamp), max(timestamp) FROM
market_data_ohlcv_tradeable GROUP BY 1,2` is a sequential scan over every chunk of a
hundreds-of-millions-of-rows hypertable. Instead: batch symbols (25/query) with
equality predicates on idx_ohlcv_symbol_tf_time's leading columns for the count query
(Bitmap/Index Scan per chunk, never Seq Scan -- verified via EXPLAIN, see 174-02-
SUMMARY.md), and pull min/max timestamps via a LATERAL `ORDER BY timestamp ASC/DESC
LIMIT 1` per (symbol, timeframe) so TimescaleDB's ChunkAppend can early-stop once the
newest/oldest matching chunk is found, instead of aggregating the full partition.

Also exports COMPUTE_READY_PREDICATE_SQL, the canonical all-timeframes promotion
predicate reused verbatim by the promote script so the gate cannot drift between the
places it is enforced; it is rendered from verdict_gate.REQUIRED_CHECKS.

Also exports COMPUTE_READY_1D_PREDICATE_SQL (Phase 174, plan 174-13, D-09), the
1d-only sibling of COMPUTE_READY_PREDICATE_SQL, scoped to the '1d' timeframe alone
rather than parameterized over all four -- a 1d-only symbol (e.g. the D-09 down-cap
cohort, which carries no 5m/15m/1h history at all) satisfies this predicate and
deliberately fails COMPUTE_READY_PREDICATE_SQL. The two constants sit beside each other
in this module so the two cannot drift apart. (Migration 341 used the older
bookkeeping-and-rows text inline in its backfill UPDATE; it is applied and immutable.)

Moved from `scripts/analysis/` to `scripts/infrastructure/` in phase 186 (plan 186-04,
R-05) so the onboarding SOP's stage-8 promote step
(`universe_expansion_promote_compute_eligible.py`, same directory) keeps a live import
when 186-16 deletes `scripts/analysis/`. The code below this docstring is byte-identical
to the original. Migrations 337 and 341 cite the old `scripts/analysis/` path in their
comments; those are applied and immutable, so they stay as historical citations.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402
import structlog  # noqa: E402

from src.config.instrument_onboarding import (  # noqa: E402
    COMPUTE_TIMEFRAMES_APR_KEY,
    parse_compute_timeframes,
)
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.bars.verdict_gate import (  # noqa: E402
    REQUIRED_CHECKS,
    fetch_verdict_scan,
    load_report_max_age_hours,
    ready_predicate_sql,
)

setup_service_logging("logs/instrument_compute_eligibility_audit.log")
_logger = structlog.get_logger(__name__)

_SYMBOL_BATCH_SIZE = 25

# Compute-readiness predicates over the latest bar_integrity verdicts (plan 185-41). `i` is the
# expected alias for the `instruments` row being tested by the caller's outer query. Both are
# rendered from verdict_gate.REQUIRED_CHECKS, so the checks they require and the pure gate's
# cannot drift. The all-timeframes form binds %(timeframes)s (APR
# `feature.factory.target_timeframes`, via load_compute_timeframes()) and %(max_age_hours)s
# (APR `threshold.bar_integrity.report_max_age_hours`, via verdict_gate.load_report_max_age_hours()); a bound
# timeframe without required checks cannot pass (RESEARCH.md threat T-174-41). The 1d form has
# '1d' rendered in and binds only %(max_age_hours)s.
COMPUTE_READY_PREDICATE_SQL = ready_predicate_sql()
COMPUTE_READY_1D_PREDICATE_SQL = ready_predicate_sql(("1d",))


def load_compute_timeframes(conn: psycopg.Connection) -> list[str]:
    """Read the compute timeframe stack from APR; raise if it is missing or malformed."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_value FROM config_state WHERE config_key = %s",
            (COMPUTE_TIMEFRAMES_APR_KEY,),
        )
        row = cur.fetchone()
    return parse_compute_timeframes(row[0] if row else None)


def _batched(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _fetch_active_symbols(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM instruments WHERE is_active = true ORDER BY symbol")
        return [row[0] for row in cur.fetchall()]


def _fetch_row_counts(
    conn: psycopg.Connection, symbols: list[str], timeframes: list[str]
) -> dict[tuple[str, str], int]:
    """Index-driven per-(symbol, timeframe) row counts for one symbol batch.

    Batched via symbol = ANY(%(symbols)s) AND timeframe = ANY(%(timeframes)s) so the
    planner drives from idx_ohlcv_symbol_tf_time's leading equality columns -- verified
    via EXPLAIN (ANALYZE, BUFFERS) to produce Bitmap/Index Scan nodes per chunk, never a
    Seq Scan (see 174-02-SUMMARY.md).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, timeframe, count(*)
            FROM market_data_ohlcv_tradeable
            WHERE symbol = ANY(%(symbols)s) AND timeframe = ANY(%(timeframes)s)
            GROUP BY symbol, timeframe
            """,
            {"symbols": symbols, "timeframes": timeframes},
        )
        return {(row[0], row[1]): row[2] for row in cur.fetchall()}


def _fetch_endpoints(
    conn: psycopg.Connection, symbols: list[str], timeframes: list[str]
) -> dict[tuple[str, str], tuple[object, object]]:
    """Index-driven per-(symbol, timeframe) (min_ts, max_ts) for one symbol batch.

    Each LATERAL subquery is an `ORDER BY timestamp ASC/DESC LIMIT 1` endpoint lookup
    against idx_ohlcv_symbol_tf_time -- TimescaleDB's ChunkAppend early-stops once the
    oldest/newest matching chunk is found, rather than aggregating over the full
    partition. Batched across symbols/timeframes in one round trip via unnest() + CROSS
    JOIN LATERAL, not one query per symbol (231 round trips is its own problem).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.symbol, t.tf, mn.timestamp AS min_ts, mx.timestamp AS max_ts
            FROM unnest(%(symbols)s::text[]) AS s(symbol)
            CROSS JOIN unnest(%(timeframes)s::text[]) AS t(tf)
            CROSS JOIN LATERAL (
                SELECT timestamp FROM market_data_ohlcv_tradeable m
                WHERE m.symbol = s.symbol AND m.timeframe = t.tf
                ORDER BY timestamp ASC LIMIT 1
            ) mn
            CROSS JOIN LATERAL (
                SELECT timestamp FROM market_data_ohlcv_tradeable m
                WHERE m.symbol = s.symbol AND m.timeframe = t.tf
                ORDER BY timestamp DESC LIMIT 1
            ) mx
            """,
            {"symbols": symbols, "timeframes": timeframes},
        )
        return {(row[0], row[1]): (row[2], row[3]) for row in cur.fetchall()}


def _failing_check_counts(failures: dict[str, list[str]]) -> dict[str, int]:
    """Names failing per `tf:check` (a name counts once per check, whatever the reason)."""
    counts: dict[str, int] = {}
    for reasons in failures.values():
        for reason in reasons:
            key = reason.split(" ", 1)[0]
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _fetch_promoted(conn: psycopg.Connection, column: str) -> set[str]:
    """Active symbols currently flagged on `column` (a module-owned literal, never argv)."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT symbol FROM instruments WHERE is_active = true AND {column} = true")
        return {row[0] for row in cur.fetchall()}


def _gate_report(
    conn: psycopg.Connection, symbols: list[str], timeframes: list[str], max_age_hours: float
) -> dict[str, object]:
    """What each gate says today, per dimension: pass counts, failures by check, and which
    already-promoted names would no longer qualify (a finding; nothing is demoted)."""
    report: dict[str, object] = {"max_age_hours": max_age_hours}
    for dimension, column, tfs in (
        ("compute_1d", "compute_eligible_1d", ["1d"]),
        ("compute", "compute_eligible", [tf for tf in timeframes if tf in REQUIRED_CHECKS]),
    ):
        failures = fetch_verdict_scan(conn, symbols, tfs, max_age_hours).failures
        promoted = _fetch_promoted(conn, column)
        report[dimension] = {
            "timeframes": tfs,
            "n_pass": len(symbols) - len(failures),
            "n_fail": len(failures),
            "failing_by_check": _failing_check_counts(failures),
            "promoted_that_fail": len(promoted & set(failures)),
            "promoted_that_fail_symbols": sorted(promoted & set(failures)),
        }
    return report


def main() -> int:
    start = time.time()
    settings = Settings()

    try:
        conn = psycopg.connect(settings.database_url)
        conn.autocommit = True
    except Exception as error:
        _logger.critical("instrument_compute_eligibility_audit.db_connect_failed", error=str(error))
        return 1

    try:
        timeframes = load_compute_timeframes(conn)
        symbols = _fetch_active_symbols(conn)
        print(f"instrument_compute_eligibility_audit: {len(symbols)} is_active=true symbols")

        row_counts: dict[tuple[str, str], int] = {}
        endpoints: dict[tuple[str, str], tuple[object, object]] = {}
        try:
            for batch in _batched(symbols, _SYMBOL_BATCH_SIZE):
                row_counts.update(_fetch_row_counts(conn, batch, timeframes))
                endpoints.update(_fetch_endpoints(conn, batch, timeframes))
            gates = _gate_report(conn, symbols, timeframes, load_report_max_age_hours(conn))
        except Exception as error:
            _logger.critical("instrument_compute_eligibility_audit.query_failed", error=str(error))
            return 1

        # Per-symbol table -- accumulate rows, print once (never log per-row inside the loop).
        header = (
            f"{'symbol':<8}"
            + "".join(f"{tf + '_rows':>12}" for tf in timeframes)
            + f"{'rows_all':>10}{'zero_rows':>10}"
        )
        print(header)

        zero_row_symbols: list[str] = []
        missing_tf_symbols: list[str] = []

        table_lines: list[str] = []
        for symbol in symbols:
            counts_by_tf = [row_counts.get((symbol, tf), 0) for tf in timeframes]
            has_rows_all = all(c > 0 for c in counts_by_tf)
            is_zero = all(c == 0 for c in counts_by_tf)

            if not has_rows_all:
                missing_tf_symbols.append(symbol)
            if is_zero:
                zero_row_symbols.append(symbol)

            cells = "".join(f"{c:>12}" for c in counts_by_tf)
            table_lines.append(
                f"{symbol:<8}{cells}{('Y' if has_rows_all else 'N'):>10}{('Y' if is_zero else 'N'):>10}"
            )
        print("\n".join(table_lines))

        elapsed = time.time() - start
        summary = {
            "n_active": len(symbols),
            "timeframes": timeframes,
            "n_with_rows_all_tfs": len(symbols) - len(missing_tf_symbols),
            "n_missing_any_tf": len(missing_tf_symbols),
            "n_zero_rows": len(zero_row_symbols),
            "missing_tf_symbols": missing_tf_symbols,
            "zero_row_symbols": zero_row_symbols,
            "verdict_gates": gates,
            "elapsed_seconds": round(elapsed, 2),
        }
        _logger.info("instrument_compute_eligibility_audit.summary", **summary)
        print(f"\nSummary: {summary}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
