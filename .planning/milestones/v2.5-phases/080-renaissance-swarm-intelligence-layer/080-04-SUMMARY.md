---
phase: 080-renaissance-swarm-intelligence-layer
plan: "04"
subsystem: ai-swarm
tags: [correlation-agent, cross-asset, multiplier-agent, shadow-only, phase-80]
dependency_graph:
  requires: [080-01]
  provides: [correlation_agent, correlation_prompts]
  affects: [alpha_swarm_group_service]
tech_stack:
  added: []
  patterns: [BaseMultiplierAgent, _validate_*_fields, coherence_score*confidence formula]
key_files:
  created:
    - src/intelligence/ai/alpha/correlation_agent.py
    - src/intelligence/ai/alpha/correlation_prompts.py
    - tests/unit/service_tests/test_correlation_agent.py
  modified: []
decisions:
  - "multiplier = coherence_score * confidence (D-04 formula); both clamped to [0,1] by validator"
  - "shadow_only=True at class level per Phase 80 discount-only policy"
  - "contradicting_assets non-list input coerced to [str(val)] for robustness"
metrics:
  duration: "~5 minutes"
  completed: "2026-05-07"
  tasks_completed: 3
  tasks_total: 3
  files_created: 3
  files_modified: 0
---

# Phase 80 Plan 04: CorrelationAgentComputeAgent (D-04) Summary

CorrelationAgentComputeAgent — cross-asset coherence multiplier extending BaseMultiplierAgent; judges whether ZN/VIX/ES/CL intermarket behavior supports or contradicts the I7 winner signal via `multiplier = coherence_score * confidence`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create correlation_prompts.py | 0160c2d1 | src/intelligence/ai/alpha/correlation_prompts.py |
| 2 | Create correlation_agent.py | 7d82e481 | src/intelligence/ai/alpha/correlation_agent.py |
| 3 | Unit tests for correlation_agent | d831f59e | tests/unit/service_tests/test_correlation_agent.py |

## Deviations from Plan

None — plan executed exactly as written.

## Verification Results

- `pytest tests/unit/service_tests/test_correlation_agent.py -v`: 7/7 passed
- `ruff check` all three files: clean
- Class attributes confirmed: `agent_id="correlation_v1"`, `shadow_only=True`, `tiers_needed={I1,I4,I6,I7}`, `latency_budget_ms=5000`
- Multiplier formula: `coherence_score * llm_confidence` (D-04 spec)
- Validator: strict type check on score/confidence, clamp to [0,1], coerce contradicting_assets to list[str]

## Self-Check: PASSED

- `src/intelligence/ai/alpha/correlation_agent.py`: FOUND
- `src/intelligence/ai/alpha/correlation_prompts.py`: FOUND
- `tests/unit/service_tests/test_correlation_agent.py`: FOUND
- Commit 0160c2d1: FOUND
- Commit 7d82e481: FOUND
- Commit d831f59e: FOUND
