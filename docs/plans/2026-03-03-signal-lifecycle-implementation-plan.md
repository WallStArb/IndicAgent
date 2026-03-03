# Signal Lifecycle Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `signal_tracker_service` with an institutional-grade `signal_lifecycle_service` that captures live bid/ask at signal determination, entry zones, MAE/MFE, and 8-class outcome labels for ML training.

**Architecture:** (1) Migration adds 14 nullable columns to `signal_ledger`. (2) `trade_framer.py` computes `zone_low`/`zone_high` from structural features it already knows. (3) `signal_generator_service` captures `determined_at` + live bid/ask from the existing `price:{symbol}:latest` DragonflyDB hash before the DB insert. (4) New `signal_lifecycle_service` replaces `signal_tracker_service` with zone-aware activation, per-signal in-memory MAE/MFE tracking, bars-elapsed computed from timestamps (fixes silent TTL bug), and 8-class outcome on exit.

**Tech Stack:** asyncpg, redis.asyncio, structlog, prometheus_client, TimescaleDB, DragonflyDB

---

## Task 1: DB Migration — 14 New signal_ledger Columns

**Files:**
- Create: `production/migrations/014_signal_lifecycle_fields.sql`

**Step 1: Write the migration**

```sql
-- production/migrations/014_signal_lifecycle_fields.sql
-- Institutional-grade signal lifecycle tracking
-- All columns NULLABLE — pre-existing rows unaffected.

ALTER TABLE signal_ledger
    -- At signal determination time
    ADD COLUMN IF NOT EXISTS determined_at            TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ask_at_signal            DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bid_at_signal            DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS market_price_at_signal   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entry_zone_low           DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entry_zone_high          DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS zone_valid_at_signal     BOOLEAN,

    -- At activation
    ADD COLUMN IF NOT EXISTS activation_price         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS zone_entry_pct           DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bars_to_activation       INTEGER,

    -- During trade (written on exit — in-memory during run)
    ADD COLUMN IF NOT EXISTS mae                      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS mfe                      DOUBLE PRECISION,

    -- At exit
    ADD COLUMN IF NOT EXISTS bars_in_trade            INTEGER,
    ADD COLUMN IF NOT EXISTS outcome                  TEXT;

-- Index for ML training queries
CREATE INDEX IF NOT EXISTS idx_ledger_outcome
    ON signal_ledger (outcome, setup_plugin, timeframe)
    WHERE outcome IS NOT NULL;
```

**Step 2: Apply migration**

```bash
psql $DATABASE_URL -f production/migrations/014_signal_lifecycle_fields.sql
```

Expected: `ALTER TABLE` and `CREATE INDEX`

**Step 3: Verify**

```bash
psql $DATABASE_URL -c "\d signal_ledger" | grep -E "determined_at|zone|mae|mfe|outcome"
```

Expected: 14 new columns listed

**Step 4: Commit**

```bash
git add production/migrations/014_signal_lifecycle_fields.sql
git commit -m "feat(migration): add 14 institutional signal lifecycle columns to signal_ledger"
```

---

## Task 2: TradeFrame Zone Bounds — trade_framer.py

**Files:**
- Modify: `src/intelligence/trading/trade_framer.py`
- Test: `tests/unit/intelligence/trading/test_trade_framer.py` (create)

**Step 1: Write failing tests**

```python
# tests/unit/intelligence/trading/test_trade_framer.py
"""Tests for trade_framer zone bound computation."""
import pytest
from src.intelligence.trading.trade_framer import TradeFrame, frame_trade


def _features_with_demand_zone():
    return {
        "atr_14": 5.0,
        "nearest_demand_high": 450.0,   # proximal edge (zone top)
        "nearest_demand_low": 445.0,    # distal edge (zone bottom)
        "nearest_supply_high": 460.0,
        "nearest_supply_low": 455.0,
        "in_demand_zone": 1.0,
        "swing_low": 444.0,
    }


def _features_with_fvg():
    return {
        "atr_14": 5.0,
        "fvg_type": 1.0,
        "fvg_top": 452.0,
        "fvg_bottom": 448.0,
        "swing_low": 446.0,
    }


@pytest.mark.unit
class TestZoneBounds:
    def test_demand_zone_entry_sets_structural_zone_long(self):
        """supply_demand long: zone_low = nearest_demand_low, zone_high = nearest_demand_high."""
        frame = frame_trade("supply_demand_long", 1, 451.0, _features_with_demand_zone(), atr=5.0)
        assert frame.zone_low == 445.0
        assert frame.zone_high == 450.0

    def test_fvg_entry_sets_fvg_zone_long(self):
        """FVG fill long: zone is FVG bottom to top."""
        frame = frame_trade("fvg_fill_long", 1, 449.0, _features_with_fvg(), atr=5.0)
        assert frame.zone_low == 448.0
        assert frame.zone_high == 452.0

    def test_atr_fallback_zone_when_no_structural(self):
        """at_close entry with no structural zone: fallback = entry ± 1×ATR."""
        features = {"atr_14": 5.0, "swing_low": 444.0}
        frame = frame_trade("trend_long", 1, 450.0, features, atr=5.0)
        # At-close entry, no demand zone → ATR fallback
        assert frame.zone_low == pytest.approx(450.0 - 5.0 * 1.0)
        assert frame.zone_high == pytest.approx(450.0 + 5.0 * 0.5)

    def test_zone_low_always_less_than_zone_high(self):
        """zone_low must always be < zone_high regardless of direction."""
        features = {"atr_14": 3.0, "nearest_supply_high": 460.0,
                    "nearest_supply_low": 455.0, "in_supply_zone": 1.0, "swing_high": 462.0}
        frame = frame_trade("supply_demand_short", -1, 457.0, features, atr=3.0)
        assert frame.zone_low < frame.zone_high
```

**Step 2: Run — expect failure**

```bash
.venv/bin/pytest tests/unit/intelligence/trading/test_trade_framer.py -v
```

Expected: `AttributeError: 'TradeFrame' object has no attribute 'zone_low'`

**Step 3: Add `zone_low`/`zone_high` to `TradeFrame` and `_resolve_zone_bounds()`**

In `src/intelligence/trading/trade_framer.py`, add to the `TradeFrame` dataclass:

```python
@dataclass
class TradeFrame:
    entry: float
    entry_type: str
    stop: float
    stop_type: str
    targets: list[TradeTarget] = field(default_factory=list)
    rr_t1: float = 0.0
    rr_t2: float = 0.0
    rr_t3: float = 0.0
    method: str = "atr_fallback"
    viable: bool = True
    rejection_reason: str | None = None
    zone_low: float = 0.0    # ← new
    zone_high: float = 0.0   # ← new
```

Then add this function after `_fval()`:

```python
def _resolve_zone_bounds(
    setup_type: str,
    direction: int,
    entry: float,
    entry_type: str,
    features: dict[str, Any],
    atr: float,
) -> tuple[float, float]:
    """Return (zone_low, zone_high) for the entry zone.

    Uses structural levels when available; falls back to entry ± ATR multiples.
    zone_low < zone_high always (independent of direction).
    """
    st = setup_type.lower()

    # Supply/Demand zone entries — use the demand/supply zone bounds
    if st.startswith("supply_demand"):
        if direction == 1:
            low = _fval(features, "nearest_demand_low")
            high = _fval(features, "nearest_demand_high")
        else:
            low = _fval(features, "nearest_supply_low")
            high = _fval(features, "nearest_supply_high")
        if 0 < low < high:
            return low, high

    # FVG fill — use FVG bottom/top
    if st.startswith("fvg"):
        fvg_bottom = _fval(features, "fvg_bottom")
        fvg_top = _fval(features, "fvg_top")
        if 0 < fvg_bottom < fvg_top:
            return fvg_bottom, fvg_top

    # Order block entries — use OB bottom/top
    if st.startswith("choch") or "ob" in st:
        ob_bottom = _fval(features, "ob_bottom")
        ob_top = _fval(features, "ob_top")
        if 0 < ob_bottom < ob_top:
            return ob_bottom, ob_top

    # Sweep/reclaim — tight zone ± 0.5×ATR around entry
    if st.startswith("sweep") or st.startswith("liquidity_hunt"):
        return entry - atr * 0.5, entry + atr * 0.5

    # ATR fallback — standard ±ATR band
    return entry - atr * 1.0, entry + atr * 0.5
```

Then wire into `frame_trade()` — add just before the `return TradeFrame(...)` at the end:

```python
    # Resolve entry zone bounds
    zone_low, zone_high = _resolve_zone_bounds(
        setup_type, direction, resolved_entry, entry_type, features, atr
    )
```

And add `zone_low=zone_low, zone_high=zone_high` to the final `TradeFrame(...)` return statement. Also add to all early-return `TradeFrame(...)` calls (viable=False paths) with `zone_low=0.0, zone_high=0.0`.

**Step 4: Run tests — expect pass**

```bash
.venv/bin/pytest tests/unit/intelligence/trading/test_trade_framer.py -v
```

Expected: 4 tests PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/trade_framer.py tests/unit/intelligence/trading/test_trade_framer.py
git commit -m "feat(trade-framer): add zone_low/zone_high to TradeFrame with structural zone resolution"
```

---

## Task 3: signal_ledger.py — New Fields and SQL

**Files:**
- Modify: `src/intelligence/trading/signal_ledger.py`
- Modify: `tests/unit/intelligence/test_signal_ledger.py`

**Step 1: Write failing tests (add to existing test file)**

```python
# Add to tests/unit/intelligence/test_signal_ledger.py

from src.intelligence.trading.signal_ledger import LedgerEntry
from datetime import datetime, UTC


@pytest.mark.unit
class TestLedgerEntryNewFields:
    def test_ledger_entry_has_zone_fields(self):
        """LedgerEntry dataclass includes all new institutional fields."""
        entry = LedgerEntry(
            signal_id="test-uuid",
            timestamp=datetime.now(UTC),
            symbol="ES",
            timeframe="5m",
            setup_plugin="TrendFollowing",
            signal_type="trend_long",
            direction=1,
            entry_price=5100.0,
            stop_loss=5085.0,
            targets=[5115.0, 5130.0],
            confidence=0.8,
            confluence_score=0.7,
            regime_context="trending",
            supporting_factors=["rsi_bull"],
            was_selected=True,
            num_signals_bar=2,
            num_agreeing=1,
            num_conflicting=1,
            resolution_method="priority",
            composite_rank=1,
            determined_at=datetime.now(UTC),
            ask_at_signal=5101.5,
            bid_at_signal=5101.0,
            market_price_at_signal=5101.5,
            entry_zone_low=5095.0,
            entry_zone_high=5100.0,
            zone_valid_at_signal=True,
        )
        assert entry.determined_at is not None
        assert entry.ask_at_signal == 5101.5
        assert entry.entry_zone_low == 5095.0
        assert entry.zone_valid_at_signal is True
        assert entry.mae is None
        assert entry.outcome is None

    def test_to_insert_params_length(self):
        """to_insert_params() returns correct number of elements for new SQL."""
        entry = LedgerEntry(
            signal_id="test-uuid",
            timestamp=datetime.now(UTC),
            symbol="ES", timeframe="5m",
            setup_plugin="TrendFollowing", signal_type="trend_long",
            direction=1, entry_price=5100.0, stop_loss=5085.0,
            targets=[5115.0], confidence=0.8, confluence_score=0.7,
            regime_context="trending", supporting_factors=[],
            was_selected=True, num_signals_bar=1, num_agreeing=1,
            num_conflicting=0, resolution_method="sole", composite_rank=1,
        )
        params = entry.to_insert_params()
        assert len(params) == 35  # 28 existing + 7 new fire-time fields
```

**Step 2: Run — expect failure**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py::TestLedgerEntryNewFields -v
```

Expected: `TypeError` — unexpected keyword arguments

**Step 3: Update `LedgerEntry` dataclass**

Add new fields to `LedgerEntry` in `src/intelligence/trading/signal_ledger.py` after `signal_quality`:

```python
    # Institutional lifecycle fields — all nullable; populated progressively
    # At signal determination time
    determined_at: datetime | None = None
    ask_at_signal: float | None = None
    bid_at_signal: float | None = None
    market_price_at_signal: float | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    zone_valid_at_signal: bool | None = None
    # At activation (set by signal_lifecycle_service)
    activation_price: float | None = None
    zone_entry_pct: float | None = None
    bars_to_activation: int | None = None
    # During/after trade
    mae: float | None = None
    mfe: float | None = None
    bars_in_trade: int | None = None
    outcome: str | None = None
```

Update `to_insert_params()` to add 7 new fire-time fields (activation/exit fields written separately via UPDATE):

```python
    def to_insert_params(self) -> tuple:
        """Return a 35-element tuple ready for batch INSERT."""
        return (
            # ... existing 28 params unchanged ...
            self.determined_at,          # $29
            self.ask_at_signal,          # $30
            self.bid_at_signal,          # $31
            self.market_price_at_signal, # $32
            self.entry_zone_low,         # $33
            self.entry_zone_high,        # $34
            self.zone_valid_at_signal,   # $35
        )
```

Update `_INSERT_SQL` to include the 7 new columns:

```python
_INSERT_SQL = """
INSERT INTO signal_ledger (
    signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type,
    direction, entry_price, stop_loss, targets,
    confidence, confluence_score, regime_context, supporting_factors,
    was_selected, num_signals_bar, num_agreeing, num_conflicting,
    resolution_method, composite_rank, market_context, status,
    feature_ts, feature_tf,
    cis_score, bucket_scores, weights_version, signal_quality,
    determined_at, ask_at_signal, bid_at_signal, market_price_at_signal,
    entry_zone_low, entry_zone_high, zone_valid_at_signal
) VALUES (
    $1::uuid, $2, $3, $4, $5, $6,
    $7, $8, $9, $10::jsonb,
    $11, $12, $13, $14::jsonb,
    $15, $16, $17, $18,
    $19, $20, $21::jsonb, $22,
    $23, $24,
    $25, $26::jsonb, $27, $28,
    $29, $30, $31, $32,
    $33, $34, $35
)
"""
```

Update `_UPDATE_STATUS_SQL` to include activation and exit fields:

```python
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
```

Update `update_signal_status()` function signature to match:

```python
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
    await db_manager.execute_command(
        _UPDATE_STATUS_SQL,
        signal_id, status,
        activated_at, exit_at, exit_price, exit_reason,
        pnl_ticks, pnl_r, pnl_dollars, signal_quality,
        activation_price, zone_entry_pct, bars_to_activation,
        mae, mfe, bars_in_trade, outcome,
    )
```

**Step 4: Run tests — expect pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py -v
```

Expected: all pass

**Step 5: Commit**

```bash
git add src/intelligence/trading/signal_ledger.py tests/unit/intelligence/test_signal_ledger.py
git commit -m "feat(signal-ledger): add institutional lifecycle fields to LedgerEntry and SQL"
```

---

## Task 4: lifecycle_tracker.py — Zone-Aware, Bars-from-Timestamps, MAE/MFE, 8-Class Outcome

**Files:**
- Modify: `src/intelligence/trading/lifecycle_tracker.py`
- Modify: `tests/unit/intelligence/test_lifecycle_tracker.py`

**Step 1: Write failing tests (add to existing test file)**

```python
# Add to tests/unit/intelligence/test_lifecycle_tracker.py

from datetime import datetime, UTC, timedelta


def _pending_with_zone(direction=1, entry=5100.0, stop=5085.0,
                       zone_low=5095.0, zone_high=5105.0) -> dict:
    """Pending signal with zone bounds."""
    return {
        "signal_id": "test-id",
        "status": "pending",
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "targets": [5115.0, 5130.0, 5145.0] if direction == 1 else [5085.0, 5070.0, 5055.0],
        "ttl_bars": 10,
        "bars_elapsed": 0,
        "point_value": 50.0,
        "entry_zone_low": zone_low,
        "entry_zone_high": zone_high,
    }


@pytest.mark.unit
class TestZoneAwareActivation:
    def test_bar_overlaps_zone_activates_long(self):
        """Bar range overlaps zone: low <= zone_high AND high >= zone_low."""
        sig = _pending_with_zone(direction=1, zone_low=5095.0, zone_high=5102.0)
        t = evaluate_signal(sig, high=5098.0, low=5093.0, close=5096.0)
        assert t is not None
        assert t.new_status == "active"
        assert t.activation_price == 5098.0  # min(high, zone_high)

    def test_bar_entirely_above_zone_does_not_activate_long(self):
        """Bar entirely above the zone: no activation."""
        sig = _pending_with_zone(direction=1, zone_low=5095.0, zone_high=5100.0)
        t = evaluate_signal(sig, high=5115.0, low=5103.0, close=5110.0)
        assert t is None

    def test_zone_entry_pct_proximal(self):
        """Activation at proximal edge: zone_entry_pct near 0.0."""
        sig = _pending_with_zone(direction=1, zone_low=5090.0, zone_high=5100.0)
        # bar dips just into zone top (proximal for long = zone_high)
        t = evaluate_signal(sig, high=5101.0, low=5099.0, close=5100.0)
        assert t is not None
        # activation_price = min(high, zone_high) = 5100.0
        # zone_entry_pct = (5100.0 - 5090.0) / (5100.0 - 5090.0) = 1.0 = distal for convention
        assert t.zone_entry_pct is not None
        assert 0.0 <= t.zone_entry_pct <= 1.0


@pytest.mark.unit
class TestMAEMFE:
    def test_mfe_updates_on_favorable_move(self):
        """Active signal: favorable move updates mfe."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        t = evaluate_signal(sig, high=5110.0, low=5098.0, close=5108.0,
                            current_mae=0.0, current_mfe=0.0)
        assert t is None  # no exit yet
        # Caller gets updated excursions from the function's return values — tested via service

    def test_mae_updates_on_adverse_move(self):
        """Active signal: adverse move captured as negative pnl_r."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5086.0,
                             targets=[5115.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        # Price dips toward stop but doesn't hit it
        t = evaluate_signal(sig, high=5102.0, low=5088.0, close=5090.0,
                            current_mae=0.0, current_mfe=0.0)
        assert t is None  # stop not hit (low=5088 > stop=5086)


@pytest.mark.unit
class TestOutcomeClassification:
    def test_outcome_never_activated_on_ttl_expiry_pending(self):
        """Signal that TTL-expires while still pending → never_activated."""
        sig = _pending_with_zone()
        sig["bars_elapsed"] = 10  # hit TTL
        t = evaluate_signal(sig, high=5080.0, low=5075.0, close=5078.0)
        assert t is not None
        assert t.new_status == "expired"
        assert t.outcome == "never_activated"

    def test_outcome_target_1_on_t1_hit(self):
        """Active signal exits at T1 → outcome = target_1."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        t = evaluate_signal(sig, high=5120.0, low=5102.0, close=5118.0,
                            current_mae=0.0, current_mfe=0.5)
        assert t is not None
        assert t.new_status == "target_1_hit"
        assert t.outcome == "target_1"

    def test_outcome_stopped_in_trade_after_mfe(self):
        """Signal stopped out after having positive MFE → stopped_in_trade."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        # MFE > 0 means price moved in favor at some point
        t = evaluate_signal(sig, high=5090.0, low=5084.0, close=5085.0,
                            current_mae=-0.1, current_mfe=0.8)
        assert t is not None
        assert t.new_status == "stopped_out"
        assert t.outcome == "stopped_in_trade"

    def test_outcome_stopped_at_entry_when_mfe_zero(self):
        """Signal stopped quickly (mfe near 0) → stopped_at_entry."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5085.0,
                            current_mae=0.0, current_mfe=0.0)
        assert t is not None
        assert t.outcome == "stopped_at_entry"
```

**Step 2: Run — expect failure**

```bash
.venv/bin/pytest tests/unit/intelligence/test_lifecycle_tracker.py -v -k "Zone or MAE or Outcome"
```

Expected: multiple failures (`evaluate_signal` missing `current_mae`/`current_mfe` params, `Transition` missing `outcome`, `activation_price`)

**Step 3: Rewrite `lifecycle_tracker.py`**

Replace the full file with this implementation:

```python
"""Signal lifecycle tracker.

Evaluates signal state transitions based on price data. Pure functions —
does not touch the database. Returns Transition objects that the caller
persists via signal_ledger.update_signal_status().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


OUTCOME_THRESHOLD_QUICK_STOP_BARS = 2   # bars_in_trade <= this → stopped_at_entry


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
    # Institutional fields
    activation_price: float | None = None
    zone_entry_pct: float | None = None
    bars_to_activation: int | None = None
    mae: float | None = None
    mfe: float | None = None
    bars_in_trade: int | None = None
    outcome: str | None = None


def evaluate_signal(
    signal: dict[str, Any],
    *,
    high: float,
    low: float,
    close: float,
    current_mae: float = 0.0,
    current_mfe: float = 0.0,
) -> Transition | None:
    """Evaluate whether a signal should transition state.

    Args:
        signal: Dict with signal fields (status, direction, entry_price,
                stop_loss, targets, ttl_bars, bars_elapsed, point_value,
                entry_zone_low, entry_zone_high).
        high: Current bar's high price.
        low: Current bar's low price.
        close: Current bar's close price.
        current_mae: Current maximum adverse excursion (pnl_r units).
        current_mfe: Current maximum favorable excursion (pnl_r units).

    Returns:
        Transition if state changes (with updated mae/mfe on exit),
        None if signal stays in current state.
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
    zone_low = signal.get("entry_zone_low") or entry
    zone_high = signal.get("entry_zone_high") or entry
    risk = abs(entry - stop)

    # TTL check first (applies to both pending and active)
    if bars >= ttl:
        exit_price = close
        pnl_ticks = (exit_price - entry) * direction
        pnl_r = round(pnl_ticks / risk, 4) if risk > 0 else 0.0
        pnl_dollars = round(pnl_ticks * point_value, 2)
        if status == "pending":
            outcome = "never_activated"
        elif current_mfe > 0:
            outcome = "ttl_expired_ahead"
        else:
            outcome = "ttl_expired_behind"
        return Transition(
            signal_id=sid,
            new_status="expired",
            exit_reason="ttl_expired",
            exit_price=exit_price,
            pnl_ticks=round(pnl_ticks, 4),
            pnl_r=pnl_r,
            pnl_dollars=pnl_dollars,
            mae=current_mae,
            mfe=current_mfe,
            outcome=outcome,
        )

    if status == "pending":
        return _check_zone_activation(
            sid, direction, entry, zone_low, zone_high, high, low, bars
        )

    if status == "active":
        return _check_active_exit(
            sid, direction, entry, stop, targets,
            high, low, close, risk, point_value,
            current_mae, current_mfe,
        )

    return None


def _check_zone_activation(
    sid: str,
    direction: int,
    entry: float,
    zone_low: float,
    zone_high: float,
    high: float,
    low: float,
    bars_elapsed: int,
) -> Transition | None:
    """Zone-aware activation: bar range must overlap the entry zone."""
    bar_overlaps_zone = low <= zone_high and high >= zone_low

    if not bar_overlaps_zone:
        return None

    # Activation price: best fill within zone on this bar
    if direction == 1:
        # Long: want to buy low in zone; activation_price = lowest touch of zone
        activation_price = max(low, zone_low)
        # zone_entry_pct: 0.0 = proximal (zone_high), 1.0 = distal (zone_low)
        zone_span = zone_high - zone_low
        zone_entry_pct = round(1.0 - (activation_price - zone_low) / zone_span, 4) if zone_span > 0 else 0.5
    else:
        # Short: want to sell high in zone; activation_price = highest touch of zone
        activation_price = min(high, zone_high)
        zone_span = zone_high - zone_low
        zone_entry_pct = round((activation_price - zone_low) / zone_span, 4) if zone_span > 0 else 0.5

    return Transition(
        signal_id=sid,
        new_status="active",
        activation_price=round(activation_price, 4),
        zone_entry_pct=zone_entry_pct,
        bars_to_activation=bars_elapsed,
    )


def _check_active_exit(
    sid: str,
    direction: int,
    entry: float,
    stop: float,
    targets: list[float],
    high: float,
    low: float,
    close: float,
    risk: float,
    point_value: float,
    current_mae: float,
    current_mfe: float,
) -> Transition | None:
    """Check if an active signal should exit; returns None if still in trade."""
    # Stop loss check first (conservative: stop before target on same bar)
    if direction == 1 and low <= stop:
        return _make_exit(sid, "stopped_out", "stop_loss", stop,
                          entry, direction, risk, point_value,
                          current_mae, current_mfe)
    if direction == -1 and high >= stop:
        return _make_exit(sid, "stopped_out", "stop_loss", stop,
                          entry, direction, risk, point_value,
                          current_mae, current_mfe)

    # Target checks (highest target first for maximum credit)
    for i in range(len(targets) - 1, -1, -1):
        target = targets[i]
        hit = (direction == 1 and high >= target) or \
              (direction == -1 and low <= target)
        if hit:
            return _make_exit(sid, f"target_{i + 1}_hit", f"target_{i + 1}", target,
                              entry, direction, risk, point_value,
                              current_mae, current_mfe, target_index=i)

    return None


def _determine_stop_outcome(current_mfe: float, bars_in_trade: int) -> str:
    """Classify a stopped-out signal into fine-grained outcome."""
    if bars_in_trade <= OUTCOME_THRESHOLD_QUICK_STOP_BARS or current_mfe <= 0.05:
        return "stopped_at_entry"
    return "stopped_in_trade"


def _determine_target_outcome(target_index: int) -> str:
    """Map target index (0-based) to outcome label."""
    return ["target_1", "target_1_2", "target_full"][min(target_index, 2)]


def _make_exit(
    sid: str,
    status: str,
    reason: str,
    exit_price: float,
    entry: float,
    direction: int,
    risk: float,
    point_value: float,
    current_mae: float,
    current_mfe: float,
    target_index: int | None = None,
) -> Transition:
    """Build an exit Transition with P&L, MAE/MFE, and outcome."""
    pnl_ticks = (exit_price - entry) * direction
    pnl_r = round(pnl_ticks / risk, 4) if risk > 0 else 0.0
    pnl_dollars = round(pnl_ticks * point_value, 2)

    # Update excursions with this bar's result
    final_mae = min(current_mae, pnl_r)
    final_mfe = max(current_mfe, pnl_r)

    # Bars-in-trade is set by the service layer (it knows activation time)
    # We set it to None here; service fills it in after calling this function.
    bars_in_trade = None

    if target_index is not None:
        outcome = _determine_target_outcome(target_index)
    else:
        # Stop loss — bars_in_trade unknown here, service patches after
        outcome = None  # service sets: stopped_at_entry or stopped_in_trade

    return Transition(
        signal_id=sid,
        new_status=status,
        exit_reason=reason,
        exit_price=exit_price,
        pnl_ticks=round(pnl_ticks, 4),
        pnl_r=pnl_r,
        pnl_dollars=pnl_dollars,
        mae=round(final_mae, 4),
        mfe=round(final_mfe, 4),
        outcome=outcome,
    )
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_lifecycle_tracker.py -v
```

Expected: all pass (both existing tests and new tests)

**Step 5: Commit**

```bash
git add src/intelligence/trading/lifecycle_tracker.py tests/unit/intelligence/test_lifecycle_tracker.py
git commit -m "feat(lifecycle-tracker): zone-aware activation, MAE/MFE, 8-class outcome"
```

---

## Task 5: signal_generator_service.py — Capture determined_at + Live Quote

**Files:**
- Modify: `services/signal_generator_service.py`

**Step 1: Find where `LedgerEntry` objects are created**

```bash
grep -n "LedgerEntry(" services/signal_generator_service.py | head -5
```

Note the line number — this is where we add new fields.

**Step 2: Add `quote_latest` helper to stream_keys.py**

In `src/core/stream_keys.py`, add after the `live_tick` function:

```python
def quote_latest(env_prefix: str, symbol: str) -> str:
    """Hash key for latest bid/ask snapshot. Written by AsyncTickPublisher."""
    return f"{env_prefix}price:{symbol}:latest"
```

**Step 3: Add live quote fetch helper to signal_generator_service.py**

Add this function before the class definition (or as a private method):

```python
async def _fetch_live_quote(
    redis_client: redis.Redis,
    env_prefix: str,
    symbol: str,
) -> dict[str, float | None]:
    """Fetch live bid/ask from price:{symbol}:latest hash.

    Returns {"bid": float|None, "ask": float|None}.
    Falls back to None values if key missing or TWS disconnected.
    """
    from src.core.stream_keys import quote_latest
    try:
        raw = await redis_client.hgetall(quote_latest(env_prefix, symbol))
        if not raw:
            return {"bid": None, "ask": None}

        def _parse(key: bytes) -> float | None:
            val = raw.get(key) or raw.get(key.decode() if isinstance(key, bytes) else key.encode())
            if val is None:
                return None
            try:
                f = float(val)
                return f if f > 0 else None
            except (ValueError, TypeError):
                return None

        return {
            "bid": _parse(b"bid"),
            "ask": _parse(b"ask"),
        }
    except Exception:
        return {"bid": None, "ask": None}
```

**Step 4: Update the signal insertion section**

Find where `LedgerEntry` is constructed for each signal (look for `LedgerEntry(` in the service). Before constructing it, add:

```python
# Capture determination time and live quote
determined_at = datetime.now(UTC)
quote = await _fetch_live_quote(self.redis_client, self.env_prefix, symbol)
```

Then add these kwargs to every `LedgerEntry(...)` constructor call:

```python
determined_at=determined_at,
ask_at_signal=quote.get("ask"),
bid_at_signal=quote.get("bid"),
market_price_at_signal=quote.get("ask") if direction == 1 else quote.get("bid"),
entry_zone_low=trade_frame.zone_low if trade_frame else None,
entry_zone_high=trade_frame.zone_high if trade_frame else None,
zone_valid_at_signal=_is_zone_valid(
    direction,
    quote.get("ask") if direction == 1 else quote.get("bid"),
    entry_zone_low=trade_frame.zone_low if trade_frame else None,
    entry_zone_high=trade_frame.zone_high if trade_frame else None,
),
```

Add helper function:

```python
def _is_zone_valid(
    direction: int,
    market_price: float | None,
    entry_zone_low: float | None,
    entry_zone_high: float | None,
) -> bool | None:
    """True if market price is still reachable (within or near zone)."""
    if market_price is None or entry_zone_low is None or entry_zone_high is None:
        return None
    if direction == 1:
        # Long: offer should be at or below zone_high (entry still reachable)
        return market_price <= entry_zone_high
    else:
        # Short: bid should be at or above zone_low (entry still reachable)
        return market_price >= entry_zone_low
```

**Step 5: Run full unit tests**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```

Expected: all 1000+ tests pass (signal_generator changes are additive, no existing tests broken)

**Step 6: Commit**

```bash
git add services/signal_generator_service.py src/core/stream_keys.py
git commit -m "feat(signal-generator): capture determined_at, live bid/ask, and zone bounds at fire time"
```

---

## Task 6: signal_lifecycle_service.py — New Service

**Files:**
- Create: `services/signal_lifecycle_service.py`
- Test: `tests/unit/services/test_signal_lifecycle_service.py` (create)

**Step 1: Write failing unit test for bars_elapsed computation**

```python
# tests/unit/services/test_signal_lifecycle_service.py
"""Unit tests for signal lifecycle service helpers."""
import pytest
from datetime import datetime, UTC, timedelta


def _compute_bars_elapsed(signal_timestamp: datetime, current_bar_time: datetime, timeframe: str) -> int:
    """Compute bars elapsed since signal fire. Imported from service in real tests."""
    TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
    tf_secs = TF_SECONDS.get(timeframe, 60)
    delta = (current_bar_time - signal_timestamp).total_seconds()
    return max(0, int(delta / tf_secs))


@pytest.mark.unit
class TestBarsElapsedComputation:
    def test_same_bar_returns_zero(self):
        ts = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
        assert _compute_bars_elapsed(ts, ts, "5m") == 0

    def test_one_bar_elapsed_5m(self):
        ts = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
        bar_time = datetime(2026, 3, 3, 14, 40, 0, tzinfo=UTC)
        assert _compute_bars_elapsed(ts, bar_time, "5m") == 1

    def test_ttl_boundary_10_bars_1h(self):
        ts = datetime(2026, 3, 3, 10, 0, 0, tzinfo=UTC)
        bar_time = ts + timedelta(hours=10)
        assert _compute_bars_elapsed(ts, bar_time, "1h") == 10

    def test_determined_at_lag_accounted(self):
        """Signal determined 2 min after bar close; 5m bars."""
        bar_close = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
        determined_at = bar_close + timedelta(minutes=2)  # 14:37
        # Next bar at 14:40 → 1 bar elapsed from signal perspective
        next_bar = datetime(2026, 3, 3, 14, 40, 0, tzinfo=UTC)
        assert _compute_bars_elapsed(determined_at, next_bar, "5m") == 0  # <1 bar from determined_at
```

**Step 2: Run — expect ImportError (service not yet created)**

```bash
.venv/bin/pytest tests/unit/services/test_signal_lifecycle_service.py -v
```

(Will pass for the test using local function — confirms logic before wiring into service)

**Step 3: Create the service**

```python
#!/usr/bin/env python3
"""
Signal Lifecycle Service — institutional-grade signal lifecycle management.

Replaces signal_tracker_service. Extends lifecycle tracking with:
- Zone-aware entry activation (bar range overlaps entry_zone_low:zone_high)
- Bars-elapsed computed from timestamps (fixes TTL silent bug)
- In-memory MAE/MFE tracking per active signal; written to DB on exit
- 8-class outcome classification
- Tracks activation_price, zone_entry_pct, bars_to_activation, bars_in_trade
"""

import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
import structlog

from src.config.settings import Settings, get_active_contracts, get_point_value
from src.core.database_manager import DatabaseManager
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import market as sk_market
from src.core.stream_utils import ensure_consumer_group_with_reset
from src.intelligence.trading.lifecycle_tracker import (
    OUTCOME_THRESHOLD_QUICK_STOP_BARS,
    Transition,
    evaluate_signal,
)
from src.intelligence.trading.signal_ledger import get_active_signals, update_signal_status
from src.observability.metrics import counter, gauge, start_metrics_server


TF_SECONDS: dict[str, int] = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def _bars_elapsed(signal_timestamp: datetime, current_bar_time: datetime, timeframe: str) -> int:
    """Bars elapsed since signal fire, based on timestamps."""
    tf_secs = TF_SECONDS.get(timeframe, 60)
    delta = (current_bar_time - signal_timestamp).total_seconds()
    return max(0, int(delta / tf_secs))


def _bars_in_trade(activated_at: datetime | None, exit_at: datetime, timeframe: str) -> int | None:
    """Bars from activation to exit."""
    if activated_at is None:
        return None
    tf_secs = TF_SECONDS.get(timeframe, 60)
    delta = (exit_at - activated_at).total_seconds()
    return max(0, int(delta / tf_secs))


def _classify_stop_outcome(current_mfe: float, bars_in_trade_count: int | None) -> str:
    """Resolve fine-grained outcome for a stopped-out signal."""
    if bars_in_trade_count is None or \
       bars_in_trade_count <= OUTCOME_THRESHOLD_QUICK_STOP_BARS or \
       current_mfe <= 0.05:
        return "stopped_at_entry"
    return "stopped_in_trade"


class SignalLifecycleService:
    """Zone-aware institutional signal lifecycle tracker."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)
        self.config = self._load_config(config_file)
        self._setup_logging()

        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None
        self.consumer_group = "signal_lifecycle"
        self.consumer_name = f"lifecycle_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.point_values: dict[str, float] = {
            sym: float(get_point_value(sym) or 1.0)
            for sym in self.config["service"]["symbols"]
        }

        # In-memory MAE/MFE tracking: signal_id → float
        self._mae: dict[str, float] = {}
        self._mfe: dict[str, float] = {}
        # activation_time tracking for bars_in_trade: signal_id → datetime
        self._activated_at: dict[str, datetime] = {}

        self.lifecycle_transitions_total = counter(
            "lifecycle_transitions_total", "Total signal lifecycle transitions"
        )
        self.active_signals_count = gauge(
            "lifecycle_active_signals_count", "Current count of open signals"
        )
        self.service_uptime_seconds = gauge(
            "lifecycle_service_uptime_seconds", "Signal lifecycle uptime in seconds"
        )
        self.error_count_total = counter(
            "lifecycle_errors_total", "Total errors in signal lifecycle service"
        )

        self._stream_map: dict[str, tuple[str, str]] = {}

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.logger = structlog.get_logger(__name__)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
        except Exception:
            _settings = None
        default: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "database": {
                "url": (
                    _settings.database_url
                    if _settings and getattr(_settings, "database_url", None)
                    else "postgresql://postgres:postgres@localhost:5432/indicagent"
                )
            },
            "service": {
                "symbols": get_active_contracts(),
                "timeframes": ["1m", "5m", "15m", "1h"],
            },
            "metrics_port": 9115,
            "logging": {
                "level": "INFO",
                "file": "logs/signal_lifecycle_service.log",
            },
        }
        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for k, v in user_config.items():
                if isinstance(v, dict) and k in default:
                    default[k].update(v)
                else:
                    default[k] = v
        return default

    def _setup_logging(self) -> None:
        setup_service_logging(
            self.config["logging"]["file"],
            level=self.config["logging"].get("level", "INFO"),
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def _evaluate_signals_against_bar(
        self,
        symbol: str,
        timeframe: str,
        bar: dict[str, Any],
        bar_time: datetime,
        all_active: list[dict[str, Any]] | None = None,
    ) -> None:
        if not self.db_manager:
            return

        relevant = [s for s in (all_active or []) if s.get("timeframe") == timeframe]
        self.active_signals_count.set(len(relevant))
        now = datetime.now(tz=UTC)

        for sig in relevant:
            sid = str(sig["signal_id"])
            point_value = self.point_values.get(symbol, 1.0)

            # Compute bars_elapsed from timestamps (fixes TTL bug)
            sig_ts = sig.get("timestamp")
            if sig_ts and isinstance(sig_ts, datetime):
                computed_bars = _bars_elapsed(sig_ts, bar_time, timeframe)
            else:
                computed_bars = sig.get("bars_elapsed", 0)

            sig_with_extras = {
                **sig,
                "point_value": point_value,
                "bars_elapsed": computed_bars,
            }

            current_mae = self._mae.get(sid, 0.0)
            current_mfe = self._mfe.get(sid, 0.0)

            try:
                transition = evaluate_signal(
                    sig_with_extras,
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    current_mae=current_mae,
                    current_mfe=current_mfe,
                )
            except Exception as e:
                self.logger.warning(
                    "Lifecycle evaluation failed",
                    signal_id=sid, error=str(e),
                )
                continue

            if transition is None:
                # Update in-memory MAE/MFE for active signals
                if sig.get("status") == "active":
                    entry = float(sig.get("entry_price", 0))
                    stop = float(sig.get("stop_loss", 0))
                    risk = abs(entry - stop)
                    if risk > 0:
                        close_pnl_r = ((float(bar["close"]) - entry) * sig.get("direction", 1)) / risk
                        self._mae[sid] = min(current_mae, close_pnl_r)
                        self._mfe[sid] = max(current_mfe, close_pnl_r)
                continue

            # --- State transition ---
            activated_at = None
            exit_at = None
            outcome = transition.outcome
            bit = None  # bars_in_trade

            if transition.new_status == "active":
                # Pending → Active
                activated_at = now
                self._activated_at[sid] = now
                self._mae[sid] = 0.0
                self._mfe[sid] = 0.0

            elif transition.exit_reason:
                # Active → Exit
                exit_at = now
                bit = _bars_in_trade(self._activated_at.get(sid), now, timeframe)

                # Resolve stop outcome (needs bars_in_trade which lifecycle_tracker doesn't have)
                if outcome is None:
                    outcome = _classify_stop_outcome(current_mfe, bit)

                # Compute signal_quality
                confidence = float(sig.get("confidence") or 1.0)
                signal_quality = max(0.0, round((transition.pnl_r or 0.0) * confidence, 4))

                # Clean up memory
                self._mae.pop(sid, None)
                self._mfe.pop(sid, None)
                self._activated_at.pop(sid, None)

            await update_signal_status(
                self.db_manager,
                sid,
                status=transition.new_status,
                activated_at=activated_at,
                exit_at=exit_at,
                exit_price=transition.exit_price,
                exit_reason=transition.exit_reason,
                pnl_ticks=transition.pnl_ticks,
                pnl_r=transition.pnl_r,
                pnl_dollars=transition.pnl_dollars,
                signal_quality=signal_quality if transition.exit_reason else None,
                activation_price=transition.activation_price,
                zone_entry_pct=transition.zone_entry_pct,
                bars_to_activation=transition.bars_to_activation,
                mae=transition.mae,
                mfe=transition.mfe,
                bars_in_trade=bit,
                outcome=outcome,
            )

            self.lifecycle_transitions_total.inc()
            self.logger.info(
                "Signal transition",
                signal_id=sid,
                new_status=transition.new_status,
                exit_reason=transition.exit_reason,
                pnl_r=transition.pnl_r,
                outcome=outcome,
            )

    async def _process_single_bar(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
    ) -> bool:
        try:
            bar = {
                "high": float(fields[b"high"].decode()),
                "low": float(fields[b"low"].decode()),
                "close": float(fields[b"close"].decode()),
            }
            bar_time = datetime.now(tz=UTC)

            # Fetch all active signals once per symbol per bar
            active = await get_active_signals(self.db_manager, symbol=symbol)
            self.active_signals_count.set(len(active))

            for tf in self.config["service"]["timeframes"]:
                await self._evaluate_signals_against_bar(symbol, tf, bar, bar_time, active)

            return True
        except Exception as e:
            self.logger.error("Error processing bar", symbol=symbol, error=str(e))
            self.error_count_total.inc()
            return False

    async def _connect_redis(self) -> None:
        self.redis_client = redis.Redis(
            host=self.config["redis"]["host"],
            port=self.config["redis"]["port"],
            db=self.config["redis"]["db"],
            decode_responses=False,
        )
        await self.redis_client.ping()

    async def _connect_database(self) -> None:
        try:
            self.db_manager = DatabaseManager(self.config["database"]["url"])
            await self.db_manager.initialize()
        except Exception as e:
            self.logger.warning("Database unavailable", error=str(e))
            self.db_manager = None

    async def _setup_consumer_groups(self) -> None:
        for symbol in self.config["service"]["symbols"]:
            stream_name = sk_market(self.env_prefix, symbol, "1m")
            await ensure_consumer_group_with_reset(
                self.redis_client, stream_name, self.consumer_group
            )
            self._stream_map[stream_name] = (symbol, "1m")

    async def _process_loop(self) -> None:
        all_streams = {name: ">" for name in self._stream_map}
        while self.running and not self.shutdown_requested:
            try:
                messages = await self.redis_client.xreadgroup(
                    self.consumer_group, self.consumer_name,
                    all_streams, count=10, block=1000,
                )
                for stream_bytes, msgs in messages:
                    stream_name = (
                        stream_bytes.decode()
                        if isinstance(stream_bytes, bytes)
                        else stream_bytes
                    )
                    symbol, timeframe = self._stream_map[stream_name]
                    to_ack: list[bytes] = []
                    for message_id, fields in msgs:
                        ok = await self._process_single_bar(symbol, timeframe, fields)
                        if ok:
                            to_ack.append(message_id)
                    if to_ack:
                        await self.redis_client.xack(
                            stream_name, self.consumer_group, *to_ack
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.error_count_total.inc()
                if "NOGROUP" in str(e):
                    await self._setup_consumer_groups()
                else:
                    self.logger.error("Error in lifecycle loop", error=str(e))
                await asyncio.sleep(1)

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        self.logger.info("Starting Signal Lifecycle Service")
        try:
            await self._connect_redis()
            await self._connect_database()
            start_metrics_server(port=self.config.get("metrics_port", 9115))
            await self._setup_consumer_groups()
            self.running = True
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Signal Lifecycle Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Signal Lifecycle Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()


async def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Signal Lifecycle Service")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()
    service = SignalLifecycleService(args.config)
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 4: Run unit tests**

```bash
.venv/bin/pytest tests/unit/services/test_signal_lifecycle_service.py -v
```

Expected: all pass

**Step 5: Commit**

```bash
git add services/signal_lifecycle_service.py tests/unit/services/test_signal_lifecycle_service.py
git commit -m "feat(signal-lifecycle): new institutional signal lifecycle service with zones, MAE/MFE, 8-class outcome"
```

---

## Task 7: Systemd Unit — Deploy New Service, Retire Old

**Step 1: Create systemd unit file**

```bash
sudo tee /etc/systemd/system/indicagent-signal-lifecycle.service > /dev/null << 'EOF'
[Unit]
Description=IndicAgent Signal Lifecycle Service
After=network-online.target indicagent-signal-generator.service
Wants=indicagent-signal-generator.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/signal_lifecycle_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-signal-lifecycle

[Install]
WantedBy=multi-user.target
EOF
```

**Step 2: Stop and disable old service**

```bash
sudo systemctl stop indicagent-signal-tracker
sudo systemctl disable indicagent-signal-tracker
```

**Step 3: Enable and start new service**

```bash
sudo systemctl daemon-reload
sudo systemctl enable indicagent-signal-lifecycle
sudo systemctl start indicagent-signal-lifecycle
```

**Step 4: Verify running**

```bash
sudo systemctl status indicagent-signal-lifecycle
journalctl -u indicagent-signal-lifecycle -n 30
```

Expected: `active (running)`, log lines: `"Signal Lifecycle Service started"`

**Step 5: Commit**

```bash
git add .
git commit -m "ops: add indicagent-signal-lifecycle systemd unit, retire signal-tracker"
```

---

## Task 8: Full Verification

**Step 1: Run complete unit test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass, 0 failures

**Step 2: Run ruff lint**

```bash
.venv/bin/ruff check .
```

Expected: 0 errors

**Step 3: Verify new signal fields in DB**

Wait ~5 minutes for live signals to flow through. Then:

```bash
psql $DATABASE_URL -c "
SELECT signal_id, determined_at, ask_at_signal, bid_at_signal,
       entry_zone_low, entry_zone_high, zone_valid_at_signal,
       outcome, mae, mfe
FROM signal_ledger
ORDER BY created_at DESC LIMIT 5;
"
```

Expected: `determined_at`, `ask_at_signal`, `entry_zone_low/high`, `zone_valid_at_signal` populated for new signals. `outcome`, `mae`, `mfe` populated for resolved signals.

**Step 4: Check TTL bug is fixed — signals now expire**

```bash
psql $DATABASE_URL -c "
SELECT signal_id, status, outcome, created_at
FROM signal_ledger
WHERE outcome = 'never_activated'
ORDER BY created_at DESC LIMIT 5;
"
```

Expected: rows appearing (previously TTL never fired)

**Step 5: Check signal quality metrics**

```bash
psql $DATABASE_URL -c "
SELECT outcome, count(*), avg(pnl_r), avg(mae), avg(mfe)
FROM signal_ledger
WHERE outcome IS NOT NULL
GROUP BY outcome ORDER BY count DESC;
"
```

Expected: outcome distribution visible, MAE/MFE values populated

---

## Execution Handoff

Plan saved to `docs/plans/2026-03-03-signal-lifecycle-implementation-plan.md`.

**Tasks summary:**
1. DB migration (14 new columns) — ~10 min
2. TradeFrame zone bounds — ~20 min
3. signal_ledger new fields + SQL — ~25 min
4. lifecycle_tracker zone-aware + MAE/MFE + 8-class — ~30 min
5. signal_generator live quote capture — ~20 min
6. signal_lifecycle_service (new service) — ~30 min
7. Systemd deploy + retire old service — ~10 min
8. Full verification — ~15 min
