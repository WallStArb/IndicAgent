> **HISTORICAL DOCUMENT** — `intelligence_processor_service.py` was deleted in Phase 1 (2026-02-23). References to it in this doc are for historical context only. The canonical service is now `market_analysis_service.py`.

# Signal Orchestrator Service — Design

> **Date:** 2026-02-18
> **Status:** Approved
> **Implements:** I7 Phase 2 — Live data collection flywheel

---

## Problem

The 5 I7 trading setup plugins, signal aggregator, lifecycle tracker, and signal ledger are all
built and tested. Nothing calls them. The `signal_ledger` table is empty. The ML calibration
flywheel cannot start until live signal outcome data accumulates (~500 signals, ~17 days of
running).

This service closes that gap.

---

## What It Does

`SignalOrchestratorService` is a single background service that runs on every bar close for
configured symbols/timeframes. It:

1. Runs all 5 I7 setup plugins and collects raw signals
2. Aggregates signals (conflict resolution, confidence boosting)
3. Inserts every signal — winners and losers — into `signal_ledger`
4. Publishes the winner to `signals:SYMBOL:TF:aggregated` (SSE-delivered to dashboard)
5. Evaluates open signals for price-based transitions (activation, stops, targets, expiry)
6. Updates `signal_ledger` with lifecycle transitions and P&L

---

## Architecture

### Stream Design

The intelligence stream is extended to be a **fully self-contained enriched bar event** — it
carries both the I1-I6 feature vector and the raw OHLCV bar that triggered computation. This
is a one-line change to `intelligence_processor_service.py`.

```
market:SYMBOL:TF ──► intelligence_processor_service ──► intelligence:SYMBOL:TF
                                                          {features..., open, high, low, close, volume}
                                                                        │
                                                          signal_orchestrator_service
                                                                        │
                                          ┌─────────────────────────────┼──────────────────────────┐
                                          ↓                             ↓                          ↓
                                 signal_ledger (DB)    signals:SYMBOL:TF:aggregated          DB lifecycle
                                 all signals logged    winner published to SSE              updates (P&L)
```

### Why Not Two Streams

The naive approach (subscribe to both `market:*` and `intelligence:*`) creates a sync problem:
the market stream must be drained before intelligence messages can be processed, or bar history
will be stale. It also duplicates bar state across two processes.

Enriching the intelligence stream eliminates this entirely. The orchestrator subscribes to one
stream, builds its bar history from that stream, and has everything it needs in one event. Any
future downstream service benefits from the same clean tap point.

### Service Layout

```
services/signal_orchestrator_service.py   ← new
config/signal_orchestrator.json           ← new
production/systemd/signal-orchestrator.service  ← new (if systemd used)
```

Modification:
```
services/intelligence_processor_service.py  ← add 5 OHLCV fields to _publish_intelligence()
```

---

## Per-Bar Processing Logic

On each `intelligence:SYMBOL:TF` message:

### 1. Buffer bar + parse features
```
bar = {open, high, low, close, volume, timestamp}  ← from message fields
bar_history[symbol:tf].append(bar)                 ← deque(maxlen=200)

features = {k: float(v) for non-OHLCV fields in message}
frames = {"main": DataFrame(bar_history), "features": features}
```

### 2. Run I7 setup plugins (skip if < min_history_bars=50)
```
I7_PLUGINS = [trad_TrendFollowing, trad_MeanReversion, trad_LiquiditySweepReclaim,
              trad_MTFAlignment, trad_SqueezeExpansion]

raw_signals = [plugin.compute_full(frames) for plugin in I7_PLUGINS
               if result.direction != 0]
```

### 3. Aggregate
```
result = aggregate(raw_signals, trend_regime=features["trend_regime"])
→ AggregatedResult(selected_signal, all_ranked, resolution_method, ...)
```

### 4. Insert all signals to ledger
```
entries = [LedgerEntry(..., was_selected=(rank==1 and selected exists), ...)]
await insert_signals(db, entries)
```
Every signal is logged — winners (`was_selected=True`) and losers (`was_selected=False`).
Losers are negative examples for ML training.

### 5. Publish winner
```
if result.selected_signal:
    await redis.xadd(signals_aggregated(prefix, symbol, tf), {...}, maxlen=200)
```

### 6. Lifecycle tracking
```
active = await get_active_signals(db, symbol=symbol)
for sig in [s for s in active if s["timeframe"] == tf]:
    transition = evaluate_signal(sig, high=bar.high, low=bar.low, close=bar.close)
    if transition:
        await update_signal_status(db, transition.signal_id, ...)
```

---

## Key Design Decisions

### `ttl_bars` by timeframe
Plugins don't set TTL. The orchestrator injects it based on timeframe:

| Timeframe | TTL bars | Real time |
|-----------|----------|-----------|
| 5m        | 20       | ~100 min  |
| 15m       | 12       | ~3 hours  |
| 1h        | 6        | ~6 hours  |

### `confluence_score` in LedgerEntry
Sourced from `features.get("ctf_score", 0.0)` — the I6 cross-timeframe confluence output.
This is the highest-quality confluence signal in the system and a strong ML feature.

### `market_context` snapshot (JSONB)
10 fixed keys captured per signal for future ML feature extraction:
```
trend_regime, volatility_regime, trend_confidence, atr_14, rsi_14,
ctf_score, swing_pattern, trend_strength, volatility_percentile, hmm_regime_state
```
Fixed set (not configurable) — ML training requires stable feature vectors.

### `point_value` for P&L
Looked up from `Settings().contracts` by symbol prefix at startup. Never hardcoded.
Passed into `evaluate_signal()` so P&L is in real dollars.

### Consumer group strategy
- **Intelligence stream:** `xreadgroup` — exactly-once processing on restart. If service
  crashes mid-bar, it resumes from the last unacked message.
- **Market stream:** Not consumed. Bar data arrives via the enriched intelligence stream.

### Lifecycle filter by timeframe
`get_active_signals(db, symbol=symbol)` returns signals across all timeframes for a symbol.
The orchestrator filters to `timeframe == tf` before evaluating — a 5m ES signal is only
evaluated on 5m ES bars, not 15m bars.

---

## Configuration

`config/signal_orchestrator.json`:
```json
{
  "redis": {"host": "localhost", "port": 6379, "db": 0},
  "database": {"url": "postgresql://postgres:postgres@localhost:5432/indicagent"},
  "service": {
    "symbols": ["ESU5", "NQU5", "RTYU5"],
    "timeframes": ["5m", "15m"],
    "min_history_bars": 50,
    "processing_interval": 0.1,
    "health_check_interval": 30
  },
  "logging": {
    "level": "INFO",
    "file": "logs/signal_orchestrator.log",
    "max_size": "10MB",
    "backup_count": 5
  }
}
```

**Timeframe choice rationale:** 5m and 15m produce meaningful setups at useful frequency.
1m is too noisy for the setup plugins' regime-based logic. 1h accumulates data too slowly.

---

## Prometheus Metrics (port 9112)

| Metric | Description |
|--------|-------------|
| `orchestrator_bars_processed_total` | Total intelligence events processed |
| `orchestrator_signals_generated_total` | Total signals inserted to ledger |
| `orchestrator_signals_selected_total` | Signals where was_selected=True |
| `orchestrator_lifecycle_transitions_total` | Signal status updates |
| `orchestrator_calculation_duration_ms` | Per-bar processing time |
| `orchestrator_active_signals_count` | Current pending/active signal count |
| `orchestrator_errors_total` | Total errors |

---

## Testing Approach

Unit tests (no Redis, no DB):
- `test_signal_orchestrator_frames.py` — frame reconstruction from intelligence message fields
- `test_signal_orchestrator_assembly.py` — LedgerEntry assembly from AggregatedResult
- `test_signal_orchestrator_ttl.py` — TTL injection by timeframe
- `test_signal_orchestrator_lifecycle_filter.py` — timeframe filtering of active signals
- `test_intelligence_processor_ohlcv.py` — enriched message includes OHLCV fields

Integration test:
- `test_signal_orchestrator_integration.py` — full bar → signal → ledger insert flow with
  mocked Redis and real DB (or mock DB)

Target: ~20 new tests.

---

## Files Changed

### New
```
services/signal_orchestrator_service.py
config/signal_orchestrator.json
```

### Modified
```
services/intelligence_processor_service.py   ← add OHLCV to _publish_intelligence()
```

### New tests
```
tests/unit/services/test_signal_orchestrator_frames.py
tests/unit/services/test_signal_orchestrator_assembly.py
tests/unit/services/test_signal_orchestrator_ttl.py
tests/unit/services/test_signal_orchestrator_lifecycle_filter.py
tests/unit/services/test_intelligence_processor_ohlcv.py
tests/integration/test_signal_orchestrator_integration.py
```

---

## Expected Outcome

With ES, NQ, RTY on 5m + 15m:
- ~3 symbols × 2 timeframes × ~3 signals/day = ~18 signals/day
- 500 signals in ~28 days
- ML calibration of aggregator priority weights becomes possible after that
