# Phase 23: Signal Generator Gate — Research

## RESEARCH COMPLETE

**Source:** Code analysis + todo `.planning/todos/pending/2026-03-10-research-and-fix-signal-generator-condition-vs-event-firing-and-direction-flip-gate.md`

---

## Problem Analysis

### Issue 1: Condition vs Event (plugins fire every bar)

All 17 I7 plugins are condition detectors. If FVG is open, `trad_FVGFill` fires every bar the FVG remains open — not just on first occurrence. This means:
- Same setup re-published every bar without any new trigger
- Consecutive bars with identical direction/entry/stop persisted to `signal_ledger`
- Observed: 19:50 LONG → 19:55 SHORT on same FVGFill plugin — `fvg_type` flipped +1 → -1 in the SMC detector between two 5m bars

### Issue 2: Zero cross-bar memory in signal_generator_service

`_process_bar()` has no knowledge of prior bar state. No:
- `_last_published` cache per `(symbol, timeframe)`
- Direction flip suppression
- Cooldown / minimum bars between signals
- Check whether prior signal is still pending/active

Every bar independently: run all plugins → aggregate → publish winner.

### Issue 3: Dead InputSpec `timeframe="1m"` on I7 plugins

Every I7 plugin has `inputs: InputSpec(timeframe="1m")` but `signal_generator_service` processes ALL configured TFs and passes `frames["main"]` = current TF's OHLCV regardless of InputSpec. The `timeframe="1m"` in InputSpec is silently ignored. Dead code from when signals were 1m-only.

### Issue 4: 4h/1d not processed at intelligence or signal layer

- `indicator_service`: processes `["1m", "5m", "15m", "1h", "4h", "1d"]`
- `market_analysis_service`: processes `["1m", "5m", "15m", "1h"]` — no 4h/1d
- `signal_generator_service`: processes `["1m", "5m", "15m", "1h"]` — no 4h/1d

Decision: explicitly exclude with comments (day-trading focus, low signal frequency on 4h/1d).

---

## Codebase Analysis

### signal_generator_service.py structure

```
__init__()                    ~line 360: service state initialization
_setup_config()               ~line 424: config loading
_process_bar(symbol, tf, ...)  ~line 560: main bar processing loop
  → runs all I7 plugins
  → aggregates via CISAggregator
  → publishes to signals:SYMBOL:TF:aggregated
_run()                         main service loop
```

### Stream key for lifecycle resolution

Per `src/core/stream_keys.py`, signal lifecycle publishes to `signals:SYMBOL:TF:aggregated` with `direction=0` as terminal/resolved events. This is the same stream signal_generator_service publishes to — so signal_generator can subscribe to its own stream output to detect resolutions.

### CISAggregator output shape

`aggregator.py` returns a dict with at minimum: `direction`, `entry`, `stop`, `targets`, `signal_id`, `setup_name`. Direction is `+1` (long) or `-1` (short); `0` means no signal fired.

### tf_seconds lookup

`src/core/service_utils.py` has `min_bars_for_tf()` — can derive TF seconds via: `{"1m": 60, "5m": 300, "15m": 900, "1h": 3600}`.

---

## Validation Architecture

### Unit Tests Required

1. **Signal gate cooldown test**: assert gate suppresses same-direction re-publish within MIN_BARS window
2. **Direction flip suppression test**: assert gate blocks direction flip while prior signal unresolved
3. **Direction flip allowed after resolution**: assert gate allows flip after `direction=0` lifecycle exit
4. **Gate on first signal**: assert no gate = first signal always publishes
5. **InputSpec timeframe value test**: assert all I7 plugins have `timeframe=".*"` (or confirm field unused)
6. **4h/1d exclusion test**: assert service config explicitly excludes 4h/1d with documentation

### Integration Tests (optional, requires live infra)
- Simulate 5 consecutive FVG condition bars → assert only 1 signal published
- Simulate direction flip before resolution → assert second signal blocked

### Regression Tests
- Existing `tests/unit/service_tests/test_signal_generator_service.py` must pass
- Existing plugin tests must pass (InputSpec change must be backward-compatible)
