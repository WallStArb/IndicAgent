---
phase: 17-llm-wiring-fix
plan: "01"
subsystem: intelligence
tags: [llm, regime-routing, session-extremes, plugin, vocabulary]

# Dependency graph
requires:
  - phase: 16-llm-intelligence-layer
    provides: adaptive routing in ai_narrative_service using regime keys from llm_calls table
provides:
  - SessionExtremesSetup emits session_extreme_london / session_extreme_ny / session_extreme_both
  - supporting_factors always includes session:<ctx> metadata label on every fired signal
  - All 3 session regime variants covered by TestRegimeVocabulary tests
affects:
  - 17-02 onwards (subsequent LLM wiring fix plans using this vocabulary fix)
  - ai_narrative_service (score routing will now find session_extreme_* keys in llm_model_scores)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Raw plugin string = LLM routing key: no translation layer — plugin emits the exact string that lands in llm_calls.regime"
    - "supporting_factors carries dual purpose: confirming-factor metadata AND session-context provenance"

key-files:
  created: []
  modified:
    - src/intelligence/trading/session_extremes_setup.py
    - tests/unit/intelligence/trading/test_session_extremes_setup.py

key-decisions:
  - "session_extreme_london/ny/both are the canonical regime strings for this plugin family — no canonicalization layer, raw plugin output IS the vocabulary"
  - "supporting_factors carries session:<ctx> label as metadata alongside confirming-factor strings (trend_align, rsi_extreme, volume_spike)"

patterns-established:
  - "Plugin regime_context strings must match exactly what ai_narrative_service queries in _apply_score_routing() — verify at plugin design time"

requirements-completed:
  - LLM-05

# Metrics
duration: 2min
completed: 2026-03-06
---

# Phase 17 Plan 01: LLM Wiring Fix (Session Extremes Vocabulary) Summary

**SessionExtremesSetup now emits `session_extreme_{london|ny|both}` regime strings + `session:<ctx>` metadata in supporting_factors, enabling LLM adaptive routing to find its score cache keys**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-06T15:28:50Z
- **Completed:** 2026-03-06T15:30:50Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Fixed `regime_context` in `SessionExtremesSetup.compute_full()` from bare "london"/"ny"/"both" to `session_extreme_london`/`session_extreme_ny`/`session_extreme_both`
- Added `session:<ctx>` label to `supporting_factors` on every fired signal for metadata provenance
- Added `TestRegimeVocabulary` class with 6 new tests covering all 3 session variants (regime_context + supporting_factors checks)
- Updated 4 existing tests: `test_regime_context_london`, `test_regime_context_ny` (new values), `test_fires_with_trend_align_only`, `test_fires_with_rsi_extreme_only` (membership checks instead of equality)
- 33 tests GREEN, 1187 unit tests passing, ruff 0 errors on changed files

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix regime_context vocabulary + update/add tests** - `f7fe7a7` (feat)

**Plan metadata:** (docs commit follows)

_Note: TDD sequence — tests RED first, then implementation GREEN_

## Files Created/Modified

- `src/intelligence/trading/session_extremes_setup.py` - Added `regime_ctx = f"session_extreme_{session_ctx}"` + `supporting.append(f"session:{session_ctx}")` after session_ctx assignment block; `regime_context` in return dict now uses `regime_ctx`
- `tests/unit/intelligence/trading/test_session_extremes_setup.py` - Updated 4 existing tests, added `TestRegimeVocabulary` class with 6 new tests

## Decisions Made

- Regime strings for this plugin family are `session_extreme_london`, `session_extreme_ny`, `session_extreme_both` — no canonicalization layer. The raw plugin string IS the vocab. This matches the CONTEXT.md locked decision from Phase 16.
- `supporting_factors` carries both confirming-factor labels AND session metadata label. Consumers looking for confirming factors should use `in` checks (not equality), as the list is now extended.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-existing test failure in `tests/unit/service_tests/test_ai_narrative_helpers.py::test_parse_aggregated_signal_includes_signal_id` (out of scope — pre-existing unstaged change in git status, not caused by this plan). Noted for deferred resolution.

Pre-existing ruff error in `tests/unit/service_tests/test_signal_generator_service.py` (I001 import sort — also a pre-existing unstaged change). Both out of scope per deviation boundary rules.

## Next Phase Readiness

- `session_extreme_london/ny/both` regime strings will now land in `llm_calls.regime` for all future SessionExtremesSetup signals
- Adaptive routing in `ai_narrative_service._apply_score_routing()` can now accumulate and query these keys once n_outcomes >= 30 per regime
- Phase 17 Plan 02 can proceed (next LLM wiring fix item)

---
*Phase: 17-llm-wiring-fix*
*Completed: 2026-03-06*
