---
phase: "085"
plan: "04"
subsystem: persistence-writers
tags: [pydantic, base-writer, lineage, signal-metrics, dlq, batching]
dependency_graph:
  requires:
    - "085-01"  # LineageEvent in lineage.py, SignalMetricsEvent in schemas.py
  provides:
    - services/lineage_writer_agent.py::LineageEvent payload_model + _to_row helper
    - services/signal_metrics_writer_agent.py::BaseWriterAgent migration + batch flush
  affects:
    - signal_lineage table — now DLQ-protected, no silent drops
    - signal_metrics / signal_metrics_ic / signal_metrics_dq_failures — now batched + DLQ-protected
tech_stack:
  added: []
  patterns:
    - payload_model ClassVar on BaseWriterAgent subclasses for automatic Pydantic validation
    - _to_row() helper with positional slot comments matching INSERT SQL
    - BaseWriterAgent migrate pattern: change base, add class attrs, implement abstract methods
key_files:
  created: []
  modified:
    - services/lineage_writer_agent.py
    - services/signal_metrics_writer_agent.py
decisions:
  - "lineage_writer: _to_row helper added instead of keeping inline tuple — follows D-02 named-field access pattern"
  - "signal_metrics DLQ topic constructed inline as topic + '.dlq' — no dedicated stream_key function exists"
  - "signal_metrics _flush_batch dispatches to existing module-level _handle_* helpers via event.model_dump()"
metrics:
  duration_minutes: 12
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
  completed_date: "2026-05-17"
---

# Phase 085 Plan 04: LineageEvent + SignalMetrics Writer Migration Summary

**One-liner:** Wire LineageEvent payload_model and _to_row helper in lineage_writer_agent; migrate SignalMetricsWriterAgent from BaseAgent to BaseWriterAgent with payload_model = SignalMetricsEvent and BATCH_SIZE = 50.

## What Was Built

Two writer agents fully on Phase 084 base contracts. Both now get automatic Pydantic validation, DLQ routing for malformed events, and Kafka offset commits for free from BaseWriterAgent.

### Task 1: LineageEvent payload_model + _to_row (PERSIST-01)

Four changes to `services/lineage_writer_agent.py`:

1. Added `from src.core.ai.lineage import LineageEvent` import.
2. Added `payload_model = LineageEvent` class attribute on `LineageWriterAgent`. Base now calls `LineageEvent.model_validate(raw_dict)` for every incoming message and routes `ValidationError` to `topic_signal_lineage_dlq()` automatically.
3. Replaced `_parse_payload(self, payload: dict)` with `_parse_payload(self, payload: LineageEvent) -> list | None: return [payload]`. The manual `if not payload.get("signal_id") or not payload.get("event_type"): return None` check was dead code — deleted per D-05.
4. Added `_to_row(self, event: LineageEvent) -> tuple` immediately before `_flush_batch`, mapping each field to its positional slot with `# $N field::type` comments. Updated `_flush_batch` to call `[self._to_row(e) for e in batch]`.

SQL INSERT positions verified: ts ($1 timestamptz), signal_id ($2 uuid), event_type ($3), source ($4), dag_order ($5), multiplier ($6), metadata ($7 jsonb), is_shadow ($8), symbol ($9), tf ($10).

### Task 2: SignalMetricsWriterAgent BaseWriterAgent migration (PERSIST-04)

Migrated `services/signal_metrics_writer_agent.py` from `BaseAgent` to `BaseWriterAgent`. Structural changes only — the three `_handle_*` module-level SQL functions are unchanged:

- Changed base class to `BaseWriterAgent`
- Added `BATCH_SIZE = 50`, `FLUSH_INTERVAL_SECS = 5.0`, `payload_model = SignalMetricsEvent`
- Implemented `_topic_name()` returning `topic_signal_metrics(self.env_name)`
- Implemented `_consumer_group` property returning `_CONSUMER_GROUP` constant
- Implemented `_dlq_topic()` returning `topic_signal_metrics(self.env_name) + ".dlq"` (no dedicated stream_key function exists)
- Implemented `_parse_payload(payload: SignalMetricsEvent) -> list | None: return [payload]`
- Implemented `_flush_batch(batch: list[SignalMetricsEvent])` acquiring DB connection and dispatching by `event.event_type` to `_handle_metrics_computed` / `_handle_ic_computed` / `_handle_dq_failure` via `event.model_dump()`
- Updated `_setup()` to use `_create_consumer()` instead of manual `KafkaConsumerClient`
- Updated `_teardown()` to call `super()._teardown()` for final flush before cleanup
- Removed per-record `_run()` override — base `_run()` handles the message loop

## Verification

- `grep -n "payload_model = LineageEvent" services/lineage_writer_agent.py` returns line 22
- `grep -n "class SignalMetricsWriterAgent(BaseWriterAgent)" services/signal_metrics_writer_agent.py` returns line 166
- `grep -n "payload_model = SignalMetricsEvent" services/signal_metrics_writer_agent.py` returns line 171
- `grep -n "if not payload.get" services/lineage_writer_agent.py` returns no matches (dead check deleted)
- 3260 unit tests passed, 1 skipped, 277 warnings
- `ruff check services/lineage_writer_agent.py services/signal_metrics_writer_agent.py` - all checks passed

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | `fbc95092` | feat(085-04): wire LineageEvent payload_model and _to_row helper in lineage_writer_agent |
| Task 2 | `7242bc48` | feat(085-04): migrate SignalMetricsWriterAgent to BaseWriterAgent (PERSIST-04) |

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

### Files Created/Modified

- `services/lineage_writer_agent.py` — contains `payload_model = LineageEvent` on line 22
- `services/signal_metrics_writer_agent.py` — contains `class SignalMetricsWriterAgent(BaseWriterAgent)` on line 166

### Commits Exist

- `fbc95092` — Task 1: LineageEvent payload_model
- `7242bc48` — Task 2: SignalMetricsWriterAgent BaseWriterAgent migration

## Self-Check: PASSED
