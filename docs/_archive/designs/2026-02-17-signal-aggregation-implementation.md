# I7 Phase 1.5: Signal Aggregation & Management — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a data-first signal aggregation system with rules-based conflict resolution, full signal lifecycle tracking, and position sizing — all designed to collect the outcome data needed for future ML-calibrated scoring.

**Architecture:** 5 setup plugins → Signal Aggregator (rules-based priority + conflict resolution) → Signal Ledger (PostgreSQL hypertable logging ALL signals with context) → Lifecycle Tracker (state machine: pending→active→stopped/target/expired) → Position Sizer (risk-based contract calculation). The aggregated "best" signal publishes to Redis streams for SSE delivery.

**Tech Stack:** Python 3.13, asyncpg, Redis Streams, TimescaleDB, dataclasses, structlog, pytest

**Design Doc:** `docs/plans/2026-02-17-signal-aggregation-design.md`

---

## Task 1: Signal Ledger Database Schema

**Files:**
- Modify: `production/schemas/create_schema.sql`
- Create: `production/schemas/signal_ledger_migration.sql`

**Step 1: Write the migration SQL**

Create `production/schemas/signal_ledger_migration.sql`:

```sql
-- Signal Ledger Migration
-- I7 Phase 1.5: Full signal lifecycle tracking for ML calibration
-- Run: psql -U postgres -d indicagent -f production/schemas/signal_ledger_migration.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()

CREATE TABLE IF NOT EXISTS signal_ledger (
    -- Identity
    signal_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,

    -- Signal details (from signal.v1 schema)
    setup_plugin    TEXT NOT NULL,
    signal_type     TEXT NOT NULL,
    direction       SMALLINT NOT NULL,          -- +1 or -1
    entry_price     DOUBLE PRECISION NOT NULL,
    stop_loss       DOUBLE PRECISION NOT NULL,
    targets         JSONB NOT NULL,             -- [t1, t2, t3]
    confidence      DOUBLE PRECISION NOT NULL,
    confluence_score DOUBLE PRECISION NOT NULL,
    regime_context  TEXT NOT NULL,
    supporting_factors JSONB NOT NULL,

    -- Aggregation context
    was_selected    BOOLEAN NOT NULL,           -- Did this win aggregation?
    num_signals_bar INTEGER NOT NULL,           -- How many signals fired this bar
    num_agreeing    INTEGER NOT NULL,           -- Same-direction count
    num_conflicting INTEGER NOT NULL,           -- Opposite-direction count
    resolution_method TEXT NOT NULL,            -- "sole" | "priority" | "majority" | "regime_tiebreak" | "no_signal"
    composite_rank  SMALLINT NOT NULL,          -- 1 = winner, 2 = runner-up, etc.

    -- Market context snapshot (feature vector for future ML)
    market_context  JSONB NOT NULL DEFAULT '{}',

    -- Lifecycle tracking
    status          TEXT NOT NULL DEFAULT 'pending',
    activated_at    TIMESTAMPTZ,
    exit_at         TIMESTAMPTZ,
    exit_price      DOUBLE PRECISION,
    exit_reason     TEXT,                       -- "stop_loss" | "target_1" | "target_2" | "target_3" | "ttl_expired" | "invalidated"

    -- P&L (filled on exit)
    pnl_ticks       DOUBLE PRECISION,
    pnl_r           DOUBLE PRECISION,           -- R-multiple
    pnl_dollars     DOUBLE PRECISION,

    -- Metadata
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Convert to hypertable (7-day chunks for signal-volume data)
SELECT create_hypertable('signal_ledger', 'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Compression: segment by symbol + setup_plugin
ALTER TABLE signal_ledger SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,setup_plugin',
    timescaledb.compress_orderby = 'timestamp DESC'
);
SELECT add_compression_policy('signal_ledger', INTERVAL '30 days');

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_ledger_symbol_tf_ts
    ON signal_ledger (symbol, timeframe, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_ledger_status
    ON signal_ledger (status, symbol) WHERE status IN ('pending', 'active');

CREATE INDEX IF NOT EXISTS idx_ledger_selected
    ON signal_ledger (was_selected, symbol, timestamp DESC) WHERE was_selected = TRUE;

CREATE INDEX IF NOT EXISTS idx_ledger_setup_plugin
    ON signal_ledger (setup_plugin, timestamp DESC);
```

**Step 2: Also append the signal_ledger to create_schema.sql**

Add the signal_ledger table definition and hypertable creation to the end of `production/schemas/create_schema.sql` (before the final `NOTIFY`), so fresh installs get it automatically.

**Step 3: Run the migration**

Run: `PGPASSWORD=postgres psql -h localhost -U postgres -d indicagent -f production/schemas/signal_ledger_migration.sql`
Expected: All commands succeed (CREATE TABLE, hypertable, compression, indexes)

**Step 4: Verify**

Run: `PGPASSWORD=postgres psql -h localhost -U postgres -d indicagent -c "SELECT hypertable_name, compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_name = 'signal_ledger';"`
Expected: `signal_ledger | t`

**Step 5: Commit**

```bash
git add production/schemas/signal_ledger_migration.sql production/schemas/create_schema.sql
git commit -m "feat(i7.5): add signal_ledger hypertable schema with compression"
```

---

## Task 2: Signal Ledger Repository

**Files:**
- Create: `src/intelligence/trading/signal_ledger.py`
- Create: `tests/unit/intelligence/test_signal_ledger.py`

This task builds the data access layer for reading/writing signals to the ledger. All methods are async and accept a `DatabaseManager` instance.

**Step 1: Write the failing tests**

Create `tests/unit/intelligence/test_signal_ledger.py`:

```python
"""Tests for signal_ledger repository."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.trading.signal_ledger import (
    LedgerEntry,
    insert_signals,
    update_signal_status,
    get_active_signals,
)


def _make_entry(**overrides) -> LedgerEntry:
    defaults = {
        "signal_id": str(uuid.uuid4()),
        "timestamp": datetime(2026, 2, 17, 14, 30, tzinfo=timezone.utc),
        "symbol": "ES",
        "timeframe": "5m",
        "setup_plugin": "trad_TrendFollowing",
        "signal_type": "trend_long",
        "direction": 1,
        "entry_price": 5100.0,
        "stop_loss": 5085.0,
        "targets": [5110.0, 5120.0, 5130.0],
        "confidence": 0.75,
        "confluence_score": 0.60,
        "regime_context": "bullish",
        "supporting_factors": ["strong_trend_regime"],
        "was_selected": True,
        "num_signals_bar": 2,
        "num_agreeing": 2,
        "num_conflicting": 0,
        "resolution_method": "priority",
        "composite_rank": 1,
        "market_context": {"trend_regime": 0.8, "vol_regime": 1.0},
        "status": "pending",
    }
    defaults.update(overrides)
    return LedgerEntry(**defaults)


class TestLedgerEntry:
    @pytest.mark.unit
    def test_create_entry(self):
        """LedgerEntry dataclass holds all signal fields."""
        entry = _make_entry()
        assert entry.symbol == "ES"
        assert entry.direction == 1
        assert entry.was_selected is True
        assert entry.status == "pending"

    @pytest.mark.unit
    def test_to_insert_params(self):
        """to_insert_params returns a tuple matching the INSERT column order."""
        entry = _make_entry()
        params = entry.to_insert_params()
        assert isinstance(params, tuple)
        # signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type,
        # direction, entry_price, stop_loss, targets_json, confidence, confluence_score,
        # regime_context, supporting_factors_json, was_selected, num_signals_bar,
        # num_agreeing, num_conflicting, resolution_method, composite_rank,
        # market_context_json, status
        assert len(params) == 22
        assert params[2] == "ES"  # symbol


class TestInsertSignals:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_insert_single_signal(self):
        """insert_signals writes one entry to the database."""
        db = AsyncMock()
        entry = _make_entry()
        await insert_signals(db, [entry])
        db.execute_batch.assert_called_once()
        args = db.execute_batch.call_args
        assert "INSERT INTO signal_ledger" in args[0][0]
        assert len(args[0][1]) == 1  # one row

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_insert_multiple_signals(self):
        """insert_signals writes multiple entries in one batch."""
        db = AsyncMock()
        entries = [_make_entry(signal_id=str(uuid.uuid4())) for _ in range(3)]
        await insert_signals(db, entries)
        args = db.execute_batch.call_args
        assert len(args[0][1]) == 3

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_insert_empty_list_is_noop(self):
        """insert_signals with empty list does not call database."""
        db = AsyncMock()
        await insert_signals(db, [])
        db.execute_batch.assert_not_called()


class TestUpdateSignalStatus:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_update_status_to_active(self):
        """update_signal_status issues UPDATE with correct params."""
        db = AsyncMock()
        sid = str(uuid.uuid4())
        await update_signal_status(
            db, sid, status="active",
            activated_at=datetime(2026, 2, 17, 14, 35, tzinfo=timezone.utc),
        )
        db.execute_command.assert_called_once()
        sql = db.execute_command.call_args[0][0]
        assert "UPDATE signal_ledger" in sql
        assert "status" in sql

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_update_status_with_exit(self):
        """update_signal_status fills exit fields on terminal state."""
        db = AsyncMock()
        sid = str(uuid.uuid4())
        await update_signal_status(
            db, sid, status="stopped_out",
            exit_at=datetime(2026, 2, 17, 15, 0, tzinfo=timezone.utc),
            exit_price=5085.0, exit_reason="stop_loss",
            pnl_ticks=-15.0, pnl_r=-1.0, pnl_dollars=-750.0,
        )
        sql = db.execute_command.call_args[0][0]
        assert "exit_price" in sql
        assert "pnl_r" in sql


class TestGetActiveSignals:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_returns_entries(self):
        """get_active_signals queries pending and active signals."""
        mock_row = {
            "signal_id": str(uuid.uuid4()),
            "timestamp": datetime(2026, 2, 17, 14, 30, tzinfo=timezone.utc),
            "symbol": "ES", "timeframe": "5m",
            "setup_plugin": "trad_TrendFollowing", "signal_type": "trend_long",
            "direction": 1, "entry_price": 5100.0, "stop_loss": 5085.0,
            "targets": "[5110.0]", "confidence": 0.75, "confluence_score": 0.6,
            "regime_context": "bullish", "supporting_factors": "[]",
            "was_selected": True, "num_signals_bar": 1, "num_agreeing": 1,
            "num_conflicting": 0, "resolution_method": "sole",
            "composite_rank": 1, "market_context": "{}",
            "status": "pending",
            "activated_at": None, "exit_at": None, "exit_price": None,
            "exit_reason": None, "pnl_ticks": None, "pnl_r": None, "pnl_dollars": None,
        }
        db = AsyncMock()
        db.execute_query.return_value = [mock_row]
        results = await get_active_signals(db, symbol="ES")
        assert len(results) == 1
        assert results[0]["symbol"] == "ES"
        assert results[0]["status"] == "pending"
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/unit/intelligence/test_signal_ledger.py -v`
Expected: FAIL — `signal_ledger` module not found

**Step 3: Write minimal implementation**

Create `src/intelligence/trading/signal_ledger.py`:

```python
"""Signal ledger repository — data access for signal_ledger hypertable.

Provides functions to insert, update, and query signal lifecycle records.
All functions accept a DatabaseManager instance for testability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class LedgerEntry:
    """One row in the signal_ledger table."""

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

    def to_insert_params(self) -> tuple:
        """Return a tuple matching the INSERT column order."""
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
        )


_INSERT_SQL = """
    INSERT INTO signal_ledger (
        signal_id, timestamp, symbol, timeframe,
        setup_plugin, signal_type, direction,
        entry_price, stop_loss, targets,
        confidence, confluence_score, regime_context, supporting_factors,
        was_selected, num_signals_bar, num_agreeing, num_conflicting,
        resolution_method, composite_rank, market_context, status
    ) VALUES (
        $1::uuid, $2, $3, $4,
        $5, $6, $7,
        $8, $9, $10::jsonb,
        $11, $12, $13, $14::jsonb,
        $15, $16, $17, $18,
        $19, $20, $21::jsonb, $22
    )
"""


async def insert_signals(db_manager, entries: list[LedgerEntry]) -> None:
    """Batch-insert signal ledger entries."""
    if not entries:
        return
    params = [e.to_insert_params() for e in entries]
    await db_manager.execute_batch(_INSERT_SQL, params)
    logger.info("Inserted signal ledger entries", count=len(entries))


async def update_signal_status(
    db_manager,
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
) -> None:
    """Update a signal's lifecycle status and optional exit fields."""
    sql = """
        UPDATE signal_ledger SET
            status = $2, activated_at = $3,
            exit_at = $4, exit_price = $5, exit_reason = $6,
            pnl_ticks = $7, pnl_r = $8, pnl_dollars = $9,
            updated_at = NOW()
        WHERE signal_id = $1::uuid
    """
    await db_manager.execute_command(
        sql, signal_id, status, activated_at,
        exit_at, exit_price, exit_reason,
        pnl_ticks, pnl_r, pnl_dollars,
    )
    logger.info("Updated signal status", signal_id=signal_id, status=status)


async def get_active_signals(
    db_manager, symbol: str | None = None
) -> list[dict[str, Any]]:
    """Query signals in pending or active status."""
    if symbol:
        sql = """
            SELECT * FROM signal_ledger
            WHERE status IN ('pending', 'active') AND symbol = $1
            ORDER BY timestamp DESC
        """
        return await db_manager.execute_query(sql, symbol)
    sql = """
        SELECT * FROM signal_ledger
        WHERE status IN ('pending', 'active')
        ORDER BY timestamp DESC
    """
    return await db_manager.execute_query(sql)
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/unit/intelligence/test_signal_ledger.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/signal_ledger.py tests/unit/intelligence/test_signal_ledger.py
git commit -m "feat(i7.5): add signal ledger repository with lifecycle operations"
```

---

## Task 3: Signal Aggregator (Rules-Based)

**Files:**
- Create: `src/intelligence/trading/aggregator.py`
- Create: `tests/unit/intelligence/test_aggregator.py`

This is the core conflict resolution engine. It takes a list of raw signal dicts (from plugins) and returns the winning signal plus aggregation metadata.

**Step 1: Write the failing tests**

Create `tests/unit/intelligence/test_aggregator.py`:

```python
"""Tests for rules-based signal aggregator."""

import pytest

from src.intelligence.trading.aggregator import (
    SETUP_PRIORITY,
    AggregatedResult,
    aggregate,
)


def _signal(plugin: str, direction: int, confidence: float = 0.7,
            confluence: float = 0.5, signal_type: str = "test") -> dict:
    """Build a minimal signal dict for aggregation testing."""
    return {
        "type": "signal.v1",
        "symbol": "ES",
        "timeframe": "5m",
        "timestamp": "2026-02-17T14:30:00Z",
        "signal_type": signal_type,
        "setup_plugin": plugin,
        "direction": direction,
        "entry_price": 5100.0,
        "stop_loss": 5085.0 if direction == 1 else 5115.0,
        "targets": [5115.0] if direction == 1 else [5085.0],
        "confidence": confidence,
        "risk_reward_ratio": 1.0,
        "regime_context": "bullish" if direction == 1 else "bearish",
        "confluence_score": confluence,
        "supporting_factors": ["test_factor"],
        "invalidation_conditions": [],
        "ttl_bars": 10,
    }


class TestAggregateNoSignals:
    @pytest.mark.unit
    def test_empty_list_returns_no_signal(self):
        """No signals → no_signal result."""
        result = aggregate([], trend_regime=0.5)
        assert result.selected_signal is None
        assert result.resolution_method == "no_signal"

    @pytest.mark.unit
    def test_all_none_signals_filtered(self):
        """Signals with signal_type='none' or direction=0 are filtered out."""
        none_sig = _signal("trad_TrendFollowing", 0, signal_type="none")
        result = aggregate([none_sig], trend_regime=0.5)
        assert result.selected_signal is None


class TestAggregateSoleSignal:
    @pytest.mark.unit
    def test_single_signal_selected(self):
        """One signal → selected as sole winner."""
        sig = _signal("trad_TrendFollowing", 1, confidence=0.8)
        result = aggregate([sig], trend_regime=0.6)
        assert result.selected_signal is not None
        assert result.selected_signal["setup_plugin"] == "trad_TrendFollowing"
        assert result.resolution_method == "sole"
        assert result.num_signals_fired == 1
        assert result.num_agreeing == 1
        assert result.num_conflicting == 0


class TestAggregateSameDirection:
    @pytest.mark.unit
    def test_priority_wins_among_same_direction(self):
        """Multiple longs → highest priority setup wins."""
        trend = _signal("trad_TrendFollowing", 1, confidence=0.9)
        mean_rev = _signal("trad_MeanReversion", 1, confidence=0.95)
        # TrendFollowing has higher priority than MeanReversion
        result = aggregate([trend, mean_rev], trend_regime=0.6)
        assert result.selected_signal["setup_plugin"] == "trad_TrendFollowing"
        assert result.resolution_method == "priority"
        assert result.num_agreeing == 2

    @pytest.mark.unit
    def test_liq_sweep_wins_over_all(self):
        """LiquiditySweepReclaim has highest priority."""
        liq = _signal("trad_LiquiditySweepReclaim", 1, confidence=0.6)
        mtf = _signal("trad_MTFAlignment", 1, confidence=0.9)
        result = aggregate([liq, mtf], trend_regime=0.6)
        assert result.selected_signal["setup_plugin"] == "trad_LiquiditySweepReclaim"

    @pytest.mark.unit
    def test_confidence_boosted_by_agreement(self):
        """Winner confidence boosted by +0.05 per agreeing signal."""
        trend = _signal("trad_TrendFollowing", 1, confidence=0.7)
        squeeze = _signal("trad_SqueezeExpansion", 1, confidence=0.6)
        result = aggregate([trend, squeeze], trend_regime=0.6)
        # Original 0.7 + 0.05 * 1 extra agreeing = 0.75
        assert result.selected_signal["confidence"] == pytest.approx(0.75, abs=0.001)

    @pytest.mark.unit
    def test_supporting_factors_merged(self):
        """Supporting factors from all agreeing signals are merged."""
        s1 = _signal("trad_TrendFollowing", 1)
        s1["supporting_factors"] = ["strong_trend"]
        s2 = _signal("trad_SqueezeExpansion", 1)
        s2["supporting_factors"] = ["volume_expansion"]
        result = aggregate([s1, s2], trend_regime=0.6)
        factors = result.selected_signal["supporting_factors"]
        assert "strong_trend" in factors
        assert "volume_expansion" in factors


class TestAggregateMixedDirections:
    @pytest.mark.unit
    def test_majority_wins(self):
        """2 longs vs 1 short → long side wins."""
        l1 = _signal("trad_TrendFollowing", 1)
        l2 = _signal("trad_MTFAlignment", 1)
        s1 = _signal("trad_MeanReversion", -1)
        result = aggregate([l1, l2, s1], trend_regime=0.6)
        assert result.selected_signal["direction"] == 1
        assert result.resolution_method == "majority"
        assert result.num_conflicting == 1

    @pytest.mark.unit
    def test_tied_uses_regime_tiebreak_bullish(self):
        """1 long vs 1 short with bullish regime → long wins."""
        l1 = _signal("trad_TrendFollowing", 1)
        s1 = _signal("trad_MeanReversion", -1)
        result = aggregate([l1, s1], trend_regime=0.6)
        assert result.selected_signal["direction"] == 1
        assert result.resolution_method == "regime_tiebreak"

    @pytest.mark.unit
    def test_tied_uses_regime_tiebreak_bearish(self):
        """1 long vs 1 short with bearish regime → short wins."""
        l1 = _signal("trad_TrendFollowing", 1)
        s1 = _signal("trad_MeanReversion", -1)
        result = aggregate([l1, s1], trend_regime=-0.6)
        assert result.selected_signal["direction"] == -1
        assert result.resolution_method == "regime_tiebreak"

    @pytest.mark.unit
    def test_tied_ranging_emits_no_signal(self):
        """1 long vs 1 short with ranging regime → no signal."""
        l1 = _signal("trad_TrendFollowing", 1)
        s1 = _signal("trad_MeanReversion", -1)
        result = aggregate([l1, s1], trend_regime=0.1)
        assert result.selected_signal is None
        assert result.resolution_method == "no_signal"


class TestAggregatedResultMetadata:
    @pytest.mark.unit
    def test_all_ranked_signals_returned(self):
        """all_ranked contains every signal with a composite_rank."""
        s1 = _signal("trad_TrendFollowing", 1)
        s2 = _signal("trad_SqueezeExpansion", 1)
        result = aggregate([s1, s2], trend_regime=0.6)
        assert len(result.all_ranked) == 2
        assert result.all_ranked[0]["composite_rank"] == 1
        assert result.all_ranked[1]["composite_rank"] == 2


class TestSetupPriority:
    @pytest.mark.unit
    def test_priority_order(self):
        """Priority order matches design: LiqSweep > MTF > Trend > Squeeze > MeanRev."""
        names = sorted(SETUP_PRIORITY, key=lambda k: SETUP_PRIORITY[k])
        assert names == [
            "trad_MeanReversion",
            "trad_SqueezeExpansion",
            "trad_TrendFollowing",
            "trad_MTFAlignment",
            "trad_LiquiditySweepReclaim",
        ]
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/unit/intelligence/test_aggregator.py -v`
Expected: FAIL — `aggregator` module not found

**Step 3: Write minimal implementation**

Create `src/intelligence/trading/aggregator.py`:

```python
"""Rules-based signal aggregator.

Takes raw signals from I7 setup plugins and resolves conflicts using
priority-based rules. Designed to be replaced by a calibrated scoring
model once sufficient outcome data is collected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Setup priority: higher number = higher priority.
# This ordering is a hypothesis — will be validated from outcome data.
SETUP_PRIORITY: dict[str, int] = {
    "trad_MeanReversion": 1,
    "trad_SqueezeExpansion": 2,
    "trad_TrendFollowing": 3,
    "trad_MTFAlignment": 4,
    "trad_LiquiditySweepReclaim": 5,
}

_CONFIDENCE_BOOST_PER_AGREE = 0.05
_REGIME_TIEBREAK_THRESHOLD = 0.4


@dataclass
class AggregatedResult:
    """Output of the aggregation process."""

    selected_signal: dict[str, Any] | None
    all_ranked: list[dict[str, Any]]
    resolution_method: str  # "sole" | "priority" | "majority" | "regime_tiebreak" | "no_signal"
    num_signals_fired: int = 0
    num_agreeing: int = 0
    num_conflicting: int = 0


def aggregate(
    signals: list[dict[str, Any]],
    *,
    trend_regime: float = 0.0,
) -> AggregatedResult:
    """Resolve multiple raw signals into a single recommended action.

    Args:
        signals: List of signal.v1 dicts from setup plugins.
        trend_regime: Current trend regime value for tiebreaking (-1 to +1).

    Returns:
        AggregatedResult with the winning signal and metadata.
    """
    # Filter out non-signals (direction=0 or signal_type="none")
    active = [
        s for s in signals
        if s.get("direction") in (1, -1, 1.0, -1.0) and s.get("signal_type", "none") != "none"
    ]

    if not active:
        return AggregatedResult(
            selected_signal=None, all_ranked=[], resolution_method="no_signal",
        )

    # Group by direction
    longs = [s for s in active if s["direction"] in (1, 1.0)]
    shorts = [s for s in active if s["direction"] in (-1, -1.0)]

    # Sort each group by priority (descending)
    longs.sort(key=lambda s: SETUP_PRIORITY.get(s.get("setup_plugin", ""), 0), reverse=True)
    shorts.sort(key=lambda s: SETUP_PRIORITY.get(s.get("setup_plugin", ""), 0), reverse=True)

    winner: dict[str, Any] | None = None
    method: str = "no_signal"

    if longs and not shorts:
        # Case A: only longs
        winner = _pick_with_method(longs, active)
        method = "sole" if len(longs) == 1 else "priority"
    elif shorts and not longs:
        # Case A: only shorts
        winner = _pick_with_method(shorts, active)
        method = "sole" if len(shorts) == 1 else "priority"
    else:
        # Case B: mixed directions
        if len(longs) > len(shorts):
            winner = longs[0]
            method = "majority"
        elif len(shorts) > len(longs):
            winner = shorts[0]
            method = "majority"
        else:
            # Tied — regime tiebreak
            if trend_regime > _REGIME_TIEBREAK_THRESHOLD:
                winner = longs[0]
                method = "regime_tiebreak"
            elif trend_regime < -_REGIME_TIEBREAK_THRESHOLD:
                winner = shorts[0]
                method = "regime_tiebreak"
            else:
                # Genuinely conflicting in ranging market
                winner = None
                method = "no_signal"

    # Build ranked list (all active signals sorted by priority)
    all_sorted = sorted(
        active,
        key=lambda s: SETUP_PRIORITY.get(s.get("setup_plugin", ""), 0),
        reverse=True,
    )
    for rank, sig in enumerate(all_sorted, 1):
        sig["composite_rank"] = rank

    # Enrich winner
    num_agreeing = 0
    num_conflicting = 0
    if winner:
        winner_dir = winner["direction"]
        same_dir = [s for s in active if s["direction"] == winner_dir]
        opp_dir = [s for s in active if s["direction"] != winner_dir]
        num_agreeing = len(same_dir)
        num_conflicting = len(opp_dir)

        # Boost confidence from agreement (extra signals beyond winner)
        extra_agree = num_agreeing - 1
        if extra_agree > 0:
            boosted = min(1.0, winner["confidence"] + _CONFIDENCE_BOOST_PER_AGREE * extra_agree)
            winner = {**winner, "confidence": round(boosted, 4)}

        # Merge supporting factors from agreeing signals
        all_factors = []
        seen = set()
        for s in same_dir:
            for f in s.get("supporting_factors", []):
                if f not in seen:
                    all_factors.append(f)
                    seen.add(f)
        winner = {**winner, "supporting_factors": all_factors}

    return AggregatedResult(
        selected_signal=winner,
        all_ranked=all_sorted,
        resolution_method=method,
        num_signals_fired=len(active),
        num_agreeing=num_agreeing,
        num_conflicting=num_conflicting,
    )


def _pick_with_method(
    sorted_group: list[dict[str, Any]],
    all_active: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pick highest-priority signal from a single-direction group."""
    return sorted_group[0]
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/unit/intelligence/test_aggregator.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/aggregator.py tests/unit/intelligence/test_aggregator.py
git commit -m "feat(i7.5): add rules-based signal aggregator with conflict resolution"
```

---

## Task 4: Position Sizing Calculator

**Files:**
- Create: `src/intelligence/trading/position_sizer.py`
- Create: `tests/unit/intelligence/test_position_sizer.py`

**Step 1: Write the failing tests**

Create `tests/unit/intelligence/test_position_sizer.py`:

```python
"""Tests for position sizing calculator."""

import pytest

from src.intelligence.trading.position_sizer import (
    calculate_position_size,
    PositionSize,
)


class TestCalculatePositionSize:
    @pytest.mark.unit
    def test_basic_long_position(self):
        """Standard long: risk / (entry - stop) / point_value."""
        result = calculate_position_size(
            entry_price=5100.0,
            stop_loss=5085.0,
            direction=1,
            point_value=50.0,     # ES: $50 per point
            risk_amount=1000.0,   # Risk $1000
        )
        # Risk per contract = (5100 - 5085) * 50 = $750
        # Contracts = 1000 / 750 = 1.33 → floor to 1
        assert result.contracts == 1
        assert result.risk_per_contract == pytest.approx(750.0)
        assert result.total_risk == pytest.approx(750.0)

    @pytest.mark.unit
    def test_basic_short_position(self):
        """Standard short: risk / (stop - entry) / point_value."""
        result = calculate_position_size(
            entry_price=5100.0,
            stop_loss=5115.0,
            direction=-1,
            point_value=50.0,
            risk_amount=1000.0,
        )
        assert result.contracts == 1
        assert result.risk_per_contract == pytest.approx(750.0)

    @pytest.mark.unit
    def test_max_contracts_cap(self):
        """Position size capped at max_contracts."""
        result = calculate_position_size(
            entry_price=5100.0,
            stop_loss=5099.0,     # Tight stop = 1 point = $50 risk
            direction=1,
            point_value=50.0,
            risk_amount=10000.0,  # Would be 200 contracts without cap
            max_contracts=10,
        )
        assert result.contracts == 10
        assert result.capped is True

    @pytest.mark.unit
    def test_zero_risk_returns_zero(self):
        """Entry == stop (zero risk) → 0 contracts."""
        result = calculate_position_size(
            entry_price=5100.0,
            stop_loss=5100.0,
            direction=1,
            point_value=50.0,
            risk_amount=1000.0,
        )
        assert result.contracts == 0

    @pytest.mark.unit
    def test_minimum_one_contract_when_affordable(self):
        """Small risk_amount still gets at least 1 contract if affordable."""
        result = calculate_position_size(
            entry_price=5100.0,
            stop_loss=5085.0,
            direction=1,
            point_value=50.0,
            risk_amount=800.0,   # Just above $750 risk per contract
        )
        assert result.contracts == 1

    @pytest.mark.unit
    def test_insufficient_risk_returns_zero(self):
        """Risk amount less than 1 contract's risk → 0 contracts."""
        result = calculate_position_size(
            entry_price=5100.0,
            stop_loss=5085.0,
            direction=1,
            point_value=50.0,
            risk_amount=100.0,   # Way below $750 per contract
        )
        assert result.contracts == 0

    @pytest.mark.unit
    def test_gold_futures_sizing(self):
        """GC: point_value=100, tick_size=0.10."""
        result = calculate_position_size(
            entry_price=2050.0,
            stop_loss=2040.0,
            direction=1,
            point_value=100.0,   # GC: $100 per point
            risk_amount=2000.0,
        )
        # Risk per contract = (2050 - 2040) * 100 = $1000
        # Contracts = 2000 / 1000 = 2
        assert result.contracts == 2
        assert result.risk_per_contract == pytest.approx(1000.0)
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/unit/intelligence/test_position_sizer.py -v`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

Create `src/intelligence/trading/position_sizer.py`:

```python
"""Position sizing calculator.

Risk-based position sizing: determines how many contracts to trade
given account risk tolerance and signal stop distance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PositionSize:
    """Result of a position sizing calculation."""

    contracts: int
    risk_per_contract: float
    total_risk: float
    capped: bool = False


def calculate_position_size(
    *,
    entry_price: float,
    stop_loss: float,
    direction: int,
    point_value: float,
    risk_amount: float,
    max_contracts: int = 100,
) -> PositionSize:
    """Calculate position size from risk parameters.

    Args:
        entry_price: Planned entry price.
        stop_loss: Stop loss price.
        direction: +1 for long, -1 for short.
        point_value: Dollar value per point (e.g. 50.0 for ES).
        risk_amount: Maximum dollar risk for this trade.
        max_contracts: Hard cap on number of contracts.

    Returns:
        PositionSize with contract count and risk details.
    """
    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0 or point_value <= 0:
        return PositionSize(contracts=0, risk_per_contract=0.0, total_risk=0.0)

    risk_per_contract = stop_distance * point_value
    if risk_per_contract <= 0:
        return PositionSize(contracts=0, risk_per_contract=0.0, total_risk=0.0)

    raw_contracts = risk_amount / risk_per_contract
    contracts = math.floor(raw_contracts)
    contracts = max(0, contracts)

    capped = False
    if contracts > max_contracts:
        contracts = max_contracts
        capped = True

    total_risk = contracts * risk_per_contract

    return PositionSize(
        contracts=contracts,
        risk_per_contract=round(risk_per_contract, 2),
        total_risk=round(total_risk, 2),
        capped=capped,
    )
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/unit/intelligence/test_position_sizer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/position_sizer.py tests/unit/intelligence/test_position_sizer.py
git commit -m "feat(i7.5): add risk-based position sizing calculator"
```

---

## Task 5: Lifecycle Tracker

**Files:**
- Create: `src/intelligence/trading/lifecycle_tracker.py`
- Create: `tests/unit/intelligence/test_lifecycle_tracker.py`

The lifecycle tracker evaluates whether a signal has been activated, stopped out, or hit a target based on current price data. It does NOT directly update the database — it returns state transitions that the caller persists. This keeps it pure and testable.

**Step 1: Write the failing tests**

Create `tests/unit/intelligence/test_lifecycle_tracker.py`:

```python
"""Tests for signal lifecycle tracker."""

import pytest

from src.intelligence.trading.lifecycle_tracker import (
    evaluate_signal,
    Transition,
)


def _pending_signal(direction=1, entry=5100.0, stop=5085.0,
                    targets=None) -> dict:
    """Build a pending signal dict for lifecycle testing."""
    return {
        "signal_id": "test-id",
        "status": "pending",
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "targets": targets or [5115.0, 5130.0, 5145.0],
        "ttl_bars": 10,
        "bars_elapsed": 0,
        "point_value": 50.0,
    }


def _active_signal(direction=1, entry=5100.0, stop=5085.0,
                   targets=None) -> dict:
    sig = _pending_signal(direction, entry, stop, targets)
    sig["status"] = "active"
    return sig


class TestPendingToActive:
    @pytest.mark.unit
    def test_price_crosses_entry_long(self):
        """Long signal: high >= entry_price → activate."""
        sig = _pending_signal(direction=1, entry=5100.0)
        t = evaluate_signal(sig, high=5101.0, low=5095.0, close=5100.5)
        assert t is not None
        assert t.new_status == "active"
        assert t.exit_reason is None

    @pytest.mark.unit
    def test_price_below_entry_long_stays_pending(self):
        """Long signal: high < entry_price → stays pending."""
        sig = _pending_signal(direction=1, entry=5100.0)
        t = evaluate_signal(sig, high=5098.0, low=5090.0, close=5095.0)
        assert t is None

    @pytest.mark.unit
    def test_price_crosses_entry_short(self):
        """Short signal: low <= entry_price → activate."""
        sig = _pending_signal(direction=-1, entry=5100.0, stop=5115.0,
                              targets=[5085.0, 5070.0])
        t = evaluate_signal(sig, high=5105.0, low=5099.0, close=5100.0)
        assert t is not None
        assert t.new_status == "active"


class TestActiveToExit:
    @pytest.mark.unit
    def test_stop_loss_hit_long(self):
        """Long active: low <= stop_loss → stopped_out."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0)
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5086.0)
        assert t.new_status == "stopped_out"
        assert t.exit_reason == "stop_loss"
        assert t.exit_price == 5085.0  # Assume filled at stop level

    @pytest.mark.unit
    def test_stop_loss_hit_short(self):
        """Short active: high >= stop_loss → stopped_out."""
        sig = _active_signal(direction=-1, entry=5100.0, stop=5115.0,
                             targets=[5085.0])
        t = evaluate_signal(sig, high=5116.0, low=5105.0, close=5114.0)
        assert t.new_status == "stopped_out"
        assert t.exit_reason == "stop_loss"
        assert t.exit_price == 5115.0

    @pytest.mark.unit
    def test_target_1_hit_long(self):
        """Long active: high >= target[0] → target_1_hit."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0, 5145.0])
        t = evaluate_signal(sig, high=5116.0, low=5105.0, close=5114.0)
        assert t.new_status == "target_1_hit"
        assert t.exit_reason == "target_1"
        assert t.exit_price == 5115.0

    @pytest.mark.unit
    def test_target_2_hit_long(self):
        """Long active: high >= target[1] → target_2_hit."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0, 5145.0])
        t = evaluate_signal(sig, high=5131.0, low=5120.0, close=5129.0)
        assert t.new_status == "target_2_hit"
        assert t.exit_reason == "target_2"

    @pytest.mark.unit
    def test_target_hit_short(self):
        """Short active: low <= target[0] → target_1_hit."""
        sig = _active_signal(direction=-1, entry=5100.0, stop=5115.0,
                             targets=[5085.0, 5070.0])
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5086.0)
        assert t.new_status == "target_1_hit"
        assert t.exit_reason == "target_1"
        assert t.exit_price == 5085.0

    @pytest.mark.unit
    def test_stop_checked_before_target(self):
        """If both stop and target hit on same bar, stop takes priority."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0])
        # Bar that hits both stop and target (wide range)
        t = evaluate_signal(sig, high=5116.0, low=5084.0, close=5090.0)
        assert t.new_status == "stopped_out"
        assert t.exit_reason == "stop_loss"


class TestTTLExpiry:
    @pytest.mark.unit
    def test_pending_expires_after_ttl(self):
        """Pending signal past ttl_bars → expired."""
        sig = _pending_signal()
        sig["bars_elapsed"] = 11  # > ttl_bars (10)
        t = evaluate_signal(sig, high=5095.0, low=5090.0, close=5092.0)
        assert t.new_status == "expired"
        assert t.exit_reason == "ttl_expired"

    @pytest.mark.unit
    def test_active_expires_after_ttl(self):
        """Active signal past ttl_bars → expired."""
        sig = _active_signal()
        sig["bars_elapsed"] = 11
        t = evaluate_signal(sig, high=5098.0, low=5095.0, close=5097.0)
        assert t.new_status == "expired"
        assert t.exit_reason == "ttl_expired"


class TestPnLCalculation:
    @pytest.mark.unit
    def test_pnl_on_stop_long(self):
        """PnL calculated correctly for stopped long."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0)
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5086.0)
        assert t.pnl_ticks == pytest.approx(-15.0)
        assert t.pnl_r == pytest.approx(-1.0)
        assert t.pnl_dollars == pytest.approx(-750.0)  # -15 * 50

    @pytest.mark.unit
    def test_pnl_on_target_long(self):
        """PnL calculated correctly for target hit long."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0])
        t = evaluate_signal(sig, high=5116.0, low=5105.0, close=5114.0)
        assert t.pnl_ticks == pytest.approx(15.0)
        assert t.pnl_r == pytest.approx(1.0)
        assert t.pnl_dollars == pytest.approx(750.0)

    @pytest.mark.unit
    def test_pnl_on_expired_uses_close(self):
        """Expired signal uses close as exit price."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0)
        sig["bars_elapsed"] = 11
        t = evaluate_signal(sig, high=5108.0, low=5095.0, close=5105.0)
        assert t.exit_price == 5105.0
        assert t.pnl_ticks == pytest.approx(5.0)
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/unit/intelligence/test_lifecycle_tracker.py -v`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

Create `src/intelligence/trading/lifecycle_tracker.py`:

```python
"""Signal lifecycle tracker.

Evaluates signal state transitions based on price data. Pure functions —
does not touch the database. Returns Transition objects that the caller
persists via signal_ledger.update_signal_status().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Transition:
    """A state change for a signal."""

    signal_id: str
    new_status: str
    exit_reason: str | None = None
    exit_price: float | None = None
    pnl_ticks: float | None = None
    pnl_r: float | None = None
    pnl_dollars: float | None = None


def evaluate_signal(
    signal: dict[str, Any],
    *,
    high: float,
    low: float,
    close: float,
) -> Transition | None:
    """Evaluate whether a signal should transition state.

    Args:
        signal: Dict with signal fields (status, direction, entry_price,
                stop_loss, targets, ttl_bars, bars_elapsed, point_value).
        high: Current bar's high price.
        low: Current bar's low price.
        close: Current bar's close price.

    Returns:
        Transition if state changes, None if signal stays in current state.
    """
    sid = signal["signal_id"]
    status = signal["status"]
    direction = signal["direction"]
    entry = signal["entry_price"]
    stop = signal["stop_loss"]
    targets = signal.get("targets") or []
    ttl = signal.get("ttl_bars", 10)
    bars = signal.get("bars_elapsed", 0)
    point_value = signal.get("point_value", 1.0)
    risk = abs(entry - stop)

    # TTL check first (applies to both pending and active)
    if bars > ttl:
        exit_price = close
        return _make_exit(sid, "expired", "ttl_expired", exit_price,
                          entry, direction, risk, point_value)

    if status == "pending":
        return _check_pending_activation(sid, direction, entry, high, low)

    if status == "active":
        return _check_active_exit(sid, direction, entry, stop, targets,
                                  high, low, close, risk, point_value)

    return None


def _check_pending_activation(
    sid: str, direction: int, entry: float,
    high: float, low: float,
) -> Transition | None:
    """Check if a pending signal should activate."""
    if direction == 1 and high >= entry:
        return Transition(signal_id=sid, new_status="active")
    if direction == -1 and low <= entry:
        return Transition(signal_id=sid, new_status="active")
    return None


def _check_active_exit(
    sid: str, direction: int, entry: float, stop: float,
    targets: list[float], high: float, low: float, close: float,
    risk: float, point_value: float,
) -> Transition | None:
    """Check if an active signal should exit (stop, target, or expire)."""
    # Stop loss check first (conservative: stop before target on same bar)
    if direction == 1 and low <= stop:
        return _make_exit(sid, "stopped_out", "stop_loss", stop,
                          entry, direction, risk, point_value)
    if direction == -1 and high >= stop:
        return _make_exit(sid, "stopped_out", "stop_loss", stop,
                          entry, direction, risk, point_value)

    # Target checks (highest target first for maximum credit)
    for i in range(len(targets) - 1, -1, -1):
        target = targets[i]
        hit = (direction == 1 and high >= target) or \
              (direction == -1 and low <= target)
        if hit:
            label = f"target_{i + 1}"
            return _make_exit(sid, f"target_{i + 1}_hit", label, target,
                              entry, direction, risk, point_value)

    return None


def _make_exit(
    sid: str, status: str, reason: str, exit_price: float,
    entry: float, direction: int, risk: float, point_value: float,
) -> Transition:
    """Build an exit Transition with P&L calculations."""
    pnl_ticks = (exit_price - entry) * direction
    pnl_r = pnl_ticks / risk if risk > 0 else 0.0
    pnl_dollars = pnl_ticks * point_value
    return Transition(
        signal_id=sid,
        new_status=status,
        exit_reason=reason,
        exit_price=exit_price,
        pnl_ticks=round(pnl_ticks, 4),
        pnl_r=round(pnl_r, 4),
        pnl_dollars=round(pnl_dollars, 2),
    )
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/unit/intelligence/test_lifecycle_tracker.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/lifecycle_tracker.py tests/unit/intelligence/test_lifecycle_tracker.py
git commit -m "feat(i7.5): add signal lifecycle tracker with P&L calculations"
```

---

## Task 6: Wire Aggregator Into SSE + Stream Key

**Files:**
- Modify: `src/core/stream_keys.py`
- Create: `tests/unit/core/test_stream_keys_aggregated.py`

Add a stream key helper for the aggregated signal stream.

**Step 1: Write the failing test**

Create `tests/unit/core/test_stream_keys_aggregated.py`:

```python
"""Tests for aggregated signal stream key."""

from src.core.stream_keys import signals_aggregated, get_stream_maxlen


def test_signals_aggregated_with_prefix():
    assert signals_aggregated("dev:", "ES", "5m") == "dev:signals:ES:5m:aggregated"


def test_signals_aggregated_no_prefix():
    assert signals_aggregated("", "NQ", "1h") == "signals:NQ:1h:aggregated"


def test_aggregated_maxlen():
    assert get_stream_maxlen("1m", "signals_aggregated") == 200
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/core/test_stream_keys_aggregated.py -v`
Expected: FAIL — `signals_aggregated` not importable

**Step 3: Add to stream_keys.py**

Add to `src/core/stream_keys.py`:

```python
def signals_aggregated(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}signals:{symbol}:{timeframe}:aggregated"
```

And update `get_stream_maxlen` to handle `"signals_aggregated"`:

```python
def get_stream_maxlen(
    timeframe: str,
    kind: Literal["ticks", "market", "indicators", "intelligence", "signals", "signals_aggregated"],
) -> int:
    # ... existing cases ...
    if kind == "signals_aggregated":
        return 200
    return 1000
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/unit/core/test_stream_keys_aggregated.py -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add src/core/stream_keys.py tests/unit/core/test_stream_keys_aggregated.py
git commit -m "feat(i7.5): add aggregated signal stream key helper"
```

---

## Task 7: Full Test Suite + Lint + CLAUDE.md Update

**Step 1: Run linter on all new files**

```bash
source .venv/bin/activate && ruff check src/intelligence/trading/signal_ledger.py src/intelligence/trading/aggregator.py src/intelligence/trading/position_sizer.py src/intelligence/trading/lifecycle_tracker.py tests/unit/intelligence/test_signal_ledger.py tests/unit/intelligence/test_aggregator.py tests/unit/intelligence/test_position_sizer.py tests/unit/intelligence/test_lifecycle_tracker.py --fix
```

Expected: All checks passed (or auto-fixed)

**Step 2: Run full unit test suite**

```bash
source .venv/bin/activate && python -m pytest tests/unit/ -v
```

Expected: All tests PASS (213 existing + ~40 new = ~253 total)

**Step 3: Update CLAUDE.md**

Update the following sections:
- Version: `4.1.0` → `4.2.0`
- Status line: Update test count
- Plugin System section: Add "I7 Signal Aggregation (4 components)" subsection
- Development Status: Update I7 entry to include Phase 1.5
- Completed Phases: Add `I7-P1.5` entry

**Step 4: Commit**

```bash
git add CLAUDE.md src/ tests/ production/
git commit -m "feat(i7.5): Phase 1.5 complete — signal aggregation, lifecycle tracking, position sizing"
```

---

## Summary

| Task | What | Tests | Files |
|------|------|-------|-------|
| 1 | Signal ledger DB schema | 0 (SQL) | 2 |
| 2 | Signal ledger repository | 7 | 2 |
| 3 | Rules-based aggregator | 12 | 2 |
| 4 | Position sizing calculator | 7 | 2 |
| 5 | Lifecycle tracker | 13 | 2 |
| 6 | Aggregated stream key | 3 | 2 |
| 7 | Lint + full suite + CLAUDE.md | 0 | 1 |
| **Total** | **7 tasks** | **~42 tests** | **13 files** |

**After this plan is complete:**
- Signal aggregation system fully operational
- Signal ledger collecting data for future ML calibration
- Lifecycle tracking for entry/exit/P&L measurement
- Position sizing calculator for risk management
- All signals persisted with full context for analysis
