#!/usr/bin/env python3
"""Phase 174 (174-02, D-07 Task 1): does `instruments.is_active=true` really mean
compute-ready for every existing row, or are some symbols mid-onboarding?

`get_active_contracts()`'s only query today is `is_active = true AND asset_class !=
'futures'` -- nothing downstream currently distinguishes "backfill-eligible" from
"compute-ready." This audit measures, per active symbol, whether all four timeframes
(5m/15m/1h/1d) both (a) have a `backfill_status` row with `fetch_complete = true` and
(b) have non-zero rows in `market_data_ohlcv_tradeable`. The finding decides migration
337's `compute_eligible` default for the 231 existing rows: if every active symbol
clears the bar, `compute_eligible=true` for all of them is a measured, behavior-
preserving default, not an assumption.

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

Also exports COMPUTE_READY_PREDICATE_SQL, the canonical all-four-timeframes promotion
predicate reused verbatim by Plans 10 and 12 so the gate cannot drift between the three
places it is enforced.

Also exports COMPUTE_READY_1D_PREDICATE_SQL (Phase 174, plan 174-13, D-09), the
1d-only sibling of COMPUTE_READY_PREDICATE_SQL, scoped to the '1d' timeframe alone
rather than parameterized over all four -- a 1d-only symbol (e.g. the D-09 down-cap
cohort, which carries no 5m/15m/1h history at all) satisfies this predicate and
deliberately fails COMPUTE_READY_PREDICATE_SQL. The two constants sit beside each other
in this module so the two cannot drift apart; migration 341 uses the same two-clause
text inline in its backfill UPDATE.
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

setup_service_logging("logs/instrument_compute_eligibility_audit.log")
_logger = structlog.get_logger(__name__)

_SYMBOL_BATCH_SIZE = 25

# Canonical all-four-timeframes compute-readiness predicate (Phase 174 D-07, plan
# 174-02). Plans 10 and 12 import this constant rather than re-deriving the predicate --
# do not copy/paste or approximate this fragment elsewhere. `i` is the expected alias
# for the `instruments` row being tested by the caller's outer query.
#
# Both halves are counted aggregates (`= cardinality(timeframes)`), never a bare EXISTS --
# an EXISTS here would silently degrade to "at least one timeframe complete," admitting
# partially-backfilled symbols into corpus-wide measurement (RESEARCH.md threat T-174-41).
# The required count derives from the bound timeframe list itself (APR
# `feature.factory.target_timeframes` via load_compute_timeframes()), so the list and the
# count can never disagree.
COMPUTE_READY_PREDICATE_SQL = """
    (
        SELECT count(*) FROM backfill_status b
        WHERE b.symbol = i.symbol AND b.tf = ANY(%(timeframes)s) AND b.fetch_complete
    ) = cardinality(%(timeframes)s::text[])
    AND (
        SELECT count(DISTINCT m.timeframe) FROM market_data_ohlcv_tradeable m
        WHERE m.symbol = i.symbol AND m.timeframe = ANY(%(timeframes)s)
    ) = cardinality(%(timeframes)s::text[])
""".strip()

# 1d-only sibling of COMPUTE_READY_PREDICATE_SQL (Phase 174, plan 174-13, D-09). Same
# two-clause bookkeeping-AND-ground-truth structure and the same `i.symbol` outer-alias
# convention, but scoped to the '1d' timeframe as a SQL literal rather than a
# %(timeframes)s parameter -- so this exact text is valid pasted directly into a
# migration's UPDATE ... WHERE clause (see migration 341) as well as inside a psycopg
# call from this module. A 1d-only symbol satisfies this predicate and deliberately
# fails COMPUTE_READY_PREDICATE_SQL above, since it carries no 5m/15m/1h rows at all.
COMPUTE_READY_1D_PREDICATE_SQL = """
    (
        SELECT count(*) FROM backfill_status b
        WHERE b.symbol = i.symbol AND b.tf = '1d' AND b.fetch_complete
    ) = 1
    AND (
        SELECT count(*) FROM market_data_ohlcv_tradeable m
        WHERE m.symbol = i.symbol AND m.timeframe = '1d'
    ) > 0
""".strip()


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


def _fetch_backfill_status(
    conn: psycopg.Connection, symbols: list[str], timeframes: list[str]
) -> dict[tuple[str, str], bool]:
    """fetch_complete flag per (symbol, tf). backfill_status is a small plain table
    (PK (symbol, tf)), not a hypertable -- one query for all active symbols is cheap,
    no batching needed.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, tf, fetch_complete
            FROM backfill_status
            WHERE symbol = ANY(%(symbols)s) AND tf = ANY(%(timeframes)s)
            """,
            {"symbols": symbols, "timeframes": timeframes},
        )
        return {(row[0], row[1]): bool(row[2]) for row in cur.fetchall()}


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
            backfill = _fetch_backfill_status(conn, symbols, timeframes)
        except Exception as error:
            _logger.critical("instrument_compute_eligibility_audit.query_failed", error=str(error))
            return 1

        # Per-symbol table -- accumulate rows, print once (never log per-row inside the loop).
        header = (
            f"{'symbol':<8}"
            + "".join(f"{tf + '_rows':>12}{tf + '_bfc':>8}" for tf in timeframes)
            + f"{'rows_all':>10}{'bfc_all':>10}{'zero_rows':>10}"
        )
        print(header)

        # Rows and fetch_complete are separate facts; compute-readiness (the promotion
        # predicate) needs both. Reporting only the rows half let migration 337's header
        # cite a both-halves measurement this audit never made (174 review IN-01).
        n_fetch_complete_all_tfs = 0
        n_compute_ready = 0
        zero_row_symbols: list[str] = []
        missing_tf_symbols: list[str] = []

        table_lines: list[str] = []
        for symbol in symbols:
            counts_by_tf = [row_counts.get((symbol, tf), 0) for tf in timeframes]
            bfc_by_tf = [backfill.get((symbol, tf), False) for tf in timeframes]
            has_rows_all = all(c > 0 for c in counts_by_tf)
            has_bfc_all = all(bfc_by_tf)
            is_zero = all(c == 0 for c in counts_by_tf)

            n_fetch_complete_all_tfs += has_bfc_all
            n_compute_ready += has_rows_all and has_bfc_all
            if not has_rows_all:
                missing_tf_symbols.append(symbol)
            if is_zero:
                zero_row_symbols.append(symbol)

            cells = "".join(
                f"{c:>12}{('Y' if bfc else 'N'):>8}" for c, bfc in zip(counts_by_tf, bfc_by_tf)
            )
            table_lines.append(
                f"{symbol:<8}{cells}{('Y' if has_rows_all else 'N'):>10}"
                f"{('Y' if has_bfc_all else 'N'):>10}{('Y' if is_zero else 'N'):>10}"
            )
        print("\n".join(table_lines))

        elapsed = time.time() - start
        summary = {
            "n_active": len(symbols),
            "timeframes": timeframes,
            "n_with_rows_all_tfs": len(symbols) - len(missing_tf_symbols),
            "n_fetch_complete_all_tfs": n_fetch_complete_all_tfs,
            "n_compute_ready": n_compute_ready,
            "n_missing_any_tf": len(missing_tf_symbols),
            "n_zero_rows": len(zero_row_symbols),
            "missing_tf_symbols": missing_tf_symbols,
            "zero_row_symbols": zero_row_symbols,
            "elapsed_seconds": round(elapsed, 2),
        }
        _logger.info("instrument_compute_eligibility_audit.summary", **summary)
        print(f"\nSummary: {summary}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
