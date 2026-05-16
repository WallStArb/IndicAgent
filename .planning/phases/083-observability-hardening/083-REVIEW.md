---
phase: 083-observability-hardening
reviewed: 2026-05-15T22:00:00Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - production/alertmanager-rules.yml
  - production/migrations/088_dlq_events.sql
  - production/scripts/ensure_topics.sh
  - production/systemd/indicagent-dlq-drain.service
  - services/dlq_drain_agent.py
  - src/core/agent/base.py
  - src/core/agent/base_writer.py
  - src/core/ai/base_agent.py
  - src/core/ai/base_group_service.py
  - src/core/llm/chain.py
  - src/core/plugin_circuit_breaker.py
  - src/core/stream_keys.py
  - src/observability/metrics.py
  - src/observability/otel.py
  - src/observability/spans.py
findings:
  critical: 3
  warning: 5
  info: 3
  total: 11
status: issues_found
---

# Phase 083: Code Review Report

**Reviewed:** 2026-05-15T22:00:00Z
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

Phase 083 hardened observability by migrating metrics to the OTel SDK, adding DLQ drain infrastructure, and adding five new alert rules. The DLQ drain agent, migration, and span library are structurally sound. However, three blockers were found: an alert rule that will never fire because it references a metric value (capacity_skip) that is never emitted anywhere in the codebase; a systematic misuse of `up_down_counter` as a set-semantics gauge that causes all state-tracking metrics to accumulate garbage values; and a `_settings.env_name` AttributeError crash path in `LLMProviderChain._publish_parse_failure()` when `settings=None` but a producer is injected. Several warnings cover a broken dedup key in the DLQ table, non-UTC timestamps in the circuit breaker, and the `alter-config` failure mode in `ensure_topics.sh`.

---

## Critical Issues

### CR-01: SwarmCapacitySkipRateHigh alert references a label value that is never emitted - alert will never fire

**File:** `production/alertmanager-rules.yml:85-92`

**Issue:** The alert expression filters on `swarm_invocations_total{status="capacity_skip"}`. A search of the entire codebase finds zero sites that emit `SWARM_INVOCATIONS_TOTAL.add()` with `status="capacity_skip"`. The only status values emitted by `alpha_swarm_agent.py` are `"ok"`, `"error"`, and `"all_failed"` (lines 528-567 of `services/alpha_swarm_agent.py`). This alert will never produce any matching time series and will never fire regardless of actual swarm capacity degradation.

**Fix:** Change the alert expression to use the status values that are actually emitted. Either add a `capacity_skip` emission path to `alpha_swarm_agent.py` when agents are skipped due to timeout budget, or rewrite the alert to use the existing labels:

```yaml
# Option A - alert on high error rate using actual label values
- alert: SwarmCapacitySkipRateHigh
  expr: |
    rate(swarm_invocations_total{status="error"}[5m])
    / rate(swarm_invocations_total[5m]) > 0.5
  for: 5m

# Option B - emit the label and alert on it
# In alpha_swarm_agent.py, add:
SWARM_INVOCATIONS_TOTAL.add(
    1, {"agent_id": agent.agent_id, "timeframe": tf, "status": "capacity_skip"}
)
# ... and then the existing alert expression is correct.
```

---

### CR-02: `CIRCUIT_BREAKER_STATE`, `PERSISTENCE_CONSUMER_LAG`, and `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` are `up_down_counter` instruments used with accumulation semantics, producing permanently wrong values

**File:** `src/observability/metrics.py:67-68`, `src/observability/metrics.py:98-101`, `src/observability/metrics.py:199-202`; `src/core/plugin_circuit_breaker.py:242,261,299,371,505,571`; `src/core/agent/base.py:273,285`; `src/core/agent/base_writer.py:354`

**Issue:** All three metrics are declared as `create_up_down_counter` (a cumulative instrument) but are called with `.add(current_value, ...)` semantics intended for a gauge (an instrument that represents a current point-in-time reading). This means:

1. **`CIRCUIT_BREAKER_STATE`** - Each state transition calls `.add(state.value)` where `state.value` is 0, 1, or 2. The counter accumulates these additions. After a CLOSED→OPEN→CLOSED cycle the exported value is `0+1+0=1` (OPEN), not `0` (CLOSED). Grafana dashboards and any rule using this metric will read incorrect state forever.

2. **`PERSISTENCE_CONSUMER_LAG`** - `BaseWriterAgent._report_consumer_lag()` calls `.add(len(self._buffer), attrs)` every 15 seconds. The exported value grows by `buffer_depth` every 15s and never represents the current lag. The `ConsumerLagHigh` alert in `alertmanager-rules.yml:23-29` will trigger spuriously within minutes of startup.

3. **`AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS`** - `_record_message_consumed()` calls `.add(time.time(), ...)` on each message. Every call adds the current Unix timestamp (~1.7 trillion) to the counter, producing a value that is meaningless as a liveness indicator.

**Fix:** Replace these three with `ObservableGauge` (async callback-based) or use `create_up_down_counter` correctly by subtracting the previous value before adding the new one. The cleanest fix is to use `ObservableGauge` for all three:

```python
# In metrics.py - replace the three create_up_down_counter calls with ObservableGauge

# Example for AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS:
# Store the raw value in a dict; register a callback that reads it.
# In base.py _record_message_consumed():
self._last_message_ts_wall = time.time()  # already tracked as monotonic for stall detection
# Register ObservableGauge callback in __init__ that yields self._last_message_ts_wall
```

For `PERSISTENCE_CONSUMER_LAG` specifically, since it is also used by the `ConsumerLagHigh` Prometheus alert rule, the metric name and semantics must be consistent: an `ObservableGauge` named `persistence_consumer_lag_records` that yields the current buffer depth satisfies both the metric and the alert.

---

### CR-03: `LLMProviderChain._publish_parse_failure()` dereferences `self._settings` without a None guard, crashing when `settings=None`

**File:** `src/core/llm/chain.py:239`

**Issue:** `_publish_parse_failure()` calls `topic_llm_calls(self._settings.env_name)` at line 239 without checking whether `self._settings` is `None`. `LLMProviderChain.__init__` accepts `settings: Any | None = None`, and the docstring in `src/core/llm/__init__.py` shows `LLMProviderChain(call_type="narrative")` as the canonical usage example (no settings argument). If any caller constructs the chain with `settings=None` but also passes a `producer` (e.g., in a test or future integration), calling `_report_parse_failure()` on `BaseAIAgent` will raise `AttributeError: 'NoneType' object has no attribute 'env_name'`, silently swallowed by the `except` in `BaseAIAgent._report_parse_failure()` but logged as a warning with no useful context. The same crash exists in `_publish_audit()` at line 217, though that path is guarded by `if self._producer is None: return` in the `audit_context is None` check.

**Fix:**

```python
# src/core/llm/chain.py

async def _publish_parse_failure(self, call_id: str) -> None:
    if self._producer is None or self._settings is None:  # add settings guard
        return
    from src.core.stream_keys import topic_llm_calls
    try:
        await self._producer.publish(
            topic_llm_calls(self._settings.env_name),
            {"call_id": call_id, "parse_success": False, "_parse_update": True},
        )
    except Exception:
        logger.exception("auto_audit.parse_failure_publish_failed", call_id=call_id)

async def _publish_audit(self, audit_context, provider_id, latency_s, tokens, response, model):
    if audit_context is None or self._producer is None or self._settings is None:  # add settings guard
        return
    ...
```

---

## Warnings

### WR-01: `dlq_events` dedup index uses timestamp as part of unique key - duplicate DLQ events from the same agent within the same microsecond are silently dropped

**File:** `production/migrations/088_dlq_events.sql:20-22`; `services/dlq_drain_agent.py:56-61`

**Issue:** The `ON CONFLICT DO NOTHING` clause and the `dlq_events_dedup_idx` unique index are keyed on `(agent, source_topic, routed_at)`. During burst DLQ activity (e.g., a parsing regression causing many rapid errors from one agent on one topic), multiple DLQ events arriving with the same `routed_at` microsecond timestamp will have all but the first silently discarded. The `BIGSERIAL id` column exists but is not declared as `PRIMARY KEY`, so it provides no deduplication anchor. The table is a loss-of-information audit log - silent drops violate its stated purpose.

**Fix:** Remove `routed_at` from the unique key and replace it with `id`, or include `id` in the primary key so conflicts are impossible. Also declare the primary key explicitly to satisfy TimescaleDB best practices:

```sql
CREATE TABLE IF NOT EXISTS dlq_events (
    id            BIGSERIAL,
    routed_at     TIMESTAMPTZ NOT NULL,
    agent         TEXT NOT NULL,
    source_topic  TEXT NOT NULL,
    dlq_topic     TEXT NOT NULL,
    error_type    TEXT NOT NULL,
    error_message TEXT NOT NULL,
    payload       JSONB NOT NULL,
    retry_count   INT NOT NULL DEFAULT 0,
    PRIMARY KEY (id, routed_at)  -- id is unique; routed_at required for hypertable
);

SELECT create_hypertable('dlq_events', 'routed_at', if_not_exists => TRUE);
SELECT add_retention_policy('dlq_events', INTERVAL '30 days', if_not_exists => TRUE);
-- No separate UNIQUE INDEX needed; PK on (id, routed_at) prevents nothing-duplicates
```

---

### WR-02: `plugin_circuit_breaker.py` uses naive `datetime.now()` throughout, violating the project UTC rule

**File:** `src/core/plugin_circuit_breaker.py:232,255,277,330,338,390`

**Issue:** Every timestamp recorded by `PluginCircuitBreaker` uses `datetime.now()` (local-time, timezone-naive). CLAUDE.md mandates `datetime.now(UTC)` exclusively. There are six call sites. The `_count_recent_failures()` comparison at line 390 (`failure.timestamp > cutoff_time`) compares a naive timestamp against another naive timestamp from `datetime.now()`, so arithmetic is internally consistent. However, persisted state in `_serialize_plugin_state()` / `restore_plugin_state()` uses `.isoformat()` on these naive datetimes, producing timezone-ambiguous ISO strings (e.g. `"2026-05-15T14:30:00"` with no `Z` or offset). State restored across a DST boundary or on a server with a non-UTC locale will produce incorrect recovery timeout calculations - the OPEN circuit may never transition to HALF_OPEN or may do so prematurely.

**Fix:**

```python
# At top of plugin_circuit_breaker.py:
from datetime import UTC, datetime

# Replace all datetime.now() calls with:
datetime.now(UTC)
```

---

### WR-03: `ensure_topics.sh` alter-config step runs without error suppression; topic creation failure silently allows retention to be unset

**File:** `production/scripts/ensure_topics.sh:32-38`

**Issue:** The `rpk topic create` at line 33 uses `2>/dev/null || true`, suppressing all errors. If `docker exec redpanda` fails (e.g., the container is not running), the create silently succeeds (no-op). The subsequent `rpk topic alter-config` at line 36 then fails with a connection error (no `|| true`), and because the script runs with `set -euo pipefail`, it exits immediately. Topics processed after the failing one are never configured. The script prints `Done.` only when all 15 topics succeed, but does not indicate which topic caused an abort, making debugging non-obvious.

Additionally, if `rpk topic create` fails because the container is down (silently suppressed by `|| true`), the `alter-config` will fail for the same reason and the script exits part-way through. The intent of the `|| true` is to suppress the "topic already exists" error, not connectivity errors.

**Fix:**

```bash
for topic in "${DLQ_TOPICS[@]}"; do
  # Create if absent (only suppress "already exists" error, not connectivity)
  if ! docker exec redpanda rpk topic create "$topic" --replicas 1 \
    -c retention.ms=604800000 2>&1 | grep -q "TOPIC_ALREADY_EXISTS"; then
    # Either creation succeeded or a real error occurred
    :
  fi

  # Set retention (fail loudly if Redpanda is unreachable)
  docker exec redpanda rpk topic alter-config "$topic" \
    --set retention.ms=604800000
  echo "  OK $topic"
done
```

Alternatively, add `|| true` to the `alter-config` line as well and log failures explicitly, since idempotency is the stated goal.

---

### WR-04: `BaseAgent._report_consumer_lag()` calls `PERSISTENCE_CONSUMER_LAG.add(0, ...)` in a 15-second loop, indefinitely incrementing a cumulative counter by zero

**File:** `src/core/agent/base.py:272-274`

**Issue:** `BaseAgent._report_consumer_lag()` calls `PERSISTENCE_CONSUMER_LAG.add(0, self._consumer_lag_attrs)` every 15 seconds. Even though adding zero to an `up_down_counter` produces no arithmetic change, this is semantically wrong for two reasons: (1) it conflates `BaseAgent` (stream processors with no buffer) and `BaseWriterAgent` (which accumulates rows) under the same metric with different semantics, and (2) once CR-02 is fixed and `PERSISTENCE_CONSUMER_LAG` becomes an `ObservableGauge`, this `add(0)` call site will need to be removed. The current loop is dead weight that creates 4 Kafka/OTel submissions per minute per agent for zero informational value.

**Fix:** Remove the `add(0)` loop from `BaseAgent._report_consumer_lag()`. Stream processors (non-writer agents) have no buffer lag to report; suppress the loop entirely:

```python
async def _report_consumer_lag(self) -> None:
    """No-op for stream processors. BaseWriterAgent overrides with buffer depth."""
    while not self._stop_event.is_set():
        await asyncio.sleep(60)  # wake periodically so stop_event check works
```

---

### WR-05: `PluginCircuitBreaker.CIRCUIT_BREAKER_STATE` metric is never decremented on OPEN→HALF_OPEN transition, so the metric accumulates permanently incorrect state

**File:** `src/core/plugin_circuit_breaker.py:230-244`

**Issue:** In `_should_use_fallback()`, when the recovery timeout expires and the circuit transitions OPEN→HALF_OPEN (line 235-244), `CIRCUIT_BREAKER_STATE.add(plugin_state.state.value, ...)` is called with the HALF_OPEN value (2). But the metric is an `up_down_counter` and was previously incremented to OPEN (1). After the transition, the exported value is `1 + 2 = 3`, which does not correspond to any valid `CircuitState` enum value (CLOSED=0, OPEN=1, HALF_OPEN=2). The metric is structurally unreadable. This is closely related to CR-02 but is separately noteworthy because HALF_OPEN transitions are the ones most critical to monitor for recovery detection.

**Fix:** Resolve as part of CR-02 by replacing `CIRCUIT_BREAKER_STATE` with an `ObservableGauge` whose callback reads `self.plugin_states[name].state.value` directly.

---

## Info

### IN-01: `dlq_events` table is missing an explicit `PRIMARY KEY` constraint on `id`

**File:** `production/migrations/088_dlq_events.sql:6`

**Issue:** `id BIGSERIAL` allocates a sequence and creates an implicit unique constraint on `id`, but does not declare `PRIMARY KEY`. TimescaleDB hypertable documentation recommends that the primary key always include the time partitioning column (`routed_at`). Omitting the primary key declaration means ORM tools, `pg_dump`, and replication setups may not treat `id` as the canonical row identity. This is addressed by WR-01's fix.

---

### IN-02: `base_group_service.py` `_graduation_loop()` is a TODO stub but `has_graduation=True` can be set by subclasses

**File:** `src/core/ai/base_group_service.py:282-303`

**Issue:** `_graduation_loop()` contains only `# TODO: Implement graduation logic (Phase 75)` comments and no implementation. The `has_graduation` class attribute is `False` by default so no current subclass is affected. However the stub contains an `except` that swallows all exceptions (`except Exception`) and loops forever via `while self.running`. If a future phase sets `has_graduation=True` before implementing the body, it will silently run an infinite no-op loop consuming one `asyncio.Task` slot.

**Fix:** Add a `raise NotImplementedError` or at minimum a structured log at DEBUG level so operators know the loop is running but empty:

```python
async def _graduation_loop(self) -> None:
    raise NotImplementedError(
        "_graduation_loop() not yet implemented. Set has_graduation=False until Phase 75."
    )
```

---

### IN-03: `plugin_circuit_breaker.py` imports `timedelta` and `datetime` from stdlib but never imports `UTC`, inconsistent with project convention

**File:** `src/core/plugin_circuit_breaker.py:29`

**Issue:** `from datetime import datetime, timedelta` is present but `UTC` is not imported. This is the proximate cause of the WR-02 finding (all `datetime.now()` calls are timezone-naive). Once WR-02 is fixed, the import line must be updated.

**Fix:**

```python
from datetime import UTC, datetime, timedelta
```

---

_Reviewed: 2026-05-15T22:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
