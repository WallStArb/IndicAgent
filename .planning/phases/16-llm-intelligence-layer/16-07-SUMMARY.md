---
phase: 16-llm-intelligence-layer
plan: "07"
subsystem: ai-narrative
tags: [llm, routing, regime, adaptive, ollama, redis]

# Dependency graph
requires:
  - phase: 16-llm-intelligence-layer
    provides: _apply_score_routing, llm_scores_cache, AINarrativeService, LLM-03/04/05 groundwork
provides:
  - Per-regime preferred model routing in _apply_score_routing
  - _preferred_models attribute on AINarrativeService (per call_type, per regime)
  - Regime-aware model promotion injected at per_signal_chain.generate() call site
  - Group synthesis uses __all__ regime entry for cross-symbol promotion
affects:
  - ai-narrative-service
  - llm-routing
  - 16-llm-intelligence-layer

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-regime routing: _apply_score_routing populates _preferred_models[call_type][regime] independently — trending winner does not override ranging"
    - "Regime-aware promotion: read signal_data[regime_context], look up _preferred_models, call _promote_model_in_chain before chain.generate()"
    - "__new__ pattern: any new instance attribute in __init__ must also be set in _make_service_new() test helper"

key-files:
  created: []
  modified:
    - services/ai_narrative_service.py
    - tests/unit/service_tests/test_ai_narrative_service.py

key-decisions:
  - "Per-regime routing: _preferred_models[call_type][regime] stores best is_significant model per regime independently — no global winner overrides per-regime winners"
  - "Fallback chain: regime-specific winner OR __all__ entry OR no promotion (existing provider order preserved)"
  - "Group synthesis uses __all__ entry only — cross-symbol synthesis has no single regime so per-regime keys don't apply"
  - "Startup routing call and 5-min refresh loop cadence unchanged — only the internal data structure upgraded"

patterns-established:
  - "_preferred_models pattern: {call_type: {regime: model_provider_id}} — built atomically by _apply_score_routing, consumed at call sites"
  - "Test helper must track __init__ attributes: added _preferred_models = {} to _make_service_new() per CLAUDE.md rule"

requirements-completed:
  - LLM-05

# Metrics
duration: 3min
completed: 2026-03-06
---

# Phase 16 Plan 07: Per-Regime LLM Routing Summary

**_apply_score_routing upgraded to build per-(call_type, regime) preferred model dict — trending winner no longer overrides ranging regime calls**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-06T05:05:31Z
- **Completed:** 2026-03-06T05:09:13Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- `_apply_score_routing` now populates `_preferred_models[call_type][regime]` independently for each (call_type, regime) pair — a trending-regime winner does not promote for ranging calls
- `_preferred_models: dict[str, dict[str, str]]` initialized to `{}` in `__init__` so service starts without AttributeError
- Per-signal call site in `_process_single_message` looks up `signal_data["regime_context"]` and promotes regime-specific model before `per_signal_chain.generate()`; falls back to `__all__` entry if no regime-specific winner
- Group synthesis in `_synthesize_group` promotes `__all__` entry before `group_chain.generate()` (cross-symbol, no single regime)
- 4 new TDD unit tests: `test_apply_score_routing_per_regime`, `test_apply_score_routing_falls_back_without_significant`, `test_preferred_models_initialized`, `test_promote_uses_regime_from_signal`
- All 29 `test_ai_narrative_service.py` tests GREEN; full unit suite 1172 tests GREEN; ruff 0 errors

## Task Commits

Each task was committed atomically:

1. **Task 1: Add per-regime routing to _apply_score_routing + tests** - `729ec84` (feat)

## Files Created/Modified

- `services/ai_narrative_service.py` — `_preferred_models` attr in `__init__`, `_apply_score_routing` rewritten for per-regime dict, regime-aware promotion in `_process_single_message` and `_synthesize_group`
- `tests/unit/service_tests/test_ai_narrative_service.py` — 4 new per-regime tests, `_preferred_models = {}` added to `_make_service_new()` helper, `json` import added at top

## Decisions Made

- Per-regime routing stores winners independently — `_preferred_models["per_signal"]["trending"] = "model_A"` and `_preferred_models["per_signal"]["ranging"] = "model_B"` are separate entries, not overriding each other
- No fallback to global winner: if no is_significant model for a regime, that regime has no entry and promotion is skipped (existing provider order preserved)
- `__all__` regime key still used as fallback for per-signal and exclusively for group synthesis

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added `_preferred_models = {}` to `_make_service_new()` test helper**
- **Found during:** Task 1 (GREEN phase — running tests after implementation)
- **Issue:** `_make_service_new()` bypasses `__init__` via `__new__` pattern. New `_preferred_models` attribute added to `__init__` was not present in helper, causing `AttributeError` inside `_process_single_message` which was caught by the exception handler — silently breaking 3 existing i8 tests
- **Fix:** Added `svc._preferred_models = {}` to `_make_service_new()` per CLAUDE.md rule: "any new instance attribute added in `__init__` must also be manually set in the test"
- **Files modified:** `tests/unit/service_tests/test_ai_narrative_service.py`
- **Verification:** All 29 ai_narrative tests pass after fix
- **Committed in:** `729ec84` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking test breakage)
**Impact on plan:** Auto-fix necessary per established CLAUDE.md test pattern. No scope creep.

## Issues Encountered

None beyond the `_make_service_new()` helper fix documented above.

## Next Phase Readiness

- LLM-05 complete: per-regime routing in place
- Phase 16 (16-01 through 16-07) now fully complete
- As the `llm_model_scores` hypertable accumulates n >= 30 significant outcomes per regime, `_apply_score_routing` will automatically promote regime-specific winners at each 5-minute refresh cycle
- No blockers for next milestone work

---
*Phase: 16-llm-intelligence-layer*
*Completed: 2026-03-06*
