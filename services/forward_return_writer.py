#!/usr/bin/env python3
"""Forward Return Writer — oneshot that computes executable causal forward log returns.

Reads market_data_ohlcv (OHLCV), computes forward returns via LEAD() window functions,
and inserts rows into forward_returns for every (symbol, tf) that has a matching
feature_vectors row. This is the dependent variable (Y) for IC measurement.

CORRECTNESS INVARIANTS:
- Forward return formula (IC spec §V): ln(open[T+N+1] / open[T+1]).
  Entry at T+1 open, exit at T+N+1 open. NEVER ln(close[T+N]/close[T]).
- TRAINING_WINDOW_END gate: only bars with timestamp <= MAX(bar_ts) FROM feature_vectors
  are processed. Prevents future-gap rows (bars beyond the training corpus).
- JOIN gate: only emits rows where bar_ts has a matching feature_vectors row (exact JOIN).
- Idempotent: ON CONFLICT (symbol, tf, bar_ts) DO NOTHING. Re-run inserts 0 rows.
- complete_Nbar=false for the last N bars of each (symbol, tf) series where
  open[T+N+1] is NULL (insufficient future data).

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB"
rule exactly as backfill_feature_factory.py is — batch labeling tool, not a daemon.

Usage:
    python services/forward_return_writer.py --training-window-end 2025-12-24T05:15:00+00:00
    python services/forward_return_writer.py --symbols SPY TLT --training-window-end 2025-12-24T05:15:00+00:00
    python services/forward_return_writer.py --symbols SPY --tf 5m --training-window-end 2025-12-24T05:15:00+00:00

--training-window-end is REQUIRED (not optional) -- see services/ic_engine.py and
docs/plans/OOS-EVAL-PROTOCOL.md (Phase 141.1 CR-01/IN-02). A bare MAX(bar_ts) fallback
would silently consume the OOS holdout window on any ad-hoc invocation.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import uuid
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
import structlog
from opentelemetry import trace
from opentelemetry.trace import StatusCode

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import LOOKAHEAD_FALLBACKS_BY_TF as _SCALE_FALLBACKS_BY_TF
from services._batch_utils import load_config_service_sync as _load_config_service
from src.config.settings import Settings
from src.core.integrity_monitor import emit_integrity_fact_sync
from src.core.service_utils import setup_service_logging
from src.intelligence.statistics.ic_math import scale_max_abs_return
from src.observability.metrics import (
    FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL,
    FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS,
    JOB_COMPLETED_TOTAL,
    OUTCOME_LABELS_COVERAGE,
    flush_and_shutdown_metrics,
)
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/forward_return_writer.log")

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOB = "forward-return-writer"

# Gradient scale identifiers — schema column names for forward return horizons.
# Schema holds the concept (fast/mid/slow/extended); APR holds the period in bars
# under alpha.ic.lookahead.{tf}.{scale} (todo 146: per-tf, not shared across tfs).
# Loaded at runtime from APR.
_SCALES: tuple[str, ...] = ("fast", "mid", "slow", "extended")

# Fallback defaults used only when APR key is absent (pre-migration bootstrap).
# Todo 146: shared with ICEngineConfig/EnsembleICConfig via _batch_utils.LOOKAHEAD_FALLBACKS_BY_TF
# (imported above as _SCALE_FALLBACKS_BY_TF) -- single source of truth for the per-tf grid.

_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]

# Fallback only — actual value read from APR at runtime via cfg.get_sync()
_INSERT_BATCH_SIZE_DEFAULT = 500

# Fallback only — actual per-tf ceiling read from APR at runtime via cfg.get_sync().
# alpha.quant.max_abs_return.{tf} (todo 148): the 1-bar (fast) plausibility ceiling.
# |return_{scale}| above this ceiling, sqrt(lookahead_bars)-scaled per scale via
# ic_math.scale_max_abs_return(), is flagged return_{scale}_suspect rather than dropped
# (Renaissance data-retention principle).
_MAX_ABS_RETURN_FALLBACKS: dict[str, float] = {"5m": 0.25, "15m": 0.30, "1h": 0.40, "1d": 0.50}


def _suspect_col_names(scales: Iterable[str]) -> list[str]:
    """return_{scale}_suspect column names for the given scales (todo 148) — the single
    source the SQL builders and the Python-side suspect counter all derive from."""
    return [f"return_{scale}_suspect" for scale in scales]


def _make_forward_return_id(
    symbol: str, tf: str, bar_ts: datetime, pipeline_version: str
) -> uuid.UUID:
    """SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] as UUID.

    Mirrors make_feature_vector_id in feature_vector_persistence.py.
    bar_ts_ns uses nanosecond epoch to avoid sub-second precision loss.
    """
    bar_ts_ns = str(int(bar_ts.timestamp() * 1_000_000_000))
    digest = hashlib.sha256(f"{symbol}|{tf}|{bar_ts_ns}|{pipeline_version}".encode()).hexdigest()[
        :32
    ]
    return uuid.UUID(digest)


# ---------------------------------------------------------------------------
# Sync span helper — matches observed_span semantics for sync psycopg2 services
# ---------------------------------------------------------------------------


@contextmanager
def observed_span(name: str, tracer: Any, **attrs: Any) -> Generator[Any]:
    """Sync context manager mirroring src/observability/spans.py:observed_span.

    Creates a span, records exceptions, sets ERROR status on raise.
    Used here because forward_return_writer is sync (psycopg2), not async.
    """
    with tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield span
        except Exception as error:
            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            raise


# ---------------------------------------------------------------------------
# Pure forward return helper (unit-testable, no DB)
# ---------------------------------------------------------------------------


def forward_log_return(opens: np.ndarray, n: int) -> np.ndarray:
    """Compute forward log return: ln(open[T+N+1] / open[T+1]) for each T.

    This mirrors the SQL LEAD()-based formula in _build_forward_return_sql():
      - Entry at T+1 open (next bar's open, simulating market-on-open entry)
      - Exit at T+N+1 open (N bars later, simulating market-on-open exit)

    The last n rows have no complete forward return (opens[T+N+1] is unknown)
    and are set to NaN.

    Args:
        opens: Array of length M open prices, ordered by time.
        n: Lookahead in bars (1=fast, 5=mid, 20=slow, 60=extended).

    Returns:
        Array of length M float64. Value at index T = ln(opens[T+n+1] / opens[T+1]).
        Indices where T+n+1 >= M are NaN (complete_Nbar would be False in SQL).
        Index T uses only opens at indices > T (no lookahead bias).
    """
    opens_arr = np.asarray(opens, dtype=float)
    m = len(opens_arr)
    result = np.full(m, np.nan)
    # result[T] = ln(opens[T+n+1] / opens[T+1]) for T in [0, m-n-2]
    # Requires: T+1 < m (entry) and T+n+1 < m (exit)
    # So valid T range: 0 <= T <= m - n - 2
    valid_end = m - n - 1  # last valid T (inclusive) = m - n - 2
    if valid_end > 0:
        entry_idx = np.arange(1, valid_end + 1)  # T+1
        exit_idx = np.arange(n + 1, valid_end + n + 1)  # T+n+1
        entry_prices = opens_arr[entry_idx]
        exit_prices = opens_arr[exit_idx]
        valid = (entry_prices > 0) & (exit_prices > 0)
        result[:valid_end] = np.where(valid, np.log(exit_prices / entry_prices), np.nan)
    return result


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------


# LEAD() CTE: computes all lookahead opens in one pass per (symbol, tf).
# ROWS BETWEEN CURRENT ROW AND 61 FOLLOWING — explicit frame to avoid default
# range-frame semantics which can produce unexpected results on ties (RESEARCH.md F8).
# Only bars with timestamp <= TRAINING_WINDOW_END are included in the window.
def _build_forward_return_sql(lookaheads: dict[str, int]) -> str:
    """Build LEAD()-based SQL using APR-backed lookahead periods.

    lookaheads maps scale name -> period in bars (e.g. {"fast": 1, "mid": 5, ...}).
    The max period + 1 determines the ROWS BETWEEN frame size.

    No session-boundary gate for any tf, including intraday (5m/15m/1h) — todo 208
    (2026-07-30): the prior same-ET-session complete_{scale} check for intraday tfs
    zeroed out completeness across the trading-day boundary (e.g. 1h's slow/extended
    at 0.000, mid at 53.5%), silently discarding real signal for a reason that doesn't
    hold up — overnight/weekend gaps are a known, accepted market property (1d has
    never gated on them), and the trade-construction layer that actually holds
    positions (`counterfactual_tracker.py`, `hold_max_bars`) is already session-
    agnostic and bar-indexed. `complete_{scale}` now means the same thing at every
    tf: the forward bar exists (`open_{scale} IS NOT NULL`). `return_{scale}` itself
    was never session-gated — this only changes what gets marked complete, not how
    returns are computed.

    return_{scale}_suspect (todo 148) flags |return_{scale}| > %(max_abs_return_{scale})s — a
    per-(tf, scale) plausibility ceiling catching corrupt IBKR prints (e.g. a $1000 print on a
    $25 ETF) that pass market_data_ohlcv_tradeable because they carry real volume. Ceiling
    values are sqrt(lookahead_bars)-scaled per scale by the caller — see
    ic_math.scale_max_abs_return() for the full rationale. Suspect flags are computed in a
    second SELECT layer (the `returns` CTE) because a CASE expression can't reference a
    sibling SELECT-list alias in the same query level — it needs the already-materialized
    return_{scale} value, not a re-derivation from open_entry/open_{scale}.
    """
    max_n = max(lookaheads.values())
    frame_size = max_n + 1

    # Build comma-separated LEAD column list (each needs a comma separator)
    lead_col_list = [
        f"LEAD(m.open, {n + 1}) OVER w AS open_{scale}" for scale, n in lookaheads.items()
    ]
    lead_cols = ",\n        ".join(lead_col_list)
    # open_entry = LEAD(open, 1) is always needed for the entry price (T+1 open)
    lead_t1 = "LEAD(m.open, 1) OVER w AS open_entry"

    return_col_list = [
        f"CASE WHEN open_entry > 0 AND open_{scale} > 0 "
        f"THEN ln(open_{scale} / open_entry) END AS return_{scale}"
        for scale in lookaheads
    ]
    return_cols = ",\n    ".join(return_col_list)

    # complete_{scale}: forward bar exists. Same rule at every tf (todo 208) -- no
    # session-boundary check, no fwd_ts LEAD columns needed.
    fwd_ts_select = ""
    complete_col_list = [f"(open_{scale} IS NOT NULL) AS complete_{scale}" for scale in lookaheads]

    complete_cols = ",\n    ".join(complete_col_list)

    suspect_col_list = [
        f"(return_{scale} IS NOT NULL AND abs(return_{scale}) > %(max_abs_return_{scale})s) "
        f"AS {name}"
        for scale, name in zip(lookaheads, _suspect_col_names(lookaheads), strict=True)
    ]
    suspect_cols = ",\n    ".join(suspect_col_list)
    return_names = ", ".join(f"return_{scale}" for scale in lookaheads)
    complete_names = ", ".join(f"complete_{scale}" for scale in lookaheads)

    return f"""
WITH windowed AS (
    SELECT
        m.timestamp                            AS bar_ts,
        m.symbol,
        m.timeframe                            AS tf,
        fv.pipeline_version,
        {lead_t1},
        {lead_cols}{fwd_ts_select}
    FROM market_data_ohlcv_tradeable m
    JOIN feature_vectors fv
        ON fv.symbol   = m.symbol
       AND fv.tf       = m.timeframe
       AND fv.bar_ts   = m.timestamp
    WHERE m.symbol    = %(symbol)s
      AND m.timeframe = %(tf)s
      AND m.timestamp <= %(training_window_end)s
    WINDOW w AS (
        PARTITION BY m.symbol, m.timeframe
        ORDER BY m.timestamp
        ROWS BETWEEN CURRENT ROW AND {frame_size} FOLLOWING
    )
),
returns AS (
    SELECT
        bar_ts,
        symbol,
        tf,
        pipeline_version,
        {return_cols},
        {complete_cols}
    FROM windowed
    WHERE bar_ts > %(hwm)s
)
SELECT
    bar_ts,
    symbol,
    tf,
    pipeline_version,
    {return_names},
    {complete_names},
    {suspect_cols}
FROM returns
ORDER BY bar_ts
"""


def _build_insert_sql(scales: tuple[str, ...]) -> str:
    """Build INSERT SQL for gradient-named return columns."""
    suspect_col_names = _suspect_col_names(scales)
    return_cols = ", ".join(f"return_{s}" for s in scales)
    complete_cols = ", ".join(f"complete_{s}" for s in scales)
    suspect_cols = ", ".join(suspect_col_names)
    return_vals = ", ".join(f"%(return_{s})s" for s in scales)
    complete_vals = ", ".join(f"%(complete_{s})s" for s in scales)
    suspect_vals = ", ".join(f"%({name})s" for name in suspect_col_names)
    return f"""
INSERT INTO forward_returns (
    forward_return_id, symbol, tf, bar_ts, pipeline_version, return_type,
    {return_cols},
    {complete_cols},
    {suspect_cols}
)
VALUES (
    %(forward_return_id)s, %(symbol)s, %(tf)s, %(bar_ts)s, %(pipeline_version)s, %(return_type)s,
    {return_vals},
    {complete_vals},
    {suspect_vals}
)
ON CONFLICT (symbol, tf, bar_ts) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Cross-symbol corroboration (todo 152)
# ---------------------------------------------------------------------------


def _build_corroborated_windows_temp_table_sql(scales: tuple[str, ...]) -> str:
    """Build the temp-table CREATE that pools ALL scales' suspect flags as one
    per-symbol "was this symbol suspect near this time" signal (todo 152).

    Derives the any_suspect CTE's OR clause from `scales` (mirroring
    _build_insert_sql's column-list derivation from the same tuple) rather than a
    hardcoded 4-way OR -- if _SCALES ever gains or loses a scale, this CTE picks up
    the change automatically instead of silently excluding a scale from
    corroboration (a scale missing here would never contribute to, or benefit from,
    cross-symbol corroboration, with no crash and no test failure to catch it)."""
    suspect_or_clause = " OR ".join(f"return_{s}_suspect" for s in scales)
    return f"""
CREATE TEMP TABLE corroborated_windows_tmp ON COMMIT DROP AS
WITH any_suspect AS (
    SELECT DISTINCT symbol, tf, bar_ts
    FROM forward_returns
    WHERE return_type = 'executable_open_to_open'
      AND ({suspect_or_clause})
)
SELECT a.tf, a.bar_ts
FROM any_suspect a
JOIN any_suspect b
  ON b.tf = a.tf
 AND b.bar_ts BETWEEN a.bar_ts - (%(window_minutes)s || ' minutes')::interval
                   AND a.bar_ts + (%(window_minutes)s || ' minutes')::interval
GROUP BY a.tf, a.bar_ts
HAVING count(DISTINCT b.symbol) >= %(min_symbols)s
"""


def _build_corroboration_update_sql(scale: str) -> str:
    """UPDATE clearing return_{scale}_suspect for rows whose (tf, bar_ts) is in the
    ALREADY-FROZEN corroborated_windows_tmp temp table (see
    _CORROBORATED_WINDOWS_TEMP_TABLE_SQL) -- never recomputes the pooling CTE itself,
    so 4 sequential per-scale calls all see the identical, pre-mutation determination
    (todo 152's second bug: recomputing per-scale let earlier scales' clears shrink
    the pool for later scales within the same transaction)."""
    col = f"return_{scale}_suspect"
    return f"""
UPDATE forward_returns fr
SET {col} = false
FROM corroborated_windows_tmp cw
WHERE fr.tf = cw.tf
  AND fr.bar_ts = cw.bar_ts
  AND fr.return_type = 'executable_open_to_open'
  AND fr.{col} = true
"""


def _apply_cross_symbol_corroboration(
    conn: Any, scales: tuple[str, ...], min_symbols: int, window_minutes: int, tracer: Any
) -> dict[str, int]:
    """Clear return_{scale}_suspect for rows corroborated by >= min_symbols distinct
    symbols (any scale) within +/- window_minutes -- todo 152. Freezes the
    corroboration determination ONCE into a temp table before applying any per-scale
    UPDATE, so all 4 scales share the identical pre-mutation view (see
    _build_corroboration_update_sql's docstring for why this is required, not
    optional -- verified live against the 2010-05-06 Flash Crash cluster, where
    recomputing per scale silently dropped 2 symbols' worth of evidence mid-run).

    Runs once per invocation, after the full symbol/tf loop, over the WHOLE
    forward_returns table (not scoped to this run's --symbols) so historical suspect
    rows from prior runs get corrected too.

    Returns {scale: n_rows_cleared} -- logged once as an aggregate, never per-row
    (CLAUDE.md: never log per-row inside a corpus-scale loop).
    """
    with observed_span("forward_return_writer.cross_symbol_corroboration", tracer):
        with conn.cursor() as cur:
            cur.execute(
                _build_corroborated_windows_temp_table_sql(scales),
                {"min_symbols": min_symbols, "window_minutes": window_minutes},
            )
        cleared: dict[str, int] = {}
        for scale in scales:
            sql = _build_corroboration_update_sql(scale)
            with conn.cursor() as cur:
                cur.execute(sql)
                cleared[scale] = cur.rowcount
        conn.commit()
        _logger.info(
            "forward_return_writer.cross_symbol_corroboration_applied",
            min_symbols=min_symbols,
            window_minutes=window_minutes,
            cleared=cleared,
        )
        return cleared


# ---------------------------------------------------------------------------
# Symbol discovery
# ---------------------------------------------------------------------------


def _discover_symbols(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT symbol FROM feature_vectors ORDER BY symbol")
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Per-(symbol, tf) labeling
# ---------------------------------------------------------------------------


def _label_symbol_tf(
    conn: Any,
    symbol: str,
    tf: str,
    training_window_end: Any,
    tracer: Any,
    lookaheads: dict[str, int],
    max_abs_return_by_scale: dict[str, float],
    forward_return_sql: str,
    insert_sql: str,
    batch_size: int = _INSERT_BATCH_SIZE_DEFAULT,
) -> tuple[int, int]:
    """Compute and insert forward returns for one (symbol, tf) cell.

    forward_return_sql/insert_sql are built once per run by the caller (they depend
    only on lookaheads/tf and the fixed _SCALES tuple, both invariant across the whole
    symbol loop) rather than rebuilt on every cell.

    max_abs_return_by_scale is pre-scaled per scale (see scale_max_abs_return() —
    sqrt(lookahead_bars) scaling from the tf's 1-bar baseline, todo 148).

    Returns (n_inserted, n_suspect) — n_suspect counts rows where at least one
    return_{scale}_suspect flag is true. Counted here and reported once by the
    caller rather than logged per-row (CLAUDE.md: never log per-row inside a
    corpus-scale loop).
    """
    with observed_span(
        "forward_return_writer.label_symbol_tf", tracer, symbol=symbol, tf=tf
    ) as span:
        max_n = max(lookaheads.values())
        # High-water mark: on subsequent runs, recompute the tail window (last max_n+1 bars
        # before the current max) so previously-incomplete rows get completeness updates.
        # On first run, MAX(bar_ts) is NULL — use epoch to fetch all.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(bar_ts) FROM forward_returns WHERE symbol = %s AND tf = %s",
                (symbol, tf),
            )
            row = cur.fetchone()
            max_bar_ts = row[0] if row else None
        if max_bar_ts is None:
            hwm = "1970-01-01T00:00:00+00:00"
        else:
            _TF_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "1d": 1440}
            minutes_per_bar = _TF_MINUTES.get(tf, 1440)
            lookback_minutes = (max_n + 1) * minutes_per_bar
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT %s::timestamptz - INTERVAL %s",
                    (max_bar_ts, f"{lookback_minutes} minutes"),
                )
                hwm = cur.fetchone()[0]

        params = {
            "symbol": symbol,
            "tf": tf,
            "training_window_end": training_window_end,
            "hwm": hwm,
            **{
                f"max_abs_return_{scale}": ceiling
                for scale, ceiling in max_abs_return_by_scale.items()
            },
        }

        with conn.cursor() as cur:
            cur.execute(forward_return_sql, params)
            rows = cur.fetchall()
            col_names = [d[0] for d in cur.description]

        if not rows:
            return 0, 0

        insert_rows = [dict(zip(col_names, r)) for r in rows]
        suspect_cols = _suspect_col_names(lookaheads)
        n_suspect = 0
        for row in insert_rows:
            row["forward_return_id"] = _make_forward_return_id(
                row["symbol"], row["tf"], row["bar_ts"], row["pipeline_version"]
            )
            row["return_type"] = "executable_open_to_open"
            if any(row[col] for col in suspect_cols):
                n_suspect += 1

        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                insert_sql,
                insert_rows,
                page_size=batch_size,
            )
        conn.commit()

        n_inserted = len(insert_rows)
        FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL.add(n_inserted, {"symbol": symbol, "tf": tf})

        _logger.info(
            "forward_return_writer.symbol_tf_done",
            symbol=symbol,
            tf=tf,
            n_inserted=n_inserted,
            n_suspect=n_suspect,
            training_window_end=str(training_window_end),
        )
        span.set_attribute("n_inserted", n_inserted)
        span.set_attribute("n_suspect", n_suspect)
        return n_inserted, n_suspect


# ---------------------------------------------------------------------------
# Coverage gauge
# ---------------------------------------------------------------------------


def _emit_coverage(conn: Any, symbols: list[str], tfs: list[str], scales: tuple[str, ...]) -> None:
    """Compute and emit OUTCOME_LABELS_COVERAGE per (scale, symbol, tf)."""
    for symbol in symbols:
        for tf in tfs:
            for scale in scales:
                col = f"complete_{scale}"
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"SELECT "
                            f"  count(*) FILTER (WHERE {col}) AS complete, "
                            f"  count(*) AS total "
                            f"FROM forward_returns WHERE symbol = %s AND tf = %s",
                            (symbol, tf),
                        )
                        row = cur.fetchone()
                    if row and row[1] > 0:
                        fraction = row[0] / row[1]
                        OUTCOME_LABELS_COVERAGE.set(
                            fraction, {"lookahead_scale": scale, "symbol": symbol, "tf": tf}
                        )
                except Exception as error:
                    _logger.warning(
                        "forward_return_writer.coverage_gauge_error",
                        symbol=symbol,
                        tf=tf,
                        scale=scale,
                        error=str(error),
                    )


# ---------------------------------------------------------------------------
# Price-sanity integrity fact (todo 148)
# ---------------------------------------------------------------------------


def _emit_price_sanity_fact(conn: Any, total_suspect: int, training_window_end: Any) -> None:
    """One integrity_monitor row per training_window_end recording how many rows that
    run flagged as price-sanity suspect (todo 148). Delegates to the shared
    emit_integrity_fact_sync helper (todo 150) for the actual INSERT, its guard
    (log-and-continue on failure -- never corrupts the already-committed
    forward_returns write), and idempotency pre-check.

    idempotency_check=True: unlike ic_engine.py's two integrity_monitor call sites,
    nothing upstream of this function already checks "did this training_window_end
    run before" -- evaluated_at defaults to now() and is part of the table's
    composite unique key, so ON CONFLICT alone only catches an exact-instant
    duplicate insert, not a rerun of this same training_window_end minutes/hours
    later (a retry, or an overlapping scheduled invocation).

    No single scalar threshold applies (ceilings are per-tf via
    alpha.quant.max_abs_return.{tf}) -- threshold_value is NULL, metric_value is the
    raw count this run flagged.
    """
    emit_integrity_fact_sync(
        conn,
        "price_sanity",
        None,
        "rows_flagged_suspect",
        float(total_suspect),
        None,
        True,
        training_window_end,
        idempotency_check=True,
        commit=True,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Populate forward_returns with causal forward log returns"
    )
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--tf", nargs="*", choices=_DEFAULT_TFS, default=_DEFAULT_TFS)
    parser.add_argument(
        "--training-window-end",
        default=None,
        required=False,
        help="Explicit training window end (ISO 8601, timezone-aware/UTC) -- the OOS "
        "holdout clamp (LEAST(MAX(bar_ts), alpha.validation.oos_start)). No default: a "
        "bare MAX(bar_ts) fallback would silently consume the OOS holdout window "
        "(Phase 141.1 CR-01/IN-02). See docs/plans/OOS-EVAL-PROTOCOL.md. REQUIRED unless "
        "--reclassify-suspect-only is set.",
    )
    parser.add_argument(
        "--reclassify-suspect-only",
        action="store_true",
        default=False,
        help="Skip the full forward-return computation loop; only run the cross-symbol "
        "corroboration corrective pass (todo 152) against existing forward_returns "
        "rows. Does not require --training-window-end.",
    )
    args = parser.parse_args()
    if not args.reclassify_suspect_only and args.training_window_end is None:
        parser.error("--training-window-end is required unless --reclassify-suspect-only is set.")

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("forward_return_writer.otel_init_failed", error=str(error))

    tracer = trace.get_tracer("indicagent")
    t0 = time.monotonic()
    status = "success"

    try:
        settings = Settings()
        psycopg2.extras.register_uuid()
        with observed_span("forward_return_writer.run", tracer):
            conn = psycopg2.connect(
                settings.database_url,
                options="-c idle_in_transaction_session_timeout=0",
            )
            try:
                cfg = _load_config_service(conn)

                min_corroborating_symbols = int(
                    cfg.get_sync("alpha.quant.cross_symbol_corroboration.min_symbols", 4)
                )
                corroboration_window_minutes = int(
                    cfg.get_sync("alpha.quant.cross_symbol_corroboration.window_minutes", 60)
                )

                if args.reclassify_suspect_only:
                    cleared = _apply_cross_symbol_corroboration(
                        conn,
                        _SCALES,
                        min_corroborating_symbols,
                        corroboration_window_minutes,
                        tracer,
                    )
                    _logger.info(
                        "forward_return_writer.reclassify_suspect_only_complete",
                        cleared=cleared,
                    )
                    return

                batch_size = int(
                    cfg.get_sync("alpha.ic.insert_batch_size", _INSERT_BATCH_SIZE_DEFAULT)
                )

                # Load lookahead periods from APR, per tf (alpha.ic.lookahead.{tf}.{scale})
                # -- todo 146: a single global grid was measuring a different real-world
                # horizon per tf under the same scale name (60 bars is ~3 months at 1d,
                # ~5 hours at 5m).
                lookaheads_by_tf = {
                    tf: {
                        scale: int(cfg.get_sync(f"alpha.ic.lookahead.{tf}.{scale}", fb))
                        for scale, fb in _SCALE_FALLBACKS_BY_TF[tf].items()
                    }
                    for tf in args.tf
                }
                _logger.info(
                    "forward_return_writer.lookaheads_by_tf", lookaheads_by_tf=lookaheads_by_tf
                )

                # TRAINING_WINDOW_END gate — must be computed and logged before any SQL.
                # Required flag (OOS holdout enforcement point one layer up, not a bare
                # MAX(bar_ts) fallback) — see docs/plans/OOS-EVAL-PROTOCOL.md.
                training_window_end = datetime.fromisoformat(args.training_window_end)
                if training_window_end.tzinfo is None:
                    raise ValueError(
                        "--training-window-end must be timezone-aware ISO 8601 (UTC). "
                        "Naive datetimes are rejected to preserve the UTC-only invariant."
                    )
                training_window_end = training_window_end.astimezone(UTC)
                _logger.info(
                    "forward_return_writer.training_window_end_explicit",
                    value=str(training_window_end),
                )

                _logger.info(
                    "forward_return_writer.training_window_end",
                    TRAINING_WINDOW_END=str(training_window_end),
                )

                symbols = args.symbols if args.symbols else _discover_symbols(conn)
                tfs: list[str] = args.tf

                _logger.info(
                    "forward_return_writer.starting",
                    symbols_count=len(symbols),
                    tfs=tfs,
                    TRAINING_WINDOW_END=str(training_window_end),
                )

                # Per-(tf, scale) price-sanity ceilings (alpha.quant.max_abs_return.{tf},
                # todo 148) — APR holds the tf's 1-bar baseline; scale_max_abs_return()
                # sqrt-scales it per scale. Scoped to the requested tfs only (not the full
                # 4-tf fallback set) so an APR lookup isn't wasted on a tf this run excludes.
                max_abs_return_by_tf_scale = {
                    tf: scale_max_abs_return(
                        float(
                            cfg.get_sync(
                                f"alpha.quant.max_abs_return.{tf}", _MAX_ABS_RETURN_FALLBACKS[tf]
                            )
                        ),
                        lookaheads_by_tf[tf],
                    )
                    for tf in tfs
                }
                _logger.info(
                    "forward_return_writer.max_abs_return_by_tf_scale",
                    max_abs_return_by_tf_scale=max_abs_return_by_tf_scale,
                )

                # Built once per run, not once per (symbol, tf) cell — both depend only on
                # lookaheads/tf and the fixed _SCALES tuple, invariant across the symbol loop.
                forward_return_sql_by_tf = {
                    tf: _build_forward_return_sql(lookaheads_by_tf[tf]) for tf in tfs
                }
                insert_sql = _build_insert_sql(_SCALES)

                total_inserted = 0
                total_suspect = 0
                failures: list[str] = []

                for symbol in symbols:
                    for tf in tfs:
                        try:
                            n, n_suspect = _label_symbol_tf(
                                conn=conn,
                                symbol=symbol,
                                tf=tf,
                                training_window_end=training_window_end,
                                tracer=tracer,
                                lookaheads=lookaheads_by_tf[tf],
                                max_abs_return_by_scale=max_abs_return_by_tf_scale[tf],
                                forward_return_sql=forward_return_sql_by_tf[tf],
                                insert_sql=insert_sql,
                                batch_size=batch_size,
                            )
                            total_inserted += n
                            total_suspect += n_suspect
                        except Exception as error:
                            cell = f"{symbol}/{tf}"
                            _logger.error(
                                "forward_return_writer.cell_failed",
                                cell=cell,
                                error=str(error),
                            )
                            failures.append(cell)
                            try:
                                conn.rollback()
                            except Exception:
                                try:
                                    conn.close()
                                except Exception:
                                    pass
                                conn = psycopg2.connect(
                                    settings.database_url,
                                    options="-c idle_in_transaction_session_timeout=0",
                                )

                elapsed_s = time.monotonic() - t0
                FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS.record(elapsed_s)

                _emit_coverage(conn, symbols, tfs, _SCALES)
                _emit_price_sanity_fact(conn, total_suspect, training_window_end)

                cleared = _apply_cross_symbol_corroboration(
                    conn, _SCALES, min_corroborating_symbols, corroboration_window_minutes, tracer
                )

                _logger.info(
                    "forward_return_writer.run_complete",
                    total_inserted=total_inserted,
                    total_suspect=total_suspect,
                    failed_cells=failures,
                    cleared=cleared,
                    elapsed_s=round(elapsed_s, 2),
                )

            finally:
                conn.close()

    except Exception as error:
        status = "failure"
        _logger.error("forward_return_writer.fatal_error", error=str(error))
        raise
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()
        if status == "failure":
            sys.exit(1)


if __name__ == "__main__":
    main()
