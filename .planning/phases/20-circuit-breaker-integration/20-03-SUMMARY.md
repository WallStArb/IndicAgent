---
phase: 20-circuit-breaker-integration
plan: "03"
subsystem: providers
tags: [circuit-breaker, ibkr, retry, resilience, production-hardening]
dependency_graph:
  requires:
    - "20-01"  # retry_utils.py
    - "20-02"  # plugin_circuit_breaker.py
  provides:
    - "IBKR provider with circuit breaker and retry"
  affects:
    - "src/providers/ibkr.py"
tech_stack:
  added: []
  patterns:
    - "Module-level circuit breaker singleton for IBKR connection tracking"
    - "_connect_with_circuit_breaker() helper with retry_with_backoff + state mutation"
    - "Guard pattern: check _is_circuit_breaker_open() before any IBKR operation"
key_files:
  created: []
  modified:
    - src/providers/ibkr.py
decisions:
  - "Module-level _ibkr_circuit_breaker singleton tracks connection health across IBKRProvider instances — IBKR has one connection, one breaker"
  - "Direct plugin_state mutation (not _record_success/_record_failure) in helper — avoids Prometheus metrics side effects for provider-level tracking"
  - "failure_window=120s, recovery_timeout=180s — IBKR reconnects in ~1 min, 3 min recovery gives sufficient buffer"
  - "retry_with_backoff base_delay=2.0s, max_delay=15.0s for IBKR — longer than default to match TWS reconnect timing"
metrics:
  duration: 122
  completed_date: "2026-03-09"
  tasks_completed: 3
  files_modified: 1
---

# Phase 20 Plan 03: IBKR Circuit Breaker Integration Summary

**One-liner:** IBKR provider wrapped with PluginCircuitBreaker + retry_with_backoff — connection failures tracked, cascades prevented, OPEN state fast-fails both connect() and get_quote().

## What Was Built

Added circuit breaker protection to `src/providers/ibkr.py` for IBKR TWS connection resilience. The implementation follows the Renaissance "degrade gracefully, adapt automatically" principle: after 3 connection failures within 2 minutes, the circuit opens for 3 minutes, preventing thundering-herd reconnect storms.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add imports and circuit breaker instance | 98e428b | src/providers/ibkr.py |
| 2 | Update IBKRProvider.connect() | 2e54994 | src/providers/ibkr.py |
| 3 | Update IBKRProvider.get_quote() | af626d1 | src/providers/ibkr.py |

## Key Changes

**Module-level additions:**
- `_ibkr_circuit_breaker` — `PluginCircuitBreaker` singleton with IBKR-specific config
- `_connect_with_circuit_breaker(host, port, client_id, timeout)` — wraps `retry_with_backoff` (3 attempts, 2s base, 15s max, 50% jitter) and records success/failure to circuit breaker state
- `_is_circuit_breaker_open()` — predicate checking `ibkr:connection` plugin state
- `reset_circuit_breaker()` — force-reset via `force_reset_plugin()`

**IBKRProvider.connect():** Now checks `_is_circuit_breaker_open()` first (fast-fail), then delegates to `_connect_with_circuit_breaker()` which handles retry loop and state tracking.

**IBKRProvider.get_quote():** Now checks `_is_circuit_breaker_open()` before any quote request — prevents quote storms when IBKR connection is known-bad.

## Circuit Breaker Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| failure_threshold | 3 | Open after 3 failures in window |
| recovery_timeout | 180s | 3 min — IBKR reconnects ~1 min |
| success_threshold | 2 | 2 clean connections to close |
| max_half_open_calls | 2 | Limited test probes |
| failure_window | 120s | 2 min tracking window |
| performance_threshold_ms | 20000 | 20s max connection time |

## Verification Results

All 6 plan verification checks passed:
1. `_ibkr_circuit_breaker` instance with correct config
2. `_connect_with_circuit_breaker()` uses retry + state tracking
3. `IBKRProvider.connect()` delegates to `_connect_with_circuit_breaker()`
4. `IBKRProvider.connect()` fast-fails when circuit OPEN
5. `IBKRProvider.get_quote()` checks circuit breaker
6. Circuit breaker starts CLOSED (correct initial state)

Unit tests: 1327 passed, 0 new failures (6 pre-existing ZAIProvider failures unrelated to this plan).

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- [x] `src/providers/ibkr.py` exists and modified
- [x] Commit 98e428b exists (Task 1)
- [x] Commit 2e54994 exists (Task 2)
- [x] Commit af626d1 exists (Task 3)
- [x] All imports resolve cleanly
- [x] No new test failures introduced
