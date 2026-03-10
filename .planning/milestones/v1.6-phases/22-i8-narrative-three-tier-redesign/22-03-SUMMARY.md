---
phase: 22-i8-narrative-three-tier-redesign
plan: "03"
subsystem: ai-narrative
tags: [asyncio, concurrent-tasks, llm-chain, redis-streams, i8, narrative-tiering]

requires:
  - phase: 22-01
    provides: extract_short_context, extract_deep_context, build_short_prompt, build_deep_prompt
  - phase: 22-02
    provides: short_chain, deep_chain, _per_signal_timeout, _preferred_models, SYSTEM_PROMPT

provides:
  - _run_narrative_call() standalone async method on AINarrativeService
  - Concurrent narrative_short + narrative_deep asyncio tasks per signal
  - narrative_type discriminator field in narratives stream messages
  - Intelligence context enrichment via xrevrange on intelligence:SYMBOL:TF
  - narrative_short backward-compat: updates narrative:SYMBOL:TF:latest hash

affects:
  - 22-04
  - 22-05
  - dashboard NarrativeCard (consumes narrative_type field)
  - llm_writer_service (consumes call_type=narrative_short/narrative_deep)

tech-stack:
  added: []
  patterns:
    - "asyncio.create_task() for fire-and-forget concurrent LLM calls — neither tier blocks the processing loop"
    - "_run_narrative_call() isolates single-tier end-to-end: LLM call + llm_calls publish + narratives publish"
    - "xrevrange(count=1) pattern for cheap latest-entry fetch from intelligence stream"
    - "call_type.replace('narrative_', '') maps call type to narrative_type field: 'short' or 'deep'"

key-files:
  created: []
  modified:
    - services/ai_narrative_service.py
    - tests/unit/service_tests/test_ai_narrative_service.py

key-decisions:
  - "narrative_short and narrative_deep fire as independent asyncio.create_task() calls — no await, no sequencing"
  - "xrevrange(count=1) fetches intel context before prompt building — empty list degrades gracefully (empty dict)"
  - "narrative_type = call_type.replace('narrative_', '') maps to 'short' or 'deep' in stream message"
  - "Test fixtures updated: _make_service_new() now has short_chain/deep_chain with AsyncMock generate defaults; asyncio.sleep(0.1) added to background-task-dependent assertions"
  - "test_promote_uses_regime_from_signal updated: uses narrative_short key (per_signal key retired)"

patterns-established:
  - "Background-task test pattern: await _process_single_message() + await asyncio.sleep(0.1) before asserting on xadd call_args_list"
  - "Fixture __new__ pattern: _make_service_concurrent() provides short_chain + deep_chain as separate AsyncMock chains with xrevrange=AsyncMock(return_value=[])"

requirements-completed:
  - I8-03
  - I8-04
  - I8-08

duration: 15min
completed: 2026-03-09
---

# Phase 22 Plan 03: Concurrent Narrative Tier Calls Summary

**_run_narrative_call() fires narrative_short + narrative_deep as concurrent asyncio tasks, each independently calling LLM chain, publishing to llm_calls:stream, and writing to narratives stream with narrative_type discriminator**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-09T17:11:00Z
- **Completed:** 2026-03-09T17:15:32Z
- **Tasks:** 1 (GREEN implementation — RED was committed a624d05 by prior agent)
- **Files modified:** 2

## Accomplishments

- Implemented `_run_narrative_call()` as a standalone async method handling full tier lifecycle: preferred-model promotion, LLM call with timeout, llm_calls:stream publish, narratives stream publish with `narrative_type` field
- Rewrote `_process_single_message()` to fetch intelligence context via `xrevrange`, build tier-specific prompts using 22-01 helpers, and fire both tiers as concurrent background tasks
- Fixed 7 pre-existing test regressions caused by the new concurrent task architecture: added `xrevrange` mocks, `asyncio.sleep(0.1)` guards, `short_chain`/`deep_chain` to `_make_service_new()` fixture

## Task Commits

1. **RED (prior agent):** `a624d05` - test(22-03): add failing test for concurrent narrative_short + narrative_deep tasks
2. **GREEN:** `67bb7c7` - feat(22-03): implement _run_narrative_call() and concurrent narrative tier dispatch

## Files Created/Modified

- `services/ai_narrative_service.py` - Added `_run_narrative_call()` method; rewrote `_process_single_message()` with intel fetch + concurrent task dispatch
- `tests/unit/service_tests/test_ai_narrative_service.py` - Updated fixtures for concurrent task architecture; fixed 7 regression tests

## Decisions Made

- `asyncio.create_task()` used for both tiers — neither blocks the message processing loop; failures in one tier don't affect the other
- `xrevrange(count=1)` fetches intel context before prompt building; empty list returns `{}` gracefully (no crash on cold streams)
- `narrative_type = call_type.replace("narrative_", "")` — clean mapping: `"narrative_short"` → `"short"`, `"narrative_deep"` → `"deep"`
- Test fixtures updated to use `short_chain`/`deep_chain` directly per plan spec; `_preferred_models` key updated from `"per_signal"` (retired) to `"narrative_short"`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed 7 test regressions from concurrent task architecture**
- **Found during:** GREEN phase (running tests after implementation)
- **Issue:** Old tests used `_make_service()` and `_make_service_new()` without `xrevrange` mock; new `_process_single_message()` calls `xrevrange` before creating tasks, causing `MagicMock` unpack errors. Also: background tasks now run after `await`, so xadd counts were 0 without a sleep.
- **Fix:** Added `xrevrange = AsyncMock(return_value=[])` to all affected fixtures; added `asyncio.sleep(0.1)` before xadd assertions; added `short_chain`/`deep_chain` with `AsyncMock` generate defaults to `_make_service_new()`; updated `test_promote_uses_regime_from_signal` to use `narrative_short` key
- **Files modified:** `tests/unit/service_tests/test_ai_narrative_service.py`
- **Committed in:** `67bb7c7` (GREEN commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Essential to keep full test suite green. No scope creep — test fixes only update mocks/assertions to match the new concurrent architecture that the plan specified.

## Issues Encountered

None — GREEN implementation was straightforward given the existing structure from 22-01 and 22-02.

## Next Phase Readiness

- `_run_narrative_call()` is complete and tested; 22-04 (dashboard) and 22-05 (NarrativeCard) can consume `narrative_type` field from narratives stream
- `llm_writer_service` will see `call_type=narrative_short` and `call_type=narrative_deep` in `llm_calls:stream`
- Full unit suite: 1426 passing, no regressions

## Self-Check: PASSED

- services/ai_narrative_service.py: FOUND
- tests/unit/service_tests/test_ai_narrative_service.py: FOUND
- Commit 67bb7c7: FOUND
- 1426 unit tests passing

---
*Phase: 22-i8-narrative-three-tier-redesign*
*Completed: 2026-03-09*
