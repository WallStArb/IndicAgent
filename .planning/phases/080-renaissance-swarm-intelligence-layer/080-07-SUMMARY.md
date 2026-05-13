---
phase: 080-renaissance-swarm-intelligence-layer
plan: 07
subsystem: alpha-swarm
tags: [swarm, multi-agent, dispatch, weighted-aggregation, graduation, weight-learning]
dependency_graph:
  requires: [080-01, 080-02, 080-03, 080-04, 080-05, 080-06]
  provides: [multi-agent-dispatch, weighted-multiplier, spearman-weight-learning, swarm-aggregate-event]
  affects: [alpha-swarm-compute-agent, signal-lineage, swarm-agent-weights, shadow-registry]
tech_stack:
  added: []
  patterns:
    - list-driven dispatch (self._agents: list[BaseMultiplierAgent])
    - asyncio.Semaphore capacity guard with SWARM_QUEUE_TIMEOUT_MS skip path
    - per-(agent_id, timeframe) Spearman weight learning via swarm_agent_weights UPSERT
    - normalized weighted aggregation (Σ(wᵢ×mᵢ)/Σ(wᵢ)) over non-error agents
    - shadow registry refresh from DB (source of truth per D-07)
key_files:
  created: []
  modified:
    - services/alpha_swarm_agent.py
    - tests/unit/service_tests/test_alpha_swarm_agent.py
decisions:
  - Replaced old Spearman-for-skeptic-only graduation logic with per-agent _evaluate_agent loop; old promotion/demotion gate tests updated to test new per-agent iteration semantics
  - _record_swarm_result now takes an explicit `agent` parameter for future-compatible metadata (shadow_at_write, prompt_version, parse_status)
  - Old Phase 78 `test_single_agent_swarm_only_skeptic` replaced by `test_swarm_agents_are_four_typed_agents` to reflect Plan 80-07 multi-agent architecture
metrics:
  duration: "7 minutes"
  completed: "2026-05-07"
  tasks_completed: 4
  files_changed: 2
---

# Phase 80 Plan 07: Alpha Swarm Multi-Agent Dispatch Summary

One-liner: Refactored AlphaSwarmComputeAgent from single-Skeptic to list-driven multi-agent dispatch with TF/schema gates, capacity semaphore, normalized weighted aggregation, per-agent lineage, and Spearman weight learning.

## What Was Built

`services/alpha_swarm_agent.py` refactored from single-Skeptic architecture to a typed multi-agent dispatcher. All four Phase 80 agents (Skeptic, Correlation, RegimeCoherence, Counterfactual) are now in `self._agents: list[BaseMultiplierAgent]`, constructed in `_setup()` after `super()._setup()` (CLAUDE.md LLM chain rule).

### Task 1: Agent Registration + Gates + Capacity Semaphore

- `self._agents: list[BaseMultiplierAgent]` with four agents in order: Skeptic → Correlation → RegimeCoherence → Counterfactual
- `self._semaphore = asyncio.Semaphore(settings.SWARM_MAX_CONCURRENT_CALLS)` in `_setup()`
- TF gate: `_TF_MINUTES` dict replaces old `_ELIGIBLE_TFS` frozenset; driven by `settings.SWARM_MIN_TF_MINUTES`
- Schema gate: `signal_schema_version != 'v1'` returns early before any context build
- Capacity guard: `asyncio.wait_for(self._semaphore.acquire(), timeout_s)` with `capacity_skip` metric on TimeoutError
- Both gates placed before context cache build (zero cost for ineligible signals)
- Per-agent `SWARM_INVOCATIONS_TOTAL` + `SWARM_MULTIPLIER_DISTRIBUTION` metrics after gather

### Task 2: Weighted Aggregation + Lineage + Shadow Enrollment

- `_compute_final_multiplier(agents, results, agent_weights, tf)` → normalized weighted average; returns `(None, 0)` when all fail
- Default weight = `1/N` when `(agent_id, tf)` absent from `self._agent_weights`
- Per-agent lineage record with future-compatible metadata: `shadow_at_write`, `parse_status`, `prompt_version`, `payload`
- Aggregate event published on `topic_swarm_alpha(env_name)` with `msg=` kwarg (CLAUDE.md rule)
- `_shadow_registry_ensure_swarm` loops over `self._agents` (replaced single skeptic enrollment)
- `_refresh_shadow_state_from_registry` refreshes `agent.shadow_only` from DB after each graduation cycle
- `SWARM_AGGREGATED_MULTIPLIER` histogram observed when final multiplier is not None
- `all_failed` counter when all agents fail; no aggregate event emitted

### Task 3: Per-Agent Spearman Weight Learning

- `_run_graduation_cycle` iterates `self._agents`, calls `_evaluate_agent(agent_id)` per agent
- `_evaluate_agent`: queries `signal_lineage JOIN signal_ledger` for 30-day window; skips `< SWARM_WEIGHT_MIN_SAMPLES`
- Spearman rho via `scipy.stats.spearmanr` (local import); NaN guard; weight = `max(WEIGHT_FLOOR, 0.5 + rho)`
- Computes `calibration_error = |mean(stated_confidence) - empirical_win_rate|`
- UPSERT into `swarm_agent_weights(agent_id, timeframe, ...)` ON CONFLICT DO UPDATE
- `SWARM_AGENT_WEIGHT.labels(agent_id, timeframe).set(weight)` after each upsert
- `_reload_agent_weights` renormalizes per-timeframe weights and refreshes `self._agent_weights` cache
- `_refresh_shadow_state_from_registry` called at end of cycle

### Task 4: Extended Test Suite

New tests appended (7 new tests in addition to updated existing tests):

- `test_compute_final_multiplier_excludes_errors`: verifies weighted avg uses only valid agents
- `test_compute_final_multiplier_returns_none_when_all_fail`: all-error → (None, 0)
- `test_no_direct_signal_ledger_writes`: source-level assertion of zero UPDATE/INSERT signal_ledger
- `test_shadow_enrollment_loops_all_agents`: all four agent_ids enrolled via pool.execute
- `test_tf_gate_skips_signals_below_min_minutes`: 1m signal → no agent.compute called
- `test_schema_gate_skips_v0_signals`: v0 signal → no agent.compute called
- `test_capacity_skip_increments_metric`: pre-acquired semaphore → `capacity_skip` Prometheus counter increments

Final test count: 29 passing (22 original + 7 new).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _record_swarm_result signature change broke existing tests**

- **Found during:** Task 4 (test run)
- **Issue:** Plan 80-07 changed `_record_swarm_result(signal_id, enriched, result)` to `_record_swarm_result(signal_id, enriched, agent, result)` to support per-agent metadata. Four existing tests called the old 3-arg form.
- **Fix:** Added `mock_agent = MagicMock(...)` in each affected test and updated call sites.
- **Files modified:** `tests/unit/service_tests/test_alpha_swarm_agent.py`
- **Commit:** e0e51b7c

**2. [Rule 1 - Bug] test_single_agent_swarm_only_skeptic contradicted Plan 80-07 spec**

- **Found during:** Task 4 (test run)
- **Issue:** Existing test asserted `CorrelationAgentComputeAgent` is NOT importable from module — directly contradicted by Plan 80-07 which adds it. Phase 78 test vs Phase 80 spec conflict.
- **Fix:** Replaced with `test_swarm_agents_are_four_typed_agents` asserting all four agents importable; VolumeAgentComputeAgent still asserted absent.
- **Files modified:** `tests/unit/service_tests/test_alpha_swarm_agent.py`
- **Commit:** e0e51b7c

**3. [Rule 1 - Bug] Phase 78 graduation tests tested removed code path**

- **Found during:** Task 4 (test run)
- **Issue:** Three existing graduation tests (`test_promotion_gate_promotes_with_100_positive_samples`, `test_under_n_no_eval`, `test_demotion_streak_fires_after_3_consecutive_negative_cycles`) tested the old `_run_graduation_cycle` which did Spearman directly for skeptic_v1. New cycle delegates to `_evaluate_agent` per agent — old test mocks and assertions were invalid.
- **Fix:** Replaced three tests with three new tests exercising the actual new semantics: per-agent iteration, error isolation, empty-agents case.
- **Files modified:** `tests/unit/service_tests/test_alpha_swarm_agent.py`
- **Commit:** e0e51b7c

**4. [Rule 3 - Blocking] Worktree lacked .venv symlink — pre-commit hook blocked all commits**

- **Found during:** Task 1 commit
- **Issue:** Pre-commit hook at `.git/hooks/pre-commit` looks for `.venv/bin/ruff` in REPO_ROOT. Worktree has no `.venv`. Hook failed with "ruff not found".
- **Fix:** Created `.venv` symlink in worktree pointing to main repo's `.venv`: `ln -sf /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a85de5edfc4a5dc51/.venv`
- **Files modified:** `.venv` (symlink in worktree)

## Self-Check

Files created/modified:
- services/alpha_swarm_agent.py: exists ✓
- tests/unit/service_tests/test_alpha_swarm_agent.py: exists ✓

Commits:
- a13adf6c: feat(080-07): replace agent registration with typed list + apply gates and capacity semaphore
- e0e51b7c: feat(080-07): update tests to match Plan 80-07 multi-agent architecture
- 6b932a2d: test(080-07): add new dispatch tests for TF gate, schema gate, capacity skip, weighted aggregation

## Self-Check: PASSED
