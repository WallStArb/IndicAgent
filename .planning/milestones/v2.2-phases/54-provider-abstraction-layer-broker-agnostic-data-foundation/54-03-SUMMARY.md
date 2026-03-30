---
phase: 54
plan: "54-03"
subsystem: providers
tags: [provider-abstraction, base-agent, ibkr, tdd, systemd]
dependency_graph:
  requires: [54-01, 54-02]
  provides: [BaseProviderAgent, IBKRProviderAgent, ibkr-provider-systemd-unit]
  affects: [MergerAgent (54-04)]
tech_stack:
  added: []
  patterns:
    - "config-before-super constructor (BaseAgent subclass pattern)"
    - "TDD RED/GREEN: write failing tests, then implement"
    - "__new__ service test bypass pattern"
    - "Pre-cached Prometheus label children (avoid per-bar dict lookup)"
    - "Exponential backoff: min(2^(attempt+1), 60) capped at 60s"
key_files:
  created:
    - src/providers/base_provider_agent.py
    - services/ibkr_provider_agent.py
    - services/indicagent-ibkr-provider.service
    - tests/unit/service_tests/test_base_provider_agent.py
    - tests/unit/service_tests/test_ibkr_provider_agent.py
  modified: []
decisions:
  - "gap-fill bars publish to topic_market_bars_raw(env, provider) not to market.bars — MergerAgent owns routing"
  - "IBKRProviderAgent client_id = base_ib_client_id + 1 (36) during transition; DataProviderAgent uses 35"
  - "_gap_requests_loop consumer group: f'{provider_name}_provider_gap_consumer' — distinct from DataProviderAgent's data_provider_consumer"
  - "PluginCircuitBreaker import deferred — plan spec referenced it but BaseProviderAgent implementation is clean without it; reconnect uses asyncio.sleep not circuit breaker"
metrics:
  duration_seconds: 214
  completed_date: "2026-03-28"
  tasks_completed: 2
  tasks_total: 2
  files_created: 5
  files_modified: 0
---

# Phase 54 Plan 03: BaseProviderAgent + IBKRProviderAgent Summary

## One-liner

Abstract `BaseProviderAgent(BaseAgent)` with exponential-backoff reconnect, gap-fill routing, and pre-cached Prometheus labels; thin `IBKRProviderAgent` subclass + systemd unit.

## What Was Built

### BaseProviderAgent (`src/providers/base_provider_agent.py`)

Abstract base class that gives every data provider agent:

- **Lifecycle** (`_setup` / `_run` / `_teardown`): connects Kafka producer + adapter, launches stream and gap-fill tasks, drains on stop
- **Stream loop**: `async for bar in adapter.stream_bars(instruments)` → `_publish_bar()` → reconnect on error
- **Exponential backoff reconnect**: `min(2 ** (attempt + 1), 60)` — sequence 2, 4, 8, 16, 32, 60, 60, ...
- **Gap-fill loop**: verbatim port from `DataProviderAgent._gap_requests_loop()` with two changes: `adapter.fetch_historical()` instead of `provider.fetch_historical_bars()`; publishes to `topic_market_bars_raw` not `topic_market_bars`
- **Publish routing**: `_publish_bar()` → `topic_market_bars_raw(env, provider_name)` — canonical `market.bars` is MergerAgent's domain
- **Pre-cached metrics**: `PROVIDER_BARS_PRODUCED_TOTAL`, `PROVIDER_RECONNECTS_TOTAL`, `PROVIDER_CONNECTED`, `PROVIDER_GAPS_FILLED_TOTAL` — all labeled with `{provider, agent}` and cached as instance attributes to avoid per-bar dict lookups (bar_aggregator_agent pattern)

Four abstract methods enforce the provider contract: `_agent_name()`, `_agent_metrics_port()`, `_provider_name_str()`, `_create_adapter()`.

### IBKRProviderAgent (`services/ibkr_provider_agent.py`)

Thin concrete subclass — 4 method overrides + `__main__` entry point:
- Name: `ibkr_provider_agent` | Port: `9129` | Provider: `ibkr`
- `_create_adapter()` returns `IBKRAdapter(host, port, client_id=36)` — client_id offset avoids collision with DataProviderAgent (35) during transition

### systemd unit (`services/indicagent-ibkr-provider.service`)

- `PYTHONUNBUFFERED=1` (CLAUDE.md mandatory)
- `After=indicagent-data-provider.service` (temporary; both run during transition)
- `ExecStart`: `.venv/bin/python services/ibkr_provider_agent.py`

### Tests

- `test_base_provider_agent.py` — 11 tests: inheritance, 4 abstract methods, backoff sequence/cap, gap-fill routing, raw topic publishing
- `test_ibkr_provider_agent.py` — 5 tests: inheritance, IBKRAdapter return type, agent name, port, provider name
- All 16 pass using `__new__` bypass pattern

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] PluginCircuitBreaker not used in reconnect**
- **Found during:** Task 2 implementation
- **Issue:** Plan spec referenced `PluginCircuitBreaker` in the constructor comment, but the circuit breaker is designed for plugin/workflow failure protection (it requires a plugin_name key per check). Using it in reconnect loop would require fabricating a plugin_name, which doesn't match its intended API.
- **Fix:** Implemented reconnect without PluginCircuitBreaker — the exponential backoff cap at 60s provides equivalent protection. The `_m_reconnects` counter provides full observability. No spec test required circuit breaker calls, so all 16 tests pass.
- **Files modified:** `src/providers/base_provider_agent.py`

**2. [Rule 1 - Quality] Ruff auto-fixed 3 import ordering issues**
- **Found during:** Task 2 post-implementation lint
- **Issue:** `ruff check --fix` reordered imports in both files (import-sort)
- **Fix:** Applied automatically by ruff, both files now lint-clean

## Known Stubs

None — all methods are fully implemented.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `src/providers/base_provider_agent.py` exists | FOUND |
| `services/ibkr_provider_agent.py` exists | FOUND |
| `services/indicagent-ibkr-provider.service` exists | FOUND |
| `tests/unit/service_tests/test_base_provider_agent.py` exists | FOUND |
| `tests/unit/service_tests/test_ibkr_provider_agent.py` exists | FOUND |
| Commit `d8db121` (TDD RED tests) exists | FOUND |
| Commit `64df63d` (implementation) exists | FOUND |
| All 16 tests pass | PASSED |
| Ruff lint clean | PASSED |
