---
phase: 080-renaissance-swarm-intelligence-layer
plan: "06"
subsystem: intelligence/ai/alpha
tags: [ai-agent, counterfactual-reasoning, multiplier, shadow-mode, phase-80]
dependency_graph:
  requires: [080-01]
  provides: [CounterfactualAgentComputeAgent]
  affects: [alpha_swarm_group_service]
tech_stack:
  added: []
  patterns: [BaseMultiplierAgent, TDD, validator-clamp-pattern]
key_files:
  created:
    - src/intelligence/ai/alpha/counterfactual_prompts.py
    - src/intelligence/ai/alpha/counterfactual_agent.py
    - tests/unit/service_tests/test_counterfactual_agent.py
  modified: []
decisions:
  - "Used AIContext-typed prompt path only (v2 pattern, no legacy dict adapter needed for new agent)"
  - "shadow_only=True enforced at class level per Phase 80 discount-only policy"
  - "multiplier = plausibility * llm_confidence — pure discount formula, max 1.0 in practice"
metrics:
  duration_seconds: 147
  completed_date: "2026-05-07"
  tasks_completed: 3
  tasks_total: 3
  files_created: 3
  files_modified: 0
---

# Phase 80 Plan 06: CounterfactualAgentComputeAgent Summary

**One-liner:** CounterfactualAgentComputeAgent (D-06) with validation/invalidation reasoning via plausibility × confidence multiplier, shadow_only=True, tiers {I1, I4, I7}.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create counterfactual_prompts.py | 6e987d0e | src/intelligence/ai/alpha/counterfactual_prompts.py |
| 2 | Create counterfactual_agent.py | eaddc311 | src/intelligence/ai/alpha/counterfactual_agent.py |
| 3 | Unit tests for counterfactual_agent | 8a1acfad | tests/unit/service_tests/test_counterfactual_agent.py |

## What Was Built

**CounterfactualAgentComputeAgent** (`src/intelligence/ai/alpha/counterfactual_agent.py`):
- Extends `BaseMultiplierAgent` (Plan 01 base class)
- `agent_id = "counterfactual_v1"`, `group = "alpha"`, `shadow_only = True`
- `tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I7})`, `latency_budget_ms = 5000.0`
- Multiplier formula: `plausibility × llm_confidence` — discount-only per Phase 80 policy
- `_validate_counterfactual_fields()` clamps plausibility and confidence to [0.0, 1.0], coerces both list fields to `list[str]`
- Payload carries: `plausibility`, `validation_conditions`, `invalidation_conditions`, `reasoning`

**counterfactual_prompts.py** (`src/intelligence/ai/alpha/counterfactual_prompts.py`):
- `ACTIVE_VERSION = "counterfactual_v1"`, single entry in `PROMPT_REGISTRY`
- `build_counterfactual_prompt(ctx: AIContext)` raises `TypeError` for non-AIContext
- Prompt instructs LLM to list validation conditions (what must hold for signal to succeed) and invalidation conditions (what would negate it), then judge overall plausibility

**Test suite** (`tests/unit/service_tests/test_counterfactual_agent.py`):
- 10 tests covering: valid payload acceptance, non-numeric rejection, out-of-range clamping, non-list coercion (both fields), class attribute assertions, multiplier formula semantics, non-dict rejection, list item string coercion

## Verification

- `.venv/bin/pytest tests/unit/service_tests/test_counterfactual_agent.py -v` → 10 passed
- `.venv/bin/ruff check` → all checks passed on all three files

## Deviations from Plan

None — plan executed exactly as written.

The sibling reference files `correlation_agent.py` and `correlation_prompts.py` (Plan 04) were not yet present in this worktree, so `skeptic_agent.py` and `multiplier_agent.py` were used as structural references instead. No behavioral deviation.

## Self-Check: PASSED

- FOUND: src/intelligence/ai/alpha/counterfactual_prompts.py
- FOUND: src/intelligence/ai/alpha/counterfactual_agent.py
- FOUND: tests/unit/service_tests/test_counterfactual_agent.py
- FOUND commit: 6e987d0e (counterfactual_prompts.py)
- FOUND commit: eaddc311 (counterfactual_agent.py)
- FOUND commit: 8a1acfad (test_counterfactual_agent.py)
