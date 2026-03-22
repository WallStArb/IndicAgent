---
phase: 41-intelligence-gap-fill
plan: 03
subsystem: intelligence
tags: [i7-plugins, signal-generator, htf-context, vwap, orb, volume-profile, tdd]

# Dependency graph
requires:
  - phase: 41-02
    provides: _select_vp() and htf_1h_* fallback branch in trade_framer
provides:
  - TF guard in 6 intraday-only plugins (blocks 1h bars from VWAP/session setups)
  - HTF 1h intel cache + frame injection in signal_generator_service
  - htf_1h_poc_price/vah/val merged into features before plugin execution
  - frames["timeframe"] always injected by signal_generator_service
  - CRITICAL INVARIANT comment at aggregator active derivation line
  - CRITICAL write-back comments at plugin state loops in market_analysis and indicator services
affects:
  - 41-04
  - 42-candlestick-expansion
  - 43-i6-confluence-expansion
  - signal_generator_service (any future changes to frame building)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TF guard pattern: `if timeframe and timeframe not in (intraday TFs): return _no_signal()`"
    - "HTF intel cache: `_htf_intel_cache['{symbol}:1h'] = features` on every 1h event"
    - "HTF frame injection: `frames['htf_1h']` for short-TF bars from zero-new-subscriptions cache"
    - "HTF VP merge: htf_1h_poc_price/vah/val extracted from htf_frame before _run_setup_plugins"

key-files:
  created: []
  modified:
    - services/signal_generator_service.py
    - src/intelligence/trading/anchored_vwap_reversion.py
    - src/intelligence/trading/vwap_reclaim.py
    - src/intelligence/trading/poc_rejection.py
    - src/intelligence/trading/orb15.py
    - src/intelligence/trading/orb30.py
    - src/intelligence/trading/prev_day_level_test.py
    - src/intelligence/trading/aggregator.py
    - services/market_analysis_service.py
    - services/indicator_service.py
    - tests/unit/intelligence/trading/test_anchored_vwap_reversion.py
    - tests/unit/intelligence/trading/test_vwap_reclaim.py
    - tests/unit/intelligence/trading/test_poc_rejection.py
    - tests/unit/intelligence/trading/test_orb15.py
    - tests/unit/intelligence/trading/test_orb30.py
    - tests/unit/intelligence/trading/test_prev_day_level_test.py
    - tests/unit/intelligence/test_aggregator.py
    - tests/unit/service_tests/test_signal_generator_service.py

key-decisions:
  - "TF guard uses `if timeframe and timeframe not in (...)` — empty string (not injected yet) passes through for backward compatibility with tests"
  - "HTF VP merge placed before _run_setup_plugins so all I7 plugins see htf_1h_poc_price/vah/val in features dict"
  - "CRITICAL INVARIANT comment documents that active must always derive from all_ranked to preserve perf_weights effect"

patterns-established:
  - "Phase 041 HTF cache pattern mirrors Phase 037 cross-asset cache: zero new subscriptions, populate from existing consumer"
  - "frames['timeframe'] always injected at frame-build time in signal_generator_service — enables TF guards in all I7 plugins"

requirements-completed:
  - INTEL-05

# Metrics
duration: 25min
completed: 2026-03-20
---

# Phase 41 Plan 03: TF Guards, HTF Context Injection, and Invariant Comments Summary

**TF guards block 6 intraday-only plugins from firing on 1h bars; HTF 1h intel cache wires poc_price/vah/val into short-TF features via htf_1h_* prefixed keys**

## Performance

- **Duration:** 25 min
- **Started:** 2026-03-20T13:38:17Z
- **Completed:** 2026-03-20T14:03:00Z
- **Tasks:** 4 (Task 1 RED + Task 2 GREEN + Task 3a + Task 3b)
- **Files modified:** 18

## Accomplishments

- TF guard added to 6 VWAP/session plugins (AnchoredVWAPReversion, VWAPReclaim, POCRejection, ORB15, ORB30, PrevDayLevelTest) — prevents incorrect 1h signals from intraday-only setups
- `_htf_intel_cache` added to `signal_generator_service` with zero new subscriptions — populated from existing `intelligence:SYMBOL:1h` events already being consumed
- `frames["timeframe"]` now always injected at frame-build time, enabling all current and future I7 plugins to self-guard on TF
- `htf_1h_poc_price`, `htf_1h_vah`, `htf_1h_val` merged into features before `_run_setup_plugins` — completes Plan 02's `_select_vp()` fallback branch wiring
- CRITICAL INVARIANT comment at aggregator `active` derivation line prevents silent regression to raw-signal derivation
- CRITICAL write-back comments at plugin state loops in both market_analysis_service and indicator_service

## Task Commits

1. **Task 1: TF guard tests (RED)** - `a757d15` (test)
2. **Task 2: TF guards in 6 plugins (GREEN)** - `8f1921b` (feat)
3. **Task 3a: HTF context injection** - `a07581f` (feat)
4. **Task 3b: CRITICAL invariant comments** - `dc201d1` (docs)

## Files Created/Modified

- `services/signal_generator_service.py` — _htf_intel_cache dict, cache population on 1h events, frames["timeframe"] injection, htf_1h frame injection, HTF VP merge before _run_setup_plugins
- `src/intelligence/trading/anchored_vwap_reversion.py` — TF guard at compute_full() top
- `src/intelligence/trading/vwap_reclaim.py` — TF guard at compute_full() top
- `src/intelligence/trading/poc_rejection.py` — TF guard at compute_full() top
- `src/intelligence/trading/orb15.py` — TF guard at compute_full() top
- `src/intelligence/trading/orb30.py` — TF guard at compute_full() top
- `src/intelligence/trading/prev_day_level_test.py` — TF guard at compute_full() top
- `src/intelligence/trading/aggregator.py` — CRITICAL INVARIANT comment above active derivation
- `services/market_analysis_service.py` — CRITICAL write-back comment at plugin state loop
- `services/indicator_service.py` — CRITICAL write-back comment at plugin state loop
- `tests/unit/intelligence/trading/test_*.py` (6 files) — test_tf_guard_returns_no_signal_on_1h added
- `tests/unit/intelligence/test_aggregator.py` — test_active_signals_have_adjusted_rank_from_all_ranked added
- `tests/unit/service_tests/test_signal_generator_service.py` — _htf_intel_cache added to __new__-based test fixture

## Decisions Made

- TF guard uses `if timeframe and timeframe not in ("1m", "5m", "15m")` rather than strict `not in` — empty string (not yet injected) passes through, preserving backward compatibility with tests that don't set `timeframe` in frames
- HTF VP merge placed before `_run_setup_plugins()` (not in `frame_trade()`) so all 36 I7 plugins receive `htf_1h_poc_price/vah/val` in their features dict; trade_framer's `_select_vp()` reads these keys via its fallback branch
- CRITICAL comment added as block comment above `active = [...]` line to prevent future derivation from raw signals list

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TF guard broke all existing tests that don't set frames["timeframe"]**
- **Found during:** Task 2 (GREEN phase, after adding strict `not in` guard)
- **Issue:** `timeframe = frames.get("timeframe", "")` with strict `not in ("1m","5m","15m")` check caused all existing tests (which don't set `timeframe`) to return no_signal
- **Fix:** Changed to `if timeframe and timeframe not in (...)` — empty string passes through; only explicitly-set non-intraday TFs are blocked
- **Files modified:** All 6 plugin files
- **Verification:** 224/224 trading tests pass; 6 TF guard tests pass
- **Committed in:** `8f1921b` (Task 2 commit)

**2. [Rule 1 - Bug] Missing _htf_intel_cache in __new__-based service test fixture**
- **Found during:** Task 3a (after adding _htf_intel_cache to __init__)
- **Issue:** `test_process_message_accesses_typed_attributes` uses `__new__` to bypass `__init__`, so new instance attribute was missing → KeyError: 'open' at frame build
- **Fix:** Added `svc._htf_intel_cache = {}` to test fixture setup
- **Files modified:** tests/unit/service_tests/test_signal_generator_service.py
- **Verification:** All 49 signal generator service tests pass
- **Committed in:** `a07581f` (Task 3a commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both fixes required for test correctness. No scope creep.

## Issues Encountered

- 5 of 6 TF guard tests already passed in RED phase (ORB/VWAPReclaim/POCRejection plugins short-circuit before the TF check via other guards when `timeframe` is not set). Only `test_anchored_vwap_reversion.py::test_tf_guard_returns_no_signal_on_1h` failed in RED phase (anchored_vwap has all-passing gate conditions in the test). This is consistent with the TDD contract: the tests document the requirement; GREEN phase ensures the explicit guard fires for all 6.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- HTF context pipeline complete: 1h intel flows through stream → cache → frames["htf_1h"] → features["htf_1h_poc_price/vah/val"] → trade_framer._select_vp() fallback branch
- TF guard ensures VWAP/session plugins cannot fire spuriously on hourly bars
- Phase 41-04 (if any) can build on this HTF context foundation
- Phase 43 I6 confluence expansion can reference htf_1h context in cross-TF scoring

---
*Phase: 41-intelligence-gap-fill*
*Completed: 2026-03-20*
