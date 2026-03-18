---
phase: 037-cross-asset-intelligence-service
plan: 03
subsystem: pipeline
tags: [cross-asset, kafka, signal-generator, feature-writer, I7, plugin-registration]

requires:
  - phase: 037-01
    provides: cross_asset_service.py + topic_cross_asset() stream key + Settings fields
  - phase: 037-02
    provides: trad_CrossAssetDivergence I7 plugin already imported + registered in register_plugins.py

provides:
  - signal_generator_service subscribes to cross_asset topic and injects frames['cross_asset'] + frames['cross_asset_5m'] for EQ_INDEX symbols
  - feature_writer_service subscribes to cross_asset topic and persists spread features to intelligence_features via jsonb merge
  - CLAUDE.md Active Services table and systemd commands updated with Cross-Asset Service

affects:
  - signal_generator_service (cross-asset frame injection)
  - feature_writer_service (cross-asset persistence)
  - CLAUDE.md (ops documentation)

tech-stack:
  added: []
  patterns:
    - "Group-level (not symbol-level) Kafka topic routed before key-split in feature_writer _process_loop"
    - "_cross_asset_enabled guard mirrors _roll_monitor_enabled pattern for conditional topic subscription"
    - "__new__-pattern tests must set all attrs accessed by the method under test"

key-files:
  created:
    - .planning/phases/037-cross-asset-intelligence-service/037-03-SUMMARY.md
  modified:
    - services/signal_generator_service.py
    - services/feature_writer_service.py
    - src/intelligence/register_plugins.py
    - tests/unit/service_tests/test_signal_generator_service.py
    - CLAUDE.md

key-decisions:
  - "Cross-asset frames injected only for EQ_INDEX symbols (ES/NQ/RTY/YM prefix match) not all symbols"
  - "Cross-asset topic routed before symbol:tf key-split in feature_writer since it has no per-symbol key"
  - "feature_writer reuses _UPSERT_ROLL_BOUNDARY_SQL (jsonb merge) to persist cross_asset data per EQ_INDEX member"
  - "register_plugins.py import already done in 037-02 — only sort order needed fixing (ruff I001)"

requirements-completed: [XA-01, XA-02, XA-03]

duration: 22min
completed: 2026-03-18
---

# Phase 037 Plan 03: Cross-Asset Pipeline Wiring Summary

**signal_generator_service and feature_writer_service wired to cross_asset Kafka topic: EQ_INDEX symbols get cross-asset frames injected for I7 plugin; spread features persisted to intelligence_features via jsonb merge**

## Performance

- **Duration:** 22 min
- **Started:** 2026-03-18T20:12:01Z
- **Completed:** 2026-03-18T20:34:09Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- `signal_generator_service` subscribes to `development.cross_asset` topic when `cross_asset_enabled=True`, caches latest payload by timeframe, and injects `frames['cross_asset']` + `frames['cross_asset_5m']` for EQ_INDEX symbols (ES/NQ/RTY/YM) so `trad_CrossAssetDivergence` plugin receives live data
- `feature_writer_service` subscribes to `development.cross_asset` topic, adds `_process_cross_asset_message()` that persists spread features to `intelligence_features.i7` JSONB via `ON CONFLICT ... DO UPDATE || merge` for all 4 EQ_INDEX group members
- `CLAUDE.md` Active Services table updated with Cross-Asset Service row (:9118), systemd command list and metrics ports line updated
- Plugin registration (`trad_CrossAssetDivergence` in TIER_I7) was already complete from Plan 037-02 — only import sort order fix needed
- Zero regressions: 33 pre-existing failures, 33 failures after — identical count

## Task Commits

Each task was committed atomically:

1. **Task 1: Register plugin in TIER_I7 + update count tests** — already committed in `347dddc` (feat 037-02); only import sort fix needed
2. **Task 2: Wire signal_generator + feature_writer + CLAUDE.md** - `f6766a6` (feat)

## Files Created/Modified

- `services/signal_generator_service.py` — added `topic_cross_asset` import, `_cross_asset_enabled`/`_cross_asset_cache` attrs, conditional topic subscription, cache handler in `_process_loop`, frame injection in `_process_single_message`
- `services/feature_writer_service.py` — added `topic_cross_asset` import, `_cross_asset_enabled` attr (try+except blocks), conditional topic subscription, `_process_cross_asset_message()`, routing in `_process_loop`
- `src/intelligence/register_plugins.py` — ruff I001 import sort autofix (cross_asset_divergence alphabetically sorted)
- `tests/unit/service_tests/test_signal_generator_service.py` — added `svc._cross_asset_enabled = False` to `__new__`-pattern test
- `CLAUDE.md` — Cross-Asset Service row in Active Services table, systemd list, metrics ports

## Decisions Made

- Cross-asset frame injection guards on EQ_INDEX base symbol prefix match (`symbol.startswith(base) and len(symbol) > len(base)`) — same logic as `_resolve_base()` in the plugin itself
- `feature_writer` routes cross_asset topic BEFORE the `SYMBOL:TF` key-split because cross_asset messages have no per-symbol key (group-level payload)
- Reused `_UPSERT_ROLL_BOUNDARY_SQL` (`ON CONFLICT ... DO UPDATE SET i7 = i7 || EXCLUDED.i7`) for cross-asset persistence — avoids a new SQL constant and maintains the jsonb merge pattern
- Persistence writes one row per EQ_INDEX base symbol (ES, NQ, RTY, YM) for the group snapshot timestamp — this is correct since all 4 members fired the same bar

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Import sort order violation in register_plugins.py**
- **Found during:** Task 1 verification (ruff lint)
- **Issue:** `cross_asset_divergence` import was added at line 124 (after `vwap_deviation`) in 037-02, violating alphabetical order required by ruff I001
- **Fix:** Ran `ruff check --fix` to auto-sort; `cross_asset_divergence` moved to correct alphabetical position within `.trading.*` imports
- **Files modified:** `src/intelligence/register_plugins.py`
- **Committed in:** f6766a6 (Task 2 commit)

**2. [Rule 1 - Bug] Missing `_cross_asset_enabled` attr in `__new__`-pattern test**
- **Found during:** Task 2 verification (pytest)
- **Issue:** `test_process_message_accesses_typed_attributes` uses `SignalGeneratorService.__new__()` to bypass `__init__`, so `_cross_asset_enabled` was never set. `_process_single_message` accesses it, causing `AttributeError` → test failure
- **Fix:** Added `svc._cross_asset_enabled = False` before the `await` call in the test
- **Files modified:** `tests/unit/service_tests/test_signal_generator_service.py`
- **Committed in:** f6766a6 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 import sort, 1 missing test attr)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Issues Encountered

- The `test_i7_registration.py` count tests and plugin registration were already complete (committed in 037-02). Task 1 effectively only needed the import sort fix.

## Next Phase Readiness

- Phase 037 is complete — all 3 plans executed and committed
- Full cross-asset loop is wired: service (037-01) → plugin (037-02) → pipeline integration (037-03)
- System is ready for Phase 038 or next planned phase

---
*Phase: 037-cross-asset-intelligence-service*
*Completed: 2026-03-18*
