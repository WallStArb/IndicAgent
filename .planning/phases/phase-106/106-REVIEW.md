---
phase: 106
reviewed: 2026-05-24T00:00:00Z
depth: standard
files_reviewed: 27
files_reviewed_list:
  - production/systemd/indicagent-alerting-agent.service
  - production/systemd/indicagent-dlq-drain.service
  - production/systemd/indicagent-intelligence-pipeline.service
  - services/bar_aggregator_agent.py
  - services/bar_replay_provider_agent.py
  - services/intelligence_pipeline_agent.py
  - services/service_auditor_agent.py
  - services/signal_replay_auditor_agent.py
  - services/swarm_ledger_writer_agent.py
  - src/config/settings.py
  - src/core/agent/base_writer.py
  - src/core/ai/base_agent.py
  - src/core/llm/chain.py
  - src/core/ml/__init__.py
  - src/intelligence/ai/TEMPLATE_agent.py
  - src/intelligence/pipeline/feature_pipeline_executor.py
  - src/intelligence/pipeline/output_queue.py
  - src/intelligence/pipeline/state_manager.py
  - src/observability/circuit_breaker.py
  - tests/unit/core/test_base_writer_agent.py
  - tests/unit/intelligence/test_plugin_circuit_breaker_wiring.py
  - tests/unit/intelligence/test_plugin_state_manager.py
  - tests/unit/services/test_alpha_swarm_agent.py
  - tests/unit/services/test_bar_aggregator_agent.py
  - tests/unit/services/test_pipeline_backpressure.py
  - tests/unit/services/test_service_auditor_agent.py
findings:
  critical: 2
  warning: 6
  info: 3
  total: 11
status: issues_found
---

# Phase 106: Code Review Report

**Reviewed:** 2026-05-24T00:00:00Z
**Depth:** standard
**Files Reviewed:** 27
**Status:** issues_found

## Summary

Phase 106 introduces DAG decomposition improvements (PluginStateManager secondary index,
OutputQueue backpressure, circuit breaker wiring, per-tier latency metrics) alongside
test coverage for these features. The structural work is sound. Two blockers were found:
one crashes the replay auditor on every cycle (wrong method name on an OTel counter), and
one creates an indefinite deadlock in the signal/DLQ/winner output path during shutdown
if the queue is backed up. Six warnings cover logic correctness, metric drift, and unsafe
attribute access patterns.

## Critical Issues

### CR-01: `SIGNAL_REPLAY_ATTEMPTED_TOTAL.inc()` — method does not exist on OTel counter, crashes every cycle

**File:** `services/signal_replay_auditor_agent.py:440`
**Issue:** OTel counters created via `_meter.create_counter()` expose `.add(amount, attributes)`,
not `.inc()`. Calling `.inc(total)` raises `AttributeError` on every invocation of `_cycle()`,
which is caught by the outer `except Exception` in `_run()` and logged, but the entire replay
batch is silently abandoned every 5 minutes. The `SIGNAL_REPLAY_UNRESOLVED_GAUGE` north-star
metric is never updated. All `SIGNAL_REPLAY_ATTEMPTED_TOTAL` increments are lost.

The bug is confirmed by the counter definition in `src/observability/metrics.py:564`
(`_meter.create_counter(...)`) and the calling site:

```python
# line 440 — AttributeError every cycle
SIGNAL_REPLAY_ATTEMPTED_TOTAL.inc(total)
```

**Fix:**
```python
SIGNAL_REPLAY_ATTEMPTED_TOTAL.add(total)
```

---

### CR-02: `enqueue_blocking` without `timeout_sec` on signal/DLQ/winner paths — indefinite deadlock possible at shutdown

**File:** `services/intelligence_pipeline_agent.py:571-581`
**Issue:** Three of the five `enqueue_blocking` calls in `_process_bar_compute` omit
`timeout_sec`, meaning `asyncio.Queue.put()` is awaited with no deadline. The docstring for
`enqueue_blocking` explicitly warns: *"None (default) means wait without a deadline — use only
in contexts that are guaranteed to be cancelled before shutdown."* These three calls are inside
`_process_bar_inner` which runs inside `PerKeyWorkerManager` worker tasks. During teardown,
`_teardown` calls `self._worker_manager.stop()` after setting `_stop_event`, but if the output
queue is simultaneously backed up (full), any in-flight worker task will block indefinitely on
the `put()`, preventing `stop()` from completing and hanging the whole shutdown sequence.

```python
# Lines 571-581 — no timeout_sec on three of five enqueue_blocking calls
if result.success and result.signals_payload:
    await self._out_queue.enqueue_blocking(          # BLOCKS INDEFINITELY
        topic_intelligence_i7_signals(env), msg_key, result.signals_payload
    )
elif result.dlq_payload:
    await self._out_queue.enqueue_blocking(          # BLOCKS INDEFINITELY
        topic_signal_dlq(env), msg_key, result.dlq_payload
    )
if result.winner_payload:
    await self._out_queue.enqueue_blocking(          # BLOCKS INDEFINITELY
        topic_signals_aggregated(env), msg_key, result.winner_payload
    )
```

The intel and journal calls at lines 546 and 642 correctly pass `timeout_sec=5.0`.

**Fix:** Add `timeout_sec=5.0` to all three calls:
```python
if result.success and result.signals_payload:
    await self._out_queue.enqueue_blocking(
        topic_intelligence_i7_signals(env), msg_key, result.signals_payload,
        timeout_sec=5.0,
    )
elif result.dlq_payload:
    await self._out_queue.enqueue_blocking(
        topic_signal_dlq(env), msg_key, result.dlq_payload,
        timeout_sec=5.0,
    )
if result.winner_payload:
    await self._out_queue.enqueue_blocking(
        topic_signals_aggregated(env), msg_key, result.winner_payload,
        timeout_sec=5.0,
    )
```

---

## Warnings

### WR-01: `_BARS_IN_FLIGHT` counter reads internal `_value` attribute — implementation-specific, will silently break

**File:** `services/bar_aggregator_agent.py:400,407`
**Issue:** Two lines access `self._processing_semaphore._value`, a CPython implementation
detail of `asyncio.Semaphore` that is not part of the public API and is absent or different in
other Python implementations (e.g. PyPy). The check on line 400 (`if self._processing_semaphore.locked()`)
is correct API, but the log line and counter use `._value` directly:

```python
# line 400 — OK public API
if self._processing_semaphore.locked():
    self.logger.warning(
        "bar_aggregator.semaphore_saturated",
        semaphore_value=self._processing_semaphore._value,   # line 401 — private
    )
# line 407 — private
_BARS_IN_FLIGHT.add(200 - self._processing_semaphore._value)
```

The metric will produce an incorrect (always 0) reading on `asyncio.BoundedSemaphore` or if
the internal layout changes. A counter measuring "in-flight" bars via semaphore arithmetic is
also semantically wrong — it re-adds a snapshot on every bar processed rather than tracking
actual acquire/release deltas.

**Fix:** Remove the `_value` reads; use an explicit `_bars_in_flight_count` integer tracked
with +1 on semaphore acquire and -1 on release:
```python
# In __init__
self._bars_in_flight_count: int = 0

# Around the semaphore block
self._bars_in_flight_count += 1
_BARS_IN_FLIGHT.add(1)
async with self._processing_semaphore:
    ...
finally:
    self._bars_in_flight_count -= 1
    _BARS_IN_FLIGHT.add(-1)
```

---

### WR-02: `_query_prometheus` uses bare `assert` — raises `AssertionError` in production when HTTP session is None

**File:** `services/service_auditor_agent.py:744`
**Issue:** `assert self._http_session is not None` is the only guard before calling
`self._http_session.get(...)`. Python runs with optimizations (`-O`) disabled in most
deployments, but `AssertionError` is semantically wrong for a runtime invariant violation and
will produce an opaque traceback instead of a structured log entry. If `_setup()` fails and
teardown clears `_http_session`, any in-flight Prometheus poll task will raise `AssertionError`
rather than the expected `AttributeError` or a logged warning, defeating the error isolation
the surrounding `try/except` provides.

**Fix:**
```python
if self._http_session is None:
    return []
```

---

### WR-03: `get_active_contracts` cache update uses stale `now` timestamp — TTL can expire immediately

**File:** `src/config/settings.py:449`
**Issue:** The `now = time.monotonic()` snapshot is captured before the DB query (line 363)
and then written to `_active_contracts_last_refresh` after the DB query completes (line 449).
If the DB query takes, say, 55 seconds (slow connection, full table scan), `cache_age` on the
next call will be computed against a `now` that is already 55 seconds old, making the TTL
expire after only 5 seconds of actual wall-clock time. Under constant load with a slow DB,
the cache effectively never holds, causing every call to hit the DB.

**Fix:** Capture `now` after the DB query succeeds:
```python
        result = db_instruments + non_futures
        now_after_query = time.monotonic()   # fresh timestamp after query
        with _settings_lock:
            _active_contracts_cache = result
            _active_contracts_last_refresh = now_after_query
        return result
```

---

### WR-04: `_UPSERT_ML_SCORE_SQL` casts `ml_model_id` to `::uuid` even when the value is `None` — runtime error on null model_id

**File:** `services/swarm_ledger_writer_agent.py:61,239`
**Issue:** The second UPSERT SQL casts parameter `$3` to `::uuid`:
```sql
VALUES ($1::uuid, $2, $3::uuid, NOW())
```
When `ml_model_id` is `None` (the common case when no `model_id` key is present in the
agent payload), asyncpg passes `NULL` for `$3`, and PostgreSQL will attempt `NULL::uuid`.
While PostgreSQL does accept `NULL::uuid = NULL`, the explicit cast is redundant and fragile.
More importantly, at line 239:
```python
str(ml_model_id) if ml_model_id else None
```
When `ml_model_id` is an empty string `""`, `bool("")` is `False`, so it is passed as `None`.
However if `ml_model_id` is some non-UUID string (e.g. a model name slug), `::uuid` will
raise `InvalidTextRepresentationError` which is not caught in `_apply_projection`'s exception
handlers, causing the retry loop to exhaust silently and the enrichment to be dropped.

**Fix:** Remove the `::uuid` cast from the ml_model_id parameter and validate/normalize
upstream if UUID format is required:
```sql
VALUES ($1::uuid, $2, $3, NOW())
```

---

### WR-05: `TEMPLATE_agent.py` passes `latency_ms=0.0` to `_neutral()` on error paths — incorrect latency recorded in audit trail

**File:** `src/intelligence/ai/TEMPLATE_agent.py:86,97`
**Issue:** Both error returns from `_compute()` use `latency_ms=0.0` as a hardcoded
sentinel rather than capturing the actual elapsed time:
```python
return self._neutral(error="LLM returned empty response", latency_ms=0.0)
...
return self._neutral(error="JSON parse failed", latency_ms=0.0)
```
The `_neutral` output is published to the lineage trail and contributes to
`AI_AGENT_DURATION_MS` histogram. Zeroing latency masks real LLM call durations from
the audit trail and prevents accurate per-agent budget analysis. Since `_compute()` is
already called from inside `compute()` which wraps with `asyncio.wait_for`, any
`TimeoutError` is handled by the outer wrapper; the inner `_compute` should still
capture its own elapsed time.

**Fix:** Capture `t0 = time.monotonic()` at the start of `_compute()` and pass the actual
elapsed time:
```python
async def _compute(self, context: AIContext) -> AgentOutput:
    t0 = time.monotonic()
    ...
    if not response:
        return self._neutral(
            error="LLM returned empty response",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
    parsed = self._parse_multiplier_response(response, _validate_template_fields)
    if parsed is None:
        ...
        return self._neutral(
            error="JSON parse failed",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
```

---

### WR-06: `test_no_commit_on_flush_failure` expects `pytest.raises` but `_do_flush` swallows exceptions — test will never catch

**File:** `tests/unit/core/test_base_writer_agent.py:196-208`
**Issue:** `_do_flush()` in `BaseWriterAgent` wraps `_flush_batch` in a `try/except` block
(lines 286-291 of `base_writer.py`) and catches all exceptions, logging them without
re-raising. The test at line 202 uses `pytest.raises(RuntimeError, match="DB down")`:
```python
with pytest.raises(RuntimeError, match="DB down"):
    await agent._do_flush()
```
However, `_do_flush` will not raise — the exception is caught and swallowed. The test
will fail with "DID NOT RAISE" when run. This means the negative contract ("no commit
on flush failure") is untested; the commit-skipping behavior is actually guarded by the
code structure (commit only runs after `_flush_batch` returns without exception), but
the test does not prove this.

**Fix:** Replace `pytest.raises` with a check that the flush exception was swallowed
and the commit was not called:
```python
async def test_no_commit_on_flush_failure(self):
    agent = StubWriterAgent()
    agent._consumer = AsyncMock()

    async def failing_flush(batch):
        raise RuntimeError("DB down")

    agent._flush_batch = failing_flush
    agent._buffer.extend([{"id": 1}])

    # _do_flush swallows exceptions — should not raise
    await agent._do_flush()

    # Buffer should NOT be cleared (left intact for retry)
    assert len(agent._buffer) == 1
    # Commit should NOT have been called
    agent._consumer.commit.assert_not_awaited()
```

---

## Info

### IN-01: `production/systemd/indicagent-alerting-agent.service` missing `After=indicagent-intelligence-pipeline.service`

**File:** `production/systemd/indicagent-alerting-agent.service:3`
**Issue:** The alerting agent is L9 in the DAG (consumes alert requests from all upstream
services). Its systemd `After=` only declares `network-online.target` and
`indicagent-redpanda-ready.service`. The `_DAG_ORDER` in `service_auditor_agent.py`
correctly places it at priority 9, but systemd will not enforce startup ordering relative
to the intelligence pipeline (L6) or writers (L7) unless the `After=` clause includes them.
On boot, systemd may start the alerting agent before the pipeline has written any topics,
leading to unnecessary early-consumer-group registration. `indicagent-dlq-drain.service`
has the same gap.

**Fix:** Add at minimum:
```ini
After=network-online.target indicagent-redpanda-ready.service indicagent-intelligence-pipeline.service
```

---

### IN-02: `_derive_expiry_from_symbol` hardcodes year base as 2020 — will produce wrong expiry after 2029

**File:** `src/config/settings.py:299`
**Issue:**
```python
year = 2020 + int(suffix[1])
```
The single-digit year suffix `suffix[1]` maps `'0'` → 2020, `'9'` → 2029. Any contract
code with suffix `'0'` in 2030 will be misidentified as 2020, causing IBKR to reject the
contract qualification. This is a time-bomb bug, not imminent but deterministic.

**Fix:**
```python
import datetime
current_year = datetime.datetime.now().year
decade_base = (current_year // 10) * 10
year_digit = int(suffix[1])
# If constructed year is more than 5 years in the past, bump to next decade
candidate = decade_base + year_digit
if candidate < current_year - 5:
    candidate += 10
year = candidate
```

---

### IN-03: `OutputQueue.enqueue_blocking` double-counts drops — increments `_drops` before the `put()` attempt

**File:** `src/intelligence/pipeline/output_queue.py:103-104`
**Issue:**
```python
if self._queue.full():
    self._drops.add(1)
    self._logger.warning("output_queue.full_blocking")
if timeout_sec is not None:
    await asyncio.wait_for(self._queue.put((topic, key, value)), timeout=timeout_sec)
```
The counter is incremented whenever the queue is full at the moment of the check, but
`enqueue_blocking` then proceeds to actually enqueue the item (blocking until a slot opens).
The drop never occurs — it is a backpressure event, not a drop. The metric name
`intelligence_pipeline_output_buffer_drops_total` is therefore misleading and will show
inflated "drops" whenever normal backpressure is observed, making it impossible to distinguish
real drops (from the non-blocking `enqueue()` path) from backpressure events.

**Fix:** Remove the `_drops.add(1)` from `enqueue_blocking`. Use a separate counter
`intelligence_pipeline_output_buffer_backpressure_total` to track full-queue blocking events.

---

_Reviewed: 2026-05-24T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
