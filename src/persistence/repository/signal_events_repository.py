"""Signal Events Repository — data access layer for the 3-table signal architecture.

Provides persistence operations for signal_events, trade_frames, and trade_executions.
The three tables replace the legacy signal_ledger monolith introduced in Phase 128-129:

    signal_events   — one row per I7 plugin fire; detection-layer fields; immutable after emit.
    trade_frames    — one row per entry_type per signal; hypothesis fields + lifecycle JSONB.
    trade_executions — one row per live trade execution; outcome fields.

All write paths in this repository target the 3-table schema exclusively.
signal_ledger and signal_outcomes are never referenced here.

Bootstrap query uses a direct JOIN on signal_events + trade_frames (not the
signal_ledger view, which returns NULL for all lifecycle fields).

Design decisions (Phase 130, D-02, D-11):
- insert_signal_with_frames: atomic asyncpg transaction (signal_events + N trade_frames).
- update_signal_status: standalone UPDATE on signal_events.status — idempotent, retryable.
- update_frame_details: JSONB merge on trade_frames.frame_details — activation lifecycle fields.
- record_execution: standalone INSERT into trade_executions.
- frame_id: deterministic uuid5(NAMESPACE_DNS, f"{signal_id}:{entry_type}") — idempotent across replays.
- direction: always text "long"/"short" in signal_events and trade_frames (never integer).
- concurrent_signal_count and concurrent_plugins: NULL in Phase 130 (v2.11 populates).
- counterfactual_pnl_r: NULL in Phase 130 (CounterfactualTracker populates in v2.11).
- JSONB columns (factor_scores, context_features, frame_details): pass dicts directly to asyncpg.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import structlog

from src.core.service_utils import format_iso_ts

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# frame_id namespace — deterministic uuid5 generation (see git history for the
# original signal_ledger migration that established this convention, Phase 130)
# ---------------------------------------------------------------------------

_FRAME_ID_NS = uuid.NAMESPACE_DNS


def _make_frame_id(signal_id: str, entry_type: str) -> uuid.UUID:
    """Deterministic frame_id — same signal_id + entry_type always produces same UUID."""
    return uuid.uuid5(_FRAME_ID_NS, f"{signal_id}:{entry_type}")


# ---------------------------------------------------------------------------
# Signal lifecycle status enum — matches database values
# ---------------------------------------------------------------------------


class SignalStatus(str, Enum):
    """Signal lifecycle status — matches signal_events.status column values.

    Extends str so .value matches existing DB string values directly.
    No migration needed — values are identical to legacy signal_outcomes strings.
    """

    PENDING = "pending"
    ACTIVE = "active"
    REGIME_SUPPRESSED = "regime_suppressed"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Signal outcome re-exports — 8-class ML training label taxonomy
# ---------------------------------------------------------------------------

from src.intelligence.trading.signal_outcome import (  # noqa: E402, E501
    STOP_OUTCOMES,
    TTL_OUTCOMES,
    WIN_OUTCOMES,
    SignalOutcome,
)

__all__ = [
    "SignalEventsRepository",
    "SignalStatus",
    "SignalOutcome",
    "STOP_OUTCOMES",
    "TTL_OUTCOMES",
    "WIN_OUTCOMES",
    "LedgerEntry",
    "SignalEventRow",
    "TradeFrameRow",
]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SignalEventRow:
    """Detection-layer fields written once at signal fire time to signal_events.

    Immutable after emit — no fields are updated after insert (except status).
    concurrent_signal_count and concurrent_plugins are NULL in Phase 130; v2.11 populates.
    """

    signal_id: str
    ts: datetime
    symbol: str
    tf: str
    setup_plugin: str
    direction: str  # "long" or "short" — converted from integer before write
    raw_confidence: float
    calibrated_confidence: float | None = None
    cis_score: float | None = None
    weights_version: int | None = None
    factor_scores: dict | None = None
    context_features: dict | None = None
    ctf_score: float | None = None
    ctf_confirmed: bool | None = None
    zone_friction_score: float | None = None
    hmm_regime_at_fire: int | None = None
    plugin_regime_type: str | None = None
    garch_sigma_at_fire: float | None = None
    is_shadow: bool = False
    is_backfill: bool = False
    status: str = "pending"
    signal_schema_version: int | None = None
    ttl_bars: int | None = None
    expires_at: datetime | None = None
    signal_computed_at: datetime | None = None
    feature_ts: datetime | None = None


@dataclass
class TradeFrameRow:
    """Hypothesis-layer fields written at signal fire time to trade_frames.

    One row per entry_type per signal_id.
    counterfactual_pnl_r is NULL in Phase 130; CounterfactualTracker populates in v2.11.
    frame_details JSONB holds stop architecture fields and lifecycle activation metadata.
    """

    frame_id: uuid.UUID
    signal_id: str
    signal_ts: datetime
    entry_type: str
    direction: str  # "long" or "short"
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    r_multiple: float | None = None
    ttl_bars: int | None = None
    expires_at: datetime | None = None
    was_selected: bool = False
    frame_details: dict | None = None


# ---------------------------------------------------------------------------
# Backward-compat alias — callers that still reference LedgerEntry import cleanly
# ---------------------------------------------------------------------------


@dataclass
class LedgerEntry:
    """Backward-compat shim — wraps SignalEventRow fields for callers not yet migrated.

    New code should use SignalEventRow + TradeFrameRow directly.
    This dataclass is preserved so run_historical_pipeline.py and feature_replay.py
    can import it without ImportError until their Wave 3 rewrites.
    """

    signal_id: str
    timestamp: datetime
    symbol: str
    timeframe: str
    setup_plugin: str
    signal_type: str = ""
    direction: int = 1
    was_selected: bool = False
    is_shadow: bool = False
    is_backfill: bool = False
    signal_computed_at: datetime | None = None
    feature_ts: datetime | None = None
    feature_tf: str | None = None
    hmm_regime_at_fire: int | None = None
    garch_sigma_at_fire: float | None = None
    ttl_bars: int | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    targets: list[float] | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    market_entry_price: float | None = None
    cis_score: float | None = None
    bucket_scores: dict | None = None
    weights_version: int | None = None
    pipeline_lag_ms: float | None = None
    expires_at: datetime | None = None
    feature_schema_version: int | None = None
    stop_basis: str | None = None
    stop_type_col: str | None = None
    structural_stop_distance_atr: float | None = None
    adaptive_buffer_mult: float | None = None
    plugin_regime_type: str | None = None
    stop_structure_age_bars: int | None = None
    raw_confidence: float | None = None
    calibrated_confidence: float | None = None
    factor_scores: dict | None = None
    context_features: dict | None = None
    ctf_score: float | None = None
    ctf_confirmed: bool | None = None
    zone_friction_score: float | None = None
    status: SignalStatus = field(default=SignalStatus.PENDING)


# ---------------------------------------------------------------------------
# SQL constants — signal_events INSERT
# ---------------------------------------------------------------------------

_INSERT_SIGNAL_EVENTS_SQL = """
INSERT INTO signal_events (
    signal_id, ts, symbol, tf, setup_plugin, direction,
    raw_confidence, calibrated_confidence, cis_score, weights_version,
    factor_scores, context_features,
    ctf_score, ctf_confirmed, zone_friction_score,
    hmm_regime_at_fire, plugin_regime_type, garch_sigma_at_fire,
    is_shadow, is_backfill, status, signal_schema_version,
    ttl_bars, expires_at, signal_computed_at, feature_ts
) VALUES (
    $1::uuid, $2, $3, $4, $5, $6,
    $7, $8, $9, $10,
    $11::jsonb, $12::jsonb,
    $13, $14, $15,
    $16, $17, $18,
    $19, $20, $21, $22,
    $23, $24, $25, $26
)
ON CONFLICT (signal_id, ts) DO NOTHING
"""

# ---------------------------------------------------------------------------
# SQL constants — trade_frames INSERT
# ---------------------------------------------------------------------------

_INSERT_TRADE_FRAMES_SQL = """
INSERT INTO trade_frames (
    frame_id, signal_id, signal_ts, entry_type, direction,
    entry_price, stop_price, target_price, r_multiple,
    ttl_bars, expires_at, counterfactual_pnl_r, was_selected,
    frame_details, targets
) VALUES (
    $1::uuid, $2::uuid, $3, $4, $5,
    $6, $7, $8, $9,
    $10, $11, NULL, $12,
    $13::jsonb, $14::double precision[]
)
ON CONFLICT (frame_id) DO NOTHING
"""

# ---------------------------------------------------------------------------
# SQL constants — lifecycle status update (signal_events)
# ---------------------------------------------------------------------------

_UPDATE_STATUS_SQL = """
UPDATE signal_events
SET status = $2
WHERE signal_id = $1::uuid
"""

# ---------------------------------------------------------------------------
# SQL constants — frame_details JSONB merge (trade_frames)
# Merges activation lifecycle fields: activated_at, activation_price,
# zone_entry_pct, bars_to_activation, regime_at_activation.
# ---------------------------------------------------------------------------

_UPDATE_FRAME_DETAILS_SQL = """
UPDATE trade_frames
SET frame_details = frame_details || $2::jsonb
WHERE signal_id = $1::uuid
"""

# ---------------------------------------------------------------------------
# SQL constants — trade_executions INSERT
# ---------------------------------------------------------------------------

_INSERT_TRADE_EXECUTIONS_SQL = """
INSERT INTO trade_executions (
    execution_id, frame_id,
    actual_fill_price, actual_exit_price, actual_pnl_r,
    actual_mfe, actual_mae, actual_bars,
    market_entry_price, market_entry_gap_bars,
    exit_reason, executed_at, exited_at, regime_at_exit,
    outcome
) VALUES (
    $1::uuid, $2::uuid,
    $3, $4, $5,
    $6, $7, $8,
    $9, $10,
    $11, $12, $13, $14,
    $15
)
ON CONFLICT (execution_id) DO NOTHING
"""

# ---------------------------------------------------------------------------
# Bootstrap query — direct JOIN on signal_events + trade_frames
# NOT signal_ledger (which NULLs all lifecycle fields — RESEARCH Pitfall 1)
# Window bounds use $1 * INTERVAL '1 day' parameterization (APR-driven)
# ---------------------------------------------------------------------------

_BOOTSTRAP_SQL = """
SELECT
    se.signal_id,
    se.symbol,
    se.tf                                       AS timeframe,
    se.ts                                       AS timestamp,
    se.status,
    se.direction,
    se.ttl_bars,
    se.is_backfill,
    se.is_shadow,
    se.garch_sigma_at_fire,
    se.hmm_regime_at_fire,
    se.expires_at,
    tf.entry_price,
    tf.stop_price                               AS stop_loss,
    tf.target_price,
    (tf.frame_details->>'entry_zone_low')::float8       AS entry_zone_low,
    (tf.frame_details->>'entry_zone_high')::float8      AS entry_zone_high,
    (tf.frame_details->>'trailing_stop_price')::jsonb   AS trailing_stop_price,
    (tf.frame_details->>'chandelier_vol_source')::text  AS chandelier_vol_source,
    (tf.frame_details->>'activated_at')::timestamptz    AS activated_at
FROM signal_events se
LEFT JOIN trade_frames tf
    ON tf.signal_id = se.signal_id
    AND tf.signal_ts = se.ts
WHERE se.status IN ('pending', 'active', 'regime_suppressed')
  AND (
    (se.status = 'pending' AND se.ts > NOW() - ($1::int * INTERVAL '1 day'))
    OR (se.status IN ('active', 'regime_suppressed') AND se.ts > NOW() - ($2::int * INTERVAL '1 day'))
)
ORDER BY se.ts DESC
"""


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class SignalEventsRepository:
    """Repository for signal_events, trade_frames, and trade_executions persistence.

    All SQL targets the 3-table signal architecture introduced in Phase 128-129.
    signal_ledger and signal_outcomes are never referenced here.

    Write contract (Phase 130, D-11):
    - Atomic path: insert_signal_with_frames writes signal_events + trade_frames in
      one asyncpg transaction. If trade_frames INSERT fails, signal_events rolls back.
    - Standalone updates: update_signal_status and update_frame_details are idempotent
      and retryable; they do not require transaction context.
    - Execution path: record_execution writes trade_executions standalone.

    Bootstrap contract:
    - get_active_signals_for_bootstrap queries signal_events + trade_frames directly
      (not signal_ledger view, which returns NULL for all lifecycle fields).
    - Lifecycle metadata (activated_at, trailing_stop_price, etc.) is extracted from
      trade_frames.frame_details JSONB.
    """

    def __init__(self, db_manager: Any) -> None:
        self._db_manager = db_manager

    # ------------------------------------------------------------------
    # Atomic insert: signal_events + trade_frames in one transaction
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Standalone lifecycle update — signal_events.status
    # ------------------------------------------------------------------

    async def update_signal_status(self, signal_id: str, status: str) -> None:
        """Standalone UPDATE signal_events.status — idempotent, retryable.

        Parameters
        ----------
        signal_id:
            UUID string of the signal in signal_events.
        status:
            One of "pending", "active", "regime_suppressed", "expired".
        """
        await self._db_manager.execute_command(_UPDATE_STATUS_SQL, signal_id, status)
        logger.debug("Updated signal status", signal_id=signal_id, status=status)

    # ------------------------------------------------------------------
    # Standalone lifecycle update — trade_frames.frame_details JSONB
    # ------------------------------------------------------------------

    async def update_frame_details(self, signal_id: str, meta: dict) -> None:
        """Merge activation lifecycle metadata into trade_frames.frame_details JSONB.

        Uses JSONB || operator — existing keys are preserved, overlapping keys are
        updated with new values. Targets all trade_frames rows for this signal_id.

        Lifecycle fields written here (set by lifecycle_writer on activation):
            activated_at, activation_price, zone_entry_pct, bars_to_activation,
            regime_at_activation, trailing_stop_price, chandelier_vol_source.

        Parameters
        ----------
        signal_id:
            UUID string of the signal in signal_events / trade_frames.
        meta:
            Dict of fields to merge into frame_details. Timestamps should be
            formatted via format_iso_ts() before inclusion.
        """
        await self._db_manager.execute_command(_UPDATE_FRAME_DETAILS_SQL, signal_id, meta)
        logger.debug("Updated frame details", signal_id=signal_id, keys=list(meta.keys()))

    # ------------------------------------------------------------------
    # Standalone execution INSERT — trade_executions
    # ------------------------------------------------------------------

    async def record_execution(
        self,
        signal_id: str,
        entry_type: str,
        *,
        actual_fill_price: float | None = None,
        actual_exit_price: float | None = None,
        actual_pnl_r: float | None = None,
        actual_mfe: float | None = None,
        actual_mae: float | None = None,
        actual_bars: int | None = None,
        market_entry_price: float | None = None,
        market_entry_gap_bars: int | None = None,
        exit_reason: str | None = None,
        executed_at: datetime | None = None,
        exited_at: datetime | None = None,
        regime_at_exit: str | None = None,
        outcome: str | None = None,
    ) -> None:
        """INSERT INTO trade_executions for a live trade outcome.

        execution_id is deterministic: uuid5 from frame_id + '_exec' to allow
        idempotent re-runs without generating duplicate rows.

        Parameters
        ----------
        signal_id:
            UUID string of the signal in signal_events.
        entry_type:
            Entry type that was executed (determines which frame_id to link).
        outcome:
            SignalOutcome value (or str) for the exit — e.g. 'stopped_at_entry'.
            Callers should pass transition.outcome.value if it is a SignalOutcome enum
            or the raw str otherwise. Never leave this None on a real exit.
        """
        frame_id = _make_frame_id(signal_id, entry_type)
        execution_id = uuid.uuid5(_FRAME_ID_NS, f"{frame_id}:exec")
        # Normalize: SignalOutcome extends str so .value == the str itself; accept both
        outcome_str = outcome.value if hasattr(outcome, "value") else outcome

        await self._db_manager.execute_command(
            _INSERT_TRADE_EXECUTIONS_SQL,
            str(execution_id),  # $1 execution_id::uuid
            str(frame_id),  # $2 frame_id::uuid
            actual_fill_price,  # $3
            actual_exit_price,  # $4
            actual_pnl_r,  # $5
            actual_mfe,  # $6
            actual_mae,  # $7
            actual_bars,  # $8
            market_entry_price,  # $9
            market_entry_gap_bars,  # $10
            exit_reason,  # $11
            executed_at,  # $12
            exited_at,  # $13
            regime_at_exit,  # $14
            outcome_str,  # $15
        )
        logger.info(
            "Recorded execution",
            signal_id=signal_id,
            entry_type=entry_type,
            actual_pnl_r=actual_pnl_r,
        )

    # ------------------------------------------------------------------
    # Bootstrap query — direct signal_events + trade_frames JOIN
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Legacy-compatible batch API (consumed by LifecycleWriter batching)
    # ------------------------------------------------------------------

    async def batch_update_status(self, signal_ids: list[str], status: str) -> None:
        """Batch UPDATE signal_events.status for multiple signals."""
        if not signal_ids:
            return
        params = [(sid, status) for sid in signal_ids]
        await self._db_manager.execute_batch(_UPDATE_STATUS_SQL, params)
        logger.info("Batch status update", status=status, count=len(signal_ids))

    async def batch_update_frame_details(self, updates: list[dict]) -> None:
        """Batch JSONB merge on trade_frames.frame_details for multiple signals."""
        if not updates:
            return
        params = [(u["signal_id"], u["meta"]) for u in updates]
        await self._db_manager.execute_batch(_UPDATE_FRAME_DETAILS_SQL, params)
        logger.info("Batch frame_details update", count=len(updates))

    # ------------------------------------------------------------------
    # Legacy select methods (backward-compat for callers not yet on bootstrap)
    # ------------------------------------------------------------------

    async def get_active_signals(self, symbol: str | None = None) -> list[dict]:
        """Return pending/active signals, optionally filtered by symbol."""
        if symbol is not None:
            sql = """
SELECT se.signal_id, se.symbol, se.tf AS timeframe, se.ts AS timestamp,
       se.status, se.direction, se.ttl_bars, se.is_backfill, se.is_shadow,
       se.expires_at, se.hmm_regime_at_fire, se.garch_sigma_at_fire,
       se.setup_plugin, se.raw_confidence, se.calibrated_confidence,
       tf.entry_price, tf.stop_price AS stop_loss, tf.target_price,
       tf.was_selected, tf.entry_type
FROM signal_events se
LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE se.status IN ('pending', 'active', 'regime_suppressed')
  AND se.symbol = $1
ORDER BY se.ts DESC
"""
            return await self._db_manager.execute_query(sql, symbol)
        sql = """
SELECT se.signal_id, se.symbol, se.tf AS timeframe, se.ts AS timestamp,
       se.status, se.direction, se.ttl_bars, se.is_backfill, se.is_shadow,
       se.expires_at, se.hmm_regime_at_fire, se.garch_sigma_at_fire,
       se.setup_plugin, se.raw_confidence, se.calibrated_confidence,
       tf.entry_price, tf.stop_price AS stop_loss, tf.target_price,
       tf.was_selected, tf.entry_type
FROM signal_events se
LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE se.status IN ('pending', 'active', 'regime_suppressed')
ORDER BY se.ts DESC
"""
        return await self._db_manager.execute_query(sql)

    async def fetch_active_signals(self, symbol: str, tf: str) -> list[dict]:
        """Return pending/active/regime_suppressed signals for a specific symbol+timeframe."""
        sql = """
SELECT se.signal_id, se.symbol, se.tf AS timeframe, se.ts AS timestamp,
       se.status, se.direction, se.ttl_bars, se.is_backfill, se.is_shadow,
       se.expires_at, se.hmm_regime_at_fire, se.garch_sigma_at_fire,
       se.setup_plugin, se.raw_confidence, se.calibrated_confidence,
       tf.entry_price, tf.stop_price AS stop_loss, tf.target_price,
       tf.was_selected, tf.entry_type,
       (tf.frame_details->>'entry_zone_low')::float8  AS entry_zone_low,
       (tf.frame_details->>'entry_zone_high')::float8 AS entry_zone_high
FROM signal_events se
LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE se.status IN ('pending', 'active', 'regime_suppressed')
  AND se.symbol = $1
  AND se.tf = $2
ORDER BY se.ts DESC
"""
        return await self._db_manager.execute_query(sql, symbol, tf)

    async def fetch_pending_signals(self) -> list[dict]:
        """Return all pending signals across all symbols/timeframes."""
        sql = """
SELECT se.signal_id, se.symbol, se.tf AS timeframe, se.ts AS timestamp,
       se.status, se.direction, se.ttl_bars, se.is_backfill, se.is_shadow,
       se.expires_at, se.setup_plugin,
       tf.entry_price, tf.stop_price AS stop_loss, tf.target_price,
       (tf.frame_details->>'entry_zone_low')::float8  AS entry_zone_low,
       (tf.frame_details->>'entry_zone_high')::float8 AS entry_zone_high
FROM signal_events se
LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE se.status = 'pending'
ORDER BY se.ts DESC
"""
        return await self._db_manager.execute_query(sql)

    # ------------------------------------------------------------------
    # Legacy batch_execute (consumed by LifecycleWriter until Wave 3 rewrite)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Thin lifecycle aliases (consumed by signal_tracker and lifecycle_writer)
    # ------------------------------------------------------------------

    async def update_lifecycle_state(
        self,
        signal_id: str,
        new_status: str,
        outcome: str | None = None,
        exit_price: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Update signal lifecycle state — delegates to update_signal_status."""
        await self.update_signal_status(signal_id, new_status)
        meta: dict = {}
        if exit_price is not None:
            meta["exit_price"] = exit_price
        if outcome is not None:
            meta["outcome"] = outcome
        for key in (
            "exit_at",
            "mae",
            "mfe",
            "bars_in_trade",
            "pnl_r",
            "activated_at",
            "activation_price",
            "zone_entry_pct",
            "bars_to_activation",
        ):
            val = kwargs.get(key)
            if val is not None:
                meta[key] = format_iso_ts(val) if key in ("exit_at", "activated_at") else val
        if meta:
            await self.update_frame_details(signal_id, meta)

    async def update_mae_mfe(self, signal_id: str, mae: float, mfe: float) -> None:
        """Persist in-memory MAE/MFE to trade_frames.frame_details."""
        await self.update_frame_details(signal_id, {"mae": mae, "mfe": mfe})

    async def record_activation(self, signal_id: str, **kwargs: Any) -> None:
        """Write zone-track activation fields. Sets status='active'."""
        await self.update_signal_status(signal_id, "active")
        meta: dict = {}
        if kwargs.get("activated_at"):
            meta["activated_at"] = format_iso_ts(kwargs["activated_at"])
        for key in ("activation_price", "zone_entry_pct", "bars_to_activation"):
            if kwargs.get(key) is not None:
                meta[key] = kwargs[key]
        if meta:
            await self.update_frame_details(signal_id, meta)

    async def record_zone_resolution(self, signal_id: str, **kwargs: Any) -> None:
        """Write zone-track resolution fields."""
        status = kwargs.get("status", "expired")
        await self.update_signal_status(signal_id, status)
        meta: dict = {}
        for key in (
            "exit_at",
            "exit_price",
            "exit_reason",
            "pnl_r",
            "pnl_dollars",
            "signal_quality",
            "mae",
            "mfe",
            "bars_in_trade",
            "outcome",
        ):
            if kwargs.get(key) is not None:
                meta[key] = kwargs[key]
        if meta:
            await self.update_frame_details(signal_id, meta)

    async def record_market_resolution(self, signal_id: str, **kwargs: Any) -> None:
        """Write market-track resolution fields."""
        meta: dict = {}
        for key in (
            "market_entry_at",
            "market_entry_exit_price",
            "market_entry_exit_at",
            "market_entry_pnl_r",
            "market_entry_mae",
            "market_entry_mfe",
            "market_entry_bars_in_trade",
            "market_entry_outcome",
            "market_entry_gap_bars",
        ):
            if kwargs.get(key) is not None:
                meta[key] = kwargs[key]
        if meta:
            await self.update_frame_details(signal_id, meta)

    async def record_zone_resolution_with_activation(self, signal_id: str, **kwargs: Any) -> None:
        """Atomically write activation + zone exit on same bar."""
        status = kwargs.get("status", "expired")
        await self.update_signal_status(signal_id, status)
        meta: dict = {}
        for key in (
            "activated_at",
            "activation_price",
            "zone_entry_pct",
            "bars_to_activation",
            "exit_at",
            "exit_price",
            "exit_reason",
            "pnl_r",
            "pnl_dollars",
            "signal_quality",
            "mae",
            "mfe",
            "bars_in_trade",
            "outcome",
        ):
            if kwargs.get(key) is not None:
                meta[key] = kwargs[key]
        if meta:
            await self.update_frame_details(signal_id, meta)

    async def update_chandelier_state(
        self,
        signal_id: str,
        history_json: str,
        tightening_rate: float | None,
        staleness_score: float,
        staleness_reason: str | None,
        vol_source: str | None,
    ) -> None:
        """Persist Chandelier trailing stop state to frame_details JSONB."""
        meta: dict = {"trailing_stop_price": history_json}
        if tightening_rate is not None:
            meta["trailing_stop_tightening_rate"] = tightening_rate
        meta["staleness_score"] = staleness_score
        if staleness_reason:
            meta["staleness_trigger_reason"] = staleness_reason
        if vol_source:
            meta["chandelier_vol_source"] = vol_source
        await self.update_frame_details(signal_id, meta)

    async def update_chandelier_vol_source(self, signal_id: str, vol_source: str) -> None:
        """Set chandelier_vol_source in frame_details if not already set."""
        sql = """
UPDATE trade_frames
SET frame_details = frame_details || $2::jsonb
WHERE signal_id = $1::uuid
  AND (frame_details->>'chandelier_vol_source') IS NULL
"""
        await self._db_manager.execute_command(
            sql, signal_id, {"chandelier_vol_source": vol_source}
        )

    async def update_shadow_outcome(
        self,
        signal_id: str,
        start_ts: Any,
        shadow_mae: float,
        shadow_mfe: float,
        shadow_outcome: str,
    ) -> None:
        """Persist post-condition_expired shadow tracking outcome to frame_details."""
        meta: dict = {
            "shadow_mae": shadow_mae,
            "shadow_mfe": shadow_mfe,
            "shadow_outcome": shadow_outcome,
        }
        if start_ts is not None:
            meta["shadow_tracking_start_ts"] = format_iso_ts(start_ts)
        await self.update_frame_details(signal_id, meta)

    async def set_shadow_tracking_start(self, signal_id: str, start_ts: Any) -> None:
        """Record start timestamp when a signal enters shadow tracking mode."""
        if start_ts is not None:
            await self.update_frame_details(
                signal_id,
                {"shadow_tracking_start_ts": format_iso_ts(start_ts)},
            )
