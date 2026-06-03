"""Signal Ledger Repository — data access layer for signal_ledger hypertable.

Provides CRUD operations for persisting trading signals, updating their
lifecycle status, and querying active signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

import structlog

from src.intelligence.trading.signal_schema import (
    SIGNAL_SCHEMA_VERSION,  # Ring 1 constant — schema version is a domain invariant shared across persistence and intelligence layers
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Signal lifecycle status enum — type-safe replacement for raw string literals
# ---------------------------------------------------------------------------


class SignalStatus(str, Enum):
    """Signal lifecycle status — matches database values for zero-migration compatibility.

    Extends str so .value matches existing DB string values. No migration needed.
    """

    PENDING = "pending"
    ACTIVE = "active"
    REGIME_SUPPRESSED = "regime_suppressed"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Signal outcome constants — 8-class taxonomy (authoritative source)
# ---------------------------------------------------------------------------

from src.intelligence.trading.signal_outcome import (  # noqa: E501
    STOP_OUTCOMES,
    TTL_OUTCOMES,
    WIN_OUTCOMES,
    SignalOutcome,
)

__all__ = ["SignalOutcome", "STOP_OUTCOMES", "TTL_OUTCOMES", "WIN_OUTCOMES"]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LedgerEntry:
    """Fire-time signal record — set at emission, never updated.

    All mutable lifecycle state lives in signal_outcomes (see SignalLedgerRepository).
    """

    signal_id: str
    timestamp: datetime
    symbol: str
    timeframe: str
    setup_plugin: str
    signal_type: str
    direction: int
    was_selected: bool
    is_shadow: bool = False
    is_backfill: bool = False
    signal_schema_version: str = SIGNAL_SCHEMA_VERSION
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
    # Initial status for signal_outcomes seeding — NOT stored in signal_ledger
    status: SignalStatus = SignalStatus.PENDING

    def _to_row(self) -> tuple:
        return (
            self.signal_id,  # $1
            self.timestamp,  # $2
            self.symbol,  # $3
            self.timeframe,  # $4
            self.setup_plugin,  # $5
            self.signal_type,  # $6
            self.direction,  # $7
            self.was_selected,  # $8
            self.is_shadow,  # $9
            self.is_backfill,  # $10
            self.signal_schema_version,  # $11
            self.signal_computed_at,  # $12
            self.feature_ts,  # $13
            self.feature_tf,  # $14
            self.hmm_regime_at_fire,  # $15
            self.garch_sigma_at_fire,  # $16
            self.ttl_bars,  # $17
            self.entry_price,  # $18
            self.stop_loss,  # $19
            self.targets,  # $20 list → asyncpg JSONB
            self.entry_zone_low,  # $21
            self.entry_zone_high,  # $22
            self.market_entry_price,  # $23
            self.cis_score,  # $24
            self.bucket_scores,  # $25 dict → asyncpg JSONB
            self.weights_version,  # $26
            self.pipeline_lag_ms,  # $27
            self.expires_at,  # $28
            self.feature_schema_version,  # $29 (contamination boundary)
        )


# ---------------------------------------------------------------------------
# Repository functions
# ---------------------------------------------------------------------------

_INSERT_SQL = """
INSERT INTO signal_ledger (
    signal_id, timestamp, symbol, timeframe,
    setup_plugin, signal_type, direction,
    was_selected, is_shadow, is_backfill,
    signal_schema_version, signal_computed_at,
    feature_ts, feature_tf,
    hmm_regime_at_fire, garch_sigma_at_fire,
    ttl_bars,
    entry_price, stop_loss, targets, entry_zone_low, entry_zone_high,
    market_entry_price,
    cis_score, bucket_scores, weights_version,
    pipeline_lag_ms, expires_at,
    feature_schema_version
) VALUES (
    $1::uuid, $2, $3, $4,
    $5, $6, $7,
    $8, $9, $10,
    $11, $12,
    $13, $14,
    $15, $16,
    $17,
    $18, $19, $20::jsonb, $21, $22,
    $23,
    $24, $25::jsonb, $26,
    $27, $28,
    $29
)
ON CONFLICT (signal_id, timestamp) DO NOTHING
"""

_INSERT_OUTCOMES_SQL = """
INSERT INTO signal_outcomes (signal_id, status)
VALUES ($1::uuid, $2)
ON CONFLICT (signal_id) DO NOTHING
"""


# ---------------------------------------------------------------------------
# signal_features — flat feature snapshot at signal fire time (Phase 31)
# ---------------------------------------------------------------------------

# Feature-to-bucket mapping (derived from CISScorer bucket methods)
FEATURE_BUCKET_MAP: dict[str, str] = {
    # trend bucket
    "ema_slope_20": "trend",
    "ema_slope_50": "trend",
    "adx_14": "trend",
    "kalman_trend_direction": "trend",
    "kalman_trend_strength": "trend",
    "trend_direction": "trend",
    "trend_strength": "trend",
    # momentum bucket
    "rsi_14": "momentum",
    "macd_histogram_12_26_9": "momentum",
    "stochastic_k_14": "momentum",
    "roc_10": "momentum",
    "momentum_acceleration": "momentum",
    "derivative_oscillator": "momentum",
    "rel_volume": "momentum",
    # structure bucket
    "nearest_support_dist_atr": "structure",
    "nearest_resistance_dist_atr": "structure",
    "swing_momentum": "structure",
    # pattern bucket
    "squeeze_active": "pattern",
    "rsi_divergence_bullish": "pattern",
    "rsi_divergence_bearish": "pattern",
    "vol_divergence_bullish": "pattern",
    "vol_divergence_bearish": "pattern",
    # institutional bucket
    "bos_count_bullish": "institutional",
    "bos_count_bearish": "institutional",
    "choch_detected": "institutional",
    "fvg_present": "institutional",
    "order_block_present": "institutional",
    "bsl_dist_atr": "institutional",
    "ssl_dist_atr": "institutional",
    # regime bucket
    "hmm_regime": "regime",
    "garch_vol_regime": "regime",
    "hurst_exponent": "regime",
    "shannon_entropy": "regime",
    "ict_killzone": "regime",
}

_INSERT_FEATURES_SQL = """
INSERT INTO signal_features
    (signal_id, computed_at, feature_name, feature_value, feature_bucket, bucket_contribution)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (signal_id, feature_name, computed_at) DO NOTHING
"""


def _build_feature_rows(
    signal_id: str,
    computed_at: datetime,
    features: dict[str, Any],
    cis_result: Any | None = None,
) -> list[tuple]:
    """Extract non-null numeric feature values for signal_features INSERT.

    Parameters
    ----------
    signal_id:
        UUID of the signal in signal_ledger.
    computed_at:
        Timestamp of signal computation (UTC).
    features:
        Flat dict of intelligence features (all I1-I6 fields merged).
    cis_result:
        Optional CISResult with constituent_contributions for bucket_contribution cross-ref.

    Returns list of (signal_id, computed_at, feature_name, feature_value,
    feature_bucket, bucket_contribution) tuples.
    """
    if not isinstance(features, dict):
        return []

    contributions: dict[str, float] = {}
    if cis_result is not None and hasattr(cis_result, "constituent_contributions"):
        # Flatten: {bucket: {feature: score}} -> {feature: score}
        for bucket_contribs in cis_result.constituent_contributions.values():
            if isinstance(bucket_contribs, dict):
                contributions.update(bucket_contribs)

    rows = []
    for key, value in features.items():
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            continue
        bucket = FEATURE_BUCKET_MAP.get(key)
        contribution = contributions.get(key)
        rows.append(
            (
                signal_id,
                computed_at,
                key,
                float(value),
                bucket,
                float(contribution) if contribution is not None else None,
            )
        )
    return rows


_UPDATE_STATUS_SQL = """
UPDATE signal_outcomes
SET status = $2,
    activated_at = $3,
    exit_at = $4,
    exit_price = $5,
    exit_reason = $6,
    pnl_ticks = $7,
    pnl_r = $8,
    pnl_dollars = $9,
    signal_quality = $10,
    activation_price = $11,
    zone_entry_pct = $12,
    bars_to_activation = $13,
    mae = $14,
    mfe = $15,
    bars_in_trade = $16,
    outcome = $17
WHERE signal_id = $1::uuid
"""

_SELECT_ACTIVE_COLS = """
       signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type, direction,
       was_selected, status, activated_at, exit_at, exit_price, exit_reason,
       pnl_ticks, pnl_r, pnl_dollars, signal_quality, signal_computed_at,
       activation_price, zone_entry_pct, bars_to_activation,
       mae, mfe, bars_in_trade, outcome,
       feature_ts, feature_tf,
       market_entry_price, market_entry_exit_price, market_entry_outcome,
       market_entry_pnl_r, market_entry_mae, market_entry_mfe, market_entry_bars_in_trade,
       market_entry_gap_bars, market_entry_at, market_entry_exit_at,
       is_shadow, hmm_regime_at_fire, garch_sigma_at_fire,
       trailing_stop_price, staleness_score, staleness_trigger_reason,
       shadow_tracking_start_ts, shadow_mae, shadow_mfe, shadow_outcome,
       effective_ts, pipeline_lag_ms, signal_schema_version, is_backfill, ttl_bars, expires_at,
       entry_price, stop_loss, targets, entry_zone_low, entry_zone_high
"""

_SELECT_ACTIVE_SQL = f"""
SELECT {_SELECT_ACTIVE_COLS}
FROM signal_ledger_full
WHERE status IN ('pending', 'active', 'regime_suppressed') AND exit_at IS NULL
ORDER BY timestamp DESC
"""

_SELECT_ACTIVE_BY_SYMBOL_SQL = f"""
SELECT {_SELECT_ACTIVE_COLS}
FROM signal_ledger_full
WHERE status IN ('pending', 'active', 'regime_suppressed') AND symbol = $1 AND exit_at IS NULL
ORDER BY timestamp DESC
"""

_RECORD_ACTIVATION_SQL = """
UPDATE signal_outcomes
SET status = 'active',
    activated_at = $2,
    activation_price = $3,
    zone_entry_pct = $4,
    bars_to_activation = $5
WHERE signal_id = $1::uuid
"""

_RECORD_ZONE_RESOLUTION_SQL = """
UPDATE signal_outcomes
SET status = $2,
    exit_at = $3,
    exit_price = $4,
    exit_reason = $5,
    pnl_r = $6,
    pnl_dollars = $7,
    signal_quality = $8,
    mae = $9,
    mfe = $10,
    bars_in_trade = $11,
    outcome = $12
WHERE signal_id = $1::uuid
"""

_RECORD_MARKET_RESOLUTION_SQL = """
UPDATE signal_outcomes
SET market_entry_at            = $2,
    market_entry_exit_price    = $3,
    market_entry_exit_at       = $4,
    market_entry_pnl_r         = $5,
    market_entry_mae           = $6,
    market_entry_mfe           = $7,
    market_entry_bars_in_trade = $8,
    market_entry_outcome       = $9,
    market_entry_gap_bars      = $10
WHERE signal_id = $1::uuid
"""

_BATCH_MARKET_RESOLUTION_SQL = _RECORD_MARKET_RESOLUTION_SQL

_RECORD_ZONE_WITH_ACTIVATION_SQL = """
UPDATE signal_outcomes
SET status = $2,
    activated_at = $3,
    activation_price = $4,
    zone_entry_pct = $5,
    bars_to_activation = $6,
    exit_at = $7,
    exit_price = $8,
    exit_reason = $9,
    pnl_r = $10,
    pnl_dollars = $11,
    signal_quality = $12,
    mae = $13,
    mfe = $14,
    bars_in_trade = $15,
    outcome = $16
WHERE signal_id = $1::uuid
"""


class SignalLedgerRepository:
    """Repository for SignalLedger persistence operations."""

    def __init__(self, db_manager: Any):
        self._db_manager = db_manager

    async def insert(self, entries: list[LedgerEntry]) -> None:
        """Insert fire-time records into signal_ledger and seed signal_outcomes rows."""
        if not entries:
            return
        ledger_params = [e._to_row() for e in entries]
        outcomes_params = [
            (e.signal_id, e.status.value if isinstance(e.status, SignalStatus) else str(e.status))
            for e in entries
        ]
        await self._db_manager.execute_batch(_INSERT_SQL, ledger_params)
        await self._db_manager.execute_batch(_INSERT_OUTCOMES_SQL, outcomes_params)

    async def insert_signals(self, entries: list[LedgerEntry]) -> None:
        """Batch-insert ledger entries. No-op when *entries* is empty.

        Delegates to insert() which handles both signal_ledger and signal_outcomes.
        """
        await self.insert(entries)
        if entries:
            logger.info("Inserted signals into ledger", count=len(entries))

    async def insert_signals_with_features(
        self, entries: list[LedgerEntry], features: dict, cis_result: Any = None
    ) -> None:
        """Atomic write: signal_ledger + signal_outcomes + signal_features in one transaction per bar."""
        if not entries or self._db_manager.pool is None:
            return
        async with self._db_manager.pool.acquire() as conn:
            async with conn.transaction():
                for entry in entries:
                    await conn.execute(_INSERT_SQL, *entry._to_row())
                    status_val = (
                        entry.status.value
                        if isinstance(entry.status, SignalStatus)
                        else str(entry.status)
                    )
                    await conn.execute(_INSERT_OUTCOMES_SQL, entry.signal_id, status_val)
                    feature_rows = _build_feature_rows(
                        entry.signal_id,
                        entry.signal_computed_at or entry.timestamp,
                        features,
                        cis_result,
                    )
                    if feature_rows:
                        await conn.executemany(_INSERT_FEATURES_SQL, feature_rows)
        logger.info("Wrote signals + features atomically", count=len(entries))

    async def update_signal_status(self, signal_id: str, **kwargs: Any) -> None:
        """Update a signal's lifecycle status and optional exit fields."""
        await self._db_manager.execute_command(
            _UPDATE_STATUS_SQL,
            signal_id,  # $1 signal_id
            kwargs.get("status"),  # $2 status
            kwargs.get("activated_at"),  # $3 activated_at
            kwargs.get("exit_at"),  # $4 exit_at
            kwargs.get("exit_price"),  # $5 exit_price
            kwargs.get("exit_reason"),  # $6 exit_reason
            kwargs.get("pnl_ticks"),  # $7 pnl_ticks
            kwargs.get("pnl_r"),  # $8 pnl_r
            kwargs.get("pnl_dollars"),  # $9 pnl_dollars
            kwargs.get("signal_quality"),  # $10 signal_quality
            kwargs.get("activation_price"),  # $11 activation_price
            kwargs.get("zone_entry_pct"),  # $12 zone_entry_pct
            kwargs.get("bars_to_activation"),  # $13 bars_to_activation
            kwargs.get("mae"),  # $14 mae
            kwargs.get("mfe"),  # $15 mfe
            kwargs.get("bars_in_trade"),  # $16 bars_in_trade
            kwargs.get("outcome"),  # $17 outcome
        )
        logger.info("Updated signal status", signal_id=signal_id, status=kwargs.get("status"))

    async def get_active_signals(self, symbol: str | None = None) -> list[dict]:
        """Return pending/active signals, optionally filtered by *symbol*."""
        if symbol is not None:
            return await self._db_manager.execute_query(_SELECT_ACTIVE_BY_SYMBOL_SQL, symbol)
        return await self._db_manager.execute_query(_SELECT_ACTIVE_SQL)

    async def record_activation(self, signal_id: str, **kwargs: Any) -> None:
        """Write zone-track activation fields. Sets status='active'. Phase 2."""
        await self._db_manager.execute_command(
            _RECORD_ACTIVATION_SQL,
            signal_id,  # $1 signal_id
            kwargs.get("activated_at"),  # $2 activated_at
            kwargs.get("activation_price"),  # $3 activation_price
            kwargs.get("zone_entry_pct"),  # $4 zone_entry_pct
            kwargs.get("bars_to_activation"),  # $5 bars_to_activation
        )

    async def record_zone_resolution(self, signal_id: str, **kwargs: Any) -> None:
        """Write zone-track resolution fields. Phase 3, zone track only."""
        await self._db_manager.execute_command(
            _RECORD_ZONE_RESOLUTION_SQL,
            signal_id,  # $1 signal_id
            kwargs.get("status"),  # $2 status
            kwargs.get("exit_at"),  # $3 exit_at
            kwargs.get("exit_price"),  # $4 exit_price
            kwargs.get("exit_reason"),  # $5 exit_reason
            kwargs.get("pnl_r"),  # $6 pnl_r
            kwargs.get("pnl_dollars"),  # $7 pnl_dollars
            kwargs.get("signal_quality"),  # $8 signal_quality
            kwargs.get("mae"),  # $9 mae
            kwargs.get("mfe"),  # $10 mfe
            kwargs.get("bars_in_trade"),  # $11 bars_in_trade
            kwargs.get("outcome"),  # $12 outcome
        )

    async def record_market_resolution(self, signal_id: str, **kwargs: Any) -> None:
        """Write market-track resolution fields. Phase 3, market track only."""
        await self._db_manager.execute_command(
            _RECORD_MARKET_RESOLUTION_SQL,
            signal_id,  # $1 signal_id
            kwargs.get("market_entry_at"),  # $2 market_entry_at
            kwargs.get("market_entry_exit_price"),  # $3 market_entry_exit_price
            kwargs.get("market_entry_exit_at"),  # $4 market_entry_exit_at
            kwargs.get("market_entry_pnl_r"),  # $5 market_entry_pnl_r
            kwargs.get("market_entry_mae"),  # $6 market_entry_mae
            kwargs.get("market_entry_mfe"),  # $7 market_entry_mfe
            kwargs.get("market_entry_bars_in_trade"),  # $8 market_entry_bars_in_trade
            kwargs.get("market_entry_outcome"),  # $9 market_entry_outcome
            kwargs.get("market_entry_gap_bars"),  # $10 market_entry_gap_bars
        )

    async def record_zone_resolution_with_activation(self, signal_id: str, **kwargs: Any) -> None:
        """Atomically write activation + zone exit on same bar. Prevents status stuck in 'active'."""
        await self._db_manager.execute_command(
            _RECORD_ZONE_WITH_ACTIVATION_SQL,
            signal_id,  # $1 signal_id
            kwargs.get("status"),  # $2 status
            kwargs.get("activated_at"),  # $3 activated_at
            kwargs.get("activation_price"),  # $4 activation_price
            kwargs.get("zone_entry_pct"),  # $5 zone_entry_pct
            kwargs.get("bars_to_activation"),  # $6 bars_to_activation
            kwargs.get("exit_at"),  # $7 exit_at
            kwargs.get("exit_price"),  # $8 exit_price
            kwargs.get("exit_reason"),  # $9 exit_reason
            kwargs.get("pnl_r"),  # $10 pnl_r
            kwargs.get("pnl_dollars"),  # $11 pnl_dollars
            kwargs.get("signal_quality"),  # $12 signal_quality
            kwargs.get("mae"),  # $13 mae
            kwargs.get("mfe"),  # $14 mfe
            kwargs.get("bars_in_trade"),  # $15 bars_in_trade
            kwargs.get("outcome"),  # $16 outcome
        )

    async def update_lifecycle_state(
        self,
        signal_id: str,
        new_status: str,
        outcome: str | None = None,
        exit_price: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Update signal lifecycle state — delegates to update_signal_status.

        Provides the canonical name expected by SignalTrackerAgent.
        """
        await self.update_signal_status(
            signal_id,
            status=new_status,
            outcome=outcome,
            exit_price=exit_price,
            **kwargs,
        )

    async def update_mae_mfe(
        self,
        signal_id: str,
        mae: float,
        mfe: float,
    ) -> None:
        """Persist in-memory MAE/MFE to signal_ledger for the given signal."""
        sql = """
UPDATE signal_outcomes
SET mae = $2,
    mfe = $3
WHERE signal_id = $1::uuid
"""
        await self._db_manager.execute_command(sql, signal_id, mae, mfe)

    async def fetch_active_signals(self, symbol: str, tf: str) -> list[dict]:
        """Return pending/active/regime_suppressed signals for a specific symbol+timeframe."""
        sql = f"""
SELECT {_SELECT_ACTIVE_COLS}
FROM signal_ledger_full
WHERE status IN ('pending', 'active', 'regime_suppressed')
  AND symbol = $1
  AND timeframe = $2
  AND exit_at IS NULL
ORDER BY timestamp DESC
"""
        return await self._db_manager.execute_query(sql, symbol, tf)

    async def fetch_pending_signals(self) -> list[dict]:
        """Return all pending signals across all symbols/timeframes."""
        sql = """
SELECT signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type, direction,
       was_selected, status, feature_ts, feature_tf, expires_at, activation_price,
       entry_price, stop_loss, targets, entry_zone_low, entry_zone_high
FROM signal_ledger_full
WHERE status = 'pending' AND exit_at IS NULL
ORDER BY timestamp DESC
"""
        return await self._db_manager.execute_query(sql)

    async def update_chandelier_state(
        self,
        signal_id: str,
        history_json: str,
        tightening_rate: float | None,
        staleness_score: float,
        staleness_reason: str | None,
        vol_source: str | None,
    ) -> None:
        """Persist Chandelier trailing stop state and staleness fields."""
        sql = """
UPDATE signal_outcomes
SET trailing_stop_price = $2::jsonb,
    trailing_stop_tightening_rate = $3,
    staleness_score = $4,
    staleness_trigger_reason = $5,
    chandelier_vol_source = COALESCE(chandelier_vol_source, $6)
WHERE signal_id = $1::uuid
"""
        await self._db_manager.execute_command(
            sql,
            signal_id,
            history_json,
            tightening_rate,
            staleness_score,
            staleness_reason,
            vol_source,
        )

    async def update_chandelier_vol_source(self, signal_id: str, vol_source: str) -> None:
        """Set chandelier_vol_source on first active bar if not already set."""
        sql = """
UPDATE signal_outcomes
SET chandelier_vol_source = $2
WHERE signal_id = $1::uuid AND chandelier_vol_source IS NULL
"""
        await self._db_manager.execute_command(sql, signal_id, vol_source)

    async def update_shadow_outcome(
        self,
        signal_id: str,
        start_ts: Any,
        shadow_mae: float,
        shadow_mfe: float,
        shadow_outcome: str,
    ) -> None:
        """Persist post-condition_expired shadow tracking outcome."""
        sql = """
UPDATE signal_outcomes
SET shadow_tracking_start_ts = $2,
    shadow_mae = $3,
    shadow_mfe = $4,
    shadow_outcome = $5
WHERE signal_id = $1::uuid
"""
        await self._db_manager.execute_command(
            sql,
            signal_id,
            start_ts,
            shadow_mae,
            shadow_mfe,
            shadow_outcome,
        )

    async def set_shadow_tracking_start(self, signal_id: str, start_ts: Any) -> None:
        """Record start timestamp when a signal enters shadow tracking mode."""
        sql = """
UPDATE signal_outcomes
SET shadow_tracking_start_ts = $2
WHERE signal_id = $1::uuid
"""
        await self._db_manager.execute_command(sql, signal_id, start_ts)

    # ------------------------------------------------------------------
    # Batch transition persistence (consumed by LifecycleWriter)
    # ------------------------------------------------------------------

    _BATCH_ACTIVATION_SQL = """
UPDATE signal_outcomes
SET status = 'active',
    activated_at = $2,
    activation_price = $3,
    zone_entry_pct = $4,
    bars_to_activation = $5
WHERE signal_id = $1::uuid
"""

    _BATCH_EXIT_SQL = """
UPDATE signal_outcomes
SET status = $2,
    exit_at = $3,
    exit_price = $4,
    exit_reason = $5,
    pnl_r = $6,
    pnl_dollars = $7,
    signal_quality = $8,
    mae = $9,
    mfe = $10,
    bars_in_trade = $11,
    outcome = $12
WHERE signal_id = $1::uuid
"""

    _BATCH_CHANDELIER_UPDATE_SQL = """
UPDATE signal_outcomes
SET trailing_stop_price = $2::jsonb,
    trailing_stop_tightening_rate = $3,
    staleness_score = $4,
    staleness_trigger_reason = $5,
    chandelier_vol_source = COALESCE(chandelier_vol_source, $6)
WHERE signal_id = $1::uuid
"""

    _BATCH_MAE_MFE_UPDATE_SQL = """
UPDATE signal_outcomes
SET mae = $2,
    mfe = $3
WHERE signal_id = $1::uuid
"""

    _BATCH_SHADOW_OUTCOME_SQL = """
UPDATE signal_outcomes
SET shadow_tracking_start_ts = $2,
    shadow_mae = $3,
    shadow_mfe = $4,
    shadow_outcome = $5
WHERE signal_id = $1::uuid
"""

    async def batch_execute(self, transition_type: str, items: list[dict]) -> None:
        """Batch-write lifecycle transitions grouped by type.

        Parameters
        ----------
        transition_type:
            One of ``"activation"``, ``"exit"``, ``"chandelier_update"``,
            ``"mae_mfe_update"``, ``"shadow_outcome"``.
        items:
            List of transition data dicts. Each must contain ``"signal_id"``
            plus the fields relevant to the transition type.

        Raises
        ------
        ValueError
            If *transition_type* is not recognised.
        """
        if not items:
            return

        if transition_type == "activation":
            sql = self._BATCH_ACTIVATION_SQL
            params = [
                (
                    d["signal_id"],
                    d.get("activated_at"),
                    d.get("activation_price"),
                    d.get("zone_entry_pct"),
                    d.get("bars_to_activation"),
                )
                for d in items
            ]
        elif transition_type == "exit":
            sql = self._BATCH_EXIT_SQL
            params = [
                (
                    d["signal_id"],
                    d.get("status"),
                    d.get("exit_at"),
                    d.get("exit_price"),
                    d.get("exit_reason"),
                    d.get("pnl_r"),
                    d.get("pnl_dollars"),
                    d.get("signal_quality"),
                    d.get("mae"),
                    d.get("mfe"),
                    d.get("bars_in_trade"),
                    d.get("outcome"),
                )
                for d in items
            ]
        elif transition_type == "chandelier_update":
            sql = self._BATCH_CHANDELIER_UPDATE_SQL
            params = [
                (
                    d["signal_id"],
                    d.get("trailing_stop_price"),
                    d.get("trailing_stop_tightening_rate"),
                    d.get("staleness_score"),
                    d.get("staleness_trigger_reason"),
                    d.get("chandelier_vol_source"),
                )
                for d in items
            ]
        elif transition_type == "mae_mfe_update":
            sql = self._BATCH_MAE_MFE_UPDATE_SQL
            params = [(d["signal_id"], d.get("mae"), d.get("mfe")) for d in items]
        elif transition_type == "shadow_outcome":
            sql = self._BATCH_SHADOW_OUTCOME_SQL
            params = [
                (
                    d["signal_id"],
                    d.get("shadow_tracking_start_ts"),
                    d.get("shadow_mae"),
                    d.get("shadow_mfe"),
                    d.get("shadow_outcome"),
                )
                for d in items
            ]
        elif transition_type == "market_resolution":
            sql = _BATCH_MARKET_RESOLUTION_SQL
            params = [
                (
                    d["signal_id"],
                    d.get("market_entry_at"),
                    d.get("market_entry_exit_price"),
                    d.get("market_entry_exit_at"),
                    d.get("market_entry_pnl_r"),
                    d.get("market_entry_mae"),
                    d.get("market_entry_mfe"),
                    d.get("market_entry_bars_in_trade"),
                    d.get("market_entry_outcome"),
                    d.get("market_entry_gap_bars"),
                )
                for d in items
            ]
        else:
            raise ValueError(
                f"Unknown transition_type '{transition_type}'. "
                "Must be one of: activation, exit, chandelier_update, "
                "mae_mfe_update, shadow_outcome, market_resolution"
            )

        await self._db_manager.execute_batch(sql, params)
        logger.info(
            "batch_execute completed",
            transition_type=transition_type,
            count=len(items),
        )
