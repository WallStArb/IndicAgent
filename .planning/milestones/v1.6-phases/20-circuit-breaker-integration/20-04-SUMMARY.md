---
phase: 20-circuit-breaker-integration
plan: "04"
subsystem: observability
tags: [circuit-breaker, prometheus, metrics, llm, ibkr]
dependency_graph:
  requires: ["20-02", "20-03"]
  provides: [circuit-breaker-prometheus-metrics]
  affects: [src/observability/metrics.py, src/intelligence/llm_providers.py, src/providers/ibkr.py]
tech_stack:
  added: []
  patterns: [prometheus-counter, prometheus-histogram, circuit-breaker-metrics]
key_files:
  created: []
  modified:
    - src/observability/metrics.py
    - src/intelligence/llm_providers.py
    - src/providers/ibkr.py
decisions:
  - "Circuit breaker state transitions use state snapshots (previous_state captured before operation) to detect actual changes at metric recording time"
  - "CIRCUIT_BREAKER_OPEN_SECONDS histogram defined in metrics.py but not yet wired to actual timing — available for future OPEN state duration tracking"
  - "Pre-existing 6 test failures in tests/unit/test_llm_providers.py::TestZAIProvider patching a local import — pre-existing, out of scope"
metrics:
  duration: 303
  completed_date: "2026-03-09"
  tasks: 3
  files: 3
---

# Phase 20 Plan 04: Circuit Breaker Metrics Summary

**One-liner:** Prometheus metrics for circuit breaker failures, successes, and state transitions wired into LLM provider chain and IBKR connection layer.

## What Was Built

Four new Prometheus metrics added to `src/observability/metrics.py` and connected to both LLM and IBKR circuit breaker call sites. All circuit breaker events (success, failure, state transition) are now captured with provider-specific labels for Prometheus/Grafana monitoring.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add circuit breaker metrics to metrics.py | d156438 | src/observability/metrics.py |
| 2 | Wire metrics into llm_providers.py | 6988041 | src/intelligence/llm_providers.py |
| 3 | Wire metrics into ibkr.py | 9a66148 | src/providers/ibkr.py |

## Metrics Added

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `circuit_breaker_failures_total` | Counter | plugin_name, error_type | Count failures per provider and exception class |
| `circuit_breaker_successes_total` | Counter | plugin_name | Count successes per provider |
| `circuit_breaker_state_transitions_total` | Counter | plugin_name, from_state, to_state | Track state machine transitions |
| `circuit_breaker_open_duration_seconds` | Histogram | plugin_name | Time spent in OPEN state (buckets: 1s to 1800s) |

## Integration Points

**LLM providers** (`_call_llm_with_circuit_breaker`):
- `plugin_name` = provider_id (e.g., `"zai:glm-5"`, `"ollama:qwen3.5:9b"`)
- Success: increments `CIRCUIT_BREAKER_SUCCESSES_TOTAL`
- Failure: increments `CIRCUIT_BREAKER_FAILURES_TOTAL` with `error_type=ConnectionError` etc.
- Transition to OPEN: increments `CIRCUIT_BREAKER_TRANSITIONS_TOTAL(from=closed, to=open)`
- Recovery to CLOSED: increments `CIRCUIT_BREAKER_TRANSITIONS_TOTAL(from=open|half_open, to=closed)`

**IBKR connection** (`_connect_with_circuit_breaker` + `reset_circuit_breaker`):
- `plugin_name` = `"ibkr:connection"` (singleton connection)
- Same success/failure/transition recording as LLM providers
- `reset_circuit_breaker()` additionally records a manual forced transition if state was non-closed

## Deviations from Plan

### Deferred Issues (out of scope)

**Pre-existing: 6 tests in tests/unit/test_llm_providers.py::TestZAIProvider fail**
- Patch path `src.intelligence.llm_providers.to_thread` doesn't exist at module level
- `to_thread` is imported locally inside `_call_llm_with_circuit_breaker` function body
- These tests were failing before this plan — confirmed by `git stash` test run
- Not fixed: out of scope for this plan (pre-existing, no regression introduced)

## Verification

```
import check: from src.observability.metrics import CIRCUIT_BREAKER_FAILURES_TOTAL, ...
  -> All new metrics imported OK

tests/unit/intelligence/test_llm_providers.py: 19 passed
tests/unit/providers/test_ibkr_provider.py: 13 passed
tests/unit/ total: 1346 passed, 6 pre-existing failures (unchanged)
```

## Self-Check

### Files Exist
- src/observability/metrics.py: FOUND
- src/intelligence/llm_providers.py: FOUND
- src/providers/ibkr.py: FOUND

### Commits Exist
- d156438: FOUND
- 6988041: FOUND
- 9a66148: FOUND

## Self-Check: PASSED
