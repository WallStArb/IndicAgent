---
phase: 124
plan: "04"
subsystem: intelligence/trading
tags: [plugin, structural-rewrite, pattern-completion, signal-quality, wave-b]
dependency_graph:
  requires: [124-01]
  provides: [trad_PatternCompletion structural trigger]
  affects: [signal_ledger, I7 plugin fire rate]
tech_stack:
  added: []
  patterns: [parallel-dicts-to-dataclass, structural-onset, instance-consumption]
key_files:
  created: []
  modified:
    - src/intelligence/trading/pattern_completion.py
    - tests/unit/intelligence/test_pattern_completion.py
decisions:
  - "Confidence gate changed from strict-greater (>0.70) to strict-greater-than-or-equal-to (<=0.70 suppresses), preserving original exclusive gate semantics"
  - "Instance consumption is permanent (fired_bars > 0, no re-arm) unlike deduplicate_event which re-arms after 20 bars; deduplicate_event retained as secondary guard only"
  - "Triangle structural completion derived from consolidation high/low over apex_bars window using OHLCV from frames; no separate lookback buffer needed since high/low arrays available from extract_ohlcv"
metrics:
  duration_minutes: 15
  tasks_completed: 5
  files_changed: 2
  completed_date: "2026-06-14"
---

# Phase 124 Plan 04: PatternCompletion Structural Rewrite Summary

**One-liner:** PatternCompletion rewritten to fire on neckline break (DT/DB/HS) or triangle apex-bound breach, with permanent instance consumption via PatternInstanceState registry.

## What Was Built

Wave B Plugin 3/5: `trad_PatternCompletion` structural rewrite per QUALITY-01 and D-01/D-02 decisions.

**Before:** Plugin fired on `dt_db_confidence > 0.70` (continuous metric crossing threshold). Every bar where any pattern's confidence exceeded the gate produced a signal, with only `deduplicate_event` (re-arms after 20 bars) as the dedup mechanism. Fire rate: 15-30% per bar.

**After:** Plugin fires on structural completion only:
- Double top: `close[-1] < neckline` (close breaks below neckline)
- Double bottom: `close[-1] > neckline` (close breaks above neckline)
- HS top: `close[-1] < hs_neckline`
- HS bottom (inverse): `close[-1] > hs_neckline`
- Triangle bullish: `close[-1] > consolidation_high` over `apex_bars` window
- Triangle bearish: `close[-1] < consolidation_low` over `apex_bars` window

Confidence score is now a context filter (pattern quality gate, not trigger).

## Task Results

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1-4 | PatternCompletion structural rewrite (combined) | 0d79740b | src/intelligence/trading/pattern_completion.py |
| 5 | Unit tests for structural rewrite | 43b461b9 | tests/unit/intelligence/test_pattern_completion.py |

Tasks 1-4 were implemented atomically: the PatternInstanceState dataclass, _instances registry, structural completion detection, and gate ordering are tightly coupled and best committed as a unit.

## Gate Ordering (Final)

1. **Pattern existence FIRST** - `dt_db_pattern in (1,2)` or `hs_pattern in (1,2)` or `tri_breakout_bias != 0`
2. **Structural completion SECOND** - neckline break / apex-bound breach check per pattern type
3. **Confidence context filter THIRD** - `best_confidence <= confidence_min` suppresses (context filter, not trigger)
4. **Instance consumption FOURTH** - `instance.fired_bars > 0` suppresses permanently (no re-arm)
5. **Secondary dedup guard** - `deduplicate_event()` retained as edge-case protection
6. **OHLCV + trade frame FIFTH** - ATR extraction, `frame_trade()`, viability check
7. **Emit and mark consumed SIXTH** - `instance.fired_bars = 1` set before signal return

## Instance Registry (PatternInstanceState)

```python
@dataclass
class PatternInstanceState:
    pattern_name: str
    direction: int
    structural_anchor: float | int  # neckline for DT/DB/HS, apex_bars for triangle
    fired_bars: int = 0  # >0 = consumed
```

Instance ID: `f"{symbol}_{tf_key}_{pattern_name}_{best_anchor}"`

A different anchor (new structural level) creates a new instance and fires normally. Same anchor = same formation = suppressed permanently.

## Test Coverage (26 tests, all green)

- `TestConfidenceOnlyNoSignal` (3): confidence above threshold + no neckline break = no signal
- `TestNecklineBreakFiresOnce` (4): DT/DB/HS top/HS bottom with structural completion = correct direction
- `TestInstanceConsumption` (2): same anchor suppressed; different anchor fires
- `TestTriangleBreakout` (4): bullish/bearish breach fires; no-breach suppressed; instance consumed
- `TestConfidenceContextFilter` (3): below threshold + structural completion = no signal; above = fires
- `TestPatternFieldPersistence` (3): signal dict contains pattern_name, raw_confidence, count
- `TestConfidenceFormula` (2): convergence score, direction purity
- `TestClassAttributes` (5): regime_type, shadow_only, requires_i6_confluence, confidence_threshold, instances registry

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Confidence gate strict boundary mismatch**
- **Found during:** Task 5 testing
- **Issue:** Plan spec said confidence is a context filter after structural trigger. Original code used `> confidence_min` (strict greater than, excluding exactly 0.70). Rewrite initially used `< confidence_min` (less than) which passed 0.70. The existing test verified the original strict exclusive-gate semantics.
- **Fix:** Changed to `<= confidence_min` to suppress values at or below threshold.
- **Files modified:** src/intelligence/trading/pattern_completion.py
- **Commit:** 43b461b9

**2. [Rule 1 - Bug] Test close array for DT "no structural completion" case**
- **Found during:** Task 5 testing
- **Issue:** `test_confidence_only_no_fire_dt` used default close (5000 to 5050). For double_top bearish completion, `close < neckline` with neckline=5100: 5050 < 5100 is True, so the default close WAS completing the pattern. Test was asserting the wrong expected outcome.
- **Fix:** Changed test to use `close_arr = np.linspace(5100, 5150, 50)` so close[-1]=5150 > 5100 = no completion.
- **Files modified:** tests/unit/intelligence/test_pattern_completion.py
- **Commit:** 43b461b9

## Self-Check

### Files Exist

- `src/intelligence/trading/pattern_completion.py` - modified
- `tests/unit/intelligence/test_pattern_completion.py` - modified

### Commits Exist

- `0d79740b` - feat(124-04): rewrite PatternCompletion to fire on structural completion
- `43b461b9` - test(124-04): add structural rewrite tests for PatternCompletion

## Self-Check: PASSED
