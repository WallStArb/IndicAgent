---
phase: 115
plan: "03"
subsystem: plugin_wiring
tags: [regime_type, frame_trade, audit-trail, wiring, microstructure_utils]
dependency_graph:
  requires: [TradeFrame.plugin_regime_type, frame_trade.regime_type kwarg, detect_spike_signal]
  provides: [all 26 frame_trade() calls pass regime_type=self.regime_type]
  affects: [all 25 I7 plugins, microstructure_utils, cvd_spike, ofi_spike, Hurst tightening activation]
tech_stack:
  added: []
  patterns: [kwarg threading, acceptance grep verification]
key_files:
  created: []
  modified:
    - src/intelligence/trading/microstructure_utils.py
    - src/intelligence/trading/cvd_spike.py
    - src/intelligence/trading/ofi_spike.py
    - src/intelligence/trading/anchored_vwap_reversion.py
    - src/intelligence/trading/choch_reversal.py
    - src/intelligence/trading/cross_asset_divergence.py
    - src/intelligence/trading/cvd_divergence.py
    - src/intelligence/trading/delta_exhaustion.py
    - src/intelligence/trading/divergence_stack.py
    - src/intelligence/trading/dual_divergence.py
    - src/intelligence/trading/failed_breakout.py
    - src/intelligence/trading/fvg_fill.py
    - src/intelligence/trading/hvn_rejection.py
    - src/intelligence/trading/lvn_breakout.py
    - src/intelligence/trading/mean_reversion.py
    - src/intelligence/trading/mtf_alignment.py
    - src/intelligence/trading/ofi_continuation.py
    - src/intelligence/trading/ofi_divergence.py
    - src/intelligence/trading/orb15.py
    - src/intelligence/trading/orb30.py
    - src/intelligence/trading/pattern_completion.py
    - src/intelligence/trading/poc_rejection.py
    - src/intelligence/trading/prev_day_level_test.py
    - src/intelligence/trading/regime_transition.py
    - src/intelligence/trading/second_leg_continuation.py
    - src/intelligence/trading/trend_following.py
    - src/intelligence/trading/vcp.py
    - src/intelligence/trading/vwap_reclaim.py
    - tests/unit/intelligence/test_trade_framer.py
decisions:
  - "Acceptance grep (single-line filter) cannot detect multi-line unwired calls; used context-window grep (check regime_type within 10 lines of frame_trade() opener) as the authoritative 0-missing verification"
metrics:
  duration_seconds: 250
  completed_date: "2026-06-05"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 29
---

# Phase 115 Plan 03: Wire regime_type to All frame_trade() Call Sites Summary

regime_type=self.regime_type threaded to all 26 frame_trade() call sites (25 direct plugin calls + 1 inside microstructure_utils.detect_spike_signal()), activating Hurst tightening for every plugin that declares a regime_type class attribute.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 3a | Add TestRegimeTypeWired tests; wire regime_type through detect_spike_signal; update cvd_spike and ofi_spike | cfd43f1a | microstructure_utils.py, cvd_spike.py, ofi_spike.py, test_trade_framer.py |
| 3b | Wire regime_type=self.regime_type to all 25 direct plugin frame_trade() calls | 2751b131 | 25 plugin files |

## What Was Built

**TestRegimeTypeWired class** (2 tests) added to test_trade_framer.py:
- `test_hurst_tightening_fires_for_trend_regime_type` - H=0.75 with regime_type="trend" → mult < 1.0
- `test_no_hurst_tightening_when_regime_type_none` - same features with regime_type=None → mult == 1.0

These contract tests verify that the existing `_adaptive_buffer` Hurst gate is correctly wired, not adding new behavior.

**`detect_spike_signal()` in microstructure_utils.py** gained `regime_type: str = "any"` as a defaulted parameter (line 26), which is passed as `regime_type=regime_type` to the internal `frame_trade()` call (line 80). This enables cvd_spike and ofi_spike to propagate their `regime_type` class attribute through the shared utility.

**cvd_spike.py** and **ofi_spike.py** now pass `regime_type=self.regime_type` to `detect_spike_signal()`.

**25 direct plugin files** modified:
- 13 single-line calls: appended `regime_type=self.regime_type` as final positional/keyword argument
- 12 multi-line (keyword-style) calls: added `regime_type=self.regime_type,` line before closing paren

Regime categories covered:
- `regime_type="trend"` (8 plugins): lvn_breakout, mtf_alignment, ofi_continuation, orb15, orb30, second_leg_continuation, trend_following, vcp
- `regime_type="mean_reversion"` (9 plugins): anchored_vwap_reversion, cvd_divergence, delta_exhaustion, dual_divergence, failed_breakout, fvg_fill, hvn_rejection, mean_reversion, poc_rejection
- `regime_type="any"` (8 plugins): choch_reversal, cross_asset_divergence, divergence_stack, ofi_divergence, pattern_completion, prev_day_level_test, regime_transition, vwap_reclaim

## Deviations from Plan

### Acceptance grep limitation for multi-line calls

**Found during:** Task 3b verification

**Issue:** The plan's acceptance grep (`grep -v "def frame_trade\|regime_type=\|microstructure_utils\|..."`) filters out lines containing `regime_type=`. For multi-line calls, the `frame_trade(` opening line and the `regime_type=self.regime_type,` kwarg line are separate lines. The grep still matched the 12 opening lines of multi-line calls, making it appear as 12 unwired sites.

**Fix:** Used a context-window check (`sed -n "LINE,$((LINE+10))p"` and checking for `regime_type=` within the block) to verify all 12 multi-line call sites were correctly wired. All returned "OK". The acceptance grep as written only applies cleanly to single-line calls; all single-line call sites returned 0 results.

**Files modified:** None - verification approach only.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| src/intelligence/trading/microstructure_utils.py - regime_type param | FOUND (line 26) |
| src/intelligence/trading/microstructure_utils.py - regime_type= in frame_trade call | FOUND (line 80) |
| src/intelligence/trading/cvd_spike.py - regime_type=self.regime_type | FOUND |
| src/intelligence/trading/ofi_spike.py - regime_type=self.regime_type | FOUND |
| All 25 direct plugin frame_trade() calls wired | VERIFIED via context-window grep (26 OK, 0 MISSING) |
| commit cfd43f1a | FOUND |
| commit 2751b131 | FOUND |
| TestRegimeTypeWired (2 tests) | PASSED |
| Full unit suite (4360 tests) | PASSED |
