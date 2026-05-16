---
phase: 083-observability-hardening
plan: "06"
subsystem: observability
tags: [alerting, prometheus-removal, otel, integration-tests]
dependency_graph:
  requires: [083-03]
  provides: [phase83-alert-rules, clean-prometheus-dependency]
  affects: [production/alertmanager-rules.yml, requirements.txt, src/api/main.py, tests/integration]
tech_stack:
  added: []
  patterns: [alertmanager-rule-groups, otel-module-attr-verification]
key_files:
  created: []
  modified:
    - production/alertmanager-rules.yml
    - requirements.txt
    - src/api/main.py
    - tests/integration/test_phase80_swarm_end_to_end.py
decisions:
  - "API /metrics endpoint returns 404 with redirect to OTel Collector at :8889 — prometheus_client lazy import removed; Collector continues serving PromQL"
  - "Integration test rewritten to verify OTel module attrs instead of prometheus REGISTRY — Plan 03 migrated metrics to OTel but test was still using old REGISTRY pattern"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-15"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 4
---

# Phase 083 Plan 06: Alert Rules + prometheus-client Removal Summary

Single-line: Added 5 alert rules in a new `phase83-observability` group and completed prometheus-client removal by cleaning up two remaining import sites (API metrics endpoint + broken integration test).

## Tasks Completed

| Task | Name | Commit | Key Output |
|------|------|--------|------------|
| 1 | Add 5 alert rules in phase83-observability group | 0ea036d1 | 48-line addition to alertmanager-rules.yml |
| 2 | Remove prometheus-client from requirements.txt | 067a0250 | requirements.txt cleaned; 3 files updated |

## What Was Done

**Task 1 - Alert rules:**
- Appended new group `phase83-observability` to `production/alertmanager-rules.yml`
- 5 rules added: LLMCircuitBreakerOpen, SwarmCapacitySkipRateHigh, ShadowPluginEVDecayed, PipelineP95LatencyRegression, DLQActivity
- Existing groups `indicagent_pipeline` and `phase81-signal-lifecycle` unchanged
- `promtool` not installed on this machine; rule YAML validated structurally via grep

**Task 2 - prometheus-client removal:**
- Confirmed Plan 03 cleaned all services/* and src/* call sites
- Found two remaining `prometheus_client` imports not addressed in Plan 03:
  1. `src/api/main.py` lazy import in `/metrics` endpoint
  2. `tests/integration/test_phase80_swarm_end_to_end.py` — `from prometheus_client import REGISTRY`
- Replaced `/metrics` endpoint with a 404 redirect to OTel Collector at `:8889/metrics`
- Rewrote integration test to check OTel module attrs (`SWARM_INVOCATIONS_TOTAL` etc.) and mock OTel counter for round-trip test
- Removed `prometheus-client>=0.24.0` from `requirements.txt`

## Verification Results

```
grep "phase83-observability" production/alertmanager-rules.yml  # 1 match
grep -cE "alert: (LLMCircuitBreakerOpen|...)" production/alertmanager-rules.yml  # 5
grep "indicagent_pipeline|phase81-signal-lifecycle" production/alertmanager-rules.yml  # both present
grep -i "^prometheus" requirements.txt  # empty
grep -rn "from prometheus_client|import prometheus_client" src/ services/ tests/  # empty
pytest tests/unit/ -q  # 3248 passed, 1 skipped
pytest tests/integration/test_phase80_swarm_end_to_end.py -v  # 4 passed
promtool not installed; skipped with note
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Two remaining prometheus_client imports not cleaned by Plan 03**
- **Found during:** Task 2 pre-check
- **Issue:** Plan 06 requires removing prometheus-client from requirements.txt, but `src/api/main.py` and `tests/integration/test_phase80_swarm_end_to_end.py` still imported it
- **Fix:** Replaced API /metrics lazy import with a 404+redirect response; rewrote integration test to use OTel module attrs and MagicMock for counter verification
- **Files modified:** `src/api/main.py`, `tests/integration/test_phase80_swarm_end_to_end.py`
- **Commit:** 067a0250

**2. [Rule 1 - Bug] Integration test passing stale `weights` positional arg**
- **Found during:** Task 2, running integration tests after prometheus removal
- **Issue:** `test_compute_final_multiplier_weighted_average` passed `weights` dict as 4th positional arg but `_compute_final_multiplier(self, agents, results, tf)` only takes 3 params; weights come from `self._agent_weights`
- **Fix:** Set `a._agent_weights` on the instance; removed extra `weights` arg from call
- **Files modified:** `tests/integration/test_phase80_swarm_end_to_end.py`
- **Commit:** 067a0250

## Self-Check: PASSED

- `production/alertmanager-rules.yml` - contains `phase83-observability` group with 5 rules
- `requirements.txt` - no prometheus-client line
- `src/api/main.py` - no prometheus_client import
- `tests/integration/test_phase80_swarm_end_to_end.py` - no prometheus_client import
- Commit `0ea036d1` - exists (Task 1)
- Commit `067a0250` - exists (Task 2)
- `pytest tests/unit/ -q` - 3248 passed, 1 skipped
