---
phase: "60"
plan: "02"
subsystem: signal-metrics
tags: [agent, kafka, prometheus, timescaledb, tdd]
dependency_graph:
  requires: [60-01]
  provides: [signal-metrics-agents]
  affects: [setup_performance, signal_metrics, signal_metrics_ic, signal_metrics_dq_failures]
tech_stack:
  added: []
  patterns: [timer-loop-agent, kafka-writer-agent, setup_performance-shim]
key_files:
  created:
    - services/signal_metrics_compute_agent.py
    - services/signal_metrics_writer_agent.py
    - services/indicagent-signal-metrics-compute.service
    - services/indicagent-signal-metrics-writer.service
    - tests/unit/service_tests/test_signal_metrics_compute_agent.py
    - tests/unit/service_tests/test_signal_metrics_writer_agent.py
  modified: []
decisions:
  - "Used BaseAgent._setup()/_teardown()/_run() hooks instead of custom start/stop/run; plan's pseudocode used wrong API (agent_id=, self._logger, self._shutdown)"
  - "Used asyncio.wait_for(stop_event.wait(), timeout=N) for timer loop to allow clean SIGTERM drain during sleep interval"
  - "KafkaProducerClient.publish(topic, msg=, key=) — actual API uses dict msg not json.dumps; writer uses KafkaConsumerClient.messages() async generator"
metrics:
  duration_minutes: 8
  completed_date: "2026-04-05"
  tasks_completed: 3
  tasks_total: 3
  files_created: 6
  files_modified: 0
---

# Phase 60 Plan 02: Signal Metrics Agent Layer Summary

**One-liner:** Two-agent pipeline — timer-triggered SignalMetricsComputeAgent (port 9126) and Kafka-consumer SignalMetricsWriterAgent (port 9127) — query signal_ledger, validate, compute zone/market metrics across 7/30/90d windows, persist to three tables, and shim setup_performance for backward compatibility.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | SignalMetricsComputeAgent + tests | 1a3903a |
| 2 | SignalMetricsWriterAgent + tests | f5aa17c |
| 3 | Systemd units (installed + active) | e89cfc9 |

## What Was Built

### SignalMetricsComputeAgent (`services/signal_metrics_compute_agent.py`)
- Timer loop every 900s (15 min) using `asyncio.wait_for(stop_event.wait(), timeout=N)` for clean SIGTERM drain
- Queries `signal_ledger` 90d window with `was_selected = true`
- Validates each row via `validate_signal_row()` — publishes `metrics_dq_failure` events for failing rows
- Computes `compute_signal_metrics()` for zone and market tracks across WINDOWS=(7, 30, 90)
- Computes `compute_ic_metrics()` for confidence predictive power
- Publishes `metrics_computed`, `ic_computed`, `metrics_dq_failure` events to `intelligence.signal_metrics`
- Prometheus Golden Signals: compute_cycles_total, compute_cycle_duration_seconds, compute_cycle_errors_total, rows_processed_per_cycle, dq_failures_total
- Port :9126

### SignalMetricsWriterAgent (`services/signal_metrics_writer_agent.py`)
- Subscribes to `intelligence.signal_metrics`, consumer group `signal_metrics_writer_consumer`
- `_handle_metrics_computed()` → UPSERT `signal_metrics` with full ON CONFLICT key
- `_handle_ic_computed()` → UPSERT `signal_metrics_ic`
- `_handle_dq_failure()` → INSERT `signal_metrics_dq_failures`
- Backward-compat shim: market/all/30d events with n>=30 also UPSERT `setup_performance` so existing perf_multiplier logic continues working until Plan 60-03
- Port :9127

### Systemd Units
- `indicagent-signal-metrics-compute.service` — enabled, RestartSec=30
- `indicagent-signal-metrics-writer.service` — enabled, RestartSec=10
- Both verified `active (running)` with DB pool initialized and Kafka connected

## Test Results

9 unit tests, all passing:
- `test_signal_metrics_compute_agent.py`: 4 tests (attributes, query, empty-db, dq-failure)
- `test_signal_metrics_writer_agent.py`: 5 tests (upsert, shim for market/all/30d, no-shim for zone, IC upsert, DQ insert)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan pseudocode used wrong BaseAgent API**
- **Found during:** Task 1
- **Issue:** Plan used `super().__init__(agent_id=, settings=)`, `self._logger`, `self._shutdown`, `self._producer.produce()`, `KafkaProducerClient(settings=)` — none of these match the actual BaseAgent/KafkaProducerClient signatures
- **Fix:** Used correct API: `super().__init__(name=, metrics_port=)`, `self.logger`, `self._stop_event`, `self._producer.publish(topic, msg=dict, key=)`, `KafkaProducerClient(bootstrap_servers=)`; also used `_setup()/_teardown()/_run()` lifecycle hooks instead of overriding `start/stop/run`
- **Files modified:** `services/signal_metrics_compute_agent.py`, `services/signal_metrics_writer_agent.py`
- **Commits:** 1a3903a, f5aa17c

**2. [Rule 1 - Bug] Plan used `json` import in writer agent that wasn't needed**
- **Found during:** Task 2 pre-commit
- **Issue:** `import json` unused — `KafkaConsumerClient.messages()` already decodes JSON; `datetime.fromisoformat()` handles string conversion
- **Fix:** Removed unused import
- **Commit:** f5aa17c

**3. [Rule 1 - Bug] asyncio.TimeoutError deprecated alias (UP041)**
- **Found during:** Post-task ruff lint
- **Issue:** `asyncio.TimeoutError` is an aliased error; ruff UP041 requires builtin `TimeoutError`
- **Fix:** Replaced with `TimeoutError`
- **Commit:** d67992e

**4. [Rule 2 - Missing] Test imports needed adapter**
- **Found during:** Task 1 TDD RED
- **Issue:** Plan test used `agent._db.fetch` and `agent._producer.produce` (wrong method names); actual interface is `_db.execute_query` and `_producer.publish`
- **Fix:** Tests written against actual API from the start
- **Commits:** 1a3903a, f5aa17c

### Pre-existing Failures (Out of Scope)
- `tests/unit/test_pipeline_exception_isolation.py::TestExceptionIsolation::test_single_i7_plugin_raises_does_not_crash` — pre-existing failure in intelligence_pipeline_agent, unrelated to this plan. Logged to deferred-items.

## Known Stubs

None. Both agents are fully wired: compute agent reads live DB, writer agent persists to live DB.

## Self-Check: PASSED

Files exist:
- services/signal_metrics_compute_agent.py: FOUND
- services/signal_metrics_writer_agent.py: FOUND
- services/indicagent-signal-metrics-compute.service: FOUND
- services/indicagent-signal-metrics-writer.service: FOUND
- tests/unit/service_tests/test_signal_metrics_compute_agent.py: FOUND
- tests/unit/service_tests/test_signal_metrics_writer_agent.py: FOUND

Commits exist:
- 1a3903a: FOUND (SignalMetricsComputeAgent)
- f5aa17c: FOUND (SignalMetricsWriterAgent)
- e89cfc9: FOUND (systemd units)
- d67992e: FOUND (lint fix)

Services active:
- indicagent-signal-metrics-compute: active (running), port 9126
- indicagent-signal-metrics-writer: active (running), port 9127
