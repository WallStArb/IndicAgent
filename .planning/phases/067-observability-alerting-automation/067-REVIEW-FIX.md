---
phase: 067-observability-alerting-automation
fixed_at: 2026-04-14T07:59:39Z
review_path: .planning/phases/067-observability-alerting-automation/067-REVIEW.md
iteration: 1
findings_in_scope: 10
fixed: 8
skipped: 2
status: partial
---

# Phase 067: Code Review Fix Report

**Fixed at:** 2026-04-14T07:59:39Z
**Source review:** .planning/phases/067-observability-alerting-automation/067-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 10
- Fixed: 8
- Skipped: 2

## Fixed Issues

### CR-01: BaseAgent._send_to_dlq calls producer.produce() -- method does not exist

**Files modified:** `src/core/agent/base.py`
**Commit:** 9b71fc5f
**Applied fix:** Changed `produce()` to `publish()` in two locations within `_send_to_dlq()` (lines 322 and 334). KafkaProducerClient exposes `publish()`, not `produce()`, so every DLQ routing attempt would have raised AttributeError at runtime.

### CR-02: BaseAgent._send_alert references self._settings but it may not exist

**Files modified:** `src/core/agent/base.py`
**Commit:** a4077e1d
**Applied fix:** Replaced direct `self._settings.env_name` access with safe `getattr(self, "_settings", None)` fallback, and changed `produce()` to `publish()`. Agents that do not set `self._settings` will now use empty string as env_name instead of crashing with AttributeError.

### WR-01: Metrics port collision -- LifecycleWriterAgent and SignalAuditorAgent both use :9128

**Files modified:** `services/signal_auditor_agent.py`
**Commit:** c85ee736
**Applied fix:** Changed SignalAuditorAgent metrics_port from 9128 to 9134 (port was available; verified against all existing services). Updated both the constructor call and docstring references.

### WR-02: BarAuditorAgent._detect_gaps has duplicate gap request logic on the resolved path

**Files modified:** `services/bar_auditor_agent.py`
**Commit:** f5d1d808
**Applied fix:** Removed the contradictory dedup/gap-request-append block from the `elif completeness >= 1.0` branch. When completeness reaches 100%, the code now only calls `_resolve_market_data_gap()` without also queuing a new BarGapRequest for the same gap. **Status: fixed, requires human verification** (logic bug -- confirm that removing the duplicate block preserves intended behavior).

### WR-03: BaseAgent._send_to_dlq references self._topics_consumed instead of self.topics_consumed

**Files modified:** `src/core/agent/base.py`
**Commit:** 76aa31a5
**Applied fix:** Changed `self._topics_consumed[0] if hasattr(self, "_topics_consumed") and self._topics_consumed else "unknown"` to `self.topics_consumed[0] if self.topics_consumed else "unknown"`. The property `topics_consumed` is the correct public interface; the private attribute `_topics_consumed` is never set.

### WR-06: ParityAuditorAgent.start_metrics_server called before super().__init__ completes metrics setup

**Files modified:** `services/parity_auditor_agent.py`
**Commit:** d9b6c00a
**Applied fix:** Added `metrics_port=METRICS_PORT` (9133) to the `super().__init__()` call and removed the standalone `start_metrics_server()` call from `main()`. Also removed the now-unused `start_metrics_server` import. BaseAgent.start() will now handle metrics server startup consistently.

### WR-07: Grafana alert references nonexistent metric signal_writer_buffer_dropped_total

**Files modified:** `production/grafana/provisioning/alerting/alert-rules.yml`
**Commit:** 42963ddf
**Applied fix:** Changed metric name from `signal_writer_buffer_dropped_total` to `signal_writer_agent_buffer_overflow_total` to match the actual metric defined in `BaseWriterAgent` (pattern: `{agent_snake}_buffer_overflow_total`).

### WR-08: provision_dlq_topics.sh does not create all DLQ topics defined in stream_keys.py

**Files modified:** `production/scripts/provision_dlq_topics.sh`, `src/core/stream_keys.py`
**Commit:** 0ba601fe
**Applied fix:** Added 6 missing DLQ topics to the provisioning script (intelligence.signal.dlq, swarm.orchestrator.dlq, market.events.roll.dlq, intelligence.service_auditor.journal.dlq, ml.orchestrator.dlq, gap_fill.dlq). Removed the duplicate `topic_swarm_writer_dlq` function definition at line 392 of stream_keys.py, keeping the canonical one in the Swarm section at line 322.

## Skipped Issues

### WR-04: BarAuditorAgent metrics label uses "agent" instead of "agent_id"

**File:** `services/bar_auditor_agent.py:62-85`
**Reason:** Advisory/non-blocking per reviewer's own assessment. These are independent auditor-specific metrics (not PERSISTENCE_BATCH_LATENCY or PERSISTENCE_CONSUMER_LAG), and the CLAUDE.md `agent_id` convention specifically applies to those persistence metrics. Migrating label names is a separate task.
**Original issue:** BarAuditorAgent uses label key "agent" on module-level metrics while project convention uses "agent_id" for persistence metrics.

### WR-05: LLMWriterService does not inherit from BaseAgent -- no crash metrics or stall detection

**File:** `services/llm_writer_service.py`
**Reason:** Substantial refactoring needed -- migrating LLMWriterService to extend BaseWriterAgent or BaseAgent requires significant code restructuring, not a targeted fix. The service works as-is; it just lacks Phase 067 observability coverage. This is a dedicated task.
**Original issue:** LLMWriterService manages its own signal handlers, running flag, and shutdown logic without inheriting from BaseAgent, missing crash metrics, stall detection, and standard lifecycle.

---

_Fixed: 2026-04-14T07:59:39Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
