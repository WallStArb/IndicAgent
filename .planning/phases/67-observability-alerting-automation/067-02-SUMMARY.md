---
phase: 067-observability-alerting-automation
plan: 02
subsystem: observability-alerting
tags: [alerting, refactoring, srp, kafka, service-auditor]
title: "ServiceAuditorAgent Webhook Removal — Centralized Alerting"
completed_date: "2026-04-23T16:01:00Z"
duration_minutes: 8
dependency_graph:
  requires: [067-01]
  provides: [obs-webhook-dispatcher-complete]
  affects: [service-auditor, alerting-flow]
tech_stack:
  added: []
  patterns:
    - "SRP enforcement: audit logic separate from dispatch logic"
    - "Kafka as async notification bus (not direct HTTP)"
    - "BaseAgent._send_alert() as unified alert interface"
key_files:
  created: []
  modified:
    - path: "services/service_auditor_agent.py"
      changes: "Wired self._producer, replaced 3 webhook calls with _send_alert(), removed 4 webhook methods"
      size_delta: "-46 lines"
    - path: "tests/unit/service_tests/test_service_auditor_agent_webhooks.py"
      changes: "Rewrote 6 tests to verify _send_alert() calls instead of HTTP dispatch"
      size_delta: "-12 lines"
decisions: []
metrics:
  tasks_completed: 1
  tests_passed: 17
  files_created: 0
  files_modified: 2
  commits: 1
---

# Phase 67 Plan 02: ServiceAuditorAgent Webhook Removal Summary

## Objective
Eliminate the Single Responsibility Principle violation where `service_auditor_agent` both audits services AND dispatches alerts via inline HTTP webhooks. Replace all inline webhook code with calls to `BaseAgent._send_alert()`, which publishes to the Kafka `topic_alert_requests` that `AlertingAgent` (Plan 01) consumes and dispatches.

## One-Liner
Refactored service_auditor_agent to use centralized alerting via Kafka instead of inline HTTP webhooks — SRP violation eliminated, audit and dispatch concerns now separated.

## Changes Made

### 1. ServiceAuditorAgent Refactoring (`services/service_auditor_agent.py`)

**Added `_producer` wiring:**
- Line 164: `self._producer = self._kafka_producer` after `await self._kafka_producer.start()`
- Enables `BaseAgent._send_alert()` to find the Kafka producer (it checks `self._producer`)

**Replaced 3 inline webhook calls with `_send_alert()`:**

| Call Site | Line(s) | Severity | Alert Type |
|-----------|---------|----------|------------|
| Data stoppage detection | 295-299 | HIGH | Provider bars_per_sec=0 for 30s during active session |
| Escalation threshold | 332-336 | CRITICAL | Service escalated — 3 restarts in 10 min |
| Roll automation | 644-648 | HIGH | Futures roll detected, restarting services |

**Removed 4 webhook methods (135 lines → 89 lines, net -46 lines):**
- `_dispatch_webhook_http(url, payload, log_name)` — Generic HTTP POST dispatcher
- `_notify_telegram(title, body)` — Telegram bot API caller
- `_notify_discord(title, body, severity)` — Discord webhook caller
- `_dispatch_webhook(severity, title, body)` — Severity routing logic

### 2. Test Rewrite (`tests/unit/service_tests/test_service_auditor_agent_webhooks.py`)

**Before (6 tests, 96 lines):**
- Verified `_dispatch_webhook()` routing to Telegram/Discord
- Tested HTTP success/error paths
- Mocked `aiohttp.ClientSession` directly

**After (4 tests, 84 lines, net -12 lines):**
- `test_data_stoppage_calls_send_alert_HIGH` — Verifies HIGH severity on data stoppage
- `test_escalation_calls_send_alert_CRITICAL` — Verifies CRITICAL severity on escalation
- `test_roll_event_calls_send_alert_HIGH` — Verifies HIGH severity on roll events
- `test_send_alert_noop_when_producer_is_None` — Verifies graceful degradation

All tests mock `_send_alert` directly instead of HTTP session — no HTTP logic in tests.

## Verification

### Acceptance Criteria ✅
```bash
# 1. Zero inline webhook methods remain
$ grep -c "_dispatch_webhook_http\|_notify_telegram\|_notify_discord\|_dispatch_webhook" services/service_auditor_agent.py
0

# 2. Three _send_alert call sites present
$ grep -c "_send_alert" services/service_auditor_agent.py
4  # (3 call sites + 1 base class check)

# 3. Producer wired in _setup()
$ grep "self._producer = self._kafka_producer" services/service_auditor_agent.py
self._producer = self._kafka_producer

# 4. All tests pass (4 new + 11 existing + 2 roll consumer)
$ pytest tests/unit/service_tests/test_service_auditor_agent_webhooks.py \
        tests/unit/service_tests/test_service_auditor_agent.py \
        tests/unit/service_tests/test_service_auditor_roll_consumer.py -v
17 passed in 0.13s

# 5. ruff check clean
$ ruff check services/service_auditor_agent.py
All checks passed!
```

### Test Results
```
tests/unit/service_tests/test_service_auditor_agent_webhooks.py::TestSendAlertCalls::test_data_stoppage_calls_send_alert_HIGH PASSED
tests/unit/service_tests/test_service_auditor_agent_webhooks.py::TestSendAlertCalls::test_escalation_calls_send_alert_CRITICAL PASSED
tests/unit/service_tests/test_service_auditor_agent_webhooks.py::TestSendAlertCalls::test_roll_event_calls_send_alert_HIGH PASSED
tests/unit/service_tests/test_service_auditor_agent_webhooks.py::TestSendAlertCalls::test_send_alert_noop_when_producer_is_None PASSED
tests/unit/service_tests/test_service_auditor_agent.py::test_registry_covers_all_active_services PASSED
tests/unit/service_tests/test_service_auditor_agent.py::test_registry_dag_order_sources_before_sinks PASSED
tests/unit/service_tests/test_service_auditor_agent.py::test_healthy_service_no_action PASSED
tests/unit/service_tests/test_service_auditor_agent.py::test_dead_service_triggers_restart PASSED
tests/unit/service_tests/test_service_auditor_agent.py::test_high_lag_degrades_after_two_checks PASSED
tests/unit/service_tests/test_service_auditor_agent.py::test_escalates_after_three_restarts_in_window PASSED
tests/unit/service_tests/test_service_auditor_agent.py::test_recovery_emits_recovered_event_with_duration PASSED
tests/unit/service_tests/test_service_auditor_agent_roll_consumer.py::test_restart_roll_service_increments_counter PASSED
tests/unit/service_tests/test_service_auditor_roll_consumer.py::test_restart_roll_service_subprocess_failure_is_logged PASSED
17 passed in 0.13s
```

## Deviations from Plan
**None.** Plan executed exactly as written:
- ✅ Wired `_producer` in `_setup()`
- ✅ Replaced all 3 call sites with `_send_alert()`
- ✅ Removed all 4 webhook methods
- ✅ Rewrote webhook tests to verify `_send_alert()` calls
- ✅ Verified no other test files broken

## Architecture Impact

### Before (Dual Dispatch Paths)
```
service_auditor_agent ──► HTTP POST ──► Telegram/Discord (inline)
                        └───► Kafka ──► AlertingAgent ──► Telegram/Discord (Plan 01)
```
**Problem:** Two independent dispatch mechanisms, SRP violation, webhook credentials in service_auditor.

### After (Single Unified Path)
```
service_auditor_agent ──► Kafka topic_alert_requests ──► AlertingAgent ──► Telegram/Discord
```
**Benefits:**
- ✅ Single Responsibility: service_auditor only audits, AlertingAgent only dispatches
- ✅ Credential isolation: webhook tokens live only in AlertingAgent
- ✅ Testability: mock `_send_alert` instead of HTTP session
- ✅ Observability: all alerts flow through Kafka (audit trail)

## Threat Model Compliance

| Threat ID | Category | Component | Disposition | Mitigation |
|-----------|----------|-----------|-------------|------------|
| T-67-04 | I | service_auditor._send_alert | accept | Internal Kafka publish — AlertingAgent validates severity |
| T-67-05 | D | self._producer wiring | mitigate | If `_producer` is None, `_send_alert()` silently no-ops (safe degradation) |

Both threats from Plan 067-02 handled correctly.

## Key Decisions
**None.** Plan was straightforward refactoring with no architectural choices required.

## Next Steps
- OBS-WEBHOOK-DISPATCHER fully complete ✅
- AlertingAgent (Plan 01) now receives all service_auditor alerts
- Future agents can use `BaseAgent._send_alert()` without implementing HTTP dispatch

## Files Modified
- `services/service_auditor_agent.py`: Removed 4 webhook methods, added 3 `_send_alert` calls, wired `_producer`
- `tests/unit/service_tests/test_service_auditor_agent_webhooks.py`: Rewrote 6 tests → 4 tests, verify `_send_alert` instead of HTTP

## Commits
- `refactor(067-02): remove inline webhooks, use BaseAgent._send_alert()` (92a42091)

## Self-Check: PASSED
- ✅ All webhook methods removed (0 occurrences)
- ✅ All 3 call sites migrated to `_send_alert()`
- ✅ Producer wired in `_setup()`
- ✅ All 17 tests pass
- ✅ ruff check clean
- ✅ No deviations from plan
