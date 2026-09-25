# Renaissance-Style Automated Roll Detection

**Date:** 2026-03-17
**Status:** Design Draft (Enhanced)
**Milestone:** v1.9

---

## Context

IndicAgent's futures pipeline currently lacks automated roll detection. When a futures contract rolls (e.g., ESH6 → ESU6), the system requires manual intervention to update `Settings().contracts`. This violates Renaissance principles:

- **Let the system run** — Manual intervention breaks automation
- **Never drop data** — Missed rolls create gaps in `intelligence_features`
- **Data quality over model complexity** — Capture every roll event for analysis

The `contract_metadata` table (migration 036) exists but is unused by the realtime pipeline.

---

## Problem Statement

When futures volume shifts from the current front-month contract to the next contract in the roll chain, the system must:

1. **Detect the shift** using volume ratios with statistical validation
2. **Switch active contract** without service restart or data loss
3. **Record roll metadata** — roll date, roll gap, detection timestamp
4. **Graceful post-roll monitoring** — Capture 10-20 bars of post-roll behavior
5. **Persist correctly** in existing `contract_metadata` Postgres table

**Constraints:**
- No additional TWS tick subscriptions (use existing 1m bar polling infrastructure)
- Volume data from 1-minute bars only
- Dynamic monitoring with 80 total IBKR subscription cap
- Apply only to `AssetClass.FUTURES` — ETFs, FX, Crypto do not roll

---

## Architecture

### New Service Logic in `tws_daemon.py`

The TWS daemon is extended to poll bars for the roll chain (3 contracts per base symbol) and detect volume-based rolls.

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         TWS Daemon (Enhanced)                                  │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │ AssetClass.FUTURES only:                                          │   │
│  │ Poll bars for roll chain (ESM6, ESU6, ESZ6)                   │   │
│  │ ┌───────────────────────────────────────────────────────────────┐         │   │
│  │  │ Roll Chain Derivation Utility                             │         │   │
│  │  │ derive_roll_chain("ES") = [ESH6, ESM6, ESU6, ESZ6, ...] │   │
│  │  └───────────────────────────────────────────────────────────────┘         │   │
│  │  ┌───────────────────────────────────────────────────────────────┐         │   │
│  │  │ Roll Detection Logic                                       │         │   │
│  │  │ ┌─────────────────────────────────────────────────────┐         │   │
│  │  │  │ 100-bar rolling window, z-score, thresholds        │         │   │
│  │  │  │ - Time-of-day gating (RTH only)              │         │   │
│  │  │  │ - Confirmation window (3 consecutive bars)        │         │   │
│  │  │  │ - Cooldown period (30 min per base symbol)       │         │   │
│  │  │  └─────────────────────────────────────────────────────┘         │   │
│  │  ┌───────────────────────────────────────────────────────┐         │   │
│  │  │ Roll Detected?                                           │         │   │
│  │  │  ┌─────────────────────────────────────────────────┐         │   │
│  │  │  │ 1. Write roll event to Kafka:                  │         │   │
│  │  │  │    "system:events" topic                           │         │   │
│  │  │  │    event_type: "roll"                             │         │   │
│  │  │  │    base_symbol: "ES"                              │         │   │
│  │  │  │    old_symbol: "ESM6"                            │         │   │
│  │  │  │    new_symbol: "ESU6"                            │         │   │
│  │  │  │    roll_gap: 2.50 (abs(close_old - open_new))    │         │   │
│  │  │  │    roll_direction: "up"                          │         │   │
│  │  │  └─────────────────────────────────────────────────┘         │   │
│  │  ┌───────────────────────────────────────────────────────┐         │   │
│  │  │ 2. Update contract_metadata (atomic transaction):       │         │   │
│  │  │  │    - Toggle is_front_month                        │         │   │
│  │  │  │    - Set roll_gap, roll_detected_at                │         │   │
│  │  │  │    - Record roll_direction                         │         │   │
│  │  │  └───────────────────────────────────────────────────────┘         │   │
│  │  ┌───────────────────────────────────────────────────────┐         │   │
│  │  │ 3. Query contract_metadata (each 60s cache):         │         │   │
│  │  │  │ SELECT symbol WHERE is_front_month=true AND         │         │   │
│  │  │  │    base_symbol='ES'                               │         │   │
│  │  │  └───────────────────────────────────────────────────────┘         │   │
│  │  ┌───────────────────────────────────────────────────────┐         │   │
│  │  │ 4. Poll and publish 1m bars for active:          │         │   │
│  │  │  │    - Subscribe via IBKR for ESU6 only               │         │   │
│  │  │  │    - Publish to market.bars:ESU6:1m              │         │   │
│  │  │  └───────────────────────────────────────────────────────┘         │   │
│  │  ┌───────────────────────────────────────────────────────┐         │   │
│  │  │ 5. Post-roll monitoring (10-20 bars):                 │         │   │
│  │  │  │    - Continue polling old contract                      │         │   │
│  │  │  │    - Track settlement/off-market behavior               │         │   │
│  │  │  └───────────────────────────────────────────────────────┘         │   │
│  │  ┌───────────────────────────────────────────────────────┐         │   │
│  │  │ 6. Deactivate after post-roll period:                 │         │   │
│  │  │  │    - Unsubscribe from IBKR                        │         │   │
│  │  │  │    - Remove from polling loop                         │         │   │
│  │  │  └───────────────────────────────────────────────────────┘         │   │
│  │                                                              │   │
│  │                   All services consume market.bars → pipeline →   │   │   │
│  │                   intelligence_features (correct symbol)      │   │   │
│  └─────────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────┘

Key integration: Roll events published to `development.system:events` → All services update their symbol lists from this source of truth.

For ETFs/FX/Crypto: Use `Settings().contracts` directly, no roll monitoring.
```

### Roll Lifecycle

| Phase | Action | Duration | What's Captured | Renaissance Principle |
|--------|---------|----------|-------------------|---------------------|
| Pre-roll | Monitor all 3 contracts | Until volume shift | Instrument everything |
| At roll | Capture gap, toggle `is_front_month` | One bar boundary | Let the system run |
| Post-roll | Monitor for 10-20 bars | Settlement, off-market pricing, slippage | Never drop data |
| Deactivate | Stop polling, free subscription | After capturing transition | Storage is cheapest |

---

## Implementation

### Modified Files

| File | Changes |
|-------|----------|
| `services/tws_daemon.py` | Add roll detection logic, volume tracking, contract querying, roll event publishing |
| `src/core/models.py` | Add `ContractMetadata` pydantic model |
| `src/config/settings.py` | Add `get_active_contracts()` with DB-backed contract resolution |
| `src/core/stream_keys.py` | Add `topic_system_events()` |
| `production/migrations/037_roll_monitor_integration.sql` | Add columns to `contract_metadata`, `system_events` table |
| `services/indicator_service.py` | Add plugin state migration on roll events |
| `services/market_analysis_service.py` | Consume roll events, update symbol list |
| `services/signal_generator_service.py` | Consume roll events, track post-roll performance |
| `services/feature_writer_service.py` | Write roll event markers to `intelligence_features` |
| `production/scripts/historical_backfill.py` | Add roll chain seeding utility |

### Migration 037: Roll Monitor Integration

```sql
-- ============================================================
-- Table: contract_metadata (additions)
-- ============================================================

-- Active contract flag (drives TWS daemon subscription)
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS is_front_month BOOLEAN DEFAULT false;

-- Roll gap (price adjustment at roll) - always positive absolute value
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS roll_gap DOUBLE PRECISION;

-- Roll direction for back-adjustment calculation
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS roll_direction VARCHAR(10) DEFAULT 'unknown';

-- When roll was detected (for outcome tracking)
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS roll_detected_at TIMESTAMPTZ DEFAULT NOW();

-- Roll confirmation counter (for back protection)
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS confirmation_count INTEGER DEFAULT 0;

-- Index for active contract queries
CREATE INDEX IF NOT EXISTS idx_contract_meta_front_month
    ON contract_metadata (base_symbol, is_front_month);

-- Comments
COMMENT ON COLUMN contract_metadata.is_front_month IS 'Currently front-month contract (read by TWS daemon)';
COMMENT ON COLUMN contract_metadata.roll_gap IS 'Price adjustment at roll (abs(close_old - open_new), always positive)';
COMMENT ON COLUMN contract_metadata.roll_direction IS 'Roll direction: up/down';
COMMENT ON COLUMN contract_metadata.roll_detected_at IS 'Timestamp when automated roll detection triggered';
COMMENT ON COLUMN contract_metadata.confirmation_count IS 'Roll confirmation counter (3 consecutive detections before flip)';

-- ============================================================
-- Table: system_events (new)
-- ============================================================

CREATE TABLE IF NOT EXISTS system_events (
    id BIGSERIAL GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    base_symbol VARCHAR(10) NOT NULL,
    old_symbol VARCHAR(10) NOT NULL,
    new_symbol VARCHAR(10) NOT NULL,
    roll_gap DOUBLE PRECISION,
    roll_direction VARCHAR(10),
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    event_data JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_system_events_base_detected
    ON system_events (base_symbol, detected_at DESC);

COMMENT ON TABLE system_events IS 'System-wide events (rolls, configuration changes) with audit trail';
```

---

## Roll Chain Derivation Utility

```python
# src/config/contracts.py (new file)

from datetime import datetime, timedelta
from typing import list

from src.core.models import ContractMetadata

_MONTH_CODES = {
    "H": "03", "M": "06", "U": "09", "Z": "12",
    "F": "01", "G": "04", "J": "05", "K": "05", "M": "06",
    "N": "07", "Q": "08", "V": "10", "X": "11",
}

def derive_roll_chain(base_symbol: str) -> list[ContractMetadata]:
    """Derive 3-contract roll chain from base symbol and expiry codes.

    Returns: [prev, current, next] sorted chronologically.
    Uses IBKR expiry code format to determine month ordering.
    """
    contracts = []
    current_year = datetime.now().year

    for month_code, offset in [
        ("H", -2), ("M", -1), ("U", 0), ("Z", 1),
        ("F", 1), ("G", 2), ("J", 3), ("K", 4),
        ("M", 5), ("N", 6), ("Q", 7), ("V", 8), ("X", 9),
    ]:
        # Construct contract symbol: ES + month_code + 2-digit year
        contract_symbol = f"{base_symbol}{month_code}{current_year % 100:02d}"

        expiry_str = f"{current_year}{_MONTH_CODES[month_code]}"

        # Determine roll_from (previous in chain)
        if contracts:
            roll_from = contracts[-1].symbol
        else:
            roll_from = None

        contracts.append(ContractMetadata(
            symbol=contract_symbol,
            base_symbol=base_symbol,
            asset_class="futures",
            expiry_date=expiry_str,
            roll_from=roll_from,
            roll_to=None,  # Will be set after all contracts generated
        ))

    # Link roll_to for all but last contract
    for i, contract in enumerate(contracts[:-1]):
        contracts[i].roll_to = contracts[i + 1].symbol

    return contracts
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ROLL_MONITOR_ENABLED` | `false` | Feature flag to enable/disable (safe rollout) |
| `ROLL_MONITOR_WINDOW_SIZE` | `100` | Rolling window bars for volume variance |
| `ROLL_MONITOR_THRESHOLD_DEFAULT` | `1.2` | Default volume ratio threshold (20% increase) |
| `ROLL_MONITOR_POSTROLL_BARS` | `10` | Bars to monitor post-roll before deactivation |
| `ROLL_MONITOR_COOLDOWN_MIN` | `30` | Minimum minutes between rolls (circuit breaker per base symbol) |
| `ROLL_CONFIRMATION_BARS` | `3` | Consecutive confirmations required before is_front_month flip |
| `ROLL_TIME_OF_DAY_GATED` | `true` | Enable RTH-only gating (weekend/holiday protection) |

### Environment Variable Example

```bash
# Enable roll monitoring for ESM6, ESU6, ESZ6 (3 contracts per base)
ROLL_MONITOR_ENABLED=true

# Optional: Adjust per base symbol (Renaissance segmented thresholds)
ROLL_THRESHOLDS_ES=1.3
ROLL_THRESHOLDS_NQ=1.5
ROLL_THRESHOLDS_CL=1.6
```

---

## Roll Detection Algorithm

### Input
- 1-minute OHLCV bars for 3 contracts in roll chain
- Rolling window of N bars (default 100)
- Market hours gating (optional, configurable)

### Calculation

```
For each bar close:
    # Time-of-day gate (prevents false rolls on weekend/holiday spikes)
    if ROLL_TIME_OF_DAY_GATED and not self.market_hours.is_open(bar_ts):
        return

    volume_ratio = volume(contract_N) / volume(contract_0)
    rolling_mean = mean(volume of last 100 bars for contract_N)
    rolling_std = std(volume of last 100 bars for contract_0)

    if rolling_std > 0:
        z_score = (volume_N - rolling_mean) / rolling_std
    else:
        z_score = 0  # Insufficient history, skip z-score

    # Primary trigger: volume threshold AND statistical significance
    volume_threshold = get_threshold_for_base(base_symbol)  # Segmented
    threshold_met = (volume_ratio > volume_threshold and z_score > 2.0)

    if threshold_met:
        self._record_detection(base_symbol, contract_N.symbol, volume_ratio, z_score)
```

### Confirmation Window (Roll Back Protection)

```
# Require N consecutive positive detections before committing roll
# This prevents transient volume spikes from triggering false rolls

detection_count = self._detection_counts[base_symbol]
detection_count += 1

if detection_count >= ROLL_CONFIRMATION_BARS:
    # Confirmed: commit roll
    self._execute_roll(old_symbol, new_symbol)
    self._detection_counts[base_symbol] = 0  # Reset after commit
else:
    # Pending: wait for more confirmations
    return  # Don't trigger roll yet
```

### Output

| Action | Data Written |
|---------|---------------|
| Roll detected (confirmed) | `UPDATE contract_metadata SET is_front_month=false WHERE symbol='ESM6'` |
| | `UPDATE contract_metadata SET is_front_month=true, roll_gap=X.XX, roll_direction='up', roll_detected_at=NOW(), confirmation_count=confirmation_count+1 WHERE symbol='ESU6'` |
| | `INSERT INTO system_events (event_type='roll', base_symbol='ES', old_symbol='ESM6', new_symbol='ESU6', ...)` |
| | Publish to `development.system:events` Kafka topic |
| Deactivate | After 10 bars post-roll: `UPDATE contract_metadata SET is_front_month=false WHERE symbol='ESM6'` |
| | Unsubscribe from IBKR, remove from polling loop, keep in qualified list |

---

## Service Contract Resolution

All services must read from **DB-backed active contracts**, not `Settings().contracts`:

```python
# src/config/settings.py

from datetime import UTC, datetime

class Settings(BaseSettings):
    # ... existing fields ...

    _active_contracts_cache: list[Instrument] = []
    _active_contracts_last_refresh: datetime = datetime.min(UTC)

    def get_active_contracts(self) -> list[Instrument]:
        """Return currently active contracts from contract_metadata.

        Queries DB for is_front_month=true contracts.
        Caches for 60 seconds to avoid repeated DB queries.
        Returns Instrument objects for TWS subscription.
        """
        now = datetime.now(UTC)

        # Cache for 60 seconds
        if now - self._active_contracts_last_refresh < timedelta(seconds=60):
            if not self._active_contracts_cache:
                self._refresh_active_contracts()

        return self._active_contracts_cache

    def _refresh_active_contracts(self) -> None:
        """Query contract_metadata and rebuild active contracts cache."""
        # Load all contracts where is_front_month=true
        # Transform to Instrument objects
        self._active_contracts_cache = [...]
        self._active_contracts_last_refresh = datetime.now(UTC)
```

---

## Plugin State Continuity (Never Drop Data)

When `intelligence_features` symbol switches from ESM6 to ESU6, all I1 plugin state resets. This violates "Never drop data."

**Solution: Plugin state migration on roll events.**

```python
# indicator_service.py enhancements

class IndicatorService:
    def __init__(self, ...):
        # ... existing init ...
        self._plugin_state_snapshots: dict[str, dict] = {}
        self._roll_event_queue: asyncio.Queue() = asyncio.Queue()

    async def _consume_roll_events(self):
        """Consume roll events from system_events Kafka topic."""
        async for event in self._kafka_consumer_roll.messages():
            if event["event_type"] == "roll" and event["base_symbol"] in self.active_symbols:
                await self._handle_roll_event(event)

    async def _handle_roll_event(self, event: dict):
        """Migrate plugin state from old to new contract."""
        old_symbol = event["old_symbol"]
        new_symbol = event["new_symbol"]
        base_symbol = event["base_symbol"]

        # 1. Snapshot current state for old contract
        old_state = self._capture_plugin_state(old_symbol, base_symbol)

        # 2. Find new symbol position in roll chain
        roll_chain = self._get_roll_chain(base_symbol)
        new_position = roll_chain.index(new_symbol) if new_symbol in roll_chain else None

        # 3. Transfer state based on position
        if new_position == 0:  # New contract is first in chain
            # Initialize from empty (Renaissance: first contract starts fresh)
            new_state = {}
        elif new_position == 1:  # Second in chain
            # Migrate from previous contract
            prev_symbol = roll_chain[new_position - 1].symbol
            prev_state = self._plugin_state_snapshots.get(f"{base_symbol}:{prev_symbol}", {})
            new_state = self._adjust_state_for_roll(prev_state, event["roll_gap"])
        elif new_position == 2:  # Third in chain
            # Migrate from previous contract (skip first)
            prev_symbol = roll_chain[new_position - 1].symbol
            prev_state = self._plugin_state_snapshots.get(f"{base_symbol}:{prev_symbol}", {})
            new_state = self._adjust_state_for_roll(prev_state, event["roll_gap"])

        # 4. Apply new state
        self._restore_plugin_state(new_symbol, base_symbol, new_state)

        # 5. Emit warmup flag in next intelligence event
        self._warmup_queue.add(f"{base_symbol}:{new_symbol}")

    def _capture_plugin_state(self, symbol: str, base_symbol: str) -> dict:
        """Snapshot all plugin state for symbol."""
        state = {}

        for plugin_name in I1_PLUGINS:
            plugin = self._i1_plugin_cache.get(plugin_name)
            key = f"{base_symbol}:{symbol}"
            if key in self._i1_plugin_states:
                state[plugin_name] = dict(self._i1_plugin_states[key])

        return state

    def _adjust_state_for_roll(self, state: dict, roll_gap: float) -> dict:
        """Adjust plugin state for roll gap.

        Volume-neutral indicators: No change.
        Price-sensitive indicators: Adjust by roll_gap.
        """
        adjusted = {}
        price_sensitive = {"bollinger_bands", "keltner_channel", "donchian_channel"}

        for name, value in state.items():
            if name in price_sensitive and isinstance(value, dict):
                adjusted[name] = {
                    "last_upper": value.get("upper_band", 0) + roll_gap,
                    "last_lower": value.get("lower_band", 0) + roll_gap,
                    **value: {**value}  # Keep all other fields
                }
            else:
                adjusted[name] = value

        return adjusted
```

**Integration with feature_writer:**

Write roll boundary markers to `intelligence_features`:

```sql
INSERT INTO intelligence_features (ts, symbol, tf, i7)
VALUES (NOW(), 'ES', '1m', '{"roll_boundary":"ESM6->ESU6"}'::jsonb)
ON CONFLICT (ts, symbol, tf) DO UPDATE SET i7 = intelligence_features.i7 || '{"roll_boundary":"ESM6->ESU6"}'::jsonb;
```

This marks roll boundary in the feature stream for ML training and historical analysis.

---

## Renaissance-Aligned Enhancements

### 1. Segmented Thresholds (Segment Relentlessly)

Different asset classes exhibit different volume characteristics:

| Base Symbol | Threshold | Rationale |
|--------------|-----------|------------|
| ES, NQ, RTY, YM | `1.2` | High liquidity, sharp transitions |
| CL, GC, SI, HG | `1.5` | Energy markets, gradual shifts |
| ZN, ZF, ZB, ZT | `1.4` | Interest rate products, moderate liquidity |

```python
# In settings.py or environment variable
ROLL_THRESHOLDS = {
    "ES": 1.2, "NQ": 1.2, "RTY": 1.2, "YM": 1.2,
    "CL": 1.5, "GC": 1.5, "SI": 1.5, "HG": 1.5,
    "ZN": 1.4, "ZF": 1.4, "ZB": 1.4, "ZT": 1.4,
}
```

### 2. Time-of-Day Awareness

Volume patterns vary by session:

| Session | Volume Behavior | Threshold Adjustment |
|---------|---------------|-------------------|
| Pre-open (9:30-9:45 ET) | Ramp-up, high noise | `threshold * 1.3` |
| RTH (9:45-16:00 ET) | Stable, true signal | `threshold` (base) |
| Close (15:45-16:00 ET) | Drop-off, late signals | `threshold * 0.9` |
| Post-close (16:00-18:00 ET) | Thin trading | Skip roll detection |

```python
# Time-of-day gating in tws_daemon.py
hour_et = bar_ts.astimezone(ZoneInfo("America/New_York")).hour

if hour_et in (9, 10, 11):  # Pre-open ramp-up
    threshold *= 1.3
elif hour_et == 15:  # Close drop-off
    threshold *= 0.9
elif hour_et in (16, 17, 18):  # Post-close thin
    return  # Skip detection
else:
    # RTH: standard threshold
    pass
```

### 3. Roll Outcome Tracking (Earn the Right Through Proof)

Capture actual roll quality for continuous improvement:

```sql
-- Add to contract_metadata
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS roll_outcome JSONB;

-- Outcome schema stored per roll:
{
    "slippage_bps": 12,  -- Actual slippage vs theoretical
    "slippage_usd": 250,  -- Dollar value of slippage
    "settlement_price": 4325.50,  -- Settlement price of old contract
    "open_price_new": 4328.00,  -- Open of new contract (should match theoretical)
    "timeliness": "early|ontime|late",  -- Was roll early, on-time, or late?
    "detection_latency_sec": 45,  -- Time from volume shift to roll event
    "postroll_behavior": "normal|gap_fill|panic",  -- Observed post-roll pattern
    "cost_estimate_usd": 350  -- Total roll cost estimate (slippage + execution)
}
```

### 4. Roll Prediction (Pre-Warming)

Historical roll dates are highly predictable (monthly pattern, exchange-specific):

```sql
-- Materialized view for pattern analysis
CREATE MATERIALIZED VIEW roll_prediction AS
SELECT
    base_symbol,
    exchange,
    AVG(EXTRACT(MONTH FROM roll_date)) AS predicted_month,
    STDDEV(roll_date) AS variability_days,
    COUNT(*) AS roll_count,
    MAX(roll_detected_at) AS last_roll
FROM contract_metadata
GROUP BY base_symbol, exchange;

-- Predict roll date 5 days in advance
SELECT base_symbol, predicted_month
FROM roll_prediction
WHERE last_roll + INTERVAL '5 days' < EXTRACT(MONTH FROM roll_date);
```

Pre-warm monitoring on predicted roll dates — earlier detection, lower latency.

### 5. Roll Back Protection

Recovery mechanism for false rolls:

```python
# In tws_daemon.py
ROLL_BACK_WINDOW_BARS = 10

def _verify_roll_after_commit(self, base_symbol: str, new_symbol: str) -> bool:
    """Verify roll was correct by monitoring next N bars."""

    # Get last roll gap from contract_metadata
    gap = self._get_last_roll_gap(base_symbol)

    # Monitor new contract for ROLL_BACK_WINDOW_BARS bars
    for bar in self._monitor_new_contract_bars(new_symbol, limit=ROLL_BACK_WINDOW_BARS):
        # If volume shifts back to old contract (was early roll)
        # AND gap sign suggests we should have rolled up
        if self._volume_shifted_back(new_symbol, bar) and gap < 0:
            # Roll back: notify, flip is_front_month
            logger.warning("False roll detected, reverting",
                         base=base_symbol, old=new_symbol, new=self.current)
            self._rollback_roll(base_symbol, new_symbol)
            return False

    return True  # Roll verified
```

### 6. Paper Trading Account Handling

Some futures unavailable on paper accounts:

```python
# In tws_daemon.py
def _is_paper_account(self) -> bool:
    """Detect if running against paper trading."""
    return self.settings.ib_host in ("192.168.1.157", "127.0.0.1")

def _get_unavailable_symbols(self) -> set[str]:
    """Return contracts unavailable on paper."""
    paper_unavailable = {"BZJ6", "NGJ6", "SR1H6", "ZWH6"}
    return paper_unavailable if _is_paper_account() else set()
```

- Skip roll monitoring for unavailable contracts
- Log warning when paper account detected
- Add status endpoint for paper account mode

### 7. Cooldown Logic (Circuit Breaker)

Prevent rapid back-and-forth rolls:

```python
# Per base symbol cooldown tracking
self._last_roll_time: dict[str, datetime] = {}
self._cooldown_period_minutes = 30

def _is_in_cooldown(self, base_symbol: str) -> bool:
    """Check if base symbol is in cooldown period."""
    last_roll = self._last_roll_time.get(base_symbol)
    if last_roll and (datetime.now(UTC) - last_roll) < timedelta(minutes=self._cooldown_period_minutes):
        return True
    return False
```

Cooldown prevents oscillation while still allowing genuine rapid rolls in unusual market conditions (if statistically validated across multiple consecutive detections).

---

## Testing Strategy

### Unit Tests

1. `test_roll_chain_derivation.py` — Verify month code ordering, edge cases
2. `test_roll_detection_algorithm.py` — Volume ratio, z-score, thresholds
3. `test_service_contract_resolution.py` — DB-backed active contracts, cache behavior
4. `test_plugin_state_migration.py` — State transfer accuracy, roll gap adjustments
5. `test_kafka_roll_events.py` — Roll event propagation, consumer rebalance
6. `test_time_of_day_gating.py` — Session-aware detection
7. `test_rollback_protection.py` — False roll recovery
8. `test_paper_account_handling.py` — Unavailable contract handling

### Integration Tests

1. `test_roll_end_to_end_flow.py` — Full pipeline with mock IBKR data
2. `test_multiple_simultaneous_rolls.py` — ES and NQ rolling together
3. `test_weekend_false_positive.py` — Verify gating works
4. `test_roll_reversal.py` — Roll back and re-roll sequence
5. `test_roll_latency_metrics.py` — Prometheus metrics verification

### Backtest Validation

1. Run historical backtest using actual roll dates
2. Compare manual roll dates (from audit logs) vs. automated detection
3. Measure slippage vs. theoretical at each roll
4. Calculate cost of late rolls vs. on-time rolls

---

## Verification

1. **Enable feature flag** — Set `ROLL_MONITOR_ENABLED=true` for one base symbol (ES) with shadow mode
2. **Seed contract_metadata** — Run `historical_backfill.py --seed-roll-chain` to populate roll chains
3. **Simulate volume shift** — Manually update a few `intelligence_features` bars to trigger volume ratio shift
4. **Observe detection** — Check `tws_daemon` logs for "Roll detected" message
5. **Verify DB updates** — Query `contract_metadata` to confirm `is_front_month` toggled correctly
6. **Check roll event** — Verify `system_events` row written
7. **Verify Kafka propagation** — Ensure roll event reaches downstream services
8. **Test deactivation** — After 10 bars, confirm old contract unsubscribed
9. **Verify no restart** — Confirm `intelligence_features` bars continue flowing with new symbol
10. **Test rollback** — Manually trigger false roll, verify rollback logic activates
11. **Test edge cases** — First roll, paper account, weekend, multiple simultaneous rolls
12. **Shadow mode** — Disable auto-detection, verify manual operation still works

---

## Migration from Design to Implementation

This design adds **significant architectural changes** to support automated roll detection. Before implementation:

### Must-Have Before `/gsd:plan-phase`:

1. [ ] Roll chain derivation utility in `src/config/contracts.py` OR migration to seed `contract_metadata`
2. [ ] DB-backed `get_active_contracts()` in `Settings.py` with caching
3. [ ] `system_events` table created (migration 037)
4. [ ] Roll event Kafka topic created (`topic_system_events`)
5. [ ] Plugin state migration mechanism designed
6. [ ] All downstream services consume roll events
7. [ ] Roll boundary markers written to `intelligence_features`
8. [ ] Comprehensive test coverage for new roll logic

### Design Decisions Needed During Planning:

1. **Roll event delivery:** Kafka `system_events` topic vs. direct DB queries?
2. **Plugin state sync timing:** When to capture snapshot vs. when to apply?
3. **Roll back triggering:** Automatic vs. manual operator action?
4. **Shadow mode semantics:** When enabled, does it skip detection only, or all roll execution?
5. **Outcome tracking storage:** JSONB in `contract_metadata` vs. dedicated table?
6. **Test data generation:** How to create realistic volume shift scenarios for testing?

---

## Notes

- **ETFs, FX, Crypto:** No roll monitoring, use `Settings().contracts` directly
- **Paper trading:** Skip roll monitoring for unavailable contracts (BZJ6, NGJ6, etc.)
- **Shadow mode:** Feature flag `ROLL_MONITOR_ENABLED=false` disables detection entirely, manual operation
- **Feature flag rollout:** Start with `false` (shadow mode), observe system, enable per base symbol after validation
- **Renaissance iteration:** Ship basic system with outcome tracking (v1.9), add segmented thresholds and prediction in v2.0 based on actual roll data
