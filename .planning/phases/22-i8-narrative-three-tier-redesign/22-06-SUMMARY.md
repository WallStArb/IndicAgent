---
phase: 22-i8-narrative-three-tier-redesign
plan: "06"
subsystem: ai-narrative
tags: [llm, openrouter, ollama, chain-routing, config]

# Dependency graph
requires:
  - phase: 22-i8-narrative-three-tier-redesign
    provides: short_chain and deep_chain attributes in _build_chains() (from plan 22-02)
provides:
  - narrative_short and narrative_deep explicit provider lists in default_config["providers"]
  - _build_chains() uses direct key access (no .get() fallback) for both new chain types
  - SYSTEM_PROMPT updated to senior trading desk analyst voice (no banned phrases)
affects: [22-07, ai_narrative_service chain routing, llm_model_scores per-call-type tracking]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-call-type provider lists in default_config enable independent model routing as performance data accumulates"
    - "narrative_short and narrative_deep start identical to per_signal; routing diverges via _apply_score_routing() as llm_model_scores data grows"

key-files:
  created: []
  modified:
    - services/ai_narrative_service.py

key-decisions:
  - "narrative_short and narrative_deep provider lists start identical to per_signal (6 providers each); model routing diverges independently as performance data accumulates via llm_model_scores"
  - "SYSTEM_PROMPT reworded to avoid banned phrase literals in the prompt text itself — conveys same constraints without triggering the test assertion"
  - "_build_chains() uses direct dict key access for narrative_short/narrative_deep — KeyError on missing config is intentional; forces explicit config hygiene"

patterns-established:
  - "Config-first routing: all chain types have explicit provider lists in default_config; no runtime fallback to other lists"

requirements-completed:
  - I8-10

# Metrics
duration: 8min
completed: 2026-03-09
---

# Phase 22 Plan 06: Narrative Provider Config Summary

**Explicit narrative_short and narrative_deep provider entries added to default_config with direct _build_chains() key access — no fallback, config-first chain routing**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-09T08:32:00Z
- **Completed:** 2026-03-09T08:40:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Added `narrative_short` and `narrative_deep` to `default_config["providers"]` — each with the same 6 providers as `per_signal` (openrouter + ollama fallback)
- Updated `_build_chains()` to use `pcfg["narrative_short"]` and `pcfg["narrative_deep"]` directly; `per_signal_chain` aliased to `short_chain` for backward compatibility
- Fixed SYSTEM_PROMPT to senior trading desk analyst voice (addresses pre-existing TDD RED test from plan 22-02)

## Task Commits

1. **Task 1: Add narrative_short and narrative_deep to default_config providers** - `c8d2cbb` (feat)

## Files Created/Modified

- `services/ai_narrative_service.py` - Added narrative_short/narrative_deep provider lists; updated _build_chains() to direct access; updated SYSTEM_PROMPT voice

## Decisions Made

- Provider lists for narrative_short and narrative_deep start identical to per_signal — routing diverges as performance data accumulates via `_apply_score_routing()` and `llm_model_scores` table
- SYSTEM_PROMPT uses paraphrased constraints rather than listing banned phrases literally — avoids self-referential text that triggers "banned phrase found in SYSTEM_PROMPT" assertions
- Direct dict key access (`pcfg["narrative_short"]`) rather than `.get()` fallback — config entries now exist so fallback is unnecessary; KeyError makes missing config visible immediately

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Applied SYSTEM_PROMPT update and chain alias from prior incomplete TDD cycle**
- **Found during:** Task 1 (Add narrative_short and narrative_deep to default_config providers)
- **Issue:** Plan 22-02 TDD RED tests were committed but GREEN implementation (SYSTEM_PROMPT voice update, `short_chain`/`deep_chain` assignment) was never applied. Three tests failing: `test_system_prompt_establishes_analyst_voice`, `test_service_has_short_chain`, `test_service_short_chain_is_separate_from_deep_chain`. Full unit suite was blocked.
- **Fix:** Applied SYSTEM_PROMPT update to senior analyst voice; updated `_build_chains()` to assign `short_chain` and `deep_chain`; added `per_signal_chain = self.short_chain` alias; also updated `_make_svc_routing()` test helper to use `short_chain`/`deep_chain` mocks
- **Files modified:** services/ai_narrative_service.py, tests/unit/service_tests/test_ai_narrative_service.py
- **Verification:** All 33 test_ai_narrative_service.py tests pass; 1399 unit tests pass
- **Committed in:** c8d2cbb (task commit)

---

**Total deviations:** 1 auto-fixed (1 blocking — prior TDD incomplete cycle)
**Impact on plan:** Auto-fix necessary to satisfy plan's "Full unit suite passes" success criterion. No scope creep.

## Issues Encountered

- `test_ai_narrative_helpers.py` has a pre-existing collection error: imports `extract_short_context`, `extract_deep_context`, `build_short_prompt`, `build_deep_prompt`, `build_action_tag`, `get_structural_label` which are not yet committed (uncommitted changes in working tree from earlier plan execution). These functions exist as unstaged changes. Not part of this plan's scope — logged as out-of-scope.

## Next Phase Readiness

- Chain infrastructure complete: `short_chain`, `deep_chain`, `group_chain` all built from explicit config entries
- `_apply_score_routing()` already updated to use `narrative_short`/`narrative_deep` loop entries (from prior plan execution)
- Ready for plan 22-07: final integration and service wiring

## Self-Check: PASSED

- services/ai_narrative_service.py: FOUND
- 22-06-SUMMARY.md: FOUND
- Commit c8d2cbb: FOUND

---
*Phase: 22-i8-narrative-three-tier-redesign*
*Completed: 2026-03-09*
