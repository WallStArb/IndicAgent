---
phase: 067-observability-alerting-automation
plan: 01
subsystem: observability-alerting
tags: [alerting, webhooks, telegram, discord, kafka, metrics]
title: "AlertingAgent — Kafka-to-Telegram/Discord Dispatcher"
completed_date: "2026-04-23T15:56:00Z"
duration_minutes: 5
dependency_graph:
  requires: []
  provides: [alerting-infrastructure]
  affects: [observability-stack]
tech_stack:
  added:
    - "AlertingAgent: BaseAgent subclass consuming topic_alert_requests"
    - "aiohttp for HTTP webhook dispatch"
    - "Prometheus metrics: ALERTING_DISPATCH_TOTAL, ALERTING_LATENCY_SECONDS"
    - "Systemd service: indicagent-alerting-agent.service"
  patterns:
    - "TDD: RED (failing tests) → GREEN (implementation) → REFACTOR (clean code)"
    - "Async HTTP session mocking with custom MockAiohttpSession class"
    - "Severity-based routing: CRITICAL → Telegram, HIGH/MEDIUM → Discord"
key_files:
  created:
    - path: "services/alerting_agent.py"
      size_lines: 162
      description: "AlertingAgent — Kafka consumer, HTTP dispatcher, metrics emitter"
    - path: "tests/unit/service_tests/test_alerting_agent.py"
      size_lines: 293
      description: "14 TDD tests covering routing, credentials, HTTP errors, payload parsing"
    - path: "production/systemd/indicagent-alerting-agent.service"
      size_lines: 26
      description: "Systemd unit file for AlertingAgent (port 9132)"
  modified:
    - path: "src/observability/metrics.py"
      changes: "Added ALERTING_DISPATCH_TOTAL Counter and ALERTING_LATENCY_SECONDS Histogram"
decisions: []
metrics:
  tasks_completed: 2
  tests_passed: 14
  files_created: 3
  files_modified: 1
  commits: 2
---

# Phase 67 Plan 01: AlertingAgent — Kafka-to-Telegram/Discord Dispatcher Summary

## Objective
Create AlertingAgent — a minimal Kafka-to-Telegram/Discord dispatcher service that separates alert dispatch from service auditing (Single Responsibility Principle). Any agent can publish to `topic_alert_requests()` via `BaseAgent._send_alert()`; AlertingAgent consumes and routes by severity.

## One-Liner
JWT auth with refresh rotation using jose library — AlertingAgent consuming topic_alert_requests(), routing CRITICAL → Telegram, HIGH/MEDIUM → Discord, with Prometheus metrics and systemd unit.

## Tasks Completed

### Task 1: Register alerting metrics in metrics.py ✅
**Commit:** `cf6b1177`

Added two Prometheus metrics to `src/observability/metrics.py`:
- `ALERTING_DISPATCH_TOTAL` (Counter) — tracks dispatch attempts by channel, severity, status
- `ALERTING_LATENCY_SECONDS` (Histogram) — measures dispatch latency per channel

**Verification:**
```bash
.venv/bin/python -c "from src.observability.metrics import ALERTING_DISPATCH_TOTAL, ALERTING_LATENCY_SECONDS; print('OK')"
```

### Task 2: TDD AlertingAgent — write tests then implement ✅
**Commit:** `59fe23f7`

**RED Phase:** Created 14 failing tests (AlertingAgent did not exist yet)

**GREEN Phase:** Implemented AlertingAgent with all tests passing

**Files Created:**
1. `services/alerting_agent.py` (162 lines)
   - BaseAgent subclass consuming `topic_alert_requests()`
   - `_dispatch_telegram()` — HTTP POST to Telegram bot API
   - `_dispatch_discord()` — HTTP POST to Discord webhook URL
   - Graceful no-op when credentials empty
   - HTTP errors logged, not raised (service resilience)
   - Prometheus metrics emitted on every dispatch attempt

2. `tests/unit/service_tests/test_alerting_agent.py` (293 lines, 14 tests)
   - Test classes: Routing, EmptyCredentials, HTTPErrors, RunRouting
   - Custom `MockAiohttpSession` class for proper async context manager mocking
   - Coverage: severity routing, credential validation, HTTP error handling, payload parsing

3. `production/systemd/indicagent-alerting-agent.service` (26 lines)
   - Description: "IndicAgent Alerting Dispatcher"
   - After: network-online.target redpanda.service
   - ExecStart: `/home/bg/dev/indicagent/.venv/bin/python services/alerting_agent.py`
   - Environment: METRICS_PORT=9132
   - WatchdogSec=120, Restart=always

**Test Results:**
```bash
.venv/bin/pytest tests/unit/service_tests/test_alerting_agent.py -v
======================== 14 passed, 2 warnings in 0.13s ========================
```

## Deviations from Plan

None — plan executed exactly as written.

## Threat Flags

None — no new security-relevant surface introduced. AlertingAgent only reads from Kafka (existing topic) and writes to external webhooks (configurable credentials).

## Verification

- [x] All 14 AlertingAgent tests pass
- [x] ruff check clean on services/alerting_agent.py and tests
- [x] AlertingAgent imports resolve (BaseAgent, KafkaConsumerClient, metrics)
- [x] Systemd unit file has correct ExecStart and METRICS_PORT=9132
- [x] Prometheus metrics registered and importable

## Commits

1. `cf6b1177` — feat(067-01): register alerting metrics in metrics.py
2. `59fe23f7` — feat(067-01): implement AlertingAgent — Kafka-to-Telegram/Discord dispatcher

## Self-Check: PASSED

**Files Created:**
- [x] services/alerting_agent.py (162 lines)
- [x] tests/unit/service_tests/test_alerting_agent.py (293 lines)
- [x] production/systemd/indicagent-alerting-agent.service (26 lines)

**Commits Verified:**
- [x] cf6b1177 exists
- [x] 59fe23f7 exists

**Tests Passing:**
- [x] 14/14 tests pass

**Ruff Clean:**
- [x] All checks passed

## Success Criteria

- [x] services/alerting_agent.py exists, inherits BaseAgent
- [x] 14+ TDD tests pass covering: routing by severity, empty tokens, HTTP errors, payload parsing
- [x] ALERTING_DISPATCH_TOTAL and ALERTING_LATENCY_SECONDS registered in metrics.py
- [x] Systemd unit production/systemd/indicagent-alerting-agent.service exists
- [x] ruff check clean

**Phase 67 Plan 01 — OBS-WEBHOOK-DISPATCHER requirement complete.**
