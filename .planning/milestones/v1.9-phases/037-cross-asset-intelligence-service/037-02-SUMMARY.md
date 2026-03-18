---
phase: 037-cross-asset-intelligence-service
plan: 02
subsystem: intelligence
tags: [cross-asset, i7-plugin, trading-setups, divergence, eq-index]

requires:
  - phase: 037-01
    provides: cross_asset_service producing frames['cross_asset'] dict with spread z-scores

provides:
  - CrossAssetDivergencePlugin (trad_CrossAssetDivergence) I7 plugin consuming cross_asset frame
  - 43 unit tests covering all fire/no-fire conditions, direction logic, and confidence formula
  - Plugin registered in TIER_I7 (now 36 plugins, 121 total)

affects:
  - 037-03 (signal_generator_service frame injection for cross_asset)
  - test_i7_registration.py (plugin count assertions updated)

tech-stack:
  added: []
  patterns:
    - "Stateless I7 plugin with multi-layer confidence (spread magnitude + multi-pair + multi-TF + volume + regime clarity)"
    - "EQ_INDEX symbol guard: prefix match against _EQ_INDEX_BASES frozenset"
    - "Regime-biased direction: reversion in ranging (hmm_regime=0), continuation in trending (1/2), default to reversion for unknown"
    - "Active pair routing: threshold gate uses the spread_z matching frames['cross_asset']['active_pair']"

key-files:
  created:
    - src/intelligence/trading/cross_asset_divergence.py
    - tests/unit/intelligence/test_cross_asset_divergence.py
  modified:
    - src/intelligence/register_plugins.py (TIER_I7 +1, register_all_plugins +1)
    - tests/unit/intelligence/test_i7_registration.py (counts updated to 36/121)

key-decisions:
  - "Plugin outputs use target_1/target_2/target_full (mapped from frame.targets[0..2].price) matching plan spec rather than targets list"
  - "frame_trade called with correct positional signature (setup_type, direction, entry, features, atr) — plan's code example had wrong signature"
  - "supporting_factors returned as dict (not list of strings) to enable structured downstream parsing"
  - "TIER_I7 = 36, total registered plugins = 121 (27 indicators + 94 patterns)"

requirements-completed: [XA-03]

duration: 4min
completed: 2026-03-18
---

# Phase 037 Plan 02: CrossAssetDivergencePlugin Summary

**Stateless I7 plugin converting EQ_INDEX spread z-scores into regime-biased trading setups with 5-layer confidence formula**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-18T20:01:25Z
- **Completed:** 2026-03-18T20:05:01Z
- **Tasks:** 1
- **Files modified:** 4

## Accomplishments

- `CrossAssetDivergencePlugin` fires on `|spread_z| > 2.0` on the active EQ_INDEX pair (ES/NQ or ES/RTY)
- Direction is regime-biased: short on outperformer in ranging (reversion), follow leader in trending (continuation)
- Confidence formula with 5 independent boosts: spread magnitude, multi-pair confirmation (x1.2), multi-TF confirmation (x1.2), volume imbalance (+0.05), regime clarity (+0.10)
- 43 unit tests covering all guard conditions, direction combinations, exact confidence values, and supporting_factors shape
- Plugin registered in `TIER_I7`, counts updated in `test_i7_registration.py`

## Task Commits

1. **Task 1: CrossAssetDivergencePlugin implementation + tests** - `c08f433` (feat)

## Files Created/Modified

- `src/intelligence/trading/cross_asset_divergence.py` - CrossAssetDivergencePlugin I7 plugin, stateless, consumes frames['cross_asset']
- `tests/unit/intelligence/test_cross_asset_divergence.py` - 43 unit tests (TDD, all green)
- `src/intelligence/register_plugins.py` - Added import + register call + TIER_I7 entry (now 36 plugins)
- `tests/unit/intelligence/test_i7_registration.py` - Updated counts (36 in TIER_I7, 121 total plugins)

## Decisions Made

- `frame_trade` is called with the correct signature `(setup_type, direction, entry, features, atr)` — the plan's pseudocode used a wrong positional order. Fixed to match actual `trade_framer.py` signature.
- `supporting_factors` returned as a `dict` (not a list of strings like other I7 plugins). This allows structured access by downstream consumers (dashboard, feature writer, analytics) vs string parsing.
- `target_1`, `target_2`, `target_full` mapped from `frame.targets[0..2].price` to match the plan's `outputs` frozenset specification.
- `_resolve_base()` extracted as a module-level pure function for testability and clarity.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected frame_trade call signature**
- **Found during:** Task 1 (implementation)
- **Issue:** Plan's code example called `frame_trade(df, direction, "cross_asset_divergence", features=features)` — wrong positional order and wrong types. Actual signature: `frame_trade(setup_type, direction, entry, features, atr)`
- **Fix:** Called with correct keyword arguments matching actual `trade_framer.py` definition; extracted `entry_price` from `df["close"].iloc[-1]` and `atr` from `features.get("atr_14")`
- **Files modified:** `src/intelligence/trading/cross_asset_divergence.py`
- **Verification:** All 43 tests pass; `plugin imports cleanly` verification passed
- **Committed in:** c08f433

---

**Total deviations:** 1 auto-fixed (1 bug in plan pseudocode)
**Impact on plan:** Necessary correctness fix. No scope changes.

## Issues Encountered

None beyond the frame_trade signature mismatch documented above.

## Next Phase Readiness

- `CrossAssetDivergencePlugin` is fully implemented and registered — Plan 037-03 can now wire `frames["cross_asset"]` injection into `signal_generator_service._process_single_message()` and the plugin will fire automatically.
- `CROSS_ASSET_ENABLED=false` default means zero behavioral change in production until Plan 037-03 and feature flag enabled.

---
*Phase: 037-cross-asset-intelligence-service*
*Completed: 2026-03-18*
