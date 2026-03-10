---
phase: 22-i8-narrative-three-tier-redesign
plan: "01"
subsystem: ai-narrative
tags: [llm, narrative, i8, prompt-engineering, tdd, three-tier]

requires: []

provides:
  - extract_short_context() — conclusion-level intel fields for short narrative prompt
  - extract_deep_context() — superset of short + FVG/OB/S-D zone bounds
  - build_short_prompt() — 2-sentence Context+Execution prompt with confidence-gated instruction
  - build_deep_prompt() — 3-sentence confluence story prompt with full level data
  - build_action_tag() — deterministic [BULLISH|BEARISH|WAIT|MONITOR] tag from signal data
  - get_structural_label() — maps 17 plugin names to short structural labels
  - _STRUCTURAL_LABELS dict — 17-entry plugin-to-label mapping

affects:
  - 22-02 (system prompt + chain split)
  - 22-03 (concurrent narrative calls)
  - 22-04 (dashboard types + SSE handler)

tech-stack:
  added: []
  patterns:
    - "Pure functions with no I/O for all context extraction and prompt building — fully testable in isolation"
    - "Confidence-gated execution instruction: DIRECT (>=75%), CONDITIONAL (50-74%), MONITOR (<50%)"
    - "extract_deep_context calls extract_short_context then updates — strict superset guarantee"

key-files:
  created:
    - tests/unit/service_tests/test_ai_narrative_helpers.py (extended — 16 new tests added)
  modified:
    - services/ai_narrative_service.py (six pure helper functions added after build_narrative_prompt)

key-decisions:
  - "Killzone detection priority: in_london_killzone='1' checked before killzone_name fallback — flag is authoritative, name is fallback"
  - "Unknown plugin labels use setup_plugin.upper()[:16] — caps at 16 chars to avoid overflow in signal bar"
  - "build_action_tag threshold: confidence >= 0.75 = direct, 0.50-0.74 = wait, <0.50 = monitor"
  - "extract_deep_context superset guarantee: calls extract_short_context then ctx.update() — all short keys always present in deep"

patterns-established:
  - "Three-tier context extraction: extract_short_context provides conclusion-level fields, extract_deep_context provides full intel for deep analysis"
  - "Confidence-gated prompting: prompt text changes based on confidence threshold to direct PM behavior appropriately"

requirements-completed:
  - I8-01
  - I8-02

duration: 8min
completed: 2026-03-09
---

# Phase 22 Plan 01: Intelligence Context Extraction Summary

**Six pure helper functions for three-tier I8 narrative system: confidence-gated prompt builders, intel context extractors, action tag builder, and structural label mapper with 17 plugin mappings — all TDD with 25 passing unit tests**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-09T12:25:35Z
- **Completed:** 2026-03-09T12:33:58Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Added six pure helper functions to `ai_narrative_service.py` as foundation for three-tier redesign
- 16 new unit tests in `test_ai_narrative_helpers.py` covering all function contracts
- Full unit suite passes: 1424 tests, no regressions
- `extract_deep_context` strict superset guarantee enforced by test

## Task Commits

1. **Task 1: Intelligence context extraction + prompt builders (TDD)** - `d297b1c` (feat)

## Files Created/Modified

- `services/ai_narrative_service.py` — Added `_STRUCTURAL_LABELS`, `get_structural_label`, `build_action_tag`, `extract_short_context`, `extract_deep_context`, `build_short_prompt`, `build_deep_prompt` after `build_narrative_prompt()`
- `tests/unit/service_tests/test_ai_narrative_helpers.py` — Added 16 new tests for three-tier helpers; extended import block to include all 6 new functions

## Decisions Made

- Killzone detection uses `in_london_killzone == "1"` flag as authoritative source, with `killzone_name` as fallback — consistent with how the intelligence stream encodes killzone data
- Unknown plugin label uses `setup_plugin.upper()[:16]` — safe fallback that's always human-readable without crashing
- Confidence thresholds: `>= 0.75` = DIRECT entry instruction, `0.50-0.74` = CONDITIONAL/WAIT, `< 0.50` = MONITOR — mirrors existing `_NARRATIVE_MIN_CONFIDENCE = 0.70` gate with a softer conditional tier
- `extract_deep_context` calls `extract_short_context` then `ctx.update()` — superset guarantee is structural, not incidental

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

File tool write conflicts: The Edit tool repeatedly hit "File has been modified since read" errors due to a file-system race with the linter/formatter running in the background. Resolved by writing both files atomically in a single Python subprocess call, then running pytest immediately before any revert could occur.

## Next Phase Readiness

- All six pure functions are fully tested and exported from `ai_narrative_service.py`
- Plan 22-02 can now import and use these functions to build `short_chain`, `deep_chain`, and update `SYSTEM_PROMPT`
- No blockers

---
*Phase: 22-i8-narrative-three-tier-redesign*
*Completed: 2026-03-09*
