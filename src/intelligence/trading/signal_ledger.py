"""Signal Ledger Repository — data access layer for signal_ledger hypertable.

Provides CRUD operations for persisting trading signals, updating their
lifecycle status, and querying active signals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Signal outcome constants — 8-class taxonomy (authoritative source)
# ---------------------------------------------------------------------------

WIN_OUTCOMES: frozenset[str] = frozenset({"target_1", "target_1_2", "target_full"})

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LedgerEntry:
    """Single row in the signal_ledger hypertable."""

    signal_id: str
    timestamp: datetime
    symbol: str
    timeframe: str
    setup_plugin: str
    signal_type: str
    direction: int
    entry_price: float
    stop_loss: float
    targets: list[float]
    confidence: float
    confluence_score: float
    regime_context: str
    supporting_factors: list[str]
    was_selected: bool
    num_signals_bar: int
    num_agreeing: int
    num_conflicting: int
    resolution_method: str
    composite_rank: int
    market_context: dict = field(default_factory=dict)
    status: str = "pending"
    feature_ts: datetime | None = None
    feature_tf: str | None = None
    # CIS fields — populated by CIS aggregator at signal fire time (Phase 7)
    cis_score: float | None = None  # CIS composite score in [-1.0, +1.0]
    bucket_scores: dict | None = None  # {"trend": 0.4, ...} — serialised to JSONB
    weights_version: int | None = None  # FK to cis_weights.version; 0 = bootstrap
    signal_quality: float | None = None  # populated by signal_lifecycle on exit
    signal_computed_at: datetime | None = None  # when signal_generator fired; NULL for backfill
    # Institutional lifecycle fields — all nullable; populated progressively
    # At signal determination time
    determined_at: datetime | None = None
    ask_at_signal: float | None = None
    bid_at_signal: float | None = None
    market_price_at_signal: float | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    zone_valid_at_signal: bool | None = None
    # Attribution — per-constituent CIS contributions at signal fire time
    cis_attribution: dict | None = None
    # At activation (set by signal_lifecycle_service)
    activation_price: float | None = None
    zone_entry_pct: float | None = None
    bars_to_activation: int | None = None
    # During/after trade
    mae: float | None = None
    mfe: float | None = None
    bars_in_trade: int | None = None
    outcome: str | None = None
    # Market-entry parallel track — Phase 1 field set at INSERT
    # ask (long) / bid (short) at signal fire; NULL if unavailable
    market_entry_price: float | None = None
    # Shadow signal flag — A/B matched-pair comparison (Phase 31)
    is_shadow: bool = False
    # Stop basis fields — Phase 32 stop architecture (all nullable; NULL for pre-migration rows)
    stop_basis: str | None = None  # "structure_snap" | "garch_adaptive" | "atr_static"
    stop_structure_type: str | None = None  # "ob_bottom"|"demand_zone"|...|"atr_fallback"
    stop_structure_age_bars: int | None = None  # bars since structural level was formed
    # |structural_stop - atr_fallback| / effective_atr
    structural_stop_distance_atr: float | None = None
    # Fire-time point-in-time snapshots
    hmm_regime_at_fire: int | None = None  # HMM regime integer at signal fire
    garch_sigma_at_fire: float | None = None  # instantaneous GARCH σ at signal fire
    # Chandelier + trailing stop
    chandelier_vol_source: str | None = None  # "garch_sigma" | "atr_14"
    trailing_stop_price: list | None = None  # JSONB array [{ts, price}]
    trailing_stop_tightening_rate: float | None = None
    # Staleness
    staleness_score: float | None = None
    staleness_trigger_reason: str | None = None
    # Shadow tracking
    shadow_tracking_start_ts: datetime | None = None
    shadow_mae: float | None = None
    shadow_mfe: float | None = None
    shadow_outcome: str | None = None
    # Phase 35: Calibration fields — all nullable
    raw_cis_score: float | None = None          # CIS score before Kalman filter
    filtered_cis_score: float | None = None     # Kalman-filtered CIS score
    calibrated_confidence: float | None = None  # isotonic calibrated probability; NULL when N < 100
    regime_type_at_fire: str | None = None      # regime_type of winning signal at fire time

    def to_insert_params(self) -> tuple:
        """Return a 58-element tuple ready for batch INSERT.

        JSONB columns (targets, supporting_factors, market_context, bucket_scores,
        trailing_stop_price) are serialized to JSON strings so asyncpg can cast
        them via ``::jsonb``.
        """
        return (
            self.signal_id,
            self.timestamp,
            self.symbol,
            self.timeframe,
            self.setup_plugin,
            self.signal_type,
            self.direction,
            self.entry_price,
            self.stop_loss,
            json.dumps(self.targets),
            self.confidence,
            self.confluence_score,
            self.regime_context,
            json.dumps(self.supporting_factors),
            self.was_selected,
            self.num_signals_bar,
            self.num_agreeing,
            self.num_conflicting,
            self.resolution_method,
            self.composite_rank,
            json.dumps(self.market_context),
            self.status,
            self.feature_ts,  # $23 — TIMESTAMPTZ, nullable
            self.feature_tf,  # $24 — TEXT, nullable
            self.cis_score,  # $25 — FLOAT, nullable
            json.dumps(self.bucket_scores) if self.bucket_scores is not None else None,  # $26
            self.weights_version,  # $27 — INTEGER, nullable
            self.signal_quality,  # $28 — FLOAT, nullable
            self.signal_computed_at,  # $29 — TIMESTAMPTZ, nullable
            self.determined_at,  # $30
            self.ask_at_signal,  # $31
            self.bid_at_signal,  # $32
            self.market_price_at_signal,  # $33
            self.entry_zone_low,  # $34
            self.entry_zone_high,  # $35
            self.zone_valid_at_signal,  # $36
            json.dumps(self.cis_attribution) if self.cis_attribution is not None else None,  # $37
            self.market_entry_price,  # $38 — FLOAT, nullable
            self.is_shadow,  # $39 — BOOLEAN
            # Phase 32: stop basis fields
            self.stop_basis,                    # $40
            self.stop_structure_type,           # $41
            self.stop_structure_age_bars,       # $42
            self.structural_stop_distance_atr,  # $43
            self.hmm_regime_at_fire,            # $44
            self.garch_sigma_at_fire,           # $45
            self.chandelier_vol_source,         # $46
            # $47::jsonb — trailing stop path [{ts, price}]
            json.dumps(self.trailing_stop_price)
            if self.trailing_stop_price is not None
            else None,
            self.trailing_stop_tightening_rate, # $48
            self.staleness_score,               # $49
            self.staleness_trigger_reason,      # $50
            self.shadow_tracking_start_ts,      # $51
            self.shadow_mae,                    # $52
            self.shadow_mfe,                    # $53
            self.shadow_outcome,                # $54
            self.raw_cis_score,                 # $55
            self.filtered_cis_score,            # $56
            self.calibrated_confidence,         # $57
            self.regime_type_at_fire,           # $58
        )


# ---------------------------------------------------------------------------
# Repository functions
# ---------------------------------------------------------------------------

_INSERT_SQL = """
INSERT INTO signal_ledger (
    signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type,
    direction, entry_price, stop_loss, targets,
    confidence, confluence_score, regime_context, supporting_factors,
    was_selected, num_signals_bar, num_agreeing, num_conflicting,
    resolution_method, composite_rank, market_context, status,
    feature_ts, feature_tf,
    cis_score, bucket_scores, weights_version, signal_quality,
    signal_computed_at,
    determined_at, ask_at_signal, bid_at_signal, market_price_at_signal,
    entry_zone_low, entry_zone_high, zone_valid_at_signal,
    cis_attribution,
    market_entry_price,
    is_shadow,
    stop_basis, stop_structure_type, stop_structure_age_bars,
    structural_stop_distance_atr,
    hmm_regime_at_fire, garch_sigma_at_fire,
    chandelier_vol_source,
    trailing_stop_price, trailing_stop_tightening_rate,
    staleness_score, staleness_trigger_reason,
    shadow_tracking_start_ts,
    shadow_mae, shadow_mfe, shadow_outcome,
    raw_cis_score, filtered_cis_score, calibrated_confidence, regime_type_at_fire
) VALUES (
    $1::uuid, $2, $3, $4, $5, $6,
    $7, $8, $9, $10::jsonb,
    $11, $12, $13, $14::jsonb,
    $15, $16, $17, $18,
    $19, $20, $21::jsonb, $22,
    $23, $24,
    $25, $26::jsonb, $27, $28,
    $29,
    $30, $31, $32, $33,
    $34, $35, $36,
    $37::jsonb,
    $38,
    $39,
    $40, $41, $42,
    $43,
    $44, $45,
    $46,
    $47::jsonb, $48,
    $49, $50,
    $51,
    $52, $53, $54,
    $55, $56, $57, $58
)
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
        rows.append((
            signal_id,
            computed_at,
            key,
            float(value),
            bucket,
            float(contribution) if contribution is not None else None,
        ))
    return rows


_UPDATE_STATUS_SQL = """
UPDATE signal_ledger
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

_SELECT_ACTIVE_SQL = """
SELECT * FROM signal_ledger
WHERE status IN ('pending', 'active', 'regime_suppressed') AND exit_at IS NULL
ORDER BY timestamp DESC
"""

_SELECT_ACTIVE_BY_SYMBOL_SQL = """
SELECT * FROM signal_ledger
WHERE status IN ('pending', 'active', 'regime_suppressed') AND symbol = $1 AND exit_at IS NULL
ORDER BY timestamp DESC
"""

_RECORD_ACTIVATION_SQL = """
UPDATE signal_ledger
SET status = 'active',
    activated_at = $2,
    activation_price = $3,
    zone_entry_pct = $4,
    bars_to_activation = $5
WHERE signal_id = $1::uuid
"""

_RECORD_ZONE_RESOLUTION_SQL = """
UPDATE signal_ledger
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
UPDATE signal_ledger
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

_RECORD_ZONE_WITH_ACTIVATION_SQL = """
UPDATE signal_ledger
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


async def insert_signals(
    db_manager: Any,
    entries: list[LedgerEntry],
) -> None:
    """Batch-insert ledger entries. No-op when *entries* is empty."""
    if not entries:
        return
    params = [entry.to_insert_params() for entry in entries]
    await db_manager.execute_batch(_INSERT_SQL, params)
    logger.info("Inserted signals into ledger", count=len(entries))


async def insert_signals_with_features(
    pool: Any,
    entries: list[LedgerEntry],
    features: dict,
    cis_result: Any = None,
) -> None:
    """Atomic write: signal_ledger + signal_features in one transaction per bar.

    FEAT-02: No orphaned feature rows — both tables succeed or both fail for
    all signals on the bar. All entries share the same mid-bar feature snapshot.

    Parameters
    ----------
    pool:
        asyncpg connection pool (db_manager.pool).
    entries:
        Signals fired on this bar evaluation.
    features:
        Flat feature dict shared by all signals (same bar, same snapshot).
    cis_result:
        Optional CISResult for bucket_contribution cross-reference.
    """
    if not entries or pool is None:
        return
    async with pool.acquire() as conn:
        async with conn.transaction():
            for entry in entries:
                await conn.execute(_INSERT_SQL, *entry.to_insert_params())
                feature_rows = _build_feature_rows(
                    entry.signal_id,
                    entry.signal_computed_at or entry.timestamp,
                    features,
                    cis_result,
                )
                if feature_rows:
                    await conn.executemany(_INSERT_FEATURES_SQL, feature_rows)
    logger.info("Wrote signals + features atomically", count=len(entries))


async def update_signal_status(
    db_manager: Any,
    signal_id: str,
    *,
    status: str,
    activated_at: datetime | None = None,
    exit_at: datetime | None = None,
    exit_price: float | None = None,
    exit_reason: str | None = None,
    pnl_ticks: float | None = None,
    pnl_r: float | None = None,
    pnl_dollars: float | None = None,
    signal_quality: float | None = None,
    activation_price: float | None = None,
    zone_entry_pct: float | None = None,
    bars_to_activation: int | None = None,
    mae: float | None = None,
    mfe: float | None = None,
    bars_in_trade: int | None = None,
    outcome: str | None = None,
) -> None:
    """Update a signal's lifecycle status and optional exit fields."""
    await db_manager.execute_command(
        _UPDATE_STATUS_SQL,
        signal_id,
        status,
        activated_at,
        exit_at,
        exit_price,
        exit_reason,
        pnl_ticks,
        pnl_r,
        pnl_dollars,
        signal_quality,
        activation_price,
        zone_entry_pct,
        bars_to_activation,
        mae,
        mfe,
        bars_in_trade,
        outcome,
    )
    logger.info("Updated signal status", signal_id=signal_id, status=status)


async def get_active_signals(
    db_manager: Any,
    symbol: str | None = None,
) -> list[dict]:
    """Return pending/active signals, optionally filtered by *symbol*."""
    if symbol is not None:
        return await db_manager.execute_query(_SELECT_ACTIVE_BY_SYMBOL_SQL, symbol)
    return await db_manager.execute_query(_SELECT_ACTIVE_SQL)


async def record_activation(
    db_manager: Any,
    signal_id: str,
    *,
    activated_at: datetime,
    activation_price: float,
    zone_entry_pct: float | None,
    bars_to_activation: int,
) -> None:
    """Write zone-track activation fields. Sets status='active'. Phase 2."""
    await db_manager.execute_command(
        _RECORD_ACTIVATION_SQL,
        signal_id, activated_at, activation_price, zone_entry_pct, bars_to_activation,
    )


async def record_zone_resolution(
    db_manager: Any,
    signal_id: str,
    *,
    status: str,
    exit_at: datetime,
    exit_price: float | None,
    exit_reason: str | None,
    pnl_r: float | None,
    pnl_dollars: float | None,
    signal_quality: float | None,
    mae: float | None,
    mfe: float | None,
    bars_in_trade: int | None,
    outcome: str | None,
) -> None:
    """Write zone-track resolution fields. Phase 3, zone track only."""
    await db_manager.execute_command(
        _RECORD_ZONE_RESOLUTION_SQL,
        signal_id, status, exit_at, exit_price, exit_reason,
        pnl_r, pnl_dollars, signal_quality,
        mae, mfe, bars_in_trade, outcome,
    )


async def record_market_resolution(
    db_manager: Any,
    signal_id: str,
    *,
    market_entry_at: datetime | None,
    market_entry_exit_price: float | None,
    market_entry_exit_at: datetime | None,
    market_entry_pnl_r: float | None,
    market_entry_mae: float,
    market_entry_mfe: float,
    market_entry_bars_in_trade: int | None,
    market_entry_outcome: str,
    market_entry_gap_bars: int | None = None,
) -> None:
    """Write market-track resolution fields. Phase 3, market track only."""
    await db_manager.execute_command(
        _RECORD_MARKET_RESOLUTION_SQL,
        signal_id,
        market_entry_at, market_entry_exit_price, market_entry_exit_at,
        market_entry_pnl_r,
        market_entry_mae, market_entry_mfe,
        market_entry_bars_in_trade, market_entry_outcome, market_entry_gap_bars,
    )


async def record_zone_resolution_with_activation(
    db_manager: Any,
    signal_id: str,
    *,
    activated_at: datetime,
    activation_price: float,
    zone_entry_pct: float | None,
    bars_to_activation: int,
    status: str,
    exit_at: datetime,
    exit_price: float | None,
    exit_reason: str | None,
    pnl_r: float | None,
    pnl_dollars: float | None,
    signal_quality: float | None,
    mae: float | None,
    mfe: float | None,
    bars_in_trade: int | None,
    outcome: str | None,
) -> None:
    """Atomically write activation + zone exit on same bar. Prevents status stuck in 'active'."""
    await db_manager.execute_command(
        _RECORD_ZONE_WITH_ACTIVATION_SQL,
        signal_id, status,
        activated_at, activation_price, zone_entry_pct, bars_to_activation,
        exit_at, exit_price, exit_reason,
        pnl_r, pnl_dollars, signal_quality,
        mae, mfe, bars_in_trade, outcome,
    )
