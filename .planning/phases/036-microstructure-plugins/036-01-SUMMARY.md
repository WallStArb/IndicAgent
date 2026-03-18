---
phase: 036-microstructure-plugins
plan: 01
subsystem: intelligence
tags: [ofi, cvd, microstructure, i1-indicators, tick-data, kafka, indicator-service]

requires:
  - phase: 034-avwap-volume-profile
    provides: "I1 indicator plugin pattern (OBV, CMF) and register_plugins.py structure"
  - phase: 038-automated-futures-roll-detection
    provides: "topic_market_ticks() in stream_keys.py, KafkaConsumerClient pattern"

provides:
  - "OFIPlugin I1 indicator: ofi_ewma_5, ofi_ewma_20, ofi_divergence, ofi_spike_z, ofi_variant"
  - "CVDPlugin I1 indicator: cvd, cvd_slope_5bar, cvd_divergence, cvd_spike_z"
  - "Tick consumer in indicator_service (group_id=indicator_service_ticks)"
  - "Per-symbol _tick_buffers defaultdict flushed at bar close"

affects: [036-microstructure-plugins, 037-cross-asset-intelligence]

tech-stack:
  added: []
  patterns:
    - "Tick/proxy dual-path pattern: I1 plugins check frames['tick_buffer']; non-empty=tick rule, empty=OHLCV proxy"
    - "Session reset via zoneinfo ET: et_hour==9 and et_minute>=30 and et_date != last_session_date"
    - "Deque-based state for EWMA and z-score history (maxlen=100)"
    - "Separate Kafka consumer group per data type (indicator_service vs indicator_service_ticks)"

key-files:
  created:
    - src/intelligence/indicators/ofi.py
    - src/intelligence/indicators/cvd.py
    - tests/unit/intelligence/indicators/test_ofi.py
    - tests/unit/intelligence/indicators/test_cvd.py
  modified:
    - services/indicator_service.py
    - src/intelligence/register_plugins.py
    - tests/unit/intelligence/test_plugin_registry.py
    - tests/unit/intelligence/test_i7_registration.py

key-decisions:
  - "OFI proxy uses (close-low)/(high-low)*volume (Williams %R-style); CVD proxy uses (2c-h-l)/(h-l)*volume (CMF-style) — different proxies for different signal semantics"
  - "Tick buffer keyed by symbol only (not symbol:tf) — ticks arrive before bar association; bar close flushes and clears buffer for that symbol"
  - "EWMA initialized to first raw_ofi value (no cold-start bias); state persisted per (plugin_name, symbol, tf) via existing _i1_plugin_states mechanism"
  - "TIER_I1 grows from 25 to 27 (OFI + CVD); total plugin count 111 to 113"

requirements-completed: [OFI-01, OFI-02, CVD-01]

duration: 8min
completed: 2026-03-18
---

# Phase 036 Plan 01: OFI + CVD I1 Microstructure Indicators Summary

**OFI and CVD microstructure indicators added to I1 tier with tick/proxy dual-path, EWMA state, session reset, and separate Kafka tick consumer in indicator_service**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-18T05:49:18Z
- **Completed:** 2026-03-18T05:57:06Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Created OFIPlugin: tick rule on raw tick data (primary), OHLCV proxy fallback, EWMA-5/20, spike z-score, signed divergence vs price direction, ofi_variant auditing
- Created CVDPlugin: cumulative volume delta with 09:30 ET session reset, 5-bar polyfit slope, divergence vs 5-bar price change, spike z-score, same tick/proxy dual path
- Wired tick consumer into indicator_service: separate `group_id="indicator_service_ticks"`, per-symbol `_tick_buffers` flushed atomically at bar close, seed path uses `tick_buffer=[]` for proxy mode
- 19 passing unit tests covering all behavioral cases; TIER_I1 updated to 27 plugins, total count 113

## Task Commits

1. **Task 1: OFIPlugin + CVDPlugin with unit tests (TDD)** - `8264164` (feat)
2. **Task 2: Tick buffer wiring + register plugins + update test counts** - `93b05db` (feat)

## Files Created/Modified

- `src/intelligence/indicators/ofi.py` - OFIPlugin: name=ind_OFI, 5 outputs, tick+proxy paths, EWMA state
- `src/intelligence/indicators/cvd.py` - CVDPlugin: name=ind_CVD, 4 outputs, ET session reset, cumulative delta
- `tests/unit/intelligence/indicators/test_ofi.py` - 9 tests covering proxy/tick paths, EWMA convergence, divergence, spike z, guard
- `tests/unit/intelligence/indicators/test_cvd.py` - 10 tests covering accumulation, session reset, slope, divergence, spike z, proxy
- `services/indicator_service.py` - _tick_buffers, _process_tick, _process_tick_data, second KafkaConsumerClient, seed path fix
- `src/intelligence/register_plugins.py` - Import + register ofi_plugin and cvd_plugin, TIER_I1 extended to 27 entries
- `tests/unit/intelligence/test_plugin_registry.py` - Updated TIER_I1 count assertion: 25 -> 27
- `tests/unit/intelligence/test_i7_registration.py` - Updated total plugin count assertion: 111 -> 113

## Decisions Made

- OFI proxy formula `(close-low)/(high-low)*volume` differs from CVD proxy `(2c-h-l)/(h-l)*volume` — OFI measures relative position (buy pressure), CVD measures signed MFM delta. Different formulas, same tick rule primary path.
- Tick buffer keyed by `symbol` only (not `symbol:tf`), since ticks arrive before bar-timeframe association. On bar close, `self._tick_buffers.pop(symbol, [])` transfers all buffered ticks into frames and atomically clears the buffer.
- EWMA state initialized to `raw_ofi` on first call (avoids zero-bias warm-up). State management reuses existing `_i1_plugin_states` dict keyed by `(plugin_name, symbol, tf)`.

## Deviations from Plan

None - plan executed exactly as written.

One lint fix applied: renamed `topic, key` loop variables to `_topic, _key` in `_process_tick_data()` to satisfy ruff B007 (unused loop control variable).

## Issues Encountered

- 31 pre-existing test failures confirmed to be pre-existing (verified via `git stash` baseline check). All new tests and modified tests pass cleanly.

## Next Phase Readiness

- OFI and CVD I1 features now appear in every bar's I1 output (proxy path when live, tick path when ticks are buffered)
- Plan 036-02 can create I7 plugins that consume `ofi_ewma_20`, `ofi_divergence`, `cvd_slope_5bar`, `cvd_divergence` from I1Indicators (extra='allow' passes them through)
- tick_buffer injection is transparent to all other I1 plugins — they receive `frames` dict unchanged, extra key is ignored

---
*Phase: 036-microstructure-plugins*
*Completed: 2026-03-18*
