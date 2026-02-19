# Data Collection Efficiency — Design

> **Date:** 2026-02-18
> **Status:** Approved
> **Scope:** `production/daemons/high_frequency_tws_daemon.py` + downstream bar consumers

---

## Problem

The 1-minute bar pipeline has two deficiencies:

1. **Bar latency is 0–60 seconds** (average 30s). The polling loop fires every 60 seconds with a random phase offset relative to bar close. A bar that closes at 14:00:00 might not enter the Redis stream until 14:00:59.

2. **Dead code.** The legacy synchronous tick path (`tick_buffer` deque + `process_tick_buffer()`) is unreachable when `HF_ASYNC_PUBLISH=True` (the default). ~65 lines of code that confuse readers and will never run.

---

## Design

### Section 1 — Minute-Aligned Poll + Tick-Derived Provisional Bar

**Root cause of lag:** `high_frequency_tws_daemon.py:576` sets `bar_polling_interval = 60.0`. The polling loop fires at `now_ts - last_bar_poll >= 60.0` — entirely decoupled from the 60-second bar-close boundary. Average delay from bar close to bar availability: 30 seconds.

**Fix:** Replace the countdown timer with a minute-boundary check. Fire `reqHistoricalData` at `:05` past each minute (enough time for the exchange to finalize the bar and IB to process it). This is still exactly 1 API call per minute per symbol — zero overhead increase.

```python
# Replace:
if now_ts - self.last_bar_poll >= self.bar_polling_interval:

# With:
if now.second >= 5 and self.last_bar_poll_minute != now.minute:
    self.last_bar_poll_minute = now.minute
    ...poll...
```

This reduces worst-case latency from 60s → 10s. Average from 30s → 7s.

**Tick-derived provisional bar:** Accumulate `last` price and volume in `on_pending_tickers` (already called 100–500×/sec). At the minute boundary (`:00`) flush a provisional bar to the Redis stream:

```python
source: "tick_derived"    # marks as provisional
open, high, low, close    # from tick accumulator
volume                    # delta of ticker.volume since accumulator reset
```

Lag: ~1 second after bar close. The authoritative `reqHistoricalData` bar arrives at `:05–:10` and replaces it.

**Volume note:** `ticker.volume` is cumulative daily volume. Per-minute volume = delta between accumulator start and flush. If reconnected mid-minute, that bar's volume is understated — the authoritative correction fixes history within 10 seconds. Non-issue for intelligence calculations.

---

### Section 2 — Downstream Correction Handling

Two rules applied in `intelligence_processor_service.py` and `signal_orchestrator_service.py`:

**Rule 1 — Source filter:** Only `source: "tick_derived"` triggers pipeline execution. `source: "authoritative"` silently updates bar history only. This prevents double-computing a bar (once on provisional, once on correction).

```python
bar_data = {fields from message}
source = bar_data.get("source", "authoritative")

if source == "tick_derived":
    bar_history[key].append(bar_data)
    await self._process_bar(symbol, timeframe, bar_data)
else:
    # Authoritative correction — update history, skip pipeline
    if bar_history[key] and bar_history[key][-1]["timestamp"] == bar_data["timestamp"]:
        bar_history[key][-1] = bar_data
    else:
        bar_history[key].append(bar_data)
```

**Rule 2 — Timestamp dedup:** When an authoritative bar arrives with the same timestamp as the last bar in history, replace it in-place. Downstream services that subsequently read the history deque see authoritative data without re-executing.

This means:
- ML features are computed on provisional data (~1s latency)
- History deques converge to authoritative data within 10s
- No bar is ever computed twice

---

### Section 3 — Dead Code Removal

Remove from `high_frequency_tws_daemon.py`:

| What | Why |
|------|-----|
| `tick_buffer = deque(maxlen=1000)` | Never read in async mode |
| `process_tick_buffer()` method | Unreachable with `HF_ASYNC_PUBLISH=True` |
| `bar_polling_interval = 60.0` | Replaced by minute-boundary check |
| Old `if now_ts - self.last_bar_poll >= ...` block | Replaced |

~65 lines removed. No behavior change (this code was already never executing).

---

## Files Changed

### Modified
```
production/daemons/high_frequency_tws_daemon.py
  - Remove tick_buffer deque and process_tick_buffer()
  - Remove bar_polling_interval countdown timer
  - Add last_bar_poll_minute state variable
  - Add minute-boundary poll check (fire at :05)
  - Add tick accumulator in on_pending_tickers (open, high, low, close, volume_delta)
  - Flush provisional bar at :00 with source="tick_derived"
  - Add source="authoritative" to reqHistoricalData publish path

services/intelligence_processor_service.py
  - Add source field handling in _process_single_bar
  - Add timestamp dedup in bar_history update

services/signal_orchestrator_service.py  (new, from signal-orchestrator plan)
  - Written with source field handling and timestamp dedup from the start
```

---

## Metrics

| Metric | Before | After |
|--------|--------|-------|
| Bar latency (worst case) | 60s | 10s |
| Bar latency (average) | 30s | 7s |
| Bar latency (provisional) | N/A | ~1s |
| API calls/min/symbol | 1 | 1 |
| Dead code lines | ~65 | 0 |

---

## Testing Approach

Unit tests (no IB connection):
- `test_daemon_minute_boundary.py` — fires at :05, not on arbitrary countdown
- `test_daemon_tick_accumulator.py` — OHLCV accumulation and volume delta
- `test_daemon_provisional_bar.py` — provisional bar has `source: "tick_derived"`
- `test_intelligence_source_filter.py` — `source: "authoritative"` skips pipeline
- `test_intelligence_timestamp_dedup.py` — in-place replacement of matching timestamp

Target: ~12 new tests.
