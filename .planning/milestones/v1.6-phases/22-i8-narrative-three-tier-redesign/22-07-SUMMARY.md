---
phase: 22-i8-narrative-three-tier-redesign
plan: "07"
subsystem: ai
tags: [llm, narrative, i8, ai-narrative, ollama, openrouter]

# Dependency graph
requires:
  - phase: 22-03
    provides: concurrent narrative tier dispatch (_run_narrative_call, asyncio.create_task for short+deep)
  - phase: 22-05
    provides: three-tier NarrativeCard dashboard component with action_tag badge and expand toggle
  - phase: 22-06
    provides: action_tag deterministic generation, extract_short_context, extract_deep_context, build_short_prompt, build_deep_prompt
provides:
  - Live three-tier pipeline verified end-to-end (narrative_short + narrative_deep in llm_calls:stream, per_signal=0)
  - Old single-call path retired: build_narrative_prompt() tombstoned, per_signal_chain alias removed, per_signal routing entry removed
  - Final clean service state with no dead code confusion between old and new paths
affects:
  - llm_writer_service (consumes narrative_short and narrative_deep call types)
  - signal_ledger (signal lifecycle outcomes feed score routing)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Tombstone comment pattern for retired functions: one-line comment marking retirement + successor references"
    - "Config key name preservation: per_signal key kept in default_config for historical continuity; functional routing uses narrative_short/narrative_deep"

key-files:
  created: []
  modified:
    - services/ai_narrative_service.py

key-decisions:
  - "per_signal config key preserved in default_config providers dict — documents historical fallback chain; only functional routing code removed"
  - "Tombstone comment placed at line of retired function (build_narrative_prompt) rather than at call sites — single source of truth for retirement documentation"

patterns-established:
  - "Verification pattern: xrevrange(count=30) on llm_calls:stream confirms call_type distribution before cleanup commit"
  - "Retirement pattern: tombstone comment + alias removal + routing loop cleanup as three distinct micro-changes in one commit"

requirements-completed: [I8-07, I8-08, I8-09, I8-10]

# Metrics
duration: 15min
completed: 2026-03-09
---

# Phase 22 Plan 07: Verify and Retire Old Narrative Path Summary

**Three-tier I8 pipeline end-to-end verified (13 narrative_short + 11 narrative_deep in live stream, 0 per_signal) and old single-call path cleanly retired with tombstone**

## Performance

- **Duration:** ~15 min (continuation from previous session — tasks 1-3 committed, task 4 dashboard checkpoint approved)
- **Started:** 2026-03-09 (continuation)
- **Completed:** 2026-03-09
- **Tasks:** 4 (checkpoint + 2 auto + checkpoint)
- **Files modified:** 1

## Accomplishments

- Live stream verification confirmed: `narrative_short` (13 entries) and `narrative_deep` (11 entries) in `development:llm_calls:stream`, `per_signal` count = 0
- Old `build_narrative_prompt()` function retired with tombstone comment pointing to `build_short_prompt()` / `build_deep_prompt()` successors
- `per_signal_chain` alias removed from `_build_chains()`; `("per_signal", ...)` entry removed from `_apply_score_routing()` loop
- Full unit suite passes at 1425 tests (above 1318+ threshold)
- Dashboard human-verify checkpoint approved: action_tag badge, short narrative, deep expand toggle all confirmed working

## Task Commits

Each task was committed atomically:

1. **Task 1: Service restart** — human-action checkpoint (user restarted `indicagent-ai-narrative`)
2. **Task 2: Verify live stream output** — verified via xrevrange on `development:llm_calls:stream`
3. **Task 3: Retire old single-call path** — `ba0d392` (refactor)
4. **Task 4: Dashboard human-verify** — checkpoint approved by user

**Plan metadata:** (this commit — docs: complete 22-07 plan)

## Files Created/Modified

- `services/ai_narrative_service.py` — tombstone at line 177, `per_signal_chain` alias removed, `per_signal` routing entry removed

## Decisions Made

- `per_signal` config key preserved in `default_config` providers dict — documents historical fallback chain configuration; only the functional routing code (`_apply_score_routing` loop entry and `_build_chains` alias) was removed
- Tombstone comment placed at the location of the retired `build_narrative_prompt()` function body, not at call sites — single authoritative retirement marker

## Deviations from Plan

None — plan executed exactly as written. The continuation agent picked up from the correct state (Tasks 1-3 already committed at `ba0d392`, Task 4 checkpoint previously approved).

## Issues Encountered

None. All ruff errors are pre-existing E501 (line-too-long), non-blocking. No new errors introduced.

## User Setup Required

None — no external service configuration required. Service was already restarted (Task 1 checkpoint) in the previous session.

## Next Phase Readiness

- Phase 22 is now complete. All 7 plans executed. Three-tier I8 narrative pipeline is fully operational:
  - Deterministic `action_tag` from I7 signal data (no LLM)
  - Fast `narrative_short` (~500ms, 2 sentences) via `short_chain`
  - Deep `narrative_deep` (~5-8s, full analysis) via `deep_chain`
  - Group synthesis via `group_chain`
  - Dashboard three-tier layout: amber mono badge + short text + expand toggle
- `llm_writer_service` persists both `narrative_short` and `narrative_deep` call types to `llm_calls` hypertable
- No blockers for next milestone planning

---
*Phase: 22-i8-narrative-three-tier-redesign*
*Completed: 2026-03-09*
