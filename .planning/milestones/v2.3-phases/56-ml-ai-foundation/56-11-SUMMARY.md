---
phase: 56
plan: "11"
subsystem: ml-orchestrator
tags: [langgraph, orchestrator, timer, stub, phase-56-final]
dependency_graph:
  requires: [56-09, 56-10]
  provides: [ml-orchestrator-pipeline]
  affects: [indicagent-ml-orchestrator.timer]
tech_stack:
  added: [langgraph>=1.0.0]
  patterns: [LangGraph StateGraph, TypedDict state, oneshot systemd timer, sequential fallback]
key_files:
  created:
    - services/ml_orchestrator_agent.py
    - tests/unit/service_tests/test_ml_orchestrator_agent.py
    - production/systemd/indicagent-ml-orchestrator.service
    - production/systemd/indicagent-ml-orchestrator.timer
  modified: []
decisions:
  - "Used _run() not run() — BaseAgent requires abstract _run(); plan had run() which does not exist in BaseAgent contract"
  - "Used ainvoke() not invoke() — langgraph compiled graph nodes are async; sync invoke() would deadlock event loop"
  - "langgraph availability probe via 'import langgraph.graph as _lg' — avoids unused import F401 from top-level try block"
  - "Sequential fallback (_run_sequential) when langgraph unavailable — degrades gracefully per Renaissance principle"
  - "setup_service_logging called before super().__init__() — matches BaseAgent ordering requirement"
  - "langgraph already in requirements.txt from prior plan — no requirements.txt change needed"
metrics:
  duration_minutes: 25
  completed_date: "2026-04-10"
  tasks_completed: 4
  files_created: 4
  files_modified: 0
---

# Phase 56 Plan 11: MLOrchestratorComputeAgent Summary

**One-liner:** LangGraph StateGraph weekly ML orchestrator with quality gate, sequential fallback, and stub TrainingNode/MonitorNode awaiting Phase 67.

## What Was Built

`MLOrchestratorComputeAgent` — a LangGraph `StateGraph` that sequences four nodes weekly (Monday 04:00 UTC):

1. **DataQualityNode** — triggers `indicagent-ml-data-quality.service`, reads composite score from `ml_data_quality_runs`
2. **Quality Gate** — if `score < DATA_QUALITY_MIN_SCORE` (0.85): skip to END with alert; otherwise continue
3. **DiscoveryNode** — triggers `indicagent-ml-discovery.service`, captures latest `run_id` from `ml_discovery_runs`
4. **TrainingNode** (stub) — logs "awaiting Phase 67", returns state unchanged
5. **MonitorNode** (stub) — logs "awaiting Phase 67", returns state unchanged

`MLOrchestrationState` TypedDict: `data_quality_score`, `last_discovery_run_id`, `model_status`, `last_error`.

Timer fires 1h before data quality (05:00) and 2h before discovery (06:00) to allow time for data quality check to complete before discovery starts.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Create MLOrchestratorComputeAgent + 4 unit tests (all pass) | `0d576f47` |
| 2 | langgraph already in requirements.txt — no change needed | (no commit) |
| 3 | Create systemd service + timer, install + enable | `481c2381` |
| 4 | Phase 56 final verification — imports, DB tables, timers | (no new commit) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed BaseAgent method name: run() -> _run()**
- **Found during:** Task 1 implementation
- **Issue:** Plan's code called `async def run()` but BaseAgent requires abstract `_run()`. `main()` also called `agent.run()` instead of `agent.start()`.
- **Fix:** Renamed to `_run()`, updated `main()` to call `agent.start()`
- **Files modified:** `services/ml_orchestrator_agent.py`
- **Commit:** `0d576f47`

**2. [Rule 1 - Bug] Used ainvoke() not invoke() for async LangGraph nodes**
- **Found during:** Task 1 implementation
- **Issue:** Plan's code used `compiled.invoke(initial_state)` (sync). All 4 nodes are async coroutines — sync invoke would deadlock the event loop.
- **Fix:** Changed to `await compiled.ainvoke(initial_state)`
- **Files modified:** `services/ml_orchestrator_agent.py`
- **Commit:** `0d576f47`

**3. [Rule 2 - Missing] setup_service_logging before super().__init__()**
- **Found during:** Task 1 — comparing with ml_data_quality_agent.py pattern
- **Issue:** Plan called `super().__init__()` without `setup_service_logging` before it. BaseAgent creates logger in `__init__` — logging must be configured first.
- **Fix:** Added `setup_service_logging("logs/ml_orchestrator_agent.log")` before `super().__init__()`
- **Files modified:** `services/ml_orchestrator_agent.py`
- **Commit:** `0d576f47`

**4. [Rule 3 - Blocking] Task 2 (install langgraph) was already complete**
- **Found during:** Task 2
- **Issue:** `langgraph>=1.0.0` already in requirements.txt from a prior Phase 56 plan. Running `pip freeze | grep langgraph >> requirements.txt` would add duplicates.
- **Fix:** Skipped the freeze step; verified import works. No requirements.txt change.
- **No commit needed**

## Phase 56 Final Verification

- **All Phase 56 imports:** PASS — `MLOrchestratorComputeAgent`, `FeatureVector`, `FeatureExtractor`, `ShadowRecorder`, `ModelRegistry`, `TrainingDataQuery`, `LLMProviderChain`, `NarrativeOrchestrator`, `IAlphaContributor`, `SwarmBaseAgent`
- **DB tables:** PASS — `alpha_multiplier_shadow`, `ml_models`, `ml_discovery_runs` all exist
- **ML timers:** PASS — all 3 armed: orchestrator (Mon 04:00 UTC), data-quality (Mon 05:00 UTC), discovery (Mon 06:00 UTC)
- **Unit tests:** 2889 passing + 4 new from plan 56-11; 37 pre-existing failures (all pre-date this plan, confirmed on main)
- **Pre-existing test collection error:** `test_llm_providers.py` ImportError on `AnthropicProvider` — present on main, out of scope

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| `_training_node` | `services/ml_orchestrator_agent.py` | ~200 | Intentional — Phase 67 implements LightGBM training |
| `_monitor_node` | `services/ml_orchestrator_agent.py` | ~208 | Intentional — Phase 67 implements model performance monitoring |

Both stubs are architecturally correct placeholders — the graph wiring, state schema, and routing are complete. Phase 67 adds implementations without architecture changes.

## Self-Check: PASSED

- `services/ml_orchestrator_agent.py` — FOUND
- `tests/unit/service_tests/test_ml_orchestrator_agent.py` — FOUND
- `production/systemd/indicagent-ml-orchestrator.service` — FOUND
- `production/systemd/indicagent-ml-orchestrator.timer` — FOUND
- Commit `0d576f47` — FOUND
- Commit `481c2381` — FOUND
