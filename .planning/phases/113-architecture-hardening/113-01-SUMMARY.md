---
phase: "113-architecture-hardening"
plan: "113-01"
subsystem: "sse, pipeline, writer, calibration, signals, contracts"
tags: ["hardening", "correctness", "telemetry", "idempotency", "content-addressed"]
dependency_graph:
  requires: []
  provides:
    - "sse-topic-indexed-fanout"
    - "signal-id-content-addressed"
    - "in-process-calibration"
    - "writer-tuple-contract"
    - "feature-upsert-idempotent"
    - "dag-invariant-ci"
    - "contract-hot-reload"
    - "sample-gate-100"
    - "pipeline-backpressure"
  affects:
    - "services/intelligence_pipeline.py"
    - "src/api/routes/sse.py"
    - "src/core/agent/base_writer.py"
    - "src/intelligence/pipeline/signal_processor.py"
    - "src/persistence/repository/feature_repository.py"
tech_stack:
  added: []
  patterns:
    - "content-addressed IDs via SHA-256"
    - "topic-indexed SSE fan-out"
    - "atomic contract reference swap"
    - "valid/invalid tuple contract for writers"
key_files:
  created:
    - "production/migrations/115_signal_id_unique.sql"
    - "production/migrations/116_setup_performance_gate.sql"
    - "tests/unit/api/test_sse_broadcaster.py"
    - "tests/unit/intelligence/test_dag_invariants.py"
    - "tests/unit/intelligence/test_signal_id_stability.py"
  modified:
    - "src/api/routes/sse.py"
    - "src/observability/metrics.py"
    - "src/intelligence/pipeline/signal_processor.py"
    - "src/core/agent/base_writer.py"
    - "src/persistence/repository/feature_repository.py"
    - "src/core/stream_keys.py"
    - "services/intelligence_pipeline.py"
    - "src/intelligence/pipeline/ranker.py"
    - "src/intelligence/trading/aggregator.py"
    - "src/intelligence/setup_performance_updater.py"
    - "services/bar_writer.py"
    - "services/graduation_writer.py"
    - "services/lineage_writer.py"
    - "services/context_writer.py"
    - "services/signal_metrics_writer.py"
    - "services/signal_writer.py"
    - "services/feature_writer.py"
    - "services/lifecycle_writer.py"
    - "services/llm_writer.py"
decisions:
  - "signal_id uses SHA-256 of bar OHLCV inputs (not plugin outputs) — bar is the stable replay invariant"
  - "_parse_payload returns (valid, invalid) tuple — eliminates None/[] sentinel ambiguity"
  - "backpressure drops INCOMING bar (newest) not oldest — preserves Kalman/rolling state"
  - "setup_performance gate raised to 100 — fat-tailed return distributions require more samples"
  - "Task 12 backpressure committed in same commit as Task 10 (both touch intelligence_pipeline.py)"
metrics:
  duration: "~25 minutes"
  completed_date: "2026-06-03"
  tasks_completed: 12
  tasks_total: 12
  files_modified: 24
---

# Phase 113 Plan 01: Architecture Hardening Summary

SHA-256 content-addressed signal IDs, topic-indexed SSE fan-out, in-process calibration before I7, (valid, invalid) writer tuple contract, idempotent feature upserts, DAG Invariant 2 CI enforcement, live contract hot-reload, 100-sample performance gate, and pipeline backpressure — all 12 correctness findings from the Renaissance architecture review shipped.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | eaec389e | chore: delete dead Redis SSE helpers and their test |
| 2 | cde91158 | feat(metrics): add sse_messages_dropped_total counter |
| 3 | 9ce96545 | refactor(sse): topic-indexed fan-out, bounded snapshot cache, drop counter |
| 4 | cc36d7fe | test(sse): unit tests for topic-indexed broadcaster fan-out |
| 5 | 2ddba7e7 | feat(signals): content-addressed signal_id via SHA-256 (CRITICAL-01) |
| 6 | b19f664c | feat(pipeline): in-process confidence calibration before I7 (CRITICAL-02) |
| 7 | 7add9eeb | refactor(writer): _parse_payload returns (valid, invalid) tuple (HIGH-01) |
| 8 | 7ccf5605 | fix(features): upsert on conflict DO UPDATE for idempotent replay (HIGH-03) |
| 9 | 035b3036 | test(dag): CI enforcement of DAG Invariant 2 (MEDIUM-01) |
| 10+12 | 19b35b54 | feat(contracts): live hot-reload + pipeline backpressure (MEDIUM-02 + structural) |
| 11 | 321051ef | fix(shadow): raise setup_performance gate to 100 samples minimum |

## Task Details

### Task 1: Delete dead Redis SSE code
Removed 9 Redis-style `sk_*` imports, `_resolve_contract` import, `_NARRATIVE_GROUPS` constant, `_build_stream_list()` and `_event_name_for_stream()` functions. Deleted `tests/unit/api/test_sse_intelligence.py`.

### Task 2: SSE drop telemetry
Added `SSE_MESSAGES_DROPPED_TOTAL`, `CONTRACTS_RELOAD_TOTAL`, and `PIPELINE_BACKPRESSURE_DROP_TOTAL` counters to `src/observability/metrics.py`.

### Task 3: Topic-indexed SSE fan-out
Replaced `list[asyncio.Queue]` with `dict[topic, set[_Subscription]]`. Added `_Subscription` dataclass (`eq=False` for hashability). Bounded `_latest` at `_MAX_LATEST_KEYS=200`. Drop counter wired. `subscribe()` now takes `frozenset[str]` topics.

### Task 4: SSE unit tests
8 tests covering: matching topic delivery, non-matching skip, two-subscriber isolation, unsubscribe stops delivery, queue-full drop counter, snapshot cap, existing-key update without eviction, ibkr_seed skip.

### Task 5: Content-addressed signal_id (CRITICAL-01)
`_make_signal_id()` uses SHA-256 of `symbol|ts_ns|tf|open|high|low|close|volume`. Replaces `uuid4()` at line 520. Identity derived from bar OHLCV (stable replay invariant), not plugin outputs (stateful). Migration 115 adds `UNIQUE INDEX CONCURRENTLY` on `signal_ledger.signal_id`.

### Task 6: In-process calibration (CRITICAL-02)
Added calibration pass after `rank_signals()` and before winner selection in `SignalProcessor.process()`. Reads from `cache_snapshot.calibration_curves`. Populates `calibrated_confidence` and `confidence_calibrated: bool` on each ranked signal. Raw fallback explicit when no curve cached.

### Task 7: BaseWriter (valid, invalid) tuple (HIGH-01)
Changed `_parse_payload` abstract signature from `list | None` to `tuple[list, list]`. Updated `_run()` dispatch: `if invalid and not valid: DLQ; if valid: buffer`. All 10 subclasses migrated. Updated 12 failing tests in bar_writer, context_writer, feature_writer.

### Task 8: Features DO UPDATE (HIGH-03)
Changed `ON CONFLICT (ts, symbol, tf) DO NOTHING` to `DO UPDATE SET ... WHERE EXCLUDED.schema_version >= {table}.schema_version`. Version guard prevents stale replay from overwriting live data.

### Task 9: DAG Invariant CI (MEDIUM-01)
`tests/unit/intelligence/test_dag_invariants.py` uses `pkgutil.walk_packages` to enumerate all `src.intelligence.*` modules and asserts none import `asyncpg`, `asyncpg.pool`, `aiokafka`, or `confluent_kafka`. 158 modules checked, all pass.

### Task 10: Live contract hot-reload (MEDIUM-02)
Added `topic_contracts_updated()` to `stream_keys.py`. Intelligence pipeline subscribes at startup. Dispatch branch performs atomic reference swap (`self._contracts = new_contracts`) with `CONTRACTS_RELOAD_TOTAL` telemetry on both success and failure paths.

### Task 11: Setup performance gate (structural)
Raised `MIN_SAMPLE_SIZE` from 30 to 100 in `setup_performance_updater.py`. Updated `ranker.py`, `aggregator.py`, `cache_manager.py`, and `signal_metrics_writer.py`. Created migration 116 to delete stale rows. Updated 12 tests across 3 test files.

### Task 12: Pipeline backpressure (structural)
Added `_MAX_QUEUE_DEPTH=500` constant. Backpressure check before `_worker_manager.enqueue()` measures total queue depth across all per-key queues. Drops INCOMING bar (newest) when depth >= 500 — preserving established rolling windows and Kalman state. Emits `PIPELINE_BACKPRESSURE_DROP_TOTAL` with symbol+tf labels.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_Subscription` not hashable**
- **Found during:** Task 4 (test run)
- **Issue:** `@dataclass` generates `__eq__` which disables `__hash__`, making the dataclass unhashable and unable to be added to a `set`.
- **Fix:** Changed to `@dataclass(eq=False)` to preserve identity-based hash.
- **Files modified:** `src/api/routes/sse.py`
- **Commit:** cc36d7fe (included in Task 4 commit)

**2. [Rule 2 - Missing functionality] Tasks 10 and 12 committed together**
- **Found during:** Task 12
- **Issue:** Both tasks modified `intelligence_pipeline.py`; the backpressure code was added during Task 10 work for efficiency.
- **Fix:** Committed both changes in Task 10's commit. Plan commit message documents both.

## Self-Check: PASSED

Verified key artifacts exist:
- `production/migrations/115_signal_id_unique.sql` - created
- `production/migrations/116_setup_performance_gate.sql` - created
- `tests/unit/api/test_sse_broadcaster.py` - created (8 tests)
- `tests/unit/intelligence/test_dag_invariants.py` - created (158 parametrized tests)
- `tests/unit/intelligence/test_signal_id_stability.py` - created (6 tests)

All commits verified in git log. Unit tests: 4265 passed, 29 skipped.
