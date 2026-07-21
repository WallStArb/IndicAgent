#!/usr/bin/env python3
"""CounterfactualTracker — oneshot that fills alpha_frames geometry and closes each frame
via a direction-aware four-trigger state machine (FRAME-02/03), then evaluates the FRAME-04
day-clustered block-bootstrap exit gate.

Phase 142B, Plan 02. Depends on Plan 01's alpha_frames schema (migration 214) and
AlphaFrameWriter's compute_frame_geometry (imported here, never duplicated).

CORRECTNESS INVARIANTS:
- determine_exit is DIRECTION-AWARE (review H3, the single most important fix in this plan):
  for direction='short' the stop sits ABOVE entry (bar.high >= stop -> closed_stop) and the
  target sits BELOW (bar.low <= target -> closed_target), and pnl_r's sign flips. A long-only
  comparison would close every short frame as an instant false stop, silently corrupting
  ~half the corpus and the FRAME-04 verdict built on it.
- Fills are executable, not theoretical (review L2): a gap-through-stop fills at the worse of
  (bar.open, stop_price); mirrored for shorts. The same executable-returns discipline as
  Invariant 1, applied to frame exits.
- A frame with zero observed bars stays open -- never writes a NULL pnl (review L3b).
- Each open frame closes via exactly one of closed_stop / closed_target / closed_max_hold /
  closed_ic_decay, in strict priority order (stop checked before target on a same-bar
  both-hit).
- The bar-path scan and the ATR/geometry fill happen in ONE streaming named-cursor sweep per
  (symbol, tf) cell (review H2/M2/M4) -- no per-frame round-trip, and no read of the
  feature-vector corpus's normalized ATR derivatives (a price-unit ATR column doesn't exist
  there; ATR is computed here from market_data_ohlcv, review H2).
- ProcessPoolExecutor workers return list[dict] only; the serial write happens in the main
  process, flushed per-symbol as each worker result arrives (never one aggregate write over
  all symbols -- anti-OOM, DAG invariant #3).
- FRAME-04's exit gate is a DAY-CLUSTERED BLOCK BOOTSTRAP (review H4): frames are aggregated
  to per-calendar-day means before resampling (overlap-aware -- hold horizons up to 60 bars
  mean adjacent frames share most of their price path) -- BCa when the day-cluster count is
  small enough for a feasible jackknife, an analytic CLT lower bound above that (BCa's
  jackknife is infeasible at 10^6-row cells). Evaluated on GROSS counterfactual_pnl_r (D-01).
- The alpha_ensemble_ic row age consumed for the IC-decay trigger is instrumented (D-10); the
  read is never blocked on freshness (D-08). A recurring ensemble_ic_engine cadence is
  explicitly out of scope for this phase (D-09, follow-on todo 089).

Usage:
    python services/counterfactual_tracker.py [--backfill]
    python services/counterfactual_tracker.py --evaluate-gate
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import deque
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import asyncpg
import numpy as np
import psycopg2
import psycopg2.extras
import structlog
from scipy.stats import bootstrap

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import cfg as _cfg
from services._batch_utils import connect_db_from_url
from services._batch_utils import load_apr_dict_async as _load_apr
from services.alpha_frame_writer import FrameConfig, compute_frame_geometry
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.observability.corpus_manifest import CorpusManifest
from src.observability.metrics import COUNTERFACTUAL_TRACKER_IC_ROW_AGE_SECONDS
from src.observability.otel import OTelInitError, init_otel_providers

_logger = structlog.get_logger(__name__)

# Matches migration 215's alpha.scoring.bootstrap_random_state seed default -- kept as one
# named constant instead of a literal repeated across frame_gate_passes/evaluate_frame_gate/
# _run_evaluate_gate's APR fallback, so the three can't silently drift apart.
_DEFAULT_BOOTSTRAP_RANDOM_STATE = 42


class Bar(NamedTuple):
    """One OHLC bar. `open` is required for executable gap-through fills (review L2)."""

    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class ExitResult:
    """Result of determine_exit: which trigger fired, how many bars it took, and the
    executable exit price."""

    status: str
    bars: int
    exit_price: float | None


def determine_exit(
    direction: str,
    bars_since_entry: Sequence[Bar],
    stop_price: float,
    target_price: float,
    hold_max_bars: int,
    ic_ci_lower: float | None,
) -> ExitResult | None:
    """FRAME-02/03 direction-aware four-trigger exit state machine.

    Priority per bar (stop checked before target -- conservative on a same-bar both-hit):
      direction='long':  (1) bar.low <= stop_price -> closed_stop, exit = min(bar.open, stop)
                          (2) bar.high >= target_price -> closed_target, exit = target
      direction='short': (1) bar.high >= stop_price -> closed_stop, exit = max(bar.open, stop)
                          (2) bar.low <= target_price -> closed_target, exit = target
      both directions:   (3) i >= hold_max_bars -> closed_max_hold, exit = bar.close

    After the bar loop with no per-bar exit: (4) ic_ci_lower is not None and < 0 ->
    closed_ic_decay, exit = last bar.close; otherwise the frame stays open (returns None).
    The ic_ci_lower value is used as given regardless of the underlying row's age (D-08) --
    this function takes the value already fetched, it does not gate on freshness itself.

    An empty bar list returns None immediately -- the frame stays open, never a fabricated
    close with a NULL pnl (review L3b). `bars` on the returned ExitResult is 1-indexed from
    entry (the number of bars observed before/at the exit trigger).
    """
    if direction not in ("long", "short"):
        raise ValueError(f"determine_exit: unknown direction {direction!r}")
    if not bars_since_entry:
        return None

    for i, bar in enumerate(bars_since_entry, start=1):
        if direction == "long":
            if bar.low <= stop_price:
                return ExitResult("closed_stop", i, min(bar.open, stop_price))
            if bar.high >= target_price:
                return ExitResult("closed_target", i, target_price)
        else:  # direction == "short"
            if bar.high >= stop_price:
                return ExitResult("closed_stop", i, max(bar.open, stop_price))
            if bar.low <= target_price:
                return ExitResult("closed_target", i, target_price)
        if i >= hold_max_bars:
            return ExitResult("closed_max_hold", i, bar.close)

    if ic_ci_lower is not None and ic_ci_lower < 0:
        return ExitResult("closed_ic_decay", len(bars_since_entry), bars_since_entry[-1].close)
    return None


def compute_frame_pnl_r(
    direction: str, entry_price: float, stop_price: float, exit_price: float
) -> float:
    """Direction-aware realized P&L in R (risk multiples).

    risk = abs(entry_price - stop_price) -- the stop distance, always positive.
    long -> (exit_price - entry_price) / risk ; short -> (entry_price - exit_price) / risk.
    A stop-out is ~ -1.0 R in both directions; a target hit is ~ +target_r_multiple R.
    """
    if direction not in ("long", "short"):
        raise ValueError(f"compute_frame_pnl_r: unknown direction {direction!r}")
    risk = abs(entry_price - stop_price)
    if direction == "long":
        return (exit_price - entry_price) / risk
    return (entry_price - exit_price) / risk


def frame_gate_passes(
    pnl_r_values: Sequence[float],
    cluster_ids: Sequence[Any],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE,
) -> tuple[bool, float, float]:
    """FRAME-04 day-clustered block-bootstrap exit gate (review H4).

    Aggregates pnl to per-cluster (calendar-day) means BEFORE resampling -- overlapping hold
    horizons make per-frame i.i.d. resampling anticonservative (a gate that can pass on noise
    defeats the phase's purpose). Below bootstrap_max_n day-clusters, uses
    scipy.stats.bootstrap (method='BCa', one-sided alternative='greater', batch=
    bootstrap_batch to cap peak resample-matrix memory). Above bootstrap_max_n clusters,
    BCa's jackknife (N leave-one-out evaluations) is computationally infeasible and its
    bias-correction negligible at that cluster count, so an analytic one-sided 95% CLT lower
    bound is used instead: mean - 1.645 * std(ddof=1) / sqrt(n_clusters).

    Returns (passes, ci_lower, ci_upper). passes iff ci_lower > 0.
    Returns (False, nan, nan) when len(pnl_r_values) < min_n (the alpha.scoring.
    min_strategy_n frame-count sufficiency floor) or when fewer than 2 day-clusters exist
    (a bootstrap CI cannot be formed from <2 blocks).

    bootstrap_random_state seeds scipy's BCa resampling (alpha.scoring.bootstrap_random_state
    APR key, default 42) so the frozen SHADOW-REVIEW.md "no post-hoc gate renegotiation" verdict
    is reproducible across identical re-runs (code-review WR-01) -- changing this key invalidates
    any prior gate verdict for cells that used the BCa path (len(cluster_means) <= bootstrap_max_n).
    """
    if len(pnl_r_values) < min_n:
        return False, float("nan"), float("nan")

    cluster_members: dict[Any, list[float]] = {}
    for pnl, cluster_id in zip(pnl_r_values, cluster_ids):
        cluster_members.setdefault(cluster_id, []).append(pnl)
    cluster_means = np.array(
        [float(np.mean(values)) for values in cluster_members.values()], dtype=float
    )

    if len(cluster_means) < 2:
        return False, float("nan"), float("nan")

    if len(cluster_means) <= bootstrap_max_n:
        result = bootstrap(
            (cluster_means,),
            np.mean,
            confidence_level=0.95,
            alternative="greater",
            method="BCa",
            batch=bootstrap_batch,
            random_state=np.random.default_rng(bootstrap_random_state),
        )
        ci_lower = float(result.confidence_interval.low)
        ci_upper = float(result.confidence_interval.high)
    else:
        # Analytic one-sided 95% CLT lower bound -- BCa's jackknife is infeasible at this
        # cluster count and its bias correction negligible here (review H4).
        n_clusters = len(cluster_means)
        mean = float(np.mean(cluster_means))
        std = float(np.std(cluster_means, ddof=1))
        ci_lower = mean - 1.645 * std / np.sqrt(n_clusters)
        ci_upper = float("inf")

    return bool(ci_lower > 0), ci_lower, ci_upper


# ---------------------------------------------------------------------------
# Worker (pure compute -- opens a read-only connection, never a write connection;
# DAG invariant #3, T-142B-06)
# ---------------------------------------------------------------------------

# Bounded per-cell fetch (never more rows than this cell's open-frame count) -- safe to
# buffer client-side with a regular (non-named) cursor.
_OPEN_FRAMES_SQL = """
    SELECT frame_id, bar_ts, direction, max_hold_bars, stop_atr_mult, target_r_multiple, regime
    FROM alpha_frames
    WHERE symbol = %s AND tf = %s AND status = 'open' AND frame_variant = 'primary'
    ORDER BY bar_ts ASC
"""

# Most-recent alpha_ensemble_ic row per regime for this (symbol, tf) -- read regardless of
# age (D-08); a handful of rows (one per regime), safe to buffer client-side.
_IC_CI_LOWER_SQL = """
    SELECT DISTINCT ON (regime) regime, ic_ci_lower, scored_at
    FROM alpha_ensemble_ic
    WHERE symbol = %s AND tf = %s
    ORDER BY regime, scored_at DESC
"""

# Trailing history to seed the rolling price-unit ATR window "as of" the earliest open
# frame's bar_ts (review H2 -- computed from market_data_ohlcv, never a feature-vector
# derivative). +1 row so the oldest row in the window has a prior close for its true range.
_ATR_SEED_SQL = """
    SELECT open, high, low, close
    FROM market_data_ohlcv_tradeable
    WHERE symbol = %s AND timeframe = %s AND timestamp <= %s
    ORDER BY timestamp DESC
    LIMIT %s
"""

# Forward bar-path scan (review H2/M2/M4: ONE streaming pass per (symbol, tf) cell, not one
# cursor per frame). Bar-count-scoped (review L3c): no wall-clock WHERE-range arithmetic --
# the Python loop below terminates once every open frame in this cell has been activated
# and resolved (or exhausted its own max_hold_bars window), a bar-count-driven condition,
# not a calendar-date one. Sessions/gaps on intraday TFs make timestamp-range math wrong.
_BAR_SCAN_SQL = """
    SELECT timestamp, open, high, low, close
    FROM market_data_ohlcv_tradeable
    WHERE symbol = %s AND timeframe = %s AND timestamp > %s
    ORDER BY timestamp ASC
"""


def _true_range(high: float, low: float, prev_close: float | None) -> float:
    """Wilder/SMA-style true range for one bar. No prior close (series start) falls back
    to the simple high-low range."""
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _compute_excursion(
    direction: str, entry_price: float, stop_price: float, bars: Sequence[Bar]
) -> tuple[float, float]:
    """Direction-aware MFE/MAE in R units (same risk denominator as compute_frame_pnl_r) over
    the bars actually observed before the frame closed. Favorable excursion is up for long,
    down for short."""
    risk = abs(entry_price - stop_price)
    if direction == "long":
        mfe = max((bar.high - entry_price) / risk for bar in bars)
        mae = min((bar.low - entry_price) / risk for bar in bars)
    else:
        mfe = max((entry_price - bar.low) / risk for bar in bars)
        mae = min((entry_price - bar.high) / risk for bar in bars)
    return mfe, mae


def _finalize_frame(state: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """Score one active frame's accumulated bar window via determine_exit. Returns None
    (nothing to write) if the frame is still open -- never fabricates a close (review L3b)."""
    frame = state["frame"]
    direction = state["direction"]
    exit_result = determine_exit(
        direction,
        state["bars"],
        state["stop_price"],
        state["target_price"],
        frame["max_hold_bars"],
        state["ic_ci_lower"],
    )
    if exit_result is None:
        return None

    pnl_r = compute_frame_pnl_r(
        direction, state["entry_price"], state["stop_price"], exit_result.exit_price
    )
    mfe, mae = _compute_excursion(
        direction, state["entry_price"], state["stop_price"], state["bars"][: exit_result.bars]
    )
    return {
        "frame_id": frame["frame_id"],
        "bar_ts": frame["bar_ts"],
        "entry_price": state["entry_price"],
        "stop_price": state["stop_price"],
        "target_price": state["target_price"],
        "r_multiple": state["r_multiple"],
        "status": exit_result.status,
        "counterfactual_pnl_r": pnl_r,
        "counterfactual_mfe": mfe,
        "counterfactual_mae": mae,
        "counterfactual_bars": exit_result.bars,
        "exit_reason": exit_result.status,
        "closed_at": now,
        "measured_at": now,
        # Observability-only fields, not part of the UPDATE column set (main process reads
        # these to instrument IC-row staleness, D-10; never written to alpha_frames).
        "symbol": frame["symbol"],
        "tf": frame["tf"],
        "regime": frame["regime"],
        "ic_scored_at": state["ic_scored_at"],
    }


def _scan_symbol_tf(
    conn: Any,
    symbol: str,
    tf: str,
    atr_period: int,
    default_target_r_multiple: float,
    itersize: int,
) -> tuple[list[dict[str, Any]], int]:
    """ONE streaming named-cursor sweep over market_data_ohlcv for this (symbol, tf) cell,
    filling geometry (T+1 entry + causal price-unit ATR) and scoring the exit for every open
    frame in the cell -- never a per-frame round-trip (review H2/M2/M4).

    `default_target_r_multiple` is a fallback for legacy rows written before migration 215
    (NULL target_r_multiple). Every frame normally carries its own target_r_multiple snapshot
    (code-review CR-02) so a mid-run APR recalibration cannot desync it from the
    gross_expected_r/net_expected_r diagnostics AlphaFrameWriter computed at creation time.

    Returns (results, degenerate_atr_skip_count) -- the skip count is an in-loop counter, not
    a per-occurrence log call: this runs inside a ProcessPoolExecutor subprocess (workers log
    only, per ic_engine.py's convention) over a potentially large bar stream, so visibility is
    an aggregate the caller reports once, not a log line per degenerate frame."""
    conn.commit()  # clear any stale transaction before the bounded fetches below
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_OPEN_FRAMES_SQL, (symbol, tf))
        open_frames = cur.fetchall()
    if not open_frames:
        return [], 0

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_IC_CI_LOWER_SQL, (symbol, tf))
        ic_by_regime = {
            row["regime"]: (row["ic_ci_lower"], row["scored_at"]) for row in cur.fetchall()
        }

    min_bar_ts = open_frames[0]["bar_ts"]
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_ATR_SEED_SQL, (symbol, tf, min_bar_ts, atr_period + 1))
        seed_bars = list(reversed(cur.fetchall()))  # DESC fetch -> chronological order

    tr_window: deque[float] = deque(maxlen=atr_period)
    last_close: float | None = None
    for seed_bar in seed_bars:
        tr_window.append(_true_range(float(seed_bar["high"]), float(seed_bar["low"]), last_close))
        last_close = float(seed_bar["close"])

    active: dict[str, dict[str, Any]] = {}
    frame_idx = 0
    now = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    degenerate_atr_skip_count = 0

    conn.commit()  # precondition for declaring a named (server-side) cursor
    cursor_name = f"cf_scan_{symbol}_{tf}"
    with conn.cursor(name=cursor_name, cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.itersize = itersize
        cur.execute(_BAR_SCAN_SQL, (symbol, tf, min_bar_ts))

        for bar_row in cur:
            bar = Bar(
                open=float(bar_row["open"]),
                high=float(bar_row["high"]),
                low=float(bar_row["low"]),
                close=float(bar_row["close"]),
            )
            bar_ts = bar_row["timestamp"]

            # Activate every frame whose T+1 entry is exactly this bar (the first bar with
            # timestamp > frame.bar_ts). tr_window at this point reflects only bars <=
            # frame.bar_ts (it is rolled forward with the CURRENT bar at the bottom of this
            # loop, after activation) -- the causal, no-lookahead ATR (review H2).
            while frame_idx < len(open_frames) and open_frames[frame_idx]["bar_ts"] < bar_ts:
                frame = open_frames[frame_idx]
                frame_idx += 1
                if len(tr_window) < atr_period:
                    # Series start -- insufficient trailing history for this frame's ATR.
                    # Leave it open this run rather than fabricating a geometry (Claude's
                    # Discretion, CONTEXT.md).
                    continue
                atr = sum(tr_window) / len(tr_window)
                direction = frame["direction"]
                entry_price = bar.open
                frame_target_r_multiple = (
                    float(frame["target_r_multiple"])
                    if frame["target_r_multiple"] is not None
                    else default_target_r_multiple
                )
                try:
                    stop_price, target_price, r_multiple = compute_frame_geometry(
                        direction,
                        entry_price,
                        atr,
                        float(frame["stop_atr_mult"]),
                        frame_target_r_multiple,
                    )
                except ValueError:
                    # Degenerate stop distance (zero ATR on stale/forward-filled bars) --
                    # skip this frame, leave it open, do NOT let one bad bar abort the rest
                    # of this cell's scan (code-review CR-01). Counted, reported once by the
                    # caller -- not logged per-occurrence (this runs in a worker subprocess).
                    degenerate_atr_skip_count += 1
                    continue
                ic_ci_lower, ic_scored_at = ic_by_regime.get(frame["regime"], (None, None))
                active[frame["frame_id"]] = {
                    "frame": {**frame, "symbol": symbol, "tf": tf},
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "target_price": target_price,
                    "r_multiple": r_multiple,
                    "direction": direction,
                    "bars": [],
                    "ic_ci_lower": ic_ci_lower,
                    "ic_scored_at": ic_scored_at,
                }

            # Feed this bar to every currently active frame's observation window.
            for frame_id in list(active.keys()):
                state = active[frame_id]
                state["bars"].append(bar)
                if len(state["bars"]) >= state["frame"]["max_hold_bars"]:
                    result = _finalize_frame(state, now)
                    if result is not None:
                        results.append(result)
                    del active[frame_id]

            # Roll the ATR window forward with this bar (AFTER activation -- see comment
            # above: tr_window must reflect only bars <= frame.bar_ts at activation time).
            tr_window.append(_true_range(bar.high, bar.low, last_close))
            last_close = bar.close

            # Bar-count-scoped early exit (review L3c): every open frame in this cell has
            # either been activated-and-resolved or was skipped for insufficient trailing
            # history -- nothing left to scan for. Avoids reading the rest of the corpus's
            # history for a cell whose frames are all already closed.
            if frame_idx >= len(open_frames) and not active:
                break

    # Stream exhausted (or early-break) with some frames still active -- finalize with
    # whatever was observed; determine_exit returns None (still open) if nothing triggered,
    # never a fabricated close (review L3b).
    for state in active.values():
        result = _finalize_frame(state, now)
        if result is not None:
            results.append(result)

    return results, degenerate_atr_skip_count


def _run_counterfactual_worker(args: tuple) -> dict[str, Any]:
    """ProcessPoolExecutor worker -- runs in subprocess. Opens ONE read-only connection for
    this symbol and, for each of its tfs, does exactly ONE streaming pass over
    market_data_ohlcv evaluating ALL the cell's open frames (never one cursor per frame,
    review M4). Returns list[dict] rows only -- NEVER opens a write connection and performs
    no batch-persistence call of any kind (DAG invariant #3, T-142B-06).

    Args:
        args: (symbol, tfs, dsn, atr_period, default_target_r_multiple, itersize)

    Returns:
        dict with keys: symbol (str), rows (list[dict]), errors (list[str]) -- one entry per
        tf that failed to fetch/compute; a partial per-tf failure does not discard the
        symbol's other tfs -- and degenerate_atr_skip_count (int), summed across this
        symbol's tfs. Workers log only (no OTel tracer in a subprocess, ic_engine.py's
        convention); the main process aggregates and reports this count once.
    """
    symbol, tfs, dsn, atr_period, default_target_r_multiple, itersize = args
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    degenerate_atr_skip_count = 0

    try:
        conn = connect_db_from_url(dsn)
    except Exception as error:
        return {"symbol": symbol, "rows": rows, "errors": [f"{symbol}: connection failed: {error}"]}

    try:
        for tf in tfs:
            # Connection-staleness check + reconnect before each per-symbol unit of work
            # (mirrors infrastructure_run_historical_pipeline.py's precedent).
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as probe_cur:
                    probe_cur.execute("SELECT 1")
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = connect_db_from_url(dsn)
            try:
                tf_rows, tf_skip_count = _scan_symbol_tf(
                    conn, symbol, tf, atr_period, default_target_r_multiple, itersize
                )
                rows.extend(tf_rows)
                degenerate_atr_skip_count += tf_skip_count
            except Exception as error:
                errors.append(f"{symbol}/{tf}: {error}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return {
        "symbol": symbol,
        "rows": rows,
        "errors": errors,
        "degenerate_atr_skip_count": degenerate_atr_skip_count,
    }


# ---------------------------------------------------------------------------
# CounterfactualTracker
# ---------------------------------------------------------------------------


class CounterfactualTracker(BaseBatch):
    """Batch compute service: fills alpha_frames geometry and closes each frame via the
    direction-aware exit state machine (FRAME-02/03), then (in --evaluate-gate mode)
    evaluates the FRAME-04 day-clustered block-bootstrap exit gate."""

    job_name = "counterfactual-tracker"
    compute_version = "1.0.0"

    # Keys/order MUST match _row_to_update_tuple's tuple construction exactly.
    _UPDATE_KEYS: tuple[str, ...] = (
        "frame_id",
        "bar_ts",
        "entry_price",
        "stop_price",
        "target_price",
        "r_multiple",
        "status",
        "counterfactual_pnl_r",
        "counterfactual_mfe",
        "counterfactual_mae",
        "counterfactual_bars",
        "exit_reason",
        "closed_at",
        "measured_at",
    )

    # WHERE frame_id = $1 AND bar_ts = $2: the composite (frame_id, bar_ts) PK from
    # migration 214 (review M3). status = 'open' makes every UPDATE an immutability guard --
    # a re-run never re-closes an already-closed frame.
    _UPDATE_SQL = """
        UPDATE alpha_frames
        SET entry_price = $3,
            stop_price = $4,
            target_price = $5,
            r_multiple = $6,
            status = $7,
            counterfactual_pnl_r = $8,
            counterfactual_mfe = $9,
            counterfactual_mae = $10,
            counterfactual_bars = $11,
            exit_reason = $12,
            closed_at = $13,
            measured_at = $14
        WHERE frame_id = $1 AND bar_ts = $2 AND status = 'open'
    """

    def __init__(self, db_dsn: str, backfill: bool = False) -> None:
        super().__init__(db_dsn)
        self.backfill = backfill

    def _row_to_update_tuple(self, row: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(row[key] for key in self._UPDATE_KEYS)

    def _instrument_ic_staleness(self, rows: list[dict[str, Any]]) -> None:
        """D-10: make the IC-decay trigger's row age observable. Never freshness-gates the
        read itself (D-08) -- this only sets a point gauge from data workers already
        returned, main-process-side (workers stay metric-free, DAG invariant #3)."""
        now = datetime.now(UTC)
        seen: set[tuple[Any, Any, Any]] = set()
        for row in rows:
            key = (row.get("symbol"), row.get("tf"), row.get("regime"))
            scored_at = row.get("ic_scored_at")
            if key in seen or scored_at is None:
                continue
            seen.add(key)
            age_seconds = (now - scored_at).total_seconds()
            COUNTERFACTUAL_TRACKER_IC_ROW_AGE_SECONDS.set(
                age_seconds, {"symbol": key[0], "tf": key[1], "regime": key[2]}
            )

    async def _flush_worker_results(
        self, pool: asyncpg.Pool, results_iter: Iterable[list[dict[str, Any]]]
    ) -> int:
        """Per-symbol incremental flush (anti-OOM write-side twin of the read-side named-
        cursor fix, T-142B-08). Consumes an ITERABLE of per-symbol row-lists and, for EACH
        batch as it arrives, does exactly ONE serial async batch UPDATE then releases the
        connection -- NEVER accumulates all symbols' rows into one aggregate write (the
        client-side unbounded-accumulation OOM shape that crashed production twice)."""
        total_written = 0
        for symbol_rows in results_iter:
            if not symbol_rows:
                continue
            tuples = [self._row_to_update_tuple(row) for row in symbol_rows]
            async with pool.acquire() as wconn:
                await wconn.executemany(self._UPDATE_SQL, tuples)
            total_written += len(tuples)
        return total_written

    async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
        manifest = CorpusManifest("counterfactual_tracker", CorpusManifest.DEFAULT_MANIFEST_DIR)
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise

    async def _execute_inner(self, pool: asyncpg.Pool, manifest: CorpusManifest) -> None:
        async with pool.acquire() as conn:
            cfg = await _load_apr(conn, extra_like_patterns=["infra.counterfactual_tracker.%"])
            # Reuses AlphaFrameWriter's own APR-binding (same default literals, one source of
            # truth) instead of re-declaring alpha.frame.atr_period/target_r_multiple inline.
            frame_config = FrameConfig.from_apr(cfg)
            atr_period = frame_config.atr_period
            default_target_r_multiple = frame_config.target_r_multiple
            itersize = _cfg(cfg, "infra.counterfactual_tracker.itersize", 5000)
            n_workers = _cfg(cfg, "infra.counterfactual_tracker.workers", 12)

            partitions = await conn.fetch(
                "SELECT DISTINCT symbol, tf FROM alpha_frames "
                "WHERE status = 'open' AND frame_variant = 'primary' ORDER BY symbol, tf"
            )

        symbol_to_tfs: dict[str, list[str]] = {}
        for part in partitions:
            symbol_to_tfs.setdefault(part["symbol"], []).append(part["tf"])

        self.logger.info(
            "counterfactual_tracker.config_loaded",
            atr_period=atr_period,
            default_target_r_multiple=default_target_r_multiple,
            itersize=itersize,
            n_workers=n_workers,
            n_symbols=len(symbol_to_tfs),
            backfill=self.backfill,
        )
        manifest.set_inputs(backfill=self.backfill, n_symbols=len(symbol_to_tfs))

        if not symbol_to_tfs:
            self.logger.info("counterfactual_tracker.no_open_frames")
            manifest.mark_success()
            manifest.write()
            return

        worker_args = [
            (symbol, tfs, self._db_dsn, atr_period, default_target_r_multiple, itersize)
            for symbol, tfs in symbol_to_tfs.items()
        ]
        worker_errors: list[str] = []
        total_degenerate_atr_skips = 0

        def _row_lists() -> Iterable[list[dict[str, Any]]]:
            nonlocal total_degenerate_atr_skips
            n_done = 0
            with ProcessPoolExecutor(max_workers=n_workers) as exe:
                # as_completed, not exe.map(): map() yields in SUBMISSION order, so one slow
                # symbol/tf partition (e.g. an intraday tf over a 20y history) would stall
                # every later-ordered symbol's flush even though it already finished computing
                # -- silently defeating the per-symbol incremental flush below and turning any
                # restart into a from-scratch redo of the same head-of-line partition.
                futures = {
                    exe.submit(_run_counterfactual_worker, args): args[0] for args in worker_args
                }
                for future in as_completed(futures):
                    result = future.result()
                    n_done += 1
                    worker_errors.extend(result.get("errors", []))
                    total_degenerate_atr_skips += result.get("degenerate_atr_skip_count", 0)
                    rows = result.get("rows", [])
                    self._instrument_ic_staleness(rows)
                    self.logger.info(
                        "counterfactual_tracker.symbol_complete",
                        symbol=result.get("symbol"),
                        n_rows=len(rows),
                        n_done=n_done,
                        n_total=len(worker_args),
                    )
                    yield rows

        total_written = await self._flush_worker_results(pool, _row_lists())

        if worker_errors:
            self.logger.error(
                "counterfactual_tracker.worker_errors",
                n_failed=len(worker_errors),
                n_symbols=len(worker_args),
                errors=worker_errors[:10],
            )

        if total_degenerate_atr_skips:
            # CR-01: aggregate count of frames skipped for a degenerate (zero) ATR on
            # stale/forward-filled bars -- reported once here, not per-occurrence in the
            # worker subprocess.
            self.logger.warning(
                "counterfactual_tracker.degenerate_atr_skip",
                total_skipped=total_degenerate_atr_skips,
            )

        manifest.add_output(table_name="alpha_frames", rows_total=total_written)
        manifest.mark_success()
        manifest_path = manifest.write()
        self.logger.info(
            "counterfactual_tracker.complete",
            total_written=total_written,
            manifest_path=str(manifest_path),
        )


# ---------------------------------------------------------------------------
# FRAME-04 gate evaluation (--evaluate-gate CLI mode)
# ---------------------------------------------------------------------------


def evaluate_frame_gate(
    rows: Iterable[dict[str, Any]],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE,
) -> list[dict[str, Any]]:
    """Pure grouping/aggregation core for the FRAME-04 in-sample exit gate.

    Takes an in-memory iterable of dicts with keys tf, regime, cluster_id, pnl_r -- pnl_r is
    the GROSS realized counterfactual_pnl_r (D-01); this function applies no adjustment to
    it whatsoever. Groups by (tf, regime), passing each cell's per-frame calendar-date
    cluster_id straight into frame_gate_passes unmodified (day-clustered, review H4), and
    respects the min_n frame-count sufficiency floor via that same call.

    Returns one verdict dict per (tf, regime) cell: tf, regime, n_frames, n_clusters,
    ci_lower, ci_upper, passes.
    """
    groups: dict[tuple[Any, Any], dict[str, list[Any]]] = {}
    for row in rows:
        key = (row["tf"], row["regime"])
        bucket = groups.setdefault(key, {"pnl_r": [], "cluster_id": []})
        bucket["pnl_r"].append(row["pnl_r"])
        bucket["cluster_id"].append(row["cluster_id"])

    verdicts: list[dict[str, Any]] = []
    for (tf, regime), bucket in groups.items():
        passes, ci_lower, ci_upper = frame_gate_passes(
            bucket["pnl_r"],
            bucket["cluster_id"],
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
        )
        verdicts.append(
            {
                "tf": tf,
                "regime": regime,
                "n_frames": len(bucket["pnl_r"]),
                "n_clusters": len(set(bucket["cluster_id"])),
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "passes": passes,
            }
        )
    return verdicts


# In-sample only (bar_ts < oos_start); frame_variant='primary' (the sole variant this phase
# writes); status != 'open' (closed frames only -- an open frame has no counterfactual_pnl_r
# to gate on). bar_ts::date is the per-frame calendar-day cluster_id (review H4).
_GATE_QUERY_SQL = """
    SELECT tf, regime, bar_ts::date AS cluster_id, counterfactual_pnl_r AS pnl_r
    FROM alpha_frames
    WHERE frame_variant = 'primary'
      AND status != 'open'
      AND bar_ts < $1
      AND counterfactual_pnl_r IS NOT NULL
"""


async def _run_evaluate_gate(db_dsn: str) -> None:
    """--evaluate-gate CLI mode: a distinct read-only reporting branch, not a third service
    (keeps ROADMAP's 2-service scope). No D-06 job_completed_total emission -- this performs
    no persistence, unlike CounterfactualTracker.execute()."""
    conn = await asyncpg.connect(db_dsn)
    try:
        apr_rows = await conn.fetch(
            "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
            ["alpha.scoring.%"],
        )
        apr_cfg = {row["config_key"]: row["config_value"] for row in apr_rows}
        min_n = _cfg(apr_cfg, "alpha.scoring.min_strategy_n", 30)
        bootstrap_max_n = _cfg(apr_cfg, "alpha.scoring.bootstrap_max_n", 5000)
        bootstrap_batch = _cfg(apr_cfg, "alpha.scoring.bootstrap_batch", 1000)
        bootstrap_random_state = _cfg(
            apr_cfg, "alpha.scoring.bootstrap_random_state", _DEFAULT_BOOTSTRAP_RANDOM_STATE
        )

        oos_start = await conn.fetchval(
            "SELECT config_value::timestamptz FROM config_state "
            "WHERE config_key = 'alpha.validation.oos_start'"
        )
        if oos_start is None:
            raise RuntimeError(
                "counterfactual_tracker --evaluate-gate FAILED: alpha.validation.oos_start "
                "is not set in config_state -- a missing OOS boundary would silently exclude "
                "every row from the gate (bar_ts < NULL never matches)."
            )

        gate_rows = await conn.fetch(_GATE_QUERY_SQL, oos_start)
    finally:
        await conn.close()

    verdicts = evaluate_frame_gate(
        [dict(row) for row in gate_rows],
        min_n,
        bootstrap_max_n,
        bootstrap_batch,
        bootstrap_random_state,
    )

    manifest = CorpusManifest("counterfactual_tracker_gate", CorpusManifest.DEFAULT_MANIFEST_DIR)
    manifest.set_inputs(n_cells=len(verdicts), oos_start=str(oos_start))
    for verdict in verdicts:
        _logger.info("counterfactual_tracker.gate_verdict", **verdict)
    n_passing = sum(1 for verdict in verdicts if verdict["passes"])
    manifest.add_output(table_name="alpha_frames_gate_verdicts", rows_total=len(verdicts))
    manifest.mark_success()
    manifest.write()
    _logger.info(
        "counterfactual_tracker.gate_summary",
        n_cells=len(verdicts),
        n_passing=n_passing,
        n_failing=len(verdicts) - n_passing,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Counterfactual Tracker -- closes alpha_frames via FRAME-02/03 (D-05)"
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "Process the full existing open-frame backlog in one pass (D-05). Uses the same "
            "open-frame scoping as nightly-incremental -- the write path is identical."
        ),
    )
    parser.add_argument(
        "--evaluate-gate",
        action="store_true",
        help=(
            "Evaluate the FRAME-04 in-sample exit gate (bar_ts < alpha.validation.oos_start, "
            "frame_variant='primary') per (tf, regime) via the day-clustered block-bootstrap "
            "core, on GROSS counterfactual_pnl_r (D-01). Read-only -- writes no alpha_frames "
            "rows."
        ),
    )
    args = parser.parse_args()

    try:
        init_otel_providers("indicagent-counterfactual-tracker")
    except OTelInitError as error:
        _logger.warning("counterfactual_tracker.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    if args.evaluate_gate:
        asyncio.run(_run_evaluate_gate(db_dsn))
    else:
        asyncio.run(CounterfactualTracker(db_dsn=db_dsn, backfill=args.backfill).run())
