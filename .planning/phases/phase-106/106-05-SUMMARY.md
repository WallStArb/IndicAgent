---
phase: 106-foundation-hardening
plan: "05"
subsystem: observability
tags: [circuit-breaker, shadow-mode, plugin-isolation, otel, structlog]
dependency_graph:
  requires: [106-04]
  provides: [plugin-circuit-breakers-wired]
  affects: [intelligence-pipeline-agent, executor, circuit-breaker]
tech_stack:
  added: []
  patterns: [shadow-mode-first, otel-gauge, structlog-warning, dataclass-flag]
key_files:
  created: []
  modified:
    - src/observability/circuit_breaker.py
    - services/intelligence_pipeline_agent.py
decisions:
  - Plugin circuit breakers use enabled=False (shadow mode) by default; PLUGIN_CB_ENABLED=true activates gating
  - OTel gauge uses get_meter("indicagent") directly to avoid circular import with src.observability.metrics
  - name param added to CircuitBreaker dataclass to support labeled gauge + structlog warning
  - _build_plugin_circuit_breakers() is a synchronous helper called at _setup() time
metrics:
  duration: "~10 minutes"
  completed: "2026-05-24"
  tasks: 2
  files_modified: 2
---

# Phase 106 Plan 05: Plugin Circuit Breaker Wiring Summary

Per-plugin circuit breakers wired into the intelligence pipeline with transparent shadow mode; live routing unchanged until PLUGIN_CB_ENABLED is set.

## What Was Built

**Task 1: Shadow-mode flag + state-transition observability (src/observability/circuit_breaker.py)**

Added to `CircuitBreaker` dataclass:
- `name: str | None = None` — breaker identity for gauge labels and structlog
- `enabled: bool = True` — shadow-mode flag; default True preserves active-gate behavior for existing callers
- `_PLUGIN_CB_GLOBAL_ENABLE` — module-level constant read once from `PLUGIN_CB_ENABLED` env var
- `_enabled` — computed as `enabled or _PLUGIN_CB_GLOBAL_ENABLE` in `__post_init__`

Shadow-mode semantics in `allow_request()`:
- Full state machine runs unconditionally (OPEN/HALF_OPEN transitions still occur)
- When OPEN and timeout not elapsed: returns `True` if `not self._enabled`, `False` if `self._enabled`
- Shadow breakers never block live routing; they accumulate failure data for future threshold analysis

State-transition observability:
- `intelligence_pipeline_plugin_cb_state` OTel gauge (0=closed, 1=open, 2=half_open) via `opentelemetry.metrics.get_meter("indicagent")` — no circular import
- `structlog.warning("plugin.circuit_breaker_opened", breaker=name, enabled=_enabled)` on OPEN transition
- Gauge emitted in `record_failure()`, `record_success()`, `allow_request()` on state change

**Task 2: Populate circuit_breakers dict (services/intelligence_pipeline_agent.py)**

- Added `from src.observability.circuit_breaker import CircuitBreaker`
- Added `_build_plugin_circuit_breakers()` method building one `CircuitBreaker(failure_threshold=3, timeout_sec=300, name=name, enabled=False)` per plugin across all tiers (TIER_I1 + TIER_I2 + TIER_I3 + TIER_I4 + TIER_I5 + TIER_SMC + TIER_I6 + TIER_I7)
- Replaced `circuit_breakers={}` (line ~289) with `circuit_breakers=self._build_plugin_circuit_breakers()`

Key invariants preserved:
- `PluginExecutor._get_plugin_cb()` lazy-init path still works but is never reached (all 132+ plugins pre-populated)
- `_collect_plugin_results()` already called `record_success()`/`record_failure()` unconditionally — no changes needed to executor
- Shadow breakers return True from `allow_request()` so all plugin routing continues unchanged

## Deviations from Plan

**Discovery: IBKR/LLM callers use PluginCircuitBreaker, not CircuitBreaker**

- **Found during:** Task 1 verification
- **Issue:** Plan's threat model assumed `src/providers/ibkr.py:105` and `src/core/llm/providers.py:48,61` construct `CircuitBreaker` from `src.observability.circuit_breaker`. They actually use `PluginCircuitBreaker` from `src.core.plugin_circuit_breaker`.
- **Impact:** The backward-compat concern (default `enabled=True`) is still the right design choice but the IBKR/LLM callers are not at risk. The `enabled=True` default means any future direct use of `CircuitBreaker` is active by default.
- **Action:** No code change required. Default `enabled=True` preserved as planned.

No other deviations. Plan executed exactly as written.

## Verification

```
grep -rn "circuit_breakers={}" services/  # returns nothing (exit=1)
grep -n "circuit_breakers=" services/intelligence_pipeline_agent.py
  # 322: circuit_breakers=self._build_plugin_circuit_breakers(),
grep -n "enabled=False" services/intelligence_pipeline_agent.py
  # 239: enabled=False,
.venv/bin/pytest tests/unit/observability/ tests/unit/intelligence/test_executor_pre_validation.py -q
  # 31 passed
```

## Self-Check

**Files exist:**
- `src/observability/circuit_breaker.py` - FOUND (modified)
- `services/intelligence_pipeline_agent.py` - FOUND (modified)

**Commits exist:**
- `d9671a55` - Task 1 (CircuitBreaker shadow-mode + observability)
- `7646777c` - Task 2 (populate circuit_breakers dict)

## Self-Check: PASSED
