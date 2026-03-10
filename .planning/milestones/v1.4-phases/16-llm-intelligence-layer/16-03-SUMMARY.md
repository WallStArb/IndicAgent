---
phase: 16-llm-intelligence-layer
plan: "03"
subsystem: services
tags: [llm, redis, instrumentation, adaptive-routing, prometheus, tdd]

# Dependency graph
requires:
  - phase: 16-01
    provides: "llm_calls:stream key helper, llm_scores_cache key helper"
  - phase: 16-02
    provides: "LLMWriterService consuming llm_calls:stream, score cache at llm_scores:{call_type}:{regime}"
provides:
  - "services/ai_narrative_service.py — instrumented with xadd on all 3 call paths + adaptive routing"
  - "_build_llm_call_payload: pure function building flat str dict for Redis xadd"
  - "_promote_model_in_chain: atomic list replacement for concurrent-safe provider reordering"
  - "_score_refresh_loop: 5-min cadence reads Redis hgetall, promotes is_significant winner"
  - "_apply_score_routing: called at startup + every 5 min to apply score-driven routing"
affects: [16-04-lifecycle-emission, 16-05-deployment]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fire-and-forget xadd: asyncio.create_task(redis_client.xadd(llm_calls_stream(...), payload)) — zero latency impact on narrative publishing"
    - "Counterfactual logging: low-confidence signals emit call_type='counterfactual' with succeeded=0 — captures what the model would have seen"
    - "Atomic chain promotion: chain.providers = [target] + rest (list replacement, not mutation) — safe for concurrent reads"

key-files:
  created: []
  modified:
    - services/ai_narrative_service.py
    - tests/unit/service_tests/test_ai_narrative_service.py

key-decisions:
  - "Per-signal emit fires even on LLM failure (narrative_text=None) — succeeded='0' in payload, latency captured, model logged — maximum data capture"
  - "Counterfactual emit uses build_narrative_prompt() to construct prompt even though LLM is never called — captures what the model would have received"
  - "_apply_score_routing selects best_model by max avg_pnl_r across all regimes (not per-regime) — simpler first implementation, per-regime routing deferred"
  - "Two pre-existing tests updated to reflect new emit-on-every-call behavior (test_process_message_handles_ollama_failure, test_group_synthesis_fires_on_fingerprint_change)"

requirements-completed: [LLM-02, LLM-05]

# Metrics
duration: 4min
completed: 2026-03-05
---

# Phase 16 Plan 03: AI Narrative Instrumentation Summary

**ai_narrative_service instrumented with fire-and-forget xadd on all three call paths (counterfactual, per-signal, group synthesis) + _score_refresh_loop reading Redis score cache every 5 min for adaptive model routing**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-05T00:03:14Z
- **Completed:** 2026-03-05T00:07:24Z
- **Tasks:** 3 (task 3 was verification-only, no commit)
- **Files modified:** 2

## Accomplishments

- `_build_llm_call_payload` — pure function producing a flat `dict[str, str]` with all 18 required Redis stream fields; all values guaranteed str
- `_promote_model_in_chain` — atomic list replacement (`chain.providers = [target] + rest`) safe against concurrent reads from process_loop and group_synthesis_loop
- Counterfactual emit added at confidence gate: signals with confidence <= 0.70 now emit `call_type='counterfactual'`, `succeeded='0'`, `response=''` — no LLM call made but full signal context captured
- Per-signal emit: fires after every `per_signal_chain.generate()` call regardless of success/failure; latency_ms and model_id always captured
- Group synthesis emit: fires after every `group_chain.generate()` call
- `_score_refresh_loop` added: 5-min sleep loop using `asyncio.wait_for(shutdown_event.wait(), 300)` for clean shutdown
- `_apply_score_routing`: reads `llm_scores:{call_type}:{regime}` via hgetall for 4 regimes, promotes best `is_significant=True` model by `avg_pnl_r`
- `start()` calls `_apply_score_routing()` once before tasks launch — routing applied before first LLM call
- 7 new unit tests GREEN (payload builder x3, chain promotion x4); 2 existing tests updated for new emit behavior
- Full unit suite: **1156 passing**, 0 regressions

## Task Commits

1. **Task 1: _build_llm_call_payload and _promote_model_in_chain** - `c94e848` (feat)
2. **Task 2: Wire xadd + _score_refresh_loop** - `b18e266` (feat)
3. **Task 3: Full unit suite regression** — verification-only, no commit

## Files Created/Modified

- `services/ai_narrative_service.py` — added `import uuid`, `llm_calls_stream`, `llm_scores_cache` imports; `_build_llm_call_payload`, `_promote_model_in_chain` module-level functions; 3 fire-and-forget xadd calls; `_score_refresh_loop`, `_apply_score_routing` methods; wired in `start()`
- `tests/unit/service_tests/test_ai_narrative_service.py` — 7 new tests; `import asyncio` added; 2 existing tests updated; E501/E702 ruff fixes applied

## Decisions Made

- Per-signal xadd emits even when LLM fails (narrative_text=None) — `succeeded='0'`, full context preserved — data capture takes priority over brevity
- Counterfactual uses `build_narrative_prompt()` to capture the would-have-been prompt text — useful for offline LLM simulation studies
- `_apply_score_routing` picks global best across regimes (max avg_pnl_r where is_significant=True) rather than per-regime best — simpler first iteration; per-regime adaptive routing can be added once enough regime-segmented data accumulates

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Two existing tests broke after emit-on-every-call change**
- **Found during:** Task 2
- **Issue:** `test_process_message_handles_ollama_failure` asserted `xadd.assert_not_called()` — now xadd fires for the per-signal call record even on LLM failure. `test_group_synthesis_fires_on_fingerprint_change` used `assert_called_once()` but now 2 xadd calls fire (llm_calls + narratives:group)
- **Fix:** Updated both tests to check specific stream names in xadd call args rather than call count; added `await asyncio.sleep(0)` to flush create_task
- **Files modified:** `tests/unit/service_tests/test_ai_narrative_service.py`

**2. [Rule 1 - Bug] Ruff E501/E702 in test file from plan-provided code**
- **Found during:** Task 1/2
- **Issue:** Plan code examples used semicolons (`p1 = MagicMock(); p1.provider_id = ...`) and long lines
- **Fix:** Expanded to multi-line, added noqa for pre-existing E501

## Out-of-Scope Items Deferred

`tests/unit/service_tests/test_feature_writer_service.py` has pre-existing ruff I001/E501 errors (8 errors). Out of scope — logged here, not fixed.

## Self-Check

- `services/ai_narrative_service.py` — 3 `create_task.*xadd` calls confirmed (lines 525, 556, 805)
- `_score_refresh_loop` — confirmed at line 684, wired in start() line 880
- `_apply_score_routing` — confirmed at line 704, called at startup line 875
- Commits `c94e848` and `b18e266` — confirmed in git log
- 1156 unit tests passing — confirmed

## Self-Check: PASSED

---
*Phase: 16-llm-intelligence-layer*
*Completed: 2026-03-05*
