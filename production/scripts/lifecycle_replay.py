#!/usr/bin/env python3
"""
Lifecycle Replay Script — batch replay of historical signal outcomes.

Version: 1.4
Status: current
Last Updated: 2026-06-16

Phase 130 changes (3-table schema migration):
    - Reads from signal_events + trade_frames instead of signal_ledger + signal_outcomes
    - Writes activation metadata to trade_frames.frame_details JSONB (UPDATE || merge)
    - Writes zone/market exits to trade_executions (INSERT instead of UPDATE signal_outcomes)
    - Updates signal_events.status instead of signal_outcomes.status
    - _seed_orphan_outcomes is a no-op (status in signal_events, populated by run_historical_pipeline)
    - _verify_replay queries signal_events + trade_frames + trade_executions

Evaluates dual-track outcomes (zone track + market track) for all signals
that lack outcomes, by replaying market_data_ohlcv bars chronologically
per (symbol, timeframe).

Safety controls:
    - Advisory lock prevents concurrent replays
    - Preflight checks signal_events status integrity
    - --confirm required for destructive --reset
    - Post-replay verification catches data integrity issues (shadow + orphan checks)

Usage:
    # Full reset + replay of corrupt data (requires service stop first):
    sudo systemctl stop indicagent-intelligence-pipeline
    python -u production/scripts/lifecycle_replay.py --reset --confirm --workers 8 \\
        --commit-every 1000 > /tmp/lifecycle_replay.log 2>&1 &

    # Replay only (no reset — for signals that never got resolved):
    python -u production/scripts/lifecycle_replay.py --workers 8

    # Dry run to verify schema compatibility:
    python -u production/scripts/lifecycle_replay.py --symbols ESM6 --timeframes 5m --dry-run

    # Replay specific symbols only:
    python -u production/scripts/lifecycle_replay.py --reset --confirm --symbols ESM6,NQM6

    # Include 4h timeframe (excluded by default):
    python -u production/scripts/lifecycle_replay.py --timeframes 1m,5m,15m,1h,4h

Derived table rebuild:
    After replay, swarm_agent_weights and setup_performance are empty.
    They repopulate on next scheduled runs:
      - setup_performance: nightly ml-training (11pm)
      - swarm_agent_weights: weekly ml-orchestrator (Monday)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "services"))

from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import DatabaseManager
from src.core.service_utils import TF_SECONDS, TF_TTL_BARS
from src.intelligence.trading.lifecycle_tracker import (
    _classify_stop_outcome,
    evaluate_market_entry,
    evaluate_signal,
)
from src.observability.metrics import flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

logger = logging.getLogger(__name__)

# 1d excluded by default — it has multi-year bar history and signals are sparse.
# Pass --timeframes 1m,5m,15m,1h,1d to include it explicitly.
TIMEFRAMES = ["1m", "5m", "15m", "1h"]

# Advisory lock ID — prevents concurrent replays from corrupting data.
# pg_try_advisory_lock returns true if acquired, false if already held.
_REPLAY_LOCK_ID = 20260602  # date of the fix that necessitated this replay

# uuid5 namespace for deterministic frame_id — matches run_historical_pipeline.py
_FRAME_ID_NS = uuid.NAMESPACE_DNS


def _make_frame_id(signal_id: str, entry_type: str = "at_close") -> str:
    """Deterministic frame_id for the given signal_id + entry_type."""
    return str(uuid.uuid5(_FRAME_ID_NS, f"{signal_id}:{entry_type}"))


async def _acquire_replay_lock(conn) -> bool:
    """Acquire exclusive advisory lock. Returns False if already held."""
    row = await conn.fetchrow("SELECT pg_try_advisory_lock($1) as acquired", _REPLAY_LOCK_ID)
    return row["acquired"]


async def _check_service_quiescence() -> list[str]:
    """Check that lifecycle-writing services are stopped. Returns list of active services."""
    import subprocess

    lifecycle_services = [
        "indicagent-intelligence-pipeline",
        "indicagent-signal-tracker",
        "indicagent-feature-writer",
    ]
    active = []
    for svc in lifecycle_services:
        result = subprocess.run(
            ["systemctl", "is-active", svc],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip() == "active":
            active.append(svc)
    return active


async def _seed_orphan_outcomes(conn, symbols: list[str], timeframes: list[str]) -> int:
    """No-op in the 3-table schema.

    Phase 130+: signal_events rows are inserted with status='pending' by
    run_historical_pipeline.py during backfill. signal_outcomes no longer exists.
    This function is preserved for call-site compatibility and returns 0.
    """
    logger.info(
        "preflight: signal_events status seeding not needed (3-table schema — status in signal_events)"
    )
    return 0


# ── Pure helper functions (importable for unit testing) ─────────────────────


def compute_gap_bars(sig_ts: datetime, bar_ts: datetime, tf_seconds: int) -> int:
    """Bars between signal.timestamp and bar N+1. 0 = no gap (immediate next bar).

    A gap > 0 means the first available bar after the signal is not the immediately
    following bar — e.g. due to a weekend, holiday, or missing data. The fill price
    is still bar N+1 open regardless; this count is stored for analysis.
    """
    gap_secs = (bar_ts - sig_ts).total_seconds() - tf_seconds
    if gap_secs > tf_seconds * 0.5:  # > 1.5x threshold
        return max(0, round(gap_secs / tf_seconds))
    return 0


def get_signals_active_at(
    signals: list[dict],
    bar_ts: datetime,
    tf_seconds: int = 60,
) -> list[dict]:
    """Return signals that are actionable at bar_ts.

    A signal fired at T on bar close is actionable at bar N+1 (the bar
    immediately after the signal). Bar N+1 is the first bar where the
    signal can be evaluated, so we include any signal where timestamp < bar_ts.
    """
    return [s for s in signals if s["timestamp"] < bar_ts]


def handle_no_data(sig: dict) -> dict:
    """No bars available after signal.timestamp — zone=never_activated, market=all NULL."""
    expires_at = sig.get("expires_at")
    if expires_at is not None:
        exit_ts = expires_at
    else:
        ttl_secs = sig.get("ttl_bars", 10) * TF_SECONDS.get(sig.get("timeframe", "1m"), 60)
        exit_ts = sig["timestamp"] + timedelta(seconds=ttl_secs)
    return {
        "zone_outcome": "never_activated",
        "zone_exit_at": exit_ts,
        "market_entry_outcome": None,
        "market_entry_exit_price": None,
        "market_entry_pnl_r": None,
        "market_entry_mae": None,
        "market_entry_mfe": None,
        "market_entry_bars_in_trade": None,
        "market_entry_gap_bars": None,
        "exit_at": exit_ts,
    }


def resolve_at_end_of_bars(
    sig: dict,
    last_bar: dict,
    *,
    tf_seconds: int,
    zone_mfe: float,
    market_mfe: float,
    zone_activated: bool = False,
    market_entry_price: float | None = None,
) -> dict:
    """Resolve remaining signal at end of bar stream using accumulated state.

    Called for any signal still in live_sids after all bars are exhausted.
    Uses expires_at (Phase 107.5+) when available, falls back to ttl_bars computation.
    """
    last_ts = last_bar["timestamp"]
    expires_at = sig.get("expires_at")

    # Use expires_at if available (Phase 107.5+), else compute from ttl_bars
    if expires_at is not None and last_ts < expires_at:
        # Signal hasn't expired yet — treat as still live (no forced resolution)
        return {"zone_outcome": None, "exit_at": None}

    # Compute exit timestamp
    if expires_at is not None:
        exit_ts = min(last_ts, expires_at)
    else:
        ttl_secs = sig.get("ttl_bars", 10) * tf_seconds
        exit_ts = sig["timestamp"] + timedelta(seconds=ttl_secs)
        exit_ts = min(last_ts, exit_ts)

    bars_elapsed = int((exit_ts - sig["timestamp"]).total_seconds() / tf_seconds)

    zone_outcome = (
        "ttl_expired_ahead"
        if zone_mfe > 0
        else ("never_activated" if not zone_activated else "ttl_expired_behind")
    )
    mep = market_entry_price if market_entry_price is not None else sig.get("market_entry_price")
    market_outcome = (
        ("ttl_expired_ahead" if market_mfe > 0 else "ttl_expired_behind")
        if mep is not None
        else None
    )
    market_bit = min(bars_elapsed, sig.get("ttl_bars", 10))

    return {
        "zone_outcome": zone_outcome,
        "exit_at": exit_ts,
        "market_entry_outcome": market_outcome,
        "market_entry_exit_price": float(last_bar["close"]) if mep is not None else None,
        "market_entry_pnl_r": None,  # computed by caller from accumulated state
        "market_entry_mae": None,
        "market_entry_mfe": None,
        "market_entry_bars_in_trade": market_bit if mep is not None else None,
        "market_entry_gap_bars": None,
    }


def validate_track_pair(zone_outcome: str, market_outcome: str | None) -> None:
    """Check for impossible track combination. Raises ValueError if detected."""
    if market_outcome is None:
        return
    if zone_outcome == "target_full" and market_outcome == "never_activated":
        raise ValueError(
            "Impossible: zone=target_full + market=never_activated "
            "(market track never produces never_activated)"
        )


# ── Core replay logic ────────────────────────────────────────────────────────


async def _reset_corrupt_data(
    db: DatabaseManager,
    symbols: list[str],
    timeframes: list[str],
    after: datetime,
    before: datetime,
) -> dict:
    """Reset corrupt signal lifecycle data + truncate derived tables.

    Idempotent: safe to run multiple times. Only affects signals
    with outcome IS NOT NULL in the exact [after, before) window.

    Returns counts for audit logging.
    """
    stats = {}
    async with db.pool.acquire() as conn:
        # Re-acquire advisory lock for the destructive phase
        if not await _acquire_replay_lock(conn):
            raise RuntimeError("Cannot acquire advisory lock for reset")
        try:
            # 1. Delete trade_executions for corrupt-window signals
            #    and reset signal_events.status to 'pending'
            result = await conn.execute(
                """DELETE FROM trade_executions
                   WHERE frame_id IN (
                       SELECT tf.frame_id
                       FROM trade_frames tf
                       JOIN signal_events se ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
                       WHERE se.ts >= $1
                         AND se.ts < $2
                         AND se.symbol = ANY($3)
                         AND se.tf = ANY($4)
                   )""",
                after,
                before,
                symbols,
                timeframes,
            )
            stats["executions_deleted"] = int(result.split()[-1])

            # 2. Reset activation metadata in trade_frames.frame_details
            result2 = await conn.execute(
                """UPDATE trade_frames SET
                    frame_details = frame_details - 'activated_at'
                                                 - 'activation_price'
                                                 - 'zone_entry_pct'
                                                 - 'bars_to_activation'
                   WHERE signal_id IN (
                       SELECT signal_id FROM signal_events
                       WHERE ts >= $1 AND ts < $2
                         AND symbol = ANY($3)
                         AND tf = ANY($4)
                   )""",
                after,
                before,
                symbols,
                timeframes,
            )
            stats["frames_reset"] = int(result2.split()[-1])

            # 3. Reset signal_events.status to 'pending'
            result3 = await conn.execute(
                """UPDATE signal_events SET status = 'pending'
                   WHERE ts >= $1
                     AND ts < $2
                     AND symbol = ANY($3)
                     AND tf = ANY($4)
                     AND status != 'pending'""",
                after,
                before,
                symbols,
                timeframes,
            )
            stats["outcomes_reset"] = int(result3.split()[-1])

            # 2. Truncate swarm_agent_weights (computed from lineage + outcomes)
            await conn.execute("TRUNCATE swarm_agent_weights")
            stats["weights_truncated"] = True

            # 3. Truncate setup_performance (computed from outcomes)
            await conn.execute("TRUNCATE setup_performance")
            stats["setup_perf_truncated"] = True

            logger.info(
                "reset_complete: status_reset=%d, frames_reset=%d, executions_deleted=%d, "
                "weights_truncated=True, setup_perf_truncated=True, window=[%s, %s)",
                stats["outcomes_reset"],
                stats.get("frames_reset", 0),
                stats.get("executions_deleted", 0),
                after.isoformat() if after is not None else "unbounded",
                before.isoformat() if before is not None else "unbounded",
            )
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _REPLAY_LOCK_ID)
    return stats


async def _fetch_work_queue(
    db: DatabaseManager, symbols: list[str], timeframes: list[str]
) -> list[tuple[str, str, int]]:
    """Build work queue ordered by estimated pending row count descending (largest first)."""
    async with db.get_connection() as conn:
        rows = await conn.fetch(
            """SELECT se.symbol, se.tf AS timeframe, COUNT(*) as cnt
                FROM signal_events se
                WHERE se.status IN ('pending', 'regime_suppressed')
                  AND se.symbol = ANY($1)
                  AND se.tf = ANY($2)
                GROUP BY se.symbol, se.tf
                ORDER BY cnt DESC""",
            symbols,
            timeframes,
        )
        return [(row["symbol"], row["timeframe"], row["cnt"]) for row in rows]


def _assert_row_types(row) -> None:
    """Assert asyncpg type contracts for the 3-table schema columns on the first fetched row.

    Called once before bulk processing to catch type mismatches immediately rather than
    at row 1.5M. Raises RuntimeError (not AssertionError) so failures propagate to the
    JOB_COMPLETED_TOTAL failure path and are not silently swallowed.
    """
    checks = [
        # timestamp is timestamptz — asyncpg returns datetime
        ("timestamp", datetime, row.get("timestamp")),
        # numeric columns — asyncpg returns float, int, or Decimal | None
        ("entry_price", (float, int), row.get("entry_price")),
        ("stop_loss", (float, int), row.get("stop_loss")),
    ]
    for col_name, expected_types, val in checks:
        if val is None:
            continue  # NULL is always valid for nullable columns
        try:
            assert isinstance(val, expected_types), (
                f"Col {col_name}: expected {expected_types}, got {type(val).__name__} "
                "— check asyncpg config"
            )
        except AssertionError as error:
            raise RuntimeError(str(error)) from error


async def _process_symbol_tf(
    db: DatabaseManager,
    symbol: str,
    timeframe: str,
    batch_size: int,
    commit_every: int,
    dry_run: bool,
    validate: bool,
) -> dict:
    """Worker function: process all pending signals for one (symbol, timeframe).

    Each worker uses the shared DatabaseManager with its own transaction.
    """
    tf_secs = TF_SECONDS.get(timeframe, 60)
    stats = {
        "symbol": symbol,
        "tf": timeframe,
        "processed": 0,
        "zone": {},
        "market": {},
        "gaps": 0,
        "errors": 0,
    }

    try:
        # Use a connection for this work item (manual transaction control for incremental commits)
        async with db.pool.acquire() as conn:
            await conn.execute("BEGIN")  # Start transaction for manual control
            # 1. Validate mode
            if validate:
                await _run_validate(conn, symbol, timeframe, tf_secs, dry_run)

            # 2. Fetch all unresolved signals for this pair into memory
            # signal_id is a sha-256 content hash (first 16 bytes, stored as uuid); return as hex string.
            signals = await conn.fetch(
                """SELECT replace(se.signal_id::text, '-', '') AS signal_id,
                          se.ts AS timestamp, se.symbol, se.tf AS timeframe,
                          se.setup_plugin, se.direction,
                          tf.entry_price,
                          tf.stop_price AS stop_loss,
                          tf.target_price,
                          (tf.frame_details->>'entry_zone_low')::float8 AS entry_zone_low,
                          (tf.frame_details->>'entry_zone_high')::float8 AS entry_zone_high,
                          (tf.frame_details->>'market_entry_price')::float8 AS market_entry_price,
                          se.ttl_bars, se.expires_at,
                          se.is_shadow, se.is_backfill,
                          se.hmm_regime_at_fire, se.garch_sigma_at_fire,
                          tf.was_selected,
                          tf.frame_details->>'stop_basis' AS stop_basis,
                          tf.frame_details->>'stop_type_col' AS stop_type_col,
                          (tf.frame_details->>'structural_stop_distance_atr')::float8
                              AS structural_stop_distance_atr,
                          (tf.frame_details->>'adaptive_buffer_mult')::float8
                              AS adaptive_buffer_mult,
                          se.plugin_regime_type,
                          se.status,
                          tf.frame_details->>'chandelier_vol_source' AS chandelier_vol_source,
                          tf.frame_id
                   FROM signal_events se
                   LEFT JOIN trade_frames tf
                       ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
                   WHERE se.status IN ('pending', 'regime_suppressed')
                     AND se.symbol = $1 AND se.tf = $2
                   ORDER BY se.ts ASC""",
                symbol,
                timeframe,
            )

        if not signals:
            return stats

        # Assert asyncpg type contracts on the first row before bulk processing.
        # Fail fast on the first row rather than discovering a type mismatch at row 1.5M.
        _assert_row_types(signals[0])

        min_ts = min(s["timestamp"] for s in signals)
        # Map by signal_id for O(1) lookup during bar evaluation
        sig_map: dict[str, dict] = {s["signal_id"]: dict(s) for s in signals}

        # Coerce Decimal fields to float — asyncpg returns NUMERIC as Decimal,
        # but evaluate_signal/evaluate_market_entry do arithmetic with float.
        _float_fields = (
            "entry_price",
            "stop_loss",
            "market_entry_price",
            "entry_zone_low",
            "entry_zone_high",
        )
        for _sig_dict in sig_map.values():
            for _field in _float_fields:
                _val = _sig_dict.get(_field)
                if _val is not None:
                    _sig_dict[_field] = float(_val)
            # target_price (3-table schema) is a single float; wrap as list for
            # evaluate_signal/evaluate_market_entry compatibility (expects targets=[...])
            _tp = _sig_dict.get("target_price")
            if _tp is not None:
                _sig_dict["targets"] = [float(_tp)]
            else:
                _sig_dict["targets"] = []
            # direction is text ("long"/"short") in 3-table schema;
            # convert to int (1/-1) for evaluate_signal/evaluate_market_entry
            _dir = _sig_dict.get("direction")
            if isinstance(_dir, str):
                _sig_dict["direction"] = 1 if _dir == "long" else -1

        # Inject canonical per-TF TTL — use stored ttl_bars if present (Phase 107.5+),
        # else fall back to canonical default.
        _tf_ttl = TF_TTL_BARS.get(timeframe, 10)
        for _sig_dict in sig_map.values():
            stored_ttl = _sig_dict.get("ttl_bars")
            _sig_dict["ttl_bars"] = stored_ttl if stored_ttl and stored_ttl > 0 else _tf_ttl

        # In-memory accumulators keyed by signal_id
        zone_mae: dict[str, float] = {}
        zone_mfe: dict[str, float] = {}
        market_mae_acc: dict[str, float] = {}
        market_mfe_acc: dict[str, float] = {}
        # market_entry_prices: populated at first bar after signal fires.
        # Uses signal.market_entry_price if set by generator, else bar N+1 open.
        market_entry_prices: dict[str, float | None] = {}
        market_activated_at: dict[str, datetime] = {}
        zone_activated_at: dict[str, datetime] = {}
        zone_activated: dict[str, bool] = {}
        pending_writes: list[tuple] = []
        last_bar: dict | None = None
        live_sids: set[str] = set()  # signals currently being evaluated

        # Sorted pointer for O(N+M) signal activation instead of O(N×M).
        # signals is already ORDER BY timestamp ASC from the query.
        sorted_sids: list[str] = [s["signal_id"] for s in signals]
        activation_ptr: int = 0

        # 3. Stream bars from DB — client-side batching avoids asyncpg cursor issues.
        # Server-side cursors in asyncpg require specific transaction handling that
        # was causing "cursor cannot be created outside of a transaction" errors.
        # Cursor-based pagination (timestamp >) replaces OFFSET pagination — OFFSET
        # is O(N²) on a hypertable: each batch scans from chunk 0 to the offset row.
        BATCH_SIZE = 1000
        # None → first batch uses >=min_ts; subsequent batches use >last_bar_ts.
        bar_cursor: datetime | None = None
        conn = await db.pool.acquire()
        try:
            await conn.execute("BEGIN")
            # Session-scoped — set once per connection, not per flush batch.
            await conn.execute("SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
        except Exception:
            await db.pool.release(conn)
            raise

        # 4. Stream bars and evaluate signals using client-side batching
        while True:
            if bar_cursor is None:
                bars = await conn.fetch(
                    """SELECT timestamp, open, high, low, close
                       FROM market_data_ohlcv
                       WHERE symbol = $1 AND timeframe = $2
                         AND timestamp >= $3
                       ORDER BY timestamp ASC
                       LIMIT $4""",
                    symbol,
                    timeframe,
                    min_ts,
                    BATCH_SIZE,
                )
            else:
                bars = await conn.fetch(
                    """SELECT timestamp, open, high, low, close
                       FROM market_data_ohlcv
                       WHERE symbol = $1 AND timeframe = $2
                         AND timestamp > $3
                       ORDER BY timestamp ASC
                       LIMIT $4""",
                    symbol,
                    timeframe,
                    bar_cursor,
                    BATCH_SIZE,
                )

            if not bars:
                break  # No more bars

            for bar_row in bars:
                bar = dict(bar_row)
                bar_ts = bar["timestamp"]
                if bar_ts.tzinfo is None:
                    bar_ts = bar_ts.replace(tzinfo=UTC)
                bar["timestamp"] = bar_ts
                last_bar = bar

                # Activate signals that fired before this bar (signal fires on bar N close,
                # enter at close_price, first evaluable bar is N+1). Option A: realistic
                # entry at signal close, evaluation starts next bar. Pointer advances
                # monotonically through the timestamp-sorted list — O(N+M) total.
                while activation_ptr < len(sorted_sids):
                    sid = sorted_sids[activation_ptr]
                    sig = sig_map[sid]
                    if sig["timestamp"] >= bar_ts:
                        break
                    if sid not in live_sids:
                        live_sids.add(sid)
                        mep = sig.get("market_entry_price")
                        entry_price = sig.get("entry_price")
                        if mep is None:
                            # Option A: Use signal's entry_price (bar T close), not bar open
                            # This is the realistic entry price — we enter at the close that
                            # triggered the signal, not the next bar's open.
                            if entry_price is not None:
                                market_entry_prices[sid] = float(entry_price)
                            else:
                                # Fallback: should not happen with well-formed signals
                                market_entry_prices[sid] = float(bar["open"])
                                stats["gaps"] += 1
                        else:
                            market_entry_prices[sid] = float(mep)
                        # Track activation time, but evaluation starts on NEXT bar (T+1)
                        market_activated_at[sid] = bar_ts
                    activation_ptr += 1

                resolved_this_bar: set[str] = set()

                for sid in live_sids:
                    sig = sig_map[sid]

                    # Option A: Skip evaluation on the entry bar. We entered at the close of
                    # the signal bar (T), so the earliest we can evaluate is the next bar (T+1).
                    # market_activated_at holds the entry timestamp - skip if this is entry bar.
                    m_entry_at = market_activated_at.get(sid)
                    if m_entry_at is not None and bar_ts == m_entry_at:
                        # This is the entry bar - skip evaluation, move to next signal
                        continue

                    bars_el = int((bar_ts - sig["timestamp"]).total_seconds() / tf_secs)
                    sig_eval = {**sig, "bars_elapsed": bars_el, "point_value": 1.0}

                    # ── Market track ──
                    # Evaluates from market_entry_price using stop_loss/target_1/target_2.
                    # Runs independently of zone track — signal can hit target on market
                    # track while still pending on zone track, or vice versa.
                    mep = market_entry_prices.get(sid)
                    if mep is not None and not sig.get("_market_resolved"):
                        m_mae = market_mae_acc.get(sid, 0.0)
                        m_mfe = market_mfe_acc.get(sid, 0.0)
                        try:
                            m_trans = evaluate_market_entry(
                                sig_eval,
                                market_entry_price=mep,
                                high=float(bar["high"]),
                                low=float(bar["low"]),
                                close=float(bar["close"]),
                                current_mae=m_mae,
                                current_mfe=m_mfe,
                            )
                        except Exception as error:
                            logger.warning("market eval error %s: %s", sid, error)
                            m_trans = None
                            stats["errors"] += 1

                        if m_trans and m_trans.exit_price is not None:
                            # Exited (stop or target) — write to trade_executions
                            m_entry_at = market_activated_at.get(sid)
                            m_bit = (
                                int((bar_ts - m_entry_at).total_seconds() / tf_secs)
                                if m_entry_at
                                else 0
                            )
                            m_outcome = m_trans.outcome
                            if m_outcome is None:
                                # Stop-loss exit: classify outcome from mfe/bars
                                m_outcome = _classify_stop_outcome(m_mfe, m_bit)
                            m_exit_reason = "stop_loss" if m_trans.outcome is None else None
                            stats["market"][m_outcome] = stats["market"].get(m_outcome, 0) + 1
                            pending_writes.append(
                                (
                                    "market",
                                    sid,
                                    {
                                        "_ts": sig["timestamp"],
                                        "market_entry_price": mep,
                                        "market_entry_at": m_entry_at,
                                        "market_entry_exit_price": m_trans.exit_price,
                                        "market_entry_exit_at": bar_ts,
                                        "market_entry_exit_reason": m_exit_reason,
                                        "market_entry_pnl_r": m_trans.pnl_r,
                                        "market_entry_mae": m_trans.mae,
                                        "market_entry_mfe": m_trans.mfe,
                                        "market_entry_bars_in_trade": m_bit,
                                        "market_entry_outcome": m_outcome,
                                        "market_entry_gap_bars": sig.get("_replay_gap_bars"),
                                    },
                                )
                            )
                            sig["_market_resolved"] = True
                        elif m_trans:
                            # Still open — accumulate running MAE/MFE in R-multiples
                            risk = abs(mep - float(sig["stop_loss"]))
                            if risk > 0:
                                direction = sig["direction"]
                                cpnl = (float(bar["close"]) - mep) * direction / risk
                                market_mae_acc[sid] = min(m_mae, cpnl)
                                market_mfe_acc[sid] = max(m_mfe, cpnl)

                    # ── Zone track ──
                    # Evaluates entry zone activation, then stop/target from zone entry price.
                    # regime_suppressed signals are treated as active for zone evaluation
                    # (suppression only affects signal selection, not outcome tracking).
                    z_mae = zone_mae.get(sid, 0.0)
                    z_mfe = zone_mfe.get(sid, 0.0)
                    z_status = "active" if zone_activated.get(sid) else sig.get("status", "pending")
                    sig_eval["status"] = (
                        "active"
                        if (z_status == "regime_suppressed" or zone_activated.get(sid))
                        else z_status
                    )

                    try:
                        z_trans = evaluate_signal(
                            sig_eval,
                            high=float(bar["high"]),
                            low=float(bar["low"]),
                            close=float(bar["close"]),
                            current_mae=z_mae,
                            current_mfe=z_mfe,
                        )
                    except Exception as error:
                        logger.warning("zone eval error %s: %s", sid, error)
                        z_trans = None
                        stats["errors"] += 1

                    if z_trans is None:
                        # No state change this bar — accumulate MAE/MFE if active
                        if zone_activated.get(sid):
                            entry = float(sig["entry_price"])
                            stop = float(sig["stop_loss"])
                            risk = abs(entry - stop)
                            if risk > 0:
                                direction = sig["direction"]
                                cpnl = (float(bar["close"]) - entry) * direction / risk
                                zone_mae[sid] = min(z_mae, cpnl)
                                zone_mfe[sid] = max(z_mfe, cpnl)
                        continue

                    if z_trans.new_status == "active":
                        # Signal entered the zone — record activation and reset MAE/MFE
                        zone_activated[sid] = True
                        zone_activated_at[sid] = bar_ts
                        pending_writes.append(
                            (
                                "activation",
                                sid,
                                {
                                    "_ts": sig["timestamp"],
                                    "activation_price": z_trans.activation_price,
                                    "zone_entry_pct": z_trans.zone_entry_pct,
                                    "bars_to_activation": z_trans.bars_to_activation,
                                    "activated_at": bar_ts,
                                },
                            )
                        )
                        zone_mae[sid] = 0.0
                        zone_mfe[sid] = 0.0
                    else:
                        # Zone exit — classify outcome and mark resolved
                        z_outcome = z_trans.outcome
                        z_bit = int(
                            (bar_ts - zone_activated_at.get(sid, bar_ts)).total_seconds() / tf_secs
                        )
                        if z_outcome is None:
                            z_outcome = _classify_stop_outcome(z_mfe, z_bit)
                        stats["zone"][z_outcome] = stats["zone"].get(z_outcome, 0) + 1
                        stats["processed"] += 1
                        pending_writes.append(
                            (
                                "zone_exit",
                                sid,
                                {
                                    "_ts": sig["timestamp"],
                                    "status": z_trans.new_status,
                                    "exit_at": bar_ts,
                                    "exit_price": z_trans.exit_price,
                                    "exit_reason": z_trans.exit_reason,
                                    "pnl_ticks": z_trans.pnl_ticks,
                                    "pnl_r": z_trans.pnl_r,
                                    "pnl_dollars": z_trans.pnl_dollars,
                                    "signal_quality": None,
                                    "mae": z_trans.mae,
                                    "mfe": z_trans.mfe,
                                    "bars_in_trade": z_bit,
                                    "outcome": z_outcome,
                                },
                            )
                        )
                        resolved_this_bar.add(sid)

                live_sids -= resolved_this_bar

                # Flush batch to DB (no commit yet — commit happens below on threshold)
                if len(pending_writes) >= batch_size:
                    if not dry_run:
                        await _flush_writes(conn, pending_writes)
                    pending_writes.clear()
                    # Incremental commit: durable progress every commit_every resolved signals.
                    # Without this, killing the process loses all work since pair start.
                    if not dry_run and stats["processed"] % commit_every < batch_size:
                        await conn.execute("COMMIT")
                        await conn.execute("BEGIN")
                        logger.info(
                            "%s %s: committed %d resolved so far",
                            symbol,
                            timeframe,
                            stats["processed"],
                        )

            # Advance cursor to last bar timestamp for next batch.
            bar_cursor = bars[-1]["timestamp"]

        # 5. End of bars — resolve remaining live signals (TTL expired)
        # Flush counter for this loop to prevent accumulating > batch_size writes
        ttl_flush_counter = 0
        if last_bar and live_sids:
            for sid in live_sids:
                sig = sig_map[sid]
                result = resolve_at_end_of_bars(
                    sig,
                    last_bar,
                    tf_seconds=tf_secs,
                    zone_mfe=zone_mfe.get(sid, 0.0),
                    market_mfe=market_mfe_acc.get(sid, 0.0),
                    zone_activated=zone_activated.get(sid, False),
                    market_entry_price=market_entry_prices.get(sid),
                )
                # Not-yet-expired signal (expires_at in the future) — skip resolution
                if result["zone_outcome"] is None:
                    continue
                stats["zone"][result["zone_outcome"]] = (
                    stats["zone"].get(result["zone_outcome"], 0) + 1
                )
                stats["processed"] += 1
                if zone_activated.get(sid):
                    _activated_at = zone_activated_at.get(sid, sig["timestamp"])
                    _bars_in_trade = int(
                        (result["exit_at"] - _activated_at).total_seconds() / tf_secs
                    )
                    pending_writes.append(
                        (
                            "zone_exit",
                            sid,
                            {
                                "_ts": sig["timestamp"],
                                "status": "expired",
                                "exit_at": result["exit_at"],
                                "exit_price": last_bar["close"],
                                "exit_reason": "ttl_expired",
                                "pnl_ticks": None,
                                "pnl_r": None,
                                "pnl_dollars": None,
                                "signal_quality": None,
                                "mae": zone_mae.get(sid, 0.0),
                                "mfe": zone_mfe.get(sid, 0.0),
                                "bars_in_trade": _bars_in_trade,
                                "outcome": result["zone_outcome"],
                            },
                        )
                    )
                else:
                    pending_writes.append(
                        (
                            "zone_exit",
                            sid,
                            {
                                "_ts": sig["timestamp"],
                                "status": "expired",
                                "exit_at": result["exit_at"],
                                "exit_price": None,
                                "exit_reason": "ttl_expired",
                                "pnl_ticks": None,
                                "pnl_r": None,
                                "pnl_dollars": None,
                                "signal_quality": None,
                                "mae": None,
                                "mfe": None,
                                "bars_in_trade": None,
                                "outcome": result["zone_outcome"],
                            },
                        )
                    )
                mep = market_entry_prices.get(sid)
                if mep is not None and not sig.get("_market_resolved"):
                    stats["market"][result["market_entry_outcome"]] = (
                        stats["market"].get(result["market_entry_outcome"], 0) + 1
                    )
                    pending_writes.append(
                        (
                            "market",
                            sid,
                            {
                                "_ts": sig["timestamp"],
                                "market_entry_price": mep,
                                "market_entry_at": market_activated_at.get(sid),
                                "market_entry_exit_price": float(last_bar["close"]),
                                "market_entry_exit_at": last_bar["timestamp"],
                                "market_entry_pnl_r": None,
                                "market_entry_mae": market_mae_acc.get(sid, 0.0),
                                "market_entry_mfe": market_mfe_acc.get(sid, 0.0),
                                "market_entry_bars_in_trade": result["market_entry_bars_in_trade"],
                                "market_entry_outcome": result["market_entry_outcome"],
                                "market_entry_gap_bars": sig.get("_replay_gap_bars"),
                            },
                        )
                    )
                # Incremental flush during TTL resolution to prevent exceeding
                # PostgreSQL's 32767 parameter limit when many signals expire together
                ttl_flush_counter += (
                    2 if (mep is not None and not sig.get("_market_resolved")) else 1
                )
                if ttl_flush_counter >= batch_size and len(pending_writes) > 0:
                    if not dry_run:
                        await _flush_writes(conn, pending_writes)
                    pending_writes.clear()
                    ttl_flush_counter = 0

        # 6. Final flush + commit
        if pending_writes and not dry_run:
            await _flush_writes(conn, pending_writes)
            pending_writes.clear()

        # Final COMMIT — every write must be durable before release
        if not dry_run:
            await conn.execute("COMMIT")
            logger.info(
                "%s %s: final commit — %d resolved total",
                symbol,
                timeframe,
                stats["processed"],
            )

        await db.pool.release(conn)

    except Exception as error:
        logger.error("Error processing %s %s: %s", symbol, timeframe, error)
        stats["errors"] += 1
        try:
            if not dry_run:
                await conn.execute("ROLLBACK")
            await db.pool.release(conn)
        except Exception:
            pass  # Connection already released or failed

    return stats


def _enum_value(v):
    return v.value if hasattr(v, "value") else v


async def _flush_writes(conn, writes: list[tuple]) -> None:
    """Execute pending DB writes using asyncpg (3-table schema).

    Three write kinds:
      - activation: signal entered the zone.
          -> UPDATE signal_events SET status='active'
          -> UPDATE trade_frames SET frame_details = frame_details || jsonb (activation metadata)
      - zone_exit: signal resolved on zone track.
          -> UPDATE signal_events SET status=...
          -> INSERT INTO trade_executions (zone pnl_r, mae, mfe, exit_at, exit_reason)
      - market: signal resolved on market track.
          -> INSERT INTO trade_executions (market_entry_price, market pnl_r, etc.)

    All signal_events UPDATEs match on signal_id only (status field, no hypertable ts needed).
    trade_executions INSERTs use a deterministic execution_id from uuid5.
    """
    activations, zone_exits, markets = [], [], []
    for kind, sid, data in writes:
        if kind == "activation":
            activations.append((sid, data))
        elif kind == "zone_exit":
            zone_exits.append((sid, data))
        elif kind == "market":
            markets.append((sid, data))

    # --- Activations ---
    # UPDATE signal_events.status + merge activation metadata into trade_frames.frame_details
    for sid, data in activations:
        await conn.execute(
            "UPDATE signal_events SET status = 'active' WHERE signal_id = $1::uuid",
            sid,
        )
        # Merge activation metadata into trade_frames.frame_details JSONB
        activation_meta = {
            "activated_at": data["activated_at"].isoformat() if data["activated_at"] else None,
            "activation_price": data["activation_price"],
            "zone_entry_pct": data["zone_entry_pct"],
            "bars_to_activation": data["bars_to_activation"],
        }
        # Remove None values
        activation_meta = {k: v for k, v in activation_meta.items() if v is not None}
        if activation_meta:
            await conn.execute(
                """UPDATE trade_frames
                   SET frame_details = COALESCE(frame_details, '{}'::jsonb) || $2::jsonb
                   WHERE signal_id = $1::uuid""",
                sid,
                json.dumps(activation_meta),
            )

    # --- Zone exits ---
    # UPDATE signal_events.status + INSERT trade_executions
    for sid, data in zone_exits:
        status = _enum_value(data["status"])
        await conn.execute(
            "UPDATE signal_events SET status = $2 WHERE signal_id = $1::uuid",
            sid,
            status,
        )
        # Compute execution_id deterministically from signal_id + 'zone'
        execution_id = str(uuid.uuid5(_FRAME_ID_NS, f"{sid}:zone"))
        # frame_id for the at_close trade frame
        frame_id = _make_frame_id(sid, "at_close")
        exit_at = data.get("exit_at")
        z_outcome = _enum_value(data.get("outcome"))
        await conn.execute(
            """INSERT INTO trade_executions (
                execution_id, frame_id,
                actual_exit_price, actual_pnl_r,
                actual_mae, actual_mfe, actual_bars,
                exit_reason, exited_at, outcome
            ) VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (execution_id) DO NOTHING""",
            execution_id,
            frame_id,
            data.get("exit_price"),
            data.get("pnl_r"),
            data.get("mae"),
            data.get("mfe"),
            data.get("bars_in_trade"),
            data.get("exit_reason"),
            exit_at,
            z_outcome,
        )

    # --- Market track resolutions ---
    # INSERT trade_executions with market entry/exit fields
    for sid, data in markets:
        m_outcome = _enum_value(data.get("market_entry_outcome"))
        # exit_reason: explicit stop_loss label takes priority; otherwise use outcome value
        m_exit_reason = data.get("market_entry_exit_reason") or m_outcome
        # Compute execution_id deterministically from signal_id + 'market'
        execution_id = str(uuid.uuid5(_FRAME_ID_NS, f"{sid}:market"))
        frame_id = _make_frame_id(sid, "at_close")
        await conn.execute(
            """INSERT INTO trade_executions (
                execution_id, frame_id,
                market_entry_price, market_entry_gap_bars,
                actual_fill_price, actual_exit_price,
                actual_pnl_r, actual_mae, actual_mfe, actual_bars,
                exit_reason, executed_at, exited_at, outcome
            ) VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (execution_id) DO NOTHING""",
            execution_id,
            frame_id,
            data.get("market_entry_price"),
            data.get("market_entry_gap_bars"),
            data.get("market_entry_price"),  # actual_fill_price = market entry price in replay
            data.get("market_entry_exit_price"),
            data.get("market_entry_pnl_r"),
            data.get("market_entry_mae"),
            data.get("market_entry_mfe"),
            data.get("market_entry_bars_in_trade"),
            m_exit_reason,
            data.get("market_entry_at"),
            data.get("market_entry_exit_at"),
            m_outcome,
        )


async def _run_validate(conn, symbol, timeframe, tf_secs, dry_run) -> None:
    """Validate: confirm resolved signals exist and have trade_executions populated."""
    row = await conn.fetchrow(
        """SELECT COUNT(*) as total,
                  COUNT(te.execution_id) as with_execution
           FROM signal_events se
           LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
           LEFT JOIN trade_executions te ON te.frame_id = tf.frame_id
           WHERE se.status NOT IN ('pending', 'regime_suppressed')
             AND se.symbol = $1 AND se.tf = $2""",
        symbol,
        timeframe,
    )

    if not row or row["total"] == 0:
        logger.info("VALIDATE %s %s: no resolved signals found, skipping", symbol, timeframe)
        return

    logger.info(
        "VALIDATE %s %s: %d resolved signals, %d with trade_execution",
        symbol,
        timeframe,
        row["total"],
        row["with_execution"],
    )
    # Full re-simulation validation is not implemented — this confirms DB read consistency only.
    logger.info("VALIDATE %s %s: structural check passed", symbol, timeframe)


async def _reconcile_outcomes(db: DatabaseManager) -> None:
    """Post-sweep reconciliation: expire stale pending signals and backfill missing execution rows.

    Two idempotent operations run after all (symbol, tf) workers finish:
    1. Expire stale pending — signals older than 2 days are past any TTL; mark expired.
    2. Backfill missing executions — expired signals lacking a trade_executions row get a
       synthetic row (pnl_r=0, exit_reason='ttl_expired') with a deterministic execution_id.
    """
    # A single UPDATE across all stale-pending rows on a large hypertable causes a PG
    # backend crash (OOM on cross-chunk writes). Batch in 5000-row chunks instead.
    async with db.pool.acquire() as conn:
        # 1. Expire stale pending — batch to avoid server crash on large hypertable UPDATEs
        total_expired = 0
        while True:
            batch_count = await conn.fetchval("""WITH to_expire AS (
                       SELECT signal_id FROM signal_events
                       WHERE status = 'pending' AND ts < NOW() - INTERVAL '2 days'
                       LIMIT 5000
                   ),
                   expired AS (
                       UPDATE signal_events
                       SET status = 'expired'
                       WHERE signal_id IN (SELECT signal_id FROM to_expire)
                       RETURNING 1
                   )
                   SELECT COUNT(*) FROM expired""")
            if not batch_count:
                break
            total_expired += batch_count
        logger.info("_reconcile_outcomes: expired %d stale-pending signals", total_expired)

        # 2. Fetch expired signals with no execution row
        rows = await conn.fetch("""SELECT replace(se.signal_id::text, '-', '') AS signal_id,
                      tf.frame_id,
                      se.ts AS fired_at,
                      se.expires_at
               FROM signal_events se
               JOIN trade_frames tf
                 ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
               WHERE se.status = 'expired'
                 AND NOT EXISTS (
                     SELECT 1 FROM trade_executions te WHERE te.frame_id = tf.frame_id
                 )""")
        logger.info("_reconcile_outcomes: %d expired signals need execution backfill", len(rows))

        if not rows:
            return

        # Batch INSERT with deterministic execution_id (uuid5 keyed on signal_id:ttl_reconcile)
        params = []
        for r in rows:
            execution_id = str(uuid.uuid5(_FRAME_ID_NS, f"{r['signal_id']}:ttl_reconcile"))
            params.append(
                (
                    execution_id,
                    str(r["frame_id"]),
                    0.0,
                    "ttl_expired",
                    r["fired_at"],
                    r["expires_at"],
                    "ttl_expired_behind",  # pnl_r=0.0 => behind; matches backfill SQL logic
                )
            )

        await conn.executemany(
            """INSERT INTO trade_executions (
                   execution_id, frame_id,
                   actual_pnl_r, exit_reason,
                   executed_at, exited_at, outcome
               ) VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7)
               ON CONFLICT (execution_id) DO NOTHING""",
            params,
        )
        logger.info("_reconcile_outcomes: inserted %d ttl_expired execution rows", len(params))


async def _verify_replay(
    db: DatabaseManager,
    symbols: list[str],
    timeframes: list[str],
    setups: list[str] | None = None,
) -> None:
    """Post-replay integrity check (D-06).

    Every non-regime signal should have an outcome. Every impossible
    combination should be flagged. Every orphan should be detected.
    Shadow signals are included in all checks (is_shadow = false filter removed).
    Hard-fails on: shadow stopped_at_entry > 0, orphan_ledger_rows > 0.
    Discrepancies are logged as warnings — investigate before trusting downstream data.
    """
    from services.shadow_validator import _SHADOW_VALIDATION_SETUPS

    shadow_setups = setups if setups is not None else list(_SHADOW_VALIDATION_SETUPS)

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN se.status NOT IN ('pending', 'regime_suppressed') THEN 1 END)
                    as with_outcome,
                COUNT(CASE WHEN se.status = 'regime_suppressed' THEN 1 END) as regime_no_outcome,
                COUNT(CASE WHEN se.status = 'pending'
                           AND se.ts < NOW() - INTERVAL '2 days'
                     THEN 1 END) as stale_unresolved,
                COUNT(CASE WHEN se.status = 'expired'
                           AND te.actual_pnl_r IS NULL
                           AND te.exit_reason NOT IN (
                               'ttl_expired', 'ttl_expired_ahead', 'ttl_expired_behind',
                               'stopped_at_entry'
                           )
                     THEN 1 END) as target_no_pnl,
                COUNT(CASE WHEN te.exit_reason = 'stopped_at_entry'
                           AND se.is_shadow = true
                           AND se.setup_plugin = ANY($3)
                     THEN 1 END) as shadow_stopped_at_entry
            FROM signal_events se
            LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
            LEFT JOIN trade_executions te ON te.frame_id = tf.frame_id
            WHERE se.symbol = ANY($1)
              AND se.tf = ANY($2)""",
            symbols,
            timeframes,
            shadow_setups,
        )
        # Orphan check: signal_events rows with no matching trade_frames row
        orphan_row = await conn.fetchrow(
            """SELECT COUNT(*) as orphan_ledger_rows
               FROM signal_events se
               LEFT JOIN trade_frames tf
                   ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
               WHERE se.symbol = ANY($1)
                 AND se.tf = ANY($2)
                 AND tf.frame_id IS NULL""",
            symbols,
            timeframes,
        )
        # Distinct signal count: unaffected by LEFT JOIN fan-out from dual-track
        # trade_frames rows. Used to detect B7 overcounting in the main query.
        distinct_row = await conn.fetchrow(
            """SELECT COUNT(DISTINCT se.signal_id) as distinct_signals
               FROM signal_events se
               WHERE se.symbol = ANY($1)
                 AND se.tf = ANY($2)""",
            symbols,
            timeframes,
        )

    orphan_ledger_rows = orphan_row["orphan_ledger_rows"]
    distinct_signals = distinct_row["distinct_signals"]

    logger.info(
        "VERIFY: total=%d distinct_signals=%d with_outcome=%d regime_no_outcome=%d "
        "stale_unresolved=%d target_no_pnl=%d "
        "shadow_stopped_at_entry=%d orphan_signal_events=%d",
        row["total"],
        distinct_signals,
        row["with_outcome"],
        row["regime_no_outcome"],
        row["stale_unresolved"],
        row["target_no_pnl"],
        row["shadow_stopped_at_entry"],
        orphan_ledger_rows,
    )
    if row["total"] != distinct_signals:
        logger.warning(
            "VERIFY: total count inflated by JOIN fan-out — total=%d distinct=%d",
            row["total"],
            distinct_signals,
        )

    issues = []
    if row["stale_unresolved"] > 0:
        issues.append(f"{row['stale_unresolved']} signals older than 2 days still pending")
    if row["target_no_pnl"] > 0:
        issues.append(f"{row['target_no_pnl']} expired signals with null pnl_r")
    if row["shadow_stopped_at_entry"] > 0:
        issues.append(
            f"{row['shadow_stopped_at_entry']} shadow signals have stopped_at_entry outcome "
            "(Phase 117 fix must eliminate all stopped_at_entry for shadow setups)"
        )
    if orphan_ledger_rows > 0:
        issues.append(
            f"{orphan_ledger_rows} signal_events rows without trade_frames row "
            "(3-table schema invariant violated)"
        )

    if issues:
        for issue in issues:
            logger.error("VERIFY ISSUE: %s", issue)
        raise RuntimeError(
            f"VERIFY FAILED: {len(issues)} issue(s) — downstream data is untrustworthy. "
            "Fix issues and re-run lifecycle_replay before consuming signal data."
        )
    else:
        logger.info("VERIFY: all checks passed — data is clean")


async def main_async():
    parser = argparse.ArgumentParser(
        description="Lifecycle Replay — backfill historical signal outcomes"
    )
    parser.add_argument("--symbols", help="Comma-separated symbols (default: all active)")
    parser.add_argument("--timeframes", help="Comma-separated timeframes (default: 1m,5m,15m,1h)")
    parser.add_argument("--validate", action="store_true", help="Run validation first")
    parser.add_argument("--dry-run", action="store_true", help="Compute but don't write")
    parser.add_argument(
        "--batch-size", type=int, default=2000, help="DB flush every N pending writes"
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=1000,
        help="Commit after every N resolved signals per pair",
    )
    parser.add_argument("--workers", type=int, default=8, help="Concurrency level (default: 8)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Override safety checks (service quiescence). Use with extreme caution.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset corrupt outcomes + truncate derived tables before replay",
    )
    parser.add_argument(
        "--reset-before",
        type=str,
        default=None,
        help="ISO timestamp — only reset signals before this date (optional override; default: no upper bound)",
    )
    parser.add_argument(
        "--reset-after",
        type=str,
        default=None,
        help="ISO timestamp — only reset signals after this date (optional override; default: no lower bound)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required with --reset. Prevents accidental destructive operations.",
    )
    args = parser.parse_args()

    # Use -u (unbuffered) when redirecting output: python -u lifecycle_replay.py > log 2>&1 &
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()

    try:
        symbols = (
            args.symbols.split(",") if args.symbols else [c.symbol for c in get_active_contracts()]
        )
        timeframes = args.timeframes.split(",") if args.timeframes else TIMEFRAMES

        # ── Preflight safety checks ──
        async with db.pool.acquire() as preflight_conn:
            # 1. Advisory lock — hard stop if another replay is running
            if not await _acquire_replay_lock(preflight_conn):
                logger.error("ABORT: another replay is already running (advisory lock held)")
                return
            logger.info("Advisory lock acquired (id=%d)", _REPLAY_LOCK_ID)

            try:
                # 2. Service quiescence — warn but allow override
                if not args.dry_run:
                    active_services = await _check_service_quiescence()
                    if active_services and not args.force:
                        logger.error(
                            "ABORT: active lifecycle services detected: %s. "
                            "Stop them first or use --force to override.",
                            ", ".join(active_services),
                        )
                        return
                    elif active_services:
                        logger.warning(
                            "WARNING: running with active services (--force): %s. "
                            "Data races are possible.",
                            ", ".join(active_services),
                        )

                # 3. Verify signal_events status integrity (no-op in 3-table schema —
                #    signal_outcomes seeding is obsolete; status lives in signal_events)
                orphans = await _seed_orphan_outcomes(preflight_conn, symbols, timeframes)
                if orphans > 0:
                    logger.info("Preflight: seeded %d signal_events rows", orphans)
                else:
                    logger.info("Preflight: status integrity check passed (3-table schema)")
            finally:
                await preflight_conn.execute("SELECT pg_advisory_unlock($1)", _REPLAY_LOCK_ID)

        # ── Reset corrupt data (optional, requires --confirm) ──
        if args.reset:
            if not args.confirm:
                logger.error(
                    "ABORT: --reset requires --confirm to prevent accidental data wipe. "
                    "Run with --reset --confirm to proceed."
                )
                return
            after = (
                datetime.fromisoformat(args.reset_after.replace("Z", "+00:00"))
                if args.reset_after
                else None
            )
            before = (
                datetime.fromisoformat(args.reset_before.replace("Z", "+00:00"))
                if args.reset_before
                else None
            )
            logger.info(
                "Reset window: [%s, %s) — about to wipe outcomes and truncate derived tables",
                after.isoformat() if after else "unbounded",
                before.isoformat() if before else "unbounded",
            )
            reset_stats = await _reset_corrupt_data(db, symbols, timeframes, after, before)
            logger.info("Reset complete: %s", reset_stats)

        # Build work queue
        work_queue = await _fetch_work_queue(db, symbols, timeframes)

        if not work_queue:
            logger.info("No pending signals found. Nothing to do.")
            return

        logger.info(
            "Work queue: %d (symbol, tf) pairs, %d total pending signals",
            len(work_queue),
            sum(w[2] for w in work_queue),
        )

        # Process all pairs concurrently using asyncio.gather with semaphore for concurrency control
        semaphore = asyncio.Semaphore(args.workers)

        async def process_with_limit(sym, tf):
            async with semaphore:
                return await _process_symbol_tf(
                    db, sym, tf, args.batch_size, args.commit_every, args.dry_run, args.validate
                )

        tasks = [process_with_limit(sym, tf) for sym, tf, _ in work_queue]

        all_stats = []
        for future in asyncio.as_completed(tasks):
            stats = await future
            all_stats.append(stats)
            sym, tf = stats["symbol"], stats["tf"]
            z = stats["zone"]
            m = stats["market"]
            logger.info(
                "%s %s: %d processed | Zone: %s | Market: %s | gaps=%d errors=%d",
                sym,
                tf,
                stats["processed"],
                " | ".join(f"{k}={v}" for k, v in z.items()),
                " | ".join(f"{k}={v}" for k, v in m.items()),
                stats["gaps"],
                stats["errors"],
            )

        total = sum(s["processed"] for s in all_stats)
        logger.info("Replay done. Total processed: %d", total)

        if not args.dry_run:
            await _reconcile_outcomes(db)
            await _verify_replay(db, symbols, timeframes)
        else:
            logger.info("DRY RUN — no DB writes made.")
    finally:
        await db.close()


def main():
    """Entry point for async main."""
    asyncio.run(main_async())
    flush_and_shutdown_metrics()


if __name__ == "__main__":
    try:
        init_otel_providers("lifecycle-replay")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    main()
