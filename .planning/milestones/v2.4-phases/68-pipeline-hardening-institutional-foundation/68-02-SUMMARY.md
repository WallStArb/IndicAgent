---
phase: 68-pipeline-hardening-institutional-foundation
plan: "02"
subsystem: writer-agents
tags: [base-class, kafka, writer, reliability, dlq, buffer]
dependency_graph:
  requires: []
  provides: [BaseWriterAgent-ABC, writer-migration, offset-after-flush, dlq-routing, bounded-buffer]
  affects: [signal_writer_agent, feature_writer_agent, bar_writer_agent, lifecycle_writer_agent, swarm_writer_agent]
tech_stack:
  added: []
  patterns: [consume-parse-buffer-flush-commit, manual-offset-commit, DLQ-routing, bounded-buffer-overflow]
key_files:
  created: []
  modified:
    - src/core/agent/base_writer.py
    - src/core/agent/__init__.py
    - tests/unit/test_base_writer_agent.py
    - services/signal_writer_agent.py
    - services/feature_writer_agent.py
    - services/bar_writer_agent.py
    - services/lifecycle_writer_agent.py
    - services/swarm_writer_agent.py
    - src/core/stream_keys.py
    - tests/unit/test_stream_keys_dlq.py
decisions:
  - "BaseWriterAgent uses buffer_rows()/maybe_flush() cooperative model — subclasses own _run() loop for flexibility with multi-topic consumers (feature_writer, bar_writer)"
  - "Metrics registered via module-level _get_or_create_gauge/_get_or_create_counter to prevent duplicate registration across test runs"
  - "_conflict_skips_lbl removed from bar_writer — asyncpg executemany returns no rowcount so ON CONFLICT skips are not countable; removed rather than reporting misleading 0s [AUDIT-M7]"
  - "DLQ topic for signal_writer uses intelligence. prefix: intelligence.signal.writer.dlq — consistent with intelligence domain routing [AUDIT-LOW-1]"
  - "expiry_map_empty warning added in feature_writer _setup_kafka_clients after _build_expiry_map returns empty — makes days_to_expiry=0 observable [AUDIT-LOW-3]"
  - "bar_writer contract cache load wrapped in 3-attempt retry with 5s backoff — transient DB failure at startup must not leave cache empty [AUDIT-LOW-4]"
metrics:
  duration: "~25 minutes"
  completed: "2026-04-23"
  tasks_completed: 2
  files_modified: 10
---

# Phase 68 Plan 02: BaseWriterAgent Migration Summary

BaseWriterAgent ABC extracting consume-parse-buffer-flush-commit pattern with offset-after-flush guarantee, DLQ routing, and bounded buffer — all 5 writer agents migrated.

## Tasks Completed

### Task 1: Create BaseWriterAgent ABC
`src/core/agent/base_writer.py` — abstract base providing the shared buffer management pattern. Subclasses own `_run()` and call `_buffer_rows()` / `maybe_flush()`. All 12 behavioral tests pass.

Key contracts:
- `_do_flush()` commits offset ONLY after `_flush_batch()` succeeds
- Buffer hard-capped at `MAX_BUFFER_SIZE=10_000`; overflow drops oldest entries and increments counter
- `_buffer_depth_gauge` updated on every `_buffer_rows()` call
- `_teardown()` calls `_do_flush()` for remaining buffer before shutdown

### Task 2: Migrate All 5 Writer Agents
All 5 writers — SignalWriterAgent, FeatureWriterAgent, BarWriterAgent, LifecycleWriterAgent, SwarmWriterAgent — inherit `BaseWriterAgent` with `enable_auto_commit=False`.

Each writer implements only:
- `_topic_name()` — Kafka topic to consume
- `_consumer_group` — consumer group ID
- `_parse_payload()` — parse raw Kafka dict into buffer rows or None for DLQ
- `_flush_batch()` — DB write logic
- `_setup()` / `_teardown()` — DB pool + consumer lifecycle

## Deviations from Plan

### Auto-fixed Issues (Audit Findings)

**1. [Rule 1 - Bug / AUDIT-H2] Remove duplicate PERSISTENCE_CONSUMER_LAG.set() in feature_writer**
- **Found during:** Task 2 audit
- **Issue:** `PERSISTENCE_CONSUMER_LAG.set(len(batch))` was called before flush and `set(0)` after flush — two assignments per flush cycle; the pre-flush value was immediately overwritten
- **Fix:** Removed the pre-flush set; single authoritative `set(0)` after successful flush
- **Files modified:** `services/feature_writer_agent.py`
- **Commit:** dc2908f3

**2. [Rule 1 - Bug / AUDIT-M1] bar_writer auto_offset_reset "latest" → "earliest"**
- **Found during:** Task 2 audit
- **Issue:** `auto_offset_reset="latest"` inconsistent with all other writers (all use `"earliest"`); bars published before startup would be silently skipped
- **Fix:** Changed to `"earliest"`
- **Files modified:** `services/bar_writer_agent.py`
- **Commit:** dc2908f3

**3. [Rule 2 - Missing / AUDIT-M7] Remove unwired _conflict_skips_lbl counter**
- **Found during:** Task 2 audit
- **Issue:** `_conflict_skips_lbl` counter defined but never incremented (asyncpg `executemany` returns no rowcount — ON CONFLICT skips are not countable)
- **Fix:** Removed the label child cache; module-level metric registration still exists for future use if countable path is found
- **Files modified:** `services/bar_writer_agent.py`
- **Commit:** dc2908f3

**4. [Rule 1 - Bug / AUDIT-LOW-1] Fix signal_writer DLQ topic prefix**
- **Found during:** Task 2 audit
- **Issue:** `topic_signal_writer_dlq()` returned `signal.writer.dlq` without `intelligence.` prefix, inconsistent with the intelligence domain pattern
- **Fix:** Updated to `intelligence.signal.writer.dlq`; updated corresponding test
- **Files modified:** `src/core/stream_keys.py`, `tests/unit/test_stream_keys_dlq.py`
- **Commit:** dc2908f3

**5. [Rule 2 - Missing / AUDIT-LOW-2] Read num_agreeing/resolution_method from payload**
- **Found during:** Task 2 audit
- **Issue:** `num_agreeing=0` and `resolution_method="in_process"` hardcoded in `_payload_to_ledger_entries()`; payload may contain actual values from pipeline
- **Fix:** `num_agreeing=int(sig.get("num_agreeing", 0))`, `resolution_method=str(sig.get("resolution_method", "in_process"))` — defaults preserved for backward compatibility
- **Files modified:** `services/signal_writer_agent.py`
- **Commit:** dc2908f3

**6. [Rule 2 - Missing / AUDIT-LOW-3] Add expiry_map_empty warning in feature_writer**
- **Found during:** Task 2 audit
- **Issue:** When `_build_expiry_map()` fails or returns empty, `days_to_expiry=0` silently applied to all symbols; no observability
- **Fix:** Added `structlog.warning("expiry_map_empty")` when `self._expiry_map` is empty after setup attempt
- **Files modified:** `services/feature_writer_agent.py`
- **Commit:** dc2908f3

**7. [Rule 2 - Missing / AUDIT-LOW-4] Add retry loop for contract cache load in bar_writer**
- **Found during:** Task 2 audit
- **Issue:** `_load_contract_cache()` called once in `_setup()` with no retry; transient DB failure at startup leaves cache empty, causing `days_to_expiry=0` and incorrect base symbol lookups for all futures symbols
- **Fix:** Wrapped in 3-attempt retry loop with 5s backoff; re-raises on final failure
- **Files modified:** `services/bar_writer_agent.py`
- **Commit:** dc2908f3

### Deferred (Pre-existing failures — out of scope)
- `test_contract_metadata_writer_agent.py` — `_processed_rolls` attribute missing in `ContractMetadataWriterAgent`; pre-existing on base branch, not caused by this plan
- `test_persistence_metrics_wiring.py::test_llm_writer_records_consumer_lag` — pre-existing on base branch; `llm_writer_service.py` doesn't use `PERSISTENCE_CONSUMER_LAG` directly

## Verification Results

```
pytest tests/unit/test_base_writer_agent.py        — 12/12 passed
pytest tests/unit/test_feature_writer_imports.py   — 2/2 passed
pytest tests/unit/test_stream_keys_dlq.py          — 6/6 passed
pytest tests/unit/ -k "writer" (excluding pre-existing failures) — 151/151 passed
ruff check all modified files                       — All checks passed
```

## Self-Check

### Created files exist
- `src/core/agent/base_writer.py` — FOUND (in b4eddfa0 base)
- `tests/unit/test_base_writer_agent.py` — FOUND (in b4eddfa0 base)

### Commits exist
- `dc2908f3` — feat(68-02): migrate all 5 writers to BaseWriterAgent + apply audit fixes

### Acceptance Criteria Met
- [x] All 5 writers inherit BaseWriterAgent
- [x] All 5 writers use enable_auto_commit=False
- [x] All 5 writers implement _parse_payload, _flush_batch, _topic_name, _consumer_group
- [x] Manual offset commit enforced (commit only after successful flush)
- [x] DLQ routing works for unparseable payloads
- [x] Buffer bounded at 10,000 with overflow metric
- [x] Buffer depth gauge published every cycle
- [x] All writer tests pass (151 passing, 6 pre-existing failures excluded)
- [x] AUDIT-H2 PERSISTENCE_CONSUMER_LAG single assignment
- [x] AUDIT-M1 bar_writer auto_offset_reset=earliest
- [x] AUDIT-M7 _conflict_skips unwired counter removed
- [x] AUDIT-LOW-1 intelligence.signal.writer.dlq prefix
- [x] AUDIT-LOW-2 num_agreeing/resolution_method from payload
- [x] AUDIT-LOW-3 expiry_map_empty warning logged
- [x] AUDIT-LOW-4 retry loop for contract cache load

## Self-Check: PASSED
