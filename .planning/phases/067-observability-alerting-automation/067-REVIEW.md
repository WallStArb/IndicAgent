---
phase: 067-observability-alerting-automation
reviewed: 2026-04-13T12:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - services/bar_aggregator_agent.py
  - services/bar_auditor_agent.py
  - services/bar_writer_agent.py
  - services/cross_asset_service.py
  - services/feature_writer_agent.py
  - services/intelligence_pipeline_agent.py
  - services/lifecycle_writer_agent.py
  - services/llm_writer_service.py
  - services/parity_auditor_agent.py
  - services/service_auditor_agent.py
  - services/signal_auditor_agent.py
  - services/signal_tracker_compute_agent.py
  - services/signal_writer_agent.py
  - services/swarm_orchestrator_agent.py
  - services/swarm_writer_agent.py
  - src/core/agent/base.py
  - src/core/agent/base_writer.py
  - src/core/schemas/dlq_payload.py
  - src/core/service_utils.py
  - src/core/stream_keys.py
  - src/observability/metrics.py
  - production/grafana/provisioning/alerting/alert-rules.yml
  - production/scripts/provision_dlq_topics.sh
findings:
  critical: 2
  warning: 8
  info: 6
  total: 16
status: issues_found
---

# Phase 067: Code Review Report

**Reviewed:** 2026-04-13T12:00:00Z
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

Reviewed all 24 files in Phase 067 (Observability, Alerting & Automation) at standard depth. The phase adds BaseAgent/BaseWriterAgent lifecycle, DLQ routing, stall detection, crash metrics, and Grafana alert rules. Two critical bugs will cause DLQ routing and alert publishing to fail at runtime. Eight warnings include a metrics port collision, a duplicate gap detection bug, a missing `_settings` attribute, and several correctness issues in the DLQ path.

## Critical Issues

### CR-01: BaseAgent._send_to_dlq calls producer.produce() -- method does not exist

**File:** `src/core/agent/base.py:322,334`
**Issue:** `BaseAgent._send_to_dlq()` calls `await self._kafka_producer.produce(...)` and `await self._producer.produce(...)`, but `KafkaProducerClient` only exposes `publish()` (not `produce()`). This means every DLQ routing attempt will raise `AttributeError` at runtime, causing all DLQ payloads to be silently discarded after the error handler logs the failure. The DLQ system appears to work from a metrics/logging perspective (the `except` block in `_send_to_dlq` catches the `AttributeError`), but no messages ever reach the DLQ topic.

**Fix:**
```python
# In base.py, line 322 and 334, change:
await self._kafka_producer.produce(dlq_topic, dlq_payload.model_dump())
# to:
await self._kafka_producer.publish(dlq_topic, dlq_payload.model_dump())

# And similarly on line 334:
await self._producer.produce(dlq_topic, dlq_payload.model_dump())
# to:
await self._producer.publish(dlq_topic, dlq_payload.model_dump())
```

### CR-02: BaseAgent._send_alert references self._settings but it may not exist

**File:** `src/core/agent/base.py:389`
**Issue:** `_send_alert()` references `self._settings.env_name` but `BaseAgent.__init__()` never sets `self._settings`. Only subclasses that define `self._settings` themselves will work. Agents like `SignalTrackerCompute` that set `self._settings` before calling `super().__init__()` will work, but any agent that does not set `self._settings` (or sets it after `super().__init__()`) will get an `AttributeError` when attempting to publish an alert. Since `_send_alert` is a public BaseAgent method, it should not depend on subclass-specific attributes.

**Fix:**
```python
# In _send_alert(), change:
await self._producer.produce(topic_alert_requests(self._settings.env_name), payload)
# to use a safe fallback for env_name:
env = getattr(self, "_settings", None)
env_name = env.env_name if env and hasattr(env, "env_name") else ""
await self._producer.publish(topic_alert_requests(env_name), payload)
```

## Warnings

### WR-01: Metrics port collision -- LifecycleWriterAgent and SignalAuditorAgent both use :9128

**File:** `services/lifecycle_writer_agent.py:80`, `services/signal_auditor_agent.py:119`
**Issue:** Both `LifecycleWriterAgent` (metrics_port=9128) and `SignalAuditorAgent` (metrics_port=9128) bind to the same Prometheus metrics port. When both services run on the same host, whichever starts second will fail to bind, losing metrics for that agent. This is a deployment-breaking issue since both services run simultaneously.

**Fix:** Assign a unique port to one of them. For example, change `SignalAuditorAgent` to 9134 or `LifecycleWriterAgent` to 9135.

### WR-02: BarAuditorAgent._detect_gaps has duplicate gap request logic on the resolved path

**File:** `services/bar_auditor_agent.py:341-373`
**Issue:** In `_detect_gaps()`, when `completeness >= 1.0`, the code calls `_resolve_market_data_gap()` and then immediately runs the same dedup/gap-request-append block that runs in the `completeness < threshold` branch (lines 347-373). This means when completeness reaches 100%, the code both resolves the gap AND publishes a new `BarGapRequest` for it -- which is contradictory behavior. The gap is resolved but a new request to fill it is also queued.

**Fix:**
```python
elif completeness >= 1.0:
    await self._resolve_market_data_gap(
        conn, instrument.symbol, "1m", date_start_utc
    )
    # Do NOT publish a BarGapRequest for a resolved gap.
    # The code block from lines 347-373 should be removed from this branch.
```

### WR-03: BaseAgent._send_to_dlq references self._topics_consumed (private) instead of self.topics_consumed (property)

**File:** `src/core/agent/base.py:311`
**Issue:** The `source_topic` field in `DLQPayload` is derived from `self._topics_consumed[0]`, but the property is `self.topics_consumed` (no underscore). The `hasattr(self, "_topics_consumed")` guard means this degrades gracefully (falls back to `"unknown"`), but no agent will ever have `_topics_consumed` set, so the source_topic in DLQ messages will always be `"unknown"`, reducing DLQ debuggability.

**Fix:**
```python
# Change line 311 from:
source_topic=self._topics_consumed[0] if hasattr(self, "_topics_consumed") and self._topics_consumed else "unknown",
# to:
source_topic=self.topics_consumed[0] if self.topics_consumed else "unknown",
```

### WR-04: BarAuditorAgent metrics label uses "agent" instead of "agent_id"

**File:** `services/bar_auditor_agent.py:62-85`
**Issue:** `BarAuditorAgent` uses label key `"agent"` on its module-level metrics (`_AUDITS_RUN`, `_GAP_REQUESTS_PUBLISHED`, etc.), while `PERSISTENCE_BATCH_LATENCY` and `PERSISTENCE_CONSUMER_LAG` use `"agent_id"`. The CLAUDE.md project rule explicitly states: "PERSISTENCE_BATCH_LATENCY label key is `agent_id`". While these are separate metrics (not `PERSISTENCE_BATCH_LATENCY`), the inconsistency means Grafana dashboards and alert rules must handle both label names. The ServiceAuditorAgent's `_AGENT_ID_TO_UNIT` mapping uses `agent_id` from the lag query, creating a split convention.

**Fix:** For consistency with the project convention, consider migrating auditor agent labels to `agent_id` in a future phase. Not blocking since these are independent metrics.

### WR-05: LLMWriterService does not inherit from BaseAgent -- no crash metrics or stall detection

**File:** `services/llm_writer_service.py`
**Issue:** `LLMWriterService` manages its own signal handlers, running flag, and shutdown logic without inheriting from `BaseAgent`. It does not benefit from crash metrics (`agent_crash_total`), stall detection, or the standard setup/teardown lifecycle. This is the only writer service that was not migrated to `BaseWriterAgent`. While it functionally works, it lacks the observability coverage that Phase 067 added to all other agents.

**Fix:** Consider migrating `LLMWriterService` to extend `BaseWriterAgent` (like `FeatureWriterAgent` and `SignalWriterAgent`), or at minimum extend `BaseAgent` to get crash metrics and stall detection.

### WR-06: ParityAuditorAgent.start_metrics_server called before super().__init__ completes metrics setup

**File:** `services/parity_auditor_agent.py:361`
**Issue:** `ParityAuditorAgent` calls `start_metrics_server(port=METRICS_PORT)` in its `main()` function before calling `agent.start()`. `BaseAgent.start()` also calls `start_metrics_server()` if `metrics_port` is set. Since `ParityAuditorAgent` does pass `metrics_port` implicitly (it inherits from `BaseAgent` which defaults to `None`), this works because the BaseAgent check is `if self._metrics_port is not None`. However, the `start_metrics_server` in `main()` starts on port 9133, while the BaseAgent `max_idle_seconds=600` stall detection uses the default port. The stall watchdog will run but no metrics port is started by BaseAgent, meaning `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` and other BaseAgent metrics are not exposed. This means ParityAuditorAgent metrics are split across the port started in `main()` and the default port.

**Fix:** Pass `metrics_port=METRICS_PORT` to the `super().__init__()` call and remove the standalone `start_metrics_server()` call from `main()`.

### WR-07: Grafana alert references nonexistent metric signal_writer_buffer_dropped_total

**File:** `production/grafana/provisioning/alerting/alert-rules.yml:93`
**Issue:** The `signals_dropped` alert rule queries `signal_writer_buffer_dropped_total`, but no such metric is defined anywhere in the codebase. The `BaseWriterAgent` defines `{agent_snake}_buffer_overflow_total` (e.g., `signal_writer_agent_buffer_overflow_total`). The alert will never fire because the metric does not exist.

**Fix:**
```yaml
# Change from:
expr: increase(signal_writer_buffer_dropped_total[5m])
# to:
expr: increase(signal_writer_agent_buffer_overflow_total[5m])
```

### WR-08: provision_dlq_topics.sh does not create all DLQ topics defined in stream_keys.py

**File:** `production/scripts/provision_dlq_topics.sh`
**Issue:** The provisioning script creates DLQ topics for bar.writer, feature.writer, signal.writer, lifecycle.writer, swarm.writer, bar.audit, signal.audit, intelligence.pipeline, signal.tracker, cross.asset, and llm.writer. However, `stream_keys.py` also defines `topic_roll_dlq()`, `topic_health_events_dlq()`, `topic_ml_orchestrator_dlq()`, and `topic_market_data_quality_dlq()` that are not provisioned. More critically, the `topic_swarm_writer_dlq()` function is defined twice in `stream_keys.py` (lines 322-324 and 393-395) with different implementations, creating a shadowing issue.

**Fix:** Add the missing DLQ topics to the provisioning script. Remove the duplicate `topic_swarm_writer_dlq` definition at line 393 (the earlier one at line 322 is in the Swarm section and is the canonical one).

## Info

### IN-01: BaseWriterAgent._do_flush silently swallows flush exceptions

**File:** `src/core/agent/base_writer.py:196`
**Issue:** When `_flush_batch()` raises an exception, `_do_flush()` calls `self.logger.exception(...)` but does not re-raise or increment any error counter. The buffer is left intact for retry, which is correct, but the exception is invisible to metrics-driven alerting. Other writer agents (e.g., `FeatureWriterAgent`) have their own error counters, but BaseWriterAgent itself does not emit a metric on flush failure.

**Fix:** Consider adding a `_flush_failures_total` counter to `BaseWriterAgent` that increments on `_do_flush()` exception, so Grafana alerts can detect persistent write failures across all writer agents.

### IN-02: BarAggregatorComputeAgent._get_consumer_lag creates a new consumer per check

**File:** `services/bar_aggregator_agent.py:435-459`
**Issue:** `_get_consumer_lag()` creates a new `AIOKafkaConsumer` on every call (every 15 seconds during health metrics update and every 60 seconds during health logging). This creates and destroys a Kafka TCP connection each time, which is expensive. The method also directly accesses `self._kafka_consumer._consumer` (private attribute) which couples it to the implementation details of `KafkaConsumerClient`.

**Fix:** Cache the lag-check consumer or use a dedicated long-lived consumer for lag queries. Consider adding a lag reporting method to `KafkaConsumerClient` itself.

### IN-03: Hardcoded database DSN defaults in FeatureWriterAgent and LLMWriterService

**File:** `services/feature_writer_agent.py:371`, `services/llm_writer_service.py:393`
**Issue:** Both services have hardcoded default DSN `"postgresql://postgres:postgres@localhost:5432/indicagent"` in their `_load_config()` methods. These are only used when `Settings()` fails, but the credentials `postgres:postgres` are embedded in source code. While not a production security risk (the defaults are overridden by `Settings`), this is a code quality concern.

**Fix:** Use `Settings().database_url` as the sole source of truth and remove hardcoded DSN defaults.

### IN-04: ParityAuditorAgent overrides stop() but BaseAgent.start() also calls stop()

**File:** `services/parity_auditor_agent.py:346-354`
**Issue:** `ParityAuditorAgent.stop()` sets `_stop_event`, closes producer and pool, then calls `super().stop()`. However, `BaseAgent.start()` already calls `stop()` in its finally block after `_teardown()`. Since `ParityAuditorAgent` does not override `_teardown()`, its cleanup code in `stop()` runs after `_teardown()` returns, which is the correct ordering. No bug here, but the pattern is unusual -- other agents put cleanup in `_teardown()` instead of overriding `stop()`.

### IN-05: CrossAssetComputeAgent backward compatibility shim CrossAssetService = CrossAssetComputeAgent

**File:** `services/cross_asset_service.py:466`
**Issue:** The alias `CrossAssetService = CrossAssetComputeAgent` preserves backward compatibility for tests. This is fine as a transitional measure, but the comment says "test compatibility" suggesting tests import the old name. Consider updating tests to use the new name and removing the alias.

### IN-06: duplicate topic_swarm_writer_dlq function definition in stream_keys.py

**File:** `src/core/stream_keys.py:322-324,393-395`
**Issue:** `topic_swarm_writer_dlq()` is defined twice -- once in the "Swarm topics" section (line 322) and once in the "DLQ topics" section (line 393). Both return the same value, so there is no functional impact (Python uses the last definition). However, this is confusing and could lead to divergence if one is updated but not the other.

**Fix:** Remove the duplicate at line 393, keeping the canonical one in the Swarm section.

---

_Reviewed: 2026-04-13T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
