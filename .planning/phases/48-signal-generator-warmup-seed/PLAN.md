# Signal Generator Warmup Seed - Implementation Plan

## Context

**Problem:** `signal_generator_service` fails to process signals after restart because `BarHistory` is empty. I7 plugins require 50+ historical bars to compute, but the service starts with only the current bar.

**Root Cause:** Phase 26 warmup seed was removed during BarHistory refactoring (commit bc2c71a) and never restored.

**Impact:** `bars_processed_total = 0`, all I7 plugins early-return, no signals generated until 50+ live bars accumulate (~50+ minutes).

## Solution

Restore DB warmup seed to `signal_generator_service.py` following Renaissance principles:
- **Efficient:** One indexed query on startup, not per-bar
- **Simple:** ~50 lines, isolated method
- **Fault-tolerant:** Graceful fallback if DB unavailable
- **Automated:** Runs on every startup, zero manual tasks
- **Minimal:** Query only what BarHistory needs

## Architecture

```
signal_generator_service.start()
  ↓
_connect_database()
  ↓
_seed_bar_history_from_db()  ← NEW METHOD
  ↓ (for each symbol, tf)
  Query intelligence_features:
    SELECT ts, bar, session_type
    FROM intelligence_features
    WHERE symbol=$1 AND tf=$2
    ORDER BY ts DESC LIMIT 50
  ↓
  Reconstruct BarMessage from each row
  ↓
  Append to BarHistory
  ↓
  _setup_kafka_clients()
  ↓
  Process live events (BarHistory now has 50 bars)
```

## Implementation

### File: `services/signal_generator_service.py`

**1. Add `_seed_bar_history_from_db()` method**

```python
async def _seed_bar_history_from_db(self) -> None:
    """Seed BarHistory from intelligence_features on startup.

    Queries last 50 bars per (symbol, tf) from intelligence_features
    and populates BarHistory to eliminate warmup delay.

    Gracefully degrades if DB unavailable: logs WARNING and proceeds
    with empty BarHistory (falls back to live warmup).
    """
    if not self.db_manager:
        self.logger.warning("DB seed failed - no db_manager, falling back to live warmup")
        return

    active_contracts = get_active_contracts()
    timeframes = self.config["service"]["timeframes"]  # ["1m", "5m", "15m", "1h"]

    try:
        for symbol in active_contracts:
            for tf in timeframes:
                query = """
                    SELECT ts, bar, session_type
                    FROM intelligence_features
                    WHERE symbol = $1 AND tf = $2
                    ORDER BY ts DESC
                    LIMIT 50
                """

                rows = await self.db_manager.execute_query(
                    query, (symbol, tf)
                )

                if not rows:
                    continue

                # Process rows in reverse (oldest first) to maintain chronological order
                for row in reversed(rows):
                    ts = row["ts"]
                    bar_data = row["bar"]  # JSONB: {"o": x, "h": y, "l": z, "c": w, "v": n}
                    session_type = row.get("session_type", "rth")

                    # Reconstruct BarMessage
                    bar_msg = BarMessage(
                        ts=ts,
                        symbol=symbol,
                        tf=tf,
                        open=bar_data["o"],
                        high=bar_data["h"],
                        low=bar_data["l"],
                        close=bar_data["c"],
                        volume=bar_data["v"],
                        source="ibkr_seed",  # Mark as seeded from DB
                        session_type=SessionType(session_type) if session_type else SessionType.RTH,
                        gap_preceding=False,
                    )

                    self._bar_history.append(bar_msg)

        self.logger.info(
            "BarHistory seeded from database",
            symbols=len(active_contracts),
            timeframes=len(timeframes)
        )

    except Exception as e:
        self.logger.warning(
            "DB seed failed - falling back to live warmup",
            error=str(e)
        )
        # Proceed with empty BarHistory - service will warm up from live data
```

**2. Call during startup (in `start()` method)**

```python
async def start(self) -> None:
    self.logger.info("Starting Signal Generator Service")

    try:
        await self._connect_database()

        # SEED BAR HISTORY BEFORE CONSUMER STARTS
        await self._seed_bar_history_from_db()

        await self._setup_kafka_clients()
        # ... rest of startup
```

**3. Add import**

```python
from src.core.schemas.bar_message import BarMessage, SessionType
```

## Testing

### Unit Test: `test_seed_bar_history_from_db()`

```python
@pytest.mark.asyncio
async def test_seed_bar_history_from_db_success(mock_db_manager):
    """Test successful seeding populates BarHistory with 50 bars."""
    # Mock DB response with 2 bars
    mock_rows = [
        {
            "ts": datetime(2026, 3, 23, 14, 0, tzinfo=UTC),
            "bar": {"o": 4500.0, "h": 4505.0, "l": 4498.0, "c": 4502.0, "v": 1000},
            "session_type": "rth"
        },
        {
            "ts": datetime(2026, 3, 23, 14, 1, tzinfo=UTC),
            "bar": {"o": 4502.0, "h": 4506.0, "l": 4500.0, "c": 4504.0, "v": 1200},
            "session_type": "rth"
        }
    ]
    mock_db_manager.execute_query.return_value = mock_rows

    service = SignalGeneratorService()
    service.db_manager = mock_db_manager
    await service._seed_bar_history_from_db()

    # Verify BarHistory populated
    bars = service._bar_history.get("ES", "1m")
    assert len(bars) == 2
    assert bars[0].close == 4502.0
    assert bars[1].close == 4504.0
```

### Integration Test

```python
@pytest.mark.asyncio
async def test_seed_enables_signal_processing():
    """Test that seeded BarHistory allows I7 plugins to process bars."""
    # Start service with DB seed
    # Send live bar
    # Verify I7 plugin computes (no early return from min_bars check)
    # Verify bars_processed_total increments
```

## Verification

1. **Service startup:** `journalctl -u indicant-signal-generator -f` shows "BarHistory seeded from database"
2. **Metrics:** `generator_bars_processed_total` increments on first live bar (not stays at 0)
3. **Signal generation:** First bar after restart can generate signals (no 50-min wait)
4. **Graceful degradation:** Stop TimescaleDB, restart service → logs WARNING, starts anyway (live warmup fallback)

## Success Criteria

- [ ] BarHistory seeded with 50 bars per (symbol, tf) on startup
- [ ] `bars_processed_total` increments immediately (not stuck at 0)
- [ ] Service starts successfully even if DB unavailable
- [ ] No regressions in existing tests
- [ ] Code review approved

## Files Modified

- `services/signal_generator_service.py` (~60 lines added)
- `tests/unit/service_tests/test_signal_generator_service.py` (tests added)

## Dependencies

- `intelligence_features` table must exist and contain data
- Index on `(symbol, tf, ts DESC)` ensures fast query (exists: `idx_intel_features_sym_tf_ts`)

## Compute Cost

- **Startup only:** One query per (symbol, tf) combination
- ~12 contracts × 4 timeframes = 48 queries
- Each query returns 50 rows
- Total: ~2400 rows on startup
- **Zero ongoing cost** - no per-bar overhead

## Maintenance

- Isolated method (clear responsibility)
- Fault-tolerant (graceful fallback)
- Zero manual tasks (automatic on startup)
