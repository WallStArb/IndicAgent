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
    cis_score: float | None = None       # CIS composite score in [-1.0, +1.0]
    bucket_scores: dict | None = None    # {"trend": 0.4, ...} — serialised to JSONB
    weights_version: int | None = None   # FK to cis_weights.version; 0 = bootstrap
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

    def to_insert_params(self) -> tuple:
        """Return a 37-element tuple ready for batch INSERT.

        JSONB columns (targets, supporting_factors, market_context, bucket_scores)
        are serialized to JSON strings so asyncpg can cast them via ``::jsonb``.
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
            self.feature_ts,           # $23 — TIMESTAMPTZ, nullable
            self.feature_tf,           # $24 — TEXT, nullable
            self.cis_score,            # $25 — FLOAT, nullable
            json.dumps(self.bucket_scores) if self.bucket_scores is not None else None,  # $26
            self.weights_version,      # $27 — INTEGER, nullable
            self.signal_quality,       # $28 — FLOAT, nullable
            self.signal_computed_at,   # $29 — TIMESTAMPTZ, nullable
            self.determined_at,        # $30
            self.ask_at_signal,        # $31
            self.bid_at_signal,        # $32
            self.market_price_at_signal,  # $33
            self.entry_zone_low,       # $34
            self.entry_zone_high,      # $35
            self.zone_valid_at_signal, # $36
            json.dumps(self.cis_attribution) if self.cis_attribution is not None else None,  # $37
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
    cis_attribution
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
    $37::jsonb
)
"""

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
WHERE status IN ('pending', 'active', 'regime_suppressed')
ORDER BY timestamp DESC
"""

_SELECT_ACTIVE_BY_SYMBOL_SQL = """
SELECT * FROM signal_ledger
WHERE status IN ('pending', 'active', 'regime_suppressed') AND symbol = $1
ORDER BY timestamp DESC
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
        signal_id, status,
        activated_at, exit_at, exit_price, exit_reason,
        pnl_ticks, pnl_r, pnl_dollars, signal_quality,
        activation_price, zone_entry_pct, bars_to_activation,
        mae, mfe, bars_in_trade, outcome,
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
