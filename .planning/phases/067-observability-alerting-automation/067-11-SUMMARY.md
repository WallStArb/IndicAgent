---
phase: 067-observability-alerting-automation
plan: 11
subsystem: llm-writer
tags: [observability, crash-detection, stall-detection, dlq, prometheus]
dependency_graph:
  requires: []
  provides: [llm_writer_renaissance_observability]
  affects: [llm_writer_service]
tech_stack:
  added: []
  patterns: [AGENT_CRASH_TOTAL, DLQ_MESSAGES_TOTAL, DLQ_DEPTH, stall_watchdog]
key_files:
  created: []
  modified:
    - services/llm_writer_service.py
decisions:
  - "Used AGENT_CRASH_TOTAL from src/core/agent/base.py (not metrics.py) — that is where the labeled Counter is registered to avoid duplicate registration"
  - "Stall watchdog only logs warnings (does not sys.exit) per threat model disposition: stall watchdog is accept/log-only"
  - "DLQ producer started alongside consumer in _setup_kafka_clients; stopped in _shutdown before DB close"
  - "topic_llm_writer_dlq already existed in stream_keys.py from Plan 067-07 — no new stream key needed"
metrics:
  duration: "~15 minutes"
  completed: "2026-04-14"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 067 Plan 11: LLMWriterService Renaissance Observability Summary

**One-liner:** Added crash detection (AGENT_CRASH_TOTAL), stall detection (_stall_watchdog, 5 min idle threshold), and DLQ routing (llm.writer.dlq via KafkaProducerClient) to LLMWriterService without BaseAgent inheritance.

## What Was Built

LLMWriterService is the only writer service that does not inherit from BaseAgent (due to dual-topic consumption and custom buffer management). This plan added the three key observability features inline:

**1. Crash Detection**
- Imported `AGENT_CRASH_TOTAL` from `src/core/agent/base.py` (where the labeled Counter is defined)
- `self._crash_metric = AGENT_CRASH_TOTAL.labels(agent="llm_writer_service")` cached at init
- `self._crash_metric.inc()` called in `start()` exception handler before re-raising

**2. Stall Detection**
- `self._last_message_ts: float | None = None` — updated on every message in `_process_loop`
- `self._max_idle_seconds: int = 300` — 5-minute threshold
- `_stall_watchdog()` async task: 60s check interval, startup grace (no warn until first message), logs warning at WARNING level (does not kill process)
- Task started via `asyncio.create_task` in `start()` alongside existing tasks

**3. DLQ Routing**
- `self._dlq_producer: KafkaProducerClient` started in `_setup_kafka_clients`, stopped in `_shutdown`
- `_send_to_dlq(payload, source_topic, error_type)` helper: publishes to `topic_llm_writer_dlq`, increments `DLQ_MESSAGES_TOTAL` + `DLQ_DEPTH`, logs warning, never raises
- `_process_calls_message` and `_process_outcome_message` now accept `source_topic` param
- Parse failures (return None from `_parse_llm_call_fields` / `_parse_outcome_fields`) route to DLQ
- Unhandled exceptions in those methods also route to DLQ

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add crash detection, stall detection, and DLQ routing to LLMWriterService | 3a2b6ad7 | services/llm_writer_service.py |

## Verification

```
grep -c "AGENT_CRASH_TOTAL" services/llm_writer_service.py  → 3  (import + label + .inc())
grep -c "_stall_watchdog\|_last_message_ts" services/llm_writer_service.py  → 7
grep -c "DLQ_MESSAGES_TOTAL\|_send_to_dlq" services/llm_writer_service.py  → 8
```

All acceptance criteria met:
- AGENT_CRASH_TOTAL incremented on unhandled exceptions in start()
- _last_message_ts tracked per message, _stall_watchdog warns after 5 min idle
- Unparseable messages routed to DLQ topic (llm.writer.dlq) instead of silently dropped
- No BaseAgent inheritance — existing architecture preserved

## Deviations from Plan

None — plan executed exactly as written. `topic_llm_writer_dlq` and `DLQ_MESSAGES_TOTAL`/`DLQ_DEPTH` already existed from Plan 067-07, so no new infrastructure was needed.

## Known Stubs

None.

## Threat Flags

None — no new network endpoints or auth paths introduced. DLQ publishing is outbound-only to an existing Kafka topic pattern.

## Self-Check: PASSED

- services/llm_writer_service.py exists and contains all three observability features
- Commit 3a2b6ad7 exists with 1 file changed, 108 insertions(+), 12 deletions(-)
