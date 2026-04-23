---
phase: 68-pipeline-hardening-institutional-foundation
reviewed: 2026-04-23T00:00:00Z
depth: standard
files_reviewed: 31
files_reviewed_list:
  - production/migrations/063_pipeline_hardening.sql
  - production/migrations/064_symbol_keyed_aggregates.sql
  - services/bar_aggregator_agent.py
  - services/bar_writer_agent.py
  - services/feature_writer_agent.py
  - services/intelligence_pipeline_agent.py
  - services/lifecycle_writer_agent.py
  - services/llm_writer_service.py
  - services/signal_metrics_compute_agent.py
  - services/signal_metrics_writer_agent.py
  - services/signal_writer_agent.py
  - services/swarm_writer_agent.py
  - src/core/agent/base_writer.py
  - src/core/agent/__init__.py
  - src/core/bar_accumulator.py
  - src/core/schemas/bar_message.py
  - src/core/stream_keys.py
  - src/intelligence/metrics/compute.py
  - src/intelligence/pipeline/calibrator.py
  - src/intelligence/pipeline/ranker.py
  - src/intelligence/pipeline/tod_adjuster.py
  - src/intelligence/schemas.py
  - tests/unit/service_tests/test_bar_aggregator_agent.py
  - tests/unit/service_tests/test_bar_writer_agent.py
  - tests/unit/service_tests/test_feature_writer_agent.py
  - tests/unit/service_tests/test_lifecycle_writer_agent.py
  - tests/unit/service_tests/test_signal_writer_agent.py
  - tests/unit/service_tests/test_swarm_writer_agent.py
  - tests/unit/test_bar_accumulator_validation.py
  - tests/unit/test_bar_aggregator_hardening.py
  - tests/unit/test_bar_message.py
  - tests/unit/test_base_writer_agent.py
  - tests/unit/test_stream_keys_dlq.py
findings:
  critical: 0
  warning: 6
  info: 5
  total: 11
status: issues_found
---

# Phase 68: Code Review Report

**Reviewed:** 2026-04-23
**Depth:** standard
**Files Reviewed:** 31
**Status:** issues_found

## Summary

Phase 68 introduces substantial pipeline hardening: `BaseWriterAgent` ABC, per-symbol aggregate tables (migration 064), `bar_id` UUID trace (migration 063), `BarAccumulator` validation, emit-once guard, and DLQ routing across all writer agents. The overall design quality is high — the `BaseWriterAgent` abstraction is clean, the migration safety checks are correct, and the pure-function pipeline stages (calibrator, ranker, tod_adjuster) are well-structured.

Six warnings were found, primarily around a latency metric double-observation in `feature_writer_agent.py`, a duplicated SQL column in `llm_writer_service.py`, a missing `running` guard in `signal_metrics_writer_agent.py`, a potential null-dereference when `ts` is missing in legacy bar parsing, an offset commit gap in `LifecycleWriterAgent`, and a stale attribute name in the bar aggregator test helper. Five informational items cover metric double-observation noise, a magic constant, a duplicated SQL expression, dead code, and a test fixture reference mismatch.

---

## Warnings

### WR-01: Spurious zero-latency observation in `_flush_batch` corrupts percentiles

**File:** `services/feature_writer_agent.py:325`
**Issue:** After timing the actual batch write with `self._batch_latency.time()` context manager (lines 322-323), the code immediately calls `PERSISTENCE_BATCH_LATENCY.labels(agent_id="feature_writer").observe(0)` (line 325). This records a false 0-second observation on every flush, polluting the histogram and making p99 latency appear near zero in Prometheus.
**Fix:**
```python
# Remove line 325 entirely — the context manager on line 322 already records the observation.
# with self._batch_latency.time():
#     await self.db_manager.execute_batch(_INSERT_FEATURE_SQL, batch)
#
# Delete:
# PERSISTENCE_BATCH_LATENCY.labels(agent_id="feature_writer").observe(0)
```

---

### WR-02: Duplicate column alias in `_SELECT_OUTCOME_ROWS_SQL` silently shadows n_calls

**File:** `services/llm_writer_service.py:118`
**Issue:** `_SELECT_OUTCOME_ROWS_SQL` lists `COUNT(outcome) AS n_outcomes` twice on lines 117 and 118. The second occurrence shadows the first. The intent of line 116 is `COUNT(*) AS n_calls`, but the alias is missing — it is reported as `n_calls` in `asyncpg` only because it is the first positional `COUNT`. If column order ever changes or the query is refactored, `_recompute_scores()` at line 753 reads `row["n_calls"]` and `row["n_outcomes"]` by name, and the wrong count will be used for `is_significant` gating.
**Fix:**
```sql
SELECT model, regime, setup_type, call_type, symbol,
       COUNT(*) AS n_calls,
       COUNT(outcome) AS n_outcomes,          -- remove duplicate line
       AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS win_rate,
       AVG(pnl_r) AS avg_pnl_r,
       AVG(latency_ms) AS avg_latency_ms
FROM llm_calls
WHERE outcome IS NOT NULL
GROUP BY model, regime, setup_type, call_type, symbol
```

---

### WR-03: `SignalMetricsWriterAgent._run()` consumes without stop-event check on entry

**File:** `services/signal_metrics_writer_agent.py:225`
**Issue:** `_run()` enters the `async for` loop immediately without checking `self._stop_event.is_set()` before the loop starts. The check at line 228 (`if self._stop_event.is_set(): break`) only fires after the first message is received. If the stop event fires between `_setup()` and the first message arriving, the agent will block in `self._kafka_consumer.messages()` indefinitely rather than exiting promptly. All other agents in this codebase guard with `while not self._stop_event.is_set():` before entering the consume loop.

This agent does not inherit `BaseWriterAgent` and has no `maybe_flush()` call — every DB write is unbuffered (one `async with conn.execute(...)` per message). This is fine for low-volume metric events but means there is no backpressure protection and no offset commit path, which will cause the consumer to re-process all events on restart if `auto_offset_reset="latest"` is changed.

**Fix:**
```python
async def _run(self) -> None:
    if self._stop_event.is_set():
        return
    async for _topic, _key, event in self._kafka_consumer.messages():
        if self._stop_event.is_set():
            break
        ...
```

---

### WR-04: Fallback bar timestamp `datetime.now(UTC)` on missing `ts` silently creates wrong data

**File:** `services/bar_aggregator_agent.py:567` and `services/bar_writer_agent.py:365`
**Issue:** In the legacy bar parsing fallback path, when `payload.get("ts")` and `payload.get("timestamp")` are both absent, the code falls back to `ts = datetime.now(UTC)`. This fabricates a wall-clock timestamp for the bar rather than rejecting the payload. A bar with a fabricated timestamp written to `market_data_ohlcv` or used by `BarAccumulator` will corrupt the OHLCV dataset (Renaissance principle: "Never drop data that could contain signal" — but equally, never fabricate timestamps). The correct behaviour is to reject the bar and route it to the DLQ.
**Fix:**
```python
ts_raw = payload.get("ts") or payload.get("timestamp")
if not ts_raw:
    self._last_skip_reason = "missing_timestamp"
    return None  # route to DLQ rather than fabricating wall-clock time
ts = datetime.fromisoformat(str(ts_raw))
if ts.tzinfo is None:
    ts = ts.replace(tzinfo=UTC)
```

---

### WR-05: `LifecycleWriterAgent` does not wire `_consumer` for offset commits

**File:** `services/lifecycle_writer_agent.py:147-155`
**Issue:** `_setup()` assigns the Kafka consumer to `self._consumer`, which is correct (line 148: `self._consumer = KafkaConsumerClient(...)`). However, `_run()` (line 160) iterates over `self._consumer.messages()` and calls `maybe_flush()`, which calls `_do_flush()`, which commits via `self._consumer`. So far correct. The issue is that `_consumer` is also the attribute `BaseWriterAgent._consumer` — but `_setup()` stores it on `self._consumer` directly (not `self._consumer`), meaning it is overwritten. Cross-check with `LifecycleWriterAgent.__init__` (line 83): `self._consumer: KafkaConsumerClient | None = None` — but `_setup()` assigns to `self._consumer` at line 148. The attribute name collides with `BaseWriterAgent._consumer` (the commit target). The `_consumer_lag.set(...)` call at line 174 references `self._consumer_lag` which is not set in the `__new__`-based test helper but IS set in `_make_agent()` at line 44 via `agent._consumer_lag = _TEST_LAG.labels(...)`. The attribute `_consumer_lag` is not defined in `BaseWriterAgent` — only `_consumer_lag_gauge` is. This means `_run()` line 174 `self._consumer_lag.set(...)` will raise `AttributeError` at runtime if the `_consumer_lag` attribute is not present.

Checking `BaseWriterAgent`: it exposes `_consumer_lag_gauge` (in `_report_consumer_lag`) but not `_consumer_lag`. `LifecycleWriterAgent._run()` references `self._consumer_lag` — this attribute is never assigned in `__init__` or `_setup()`.

**Fix:** Replace `self._consumer_lag.set(...)` at line 174 with `self._buffer_depth_gauge.set(...)` (which is provided by `BaseWriterAgent`) or use `PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name).set(...)`.
```python
# line 174 — replace:
self._consumer_lag.set(len(self._buffer))
# with:
self._buffer_depth_gauge.set(len(self._buffer))
```

---

### WR-06: `test_bar_aggregator_agent._make_agent()` references non-existent attribute `_consumer_restart_requested`

**File:** `tests/unit/service_tests/test_bar_aggregator_agent.py:66`
**Issue:** The test helper sets `agent._consumer_restart_requested = asyncio.Event()` but the actual `BarAggregatorComputeAgent.__init__` (line 136 of `bar_aggregator_agent.py`) uses `self._consumer_restart_needed = False` (a bool flag, not an `asyncio.Event`). The `_run()` loop checks `self._consumer_restart_needed` (bool). Tests that call `_run()` or exercise the consumer restart path will use the wrong attribute type, causing the test to pass even if the wrong condition is checked, or fail with `AttributeError` in tests that do actually reach the restart branch.
**Fix:**
```python
# In _make_agent() at test_bar_aggregator_agent.py line 66 — replace:
agent._consumer_restart_requested = asyncio.Event()
# with:
agent._consumer_restart_needed = False
```

---

## Info

### IN-01: `_SELECT_OUTCOME_ROWS_SQL` `n_calls` is unreachable by name in asyncpg

**File:** `services/llm_writer_service.py:116`
**Issue:** Related to WR-02. The SQL assigns no alias to the first `COUNT(*)` on line 116 — the column name will be `count` (asyncpg default) not `n_calls`. Line 753 reads `row["n_calls"]` which may return the wrong value or raise `KeyError` depending on asyncpg column naming. This is a minor duplication of WR-02 but calls out that the bug affects the reader at `_recompute_scores()` not just the SQL.

---

### IN-02: Magic constant `0` used for `PERSISTENCE_BATCH_LATENCY.observe(0)` with no comment

**File:** `services/feature_writer_agent.py:325`
**Issue:** The `observe(0)` call (already flagged in WR-01 as a bug) would be confusing even if intentional. If the intent were to record something, a named constant with a docstring would be appropriate. The line should simply be removed.

---

### IN-03: `_build_score_insert_params` in `llm_writer_service.py` is dead code

**File:** `services/llm_writer_service.py:259`
**Issue:** `_build_score_insert_params()` (lines 259-308) is defined as a module-level function but never called. `_recompute_scores()` (line 730) computes scores inline using the DB query path. This function is a leftover from an earlier implementation iteration. It is tested nowhere.
**Fix:** Remove the function, or add a `# NOTE: retained for future use` comment if it is intentionally kept as a utility.

---

### IN-04: `bar_id` column added to `intelligence_features` in migration 063 but not populated in `_record_to_insert_params`

**File:** `services/feature_writer_agent.py:155-200` and `production/migrations/063_pipeline_hardening.sql:13`
**Issue:** Migration 063 adds `bar_id UUID` to `intelligence_features` (line 13). The `_INSERT_FEATURE_SQL` in `feature_writer_agent.py` does not include `bar_id` as a column (lines 65-87). The column will always be `NULL` in `intelligence_features` until the INSERT SQL and `_record_to_insert_params` are updated to pass `record.intelligence.bar_id` (or similar). The migration comment says the field enables "end-to-end traceability" — if `feature_writer_agent.py` does not write it, the trace is broken at the intelligence layer.

This is not a crash bug (the column is nullable), but the bar_id trace for `intelligence_features` rows will be permanently NULL until the SQL is updated.

---

### IN-05: `BarAggregatorComputeAgent` uses internal `asyncio.Semaphore._value` attribute

**File:** `services/bar_aggregator_agent.py:337` and `343`
**Issue:** The code accesses `self._processing_semaphore._value` to read the current semaphore count. `_value` is a CPython implementation detail, not part of the `asyncio.Semaphore` public API. It works today but could break in a future Python version or alternative implementation (e.g., PyPy). The gauge at line 343 (`self._bars_in_flight.set(200 - self._processing_semaphore._value)`) uses this to report in-flight count.
**Fix:** Track in-flight count explicitly with a local counter instead of reading internal semaphore state:
```python
self._bars_in_flight_count: int = 0
# on acquire: self._bars_in_flight_count += 1
# on release: self._bars_in_flight_count -= 1
self._bars_in_flight.set(self._bars_in_flight_count)
```

---

_Reviewed: 2026-04-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
