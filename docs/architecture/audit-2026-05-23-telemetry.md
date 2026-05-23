# Telemetry & Observability Audit — 2026-05-23

**Scope:** `src/observability/`, `src/core/agent/`, all `services/*.py`
**Framework:** OTel SDK (prometheus_client fully removed as of Phase 83 — confirmed clean)
**Framing:** Renaissance Technologies lens — every unobservable path is a black box that cannot be systematically improved

---

## Finding T-1: All 37 Service Files Have Zero OTel Span Coverage

**Severity:** CRITICAL
**Category:** Feedback Loop Gap
**Files:** `services/intelligence_pipeline_agent.py`, `services/bar_aggregator_agent.py`, `services/signal_tracker_compute_agent.py`, `services/signal_writer_agent.py`, `services/feature_writer_agent.py`, and all 32 remaining `services/*.py` files
**Description:**
No service file in `services/` contains any `start_as_current_span` or `observed_span` call. Span instrumentation exists only in base classes (`src/core/agent/base_writer.py:268` — `writer.flush` span, `src/core/ai/base_agent.py:97` — agent compute span) and three `src/` modules (`base_group_service.py`, `chain.py`, `base_provider_agent.py`). The entire critical path — bar ingestion, I1-I7 plugin execution, signal processing, DB persistence — has no distributed traces. You cannot answer "how long did this specific bar take to traverse the full pipeline?" or "where did this signal's processing chain break?" without log-scraping.

The `observed_span()` docstring in `src/observability/spans.py:23` says "For use only in the two pipeline span sites in `intelligence_pipeline_agent.py`" — but those two sites do not exist. The docstring describes a design intent that was never executed.

**Fix:** Add `observed_span("pipeline.process_bar")` wrapping `_process_bar_inner()` in `services/intelligence_pipeline_agent.py:473` as the minimum viable entry point.

---

## Finding T-2: Three Latency Metrics Use `up_down_counter` Instead of `histogram`

**Severity:** CRITICAL
**Category:** Alpha Leakage (no percentile visibility on the hottest path)
**Files:** `services/intelligence_pipeline_agent.py:180-191`
**Description:**
`intelligence_pipeline_i1_latency_ms`, `intelligence_pipeline_i7_latency_ms`, and `intelligence_pipeline_pipeline_latency_ms` are all created via `gauge()` which wraps `_meter.create_up_down_counter()` (confirmed at `src/observability/metrics.py:27-29`). An `up_down_counter` is a cumulative sum — it cannot produce p50/p95/p99 percentiles. Latency data emitted via `.add()` disappears into a scalar that grows forever. You can never alert on "p95 I7 latency > 50ms" from this metric. The only actionable latency visibility for the I1-I7 pipeline is the `BarIntelligenceRecord.pipeline_latency_ms` field written to Kafka — not the OTel exporter.

Additionally, `intelligence_pipeline_bars_processed_total` and `intelligence_pipeline_pipeline_errors_total` are also `up_down_counter` via `gauge()` — semantically these should be monotonic `counter` types.

**Fix:** Replace all four `gauge()` calls in `intelligence_pipeline_agent.py:176-193` with `_meter.create_histogram()` for latency metrics and `_meter.create_counter()` for count metrics.

---

## Finding T-3: `_i1_latency_ms` and `_pipeline_latency` Are Dead Instruments — Defined But Never Called

**Severity:** HIGH
**Category:** Feedback Loop Gap
**Files:** `services/intelligence_pipeline_agent.py:180-191`
**Description:**
`self._i1_latency_ms` is defined at line 180 but there is no call to `self._i1_latency_ms.add(...)` anywhere in the codebase. The I1 tier has no latency measurement at all. Similarly `self._pipeline_latency` is defined at line 190 but never called — the actual `pipeline_latency_ms` value goes into `BarIntelligenceRecord` at line 596 (written to Kafka) but is never recorded to the OTel metric. This means the Grafana dashboard for `intelligence_pipeline_pipeline_latency_ms` shows a flat zero line permanently.

**Fix:** Add `self._i1_latency_ms.record(i1_duration_ms)` in `FeaturePipelineExecutor.run()` after I1 execution, and add `self._pipeline_latency.record((time.perf_counter() - t0) * 1000)` in `_process_bar_inner()` at `services/intelligence_pipeline_agent.py:541`.

---

## Finding T-4: Per-Stage Latency (I2-I6) Is Completely Absent

**Severity:** HIGH
**Category:** Alpha Leakage
**Files:** `src/intelligence/pipeline/feature_pipeline_executor.py`, `src/intelligence/pipeline/executor.py`
**Description:**
The pipeline measures only aggregate I1 (dead, see T-3) and I7 latency. Stages I2, I3, I4, I5, SMC, and I6 — 6 sequential tiers containing 68 plugins — have no per-stage aggregate latency metrics. `feature_pipeline_executor.py` has no metric instrumentation at all (confirmed: `metric=False` in coverage scan). Per-plugin latency is tracked via `PLUGIN_DURATION_MS` (histogram, correct type, in `PluginObserver`) but there is no roll-up per tier. If a new I4 plugin causes a 30ms regression, the only signal is an increase in `intelligence_pipeline_plugin_duration_ms{tier="i4"}` — there is no `intelligence_pipeline_tier_latency_ms{tier="i4"}` to alert on directly.

**Fix:** Add six histogram instruments `tier_latency_ms{tier=i2..i6,smc}` in `FeaturePipelineExecutor` and record at each `run_tier()` call boundary.

---

## Finding T-5: `SHADOW_WIN_RATE`, `SHADOW_N_RESOLVED`, `SHADOW_EV_R`, `SHADOW_DAYS_TO_GATE`, `SHADOW_EV_CI_LOWER` Use `up_down_counter` with Absolute Values

**Severity:** HIGH
**Category:** Feedback Loop Gap
**Files:** `src/observability/metrics.py:224-243`, `services/shadow_auditor_agent.py:170-194`
**Description:**
All five shadow metrics are defined as `create_up_down_counter`. In `shadow_auditor_agent.py`, each audit cycle calls `.add(absolute_value, {"plugin": name})` — for example `SHADOW_N_RESOLVED.add(n, {"plugin": name})` where `n` is the current total resolved count. Because `up_down_counter` is cumulative, each audit cycle *adds* the current absolute value to the running total. After 10 audit cycles for a plugin with `n=50`, the metric reads `500` not `50`. The shadow governance dashboard is permanently incorrect. This is the OTel delta/cumulative anti-pattern that CLAUDE.md documents as a known previous bug.

**Fix:** Change all five to `create_gauge` (point-in-time) and call `.set(value, attrs)` instead of `.add(value, attrs)` in `shadow_auditor_agent.py`.

---

## Finding T-6: `BarWriterAgent` Custom `_run()` Never Calls `_record_message_consumed()`

**Severity:** HIGH
**Category:** Feedback Loop Gap
**Files:** `services/bar_writer_agent.py:241-270`
**Description:**
`BarWriterAgent` overrides `_run()` with a custom loop at line 241. This loop never calls `self._record_message_consumed()`. The base class `BaseAgent._record_message_consumed()` at `src/core/agent/base.py:311` is the sole updater of `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS`. As a result, `bar_writer_agent` never sets this gauge — `service_auditor_agent._fetch_stalled_agents()` at `services/service_auditor_agent.py:647` will never detect a stall in `indicagent-bar-writer`. The stall watchdog (`_stall_watchdog` in `base.py:325`) is also blind because `self._last_message_ts` (monotonic) is only set inside `_record_message_consumed()`. If bar-writer stalls (DB pool exhausted, Kafka consumer rebalancing), it will not self-terminate via `sys.exit(1)` and will not be detected by the service auditor.

**Fix:** Add `self._record_message_consumed()` inside the `async for` loop in `BarWriterAgent._run()` at `services/bar_writer_agent.py:254` (after the `_contract_updates_topic` routing check).

---

## Finding T-7: `LLMWriterService` Stall Watchdog Uses an Attribute That Is Never Set

**Severity:** HIGH
**Category:** Feedback Loop Gap
**Files:** `services/llm_writer_service.py:937-954`, `services/llm_writer_service.py:965-981`
**Description:**
`LLMWriterService` implements its own `_stall_watchdog()` at line 937 that reads `self._last_msg_ts`. However, searching the entire file reveals `_last_msg_ts` is never assigned. The `_process_loop()` at line 965 consumes Kafka messages but calls neither `self._record_message_consumed()` (which would set `self._last_message_ts` on the BaseAgent) nor any code that sets `self._last_msg_ts`. The stall watchdog will never advance past the `if self._last_msg_ts is None: continue` guard — it is permanently in startup-grace mode and will never fire. `indicagent-llm-writer` silently processes zero messages with no stall detection.

**Fix:** Replace `self._last_msg_ts` with `self._last_message_ts` (the BaseAgent attribute) and call `self._record_message_consumed()` inside `_process_loop()` after each message is consumed.

---

## Finding T-8: `"agent"` vs `"agent_id"` Label Key Inconsistency Across 83 Metric Emission Sites

**Severity:** HIGH
**Category:** Feedback Loop Gap
**Files:** `src/core/agent/base.py:121,140-141`, `services/bar_writer_agent.py:117-120`, `services/feature_writer_agent.py:276`, `services/signal_writer_agent.py:78`, `services/lifecycle_writer_agent.py:97`, `services/graduation_writer_agent.py:75`
**Description:**
The codebase uses two different label keys for identifying the agent in metrics, causing split cardinality that makes cross-service dashboards impossible to build without per-metric label mapping:

- `BaseAgent` uses `{"agent": name}` for `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` (`_last_msg_ts_attrs` at `base.py:120`) and `AGENT_CRASH_TOTAL` (`_crash_attrs` at `base.py:136`)
- `BaseWriterAgent._report_consumer_lag()` uses `{"agent_id": self.name}` for `PERSISTENCE_CONSUMER_LAG` (`base_writer.py:380`)
- Writer agents (`feature_writer`, `signal_writer`, `lifecycle_writer`, `graduation_writer`, `llm_writer`) use `{"agent_id": ...}` for `PERSISTENCE_BATCH_LATENCY`
- `bar_writer_agent` uses `{"agent": self.name}` for all its own metrics (`bar_writer_agent.py:117-120`)
- `MacroComputeAgent` emits `AGENT_CRASH_TOTAL` with `{"agent": self.agent_id}` (value `"macro_compute_agent"`) while BaseAgent would emit it with `{"agent": "macrocomputeagent"}` (lowercase, no underscore) — causing double-counting under different label values
- `service_auditor_agent._fetch_prometheus_lag()` queries `persistence_consumer_lag` with `r["metric"].get("agent_id", "")` — correct for `BaseWriterAgent` subclasses but misses any agent using `"agent"` key

**Fix:** Standardize on `"agent_id"` across all metric emissions. Update `base.py:120` to `{"agent_id": name}` and `base.py:136` to `{"agent_id": ...}`, then update all downstream Grafana queries.

---

## Finding T-9: `DB_POOL_SIZE` and `DB_POOL_IDLE` Are Written Once at Pool Creation and Never Updated

**Severity:** MEDIUM
**Category:** Feedback Loop Gap
**Files:** `src/core/database_manager.py:28-29`, `src/observability/metrics.py:639-648`
**Description:**
`DB_POOL_SIZE` and `DB_POOL_IDLE` are `up_down_counter` instruments. They are written exactly once in `create_pool()` at startup with the initial pool size values. asyncpg pools are dynamic — they grow and shrink between `min_size` and `max_size` under load. After the initial write, these metrics show the pool state at startup forever. Under heavy load when the pool is fully saturated (all connections in use, zero idle), the gauge still shows the initial idle count. There is no alerting signal for "pool exhausted."

**Fix:** Add a periodic coroutine in `DatabaseManager` that calls `DB_POOL_SIZE.add(delta)` and `DB_POOL_IDLE.add(delta)` every 30 seconds based on actual pool state change, or switch to `create_gauge` with `.set()`.

---

## Finding T-10: `DLQDrainAgent` Has Zero Metrics — DLQ Volume Is Invisible

**Severity:** MEDIUM
**Category:** Information Destruction
**Files:** `services/dlq_drain_agent.py`
**Description:**
`DLQDrainAgent` drains all 15 DLQ topics into `dlq_events` but emits no metrics at all. There is no counter for messages drained per topic, no histogram for DB insert latency, and no gauge for queue depth. The only signal is a structured log per drained message. `DLQ_MESSAGES_TOTAL` (defined in `metrics.py:326`) counts messages *routed* to the DLQ, but there is no metric for messages *consumed* from it. You cannot alert on "DLQ processing falling behind" or detect if a single DLQ topic is producing a burst of errors from a specific agent.

**Fix:** Add `dlq_drain_messages_total{dlq_topic, agent, error_type}` counter and `dlq_drain_db_latency_seconds` histogram to `DLQDrainAgent._drain_message()`.

---

## Finding T-11: `SignalMetricsWriterAgent` Has Zero Custom Metrics Despite Writing to `setup_performance`

**Severity:** MEDIUM
**Category:** Feedback Loop Gap
**Files:** `services/signal_metrics_writer_agent.py:226-295`
**Description:**
`SignalMetricsWriterAgent` writes to `signal_metrics`, `signal_metrics_ic`, `signal_metrics_dq_failures`, and `setup_performance` — the last being the source of `perf_multiplier` weights that drive signal ranking in the I7 aggregator. It has zero custom metrics. The `BaseWriterAgent` base class provides `parse_failures_total` and `flush_errors_total` but there is no metric for which event types are being processed, how many `setup_performance` upserts succeed per cycle, or whether the `metrics_computed` vs `ic_computed` split is healthy. A silent failure in `_handle_metrics_computed()` degrades signal quality without any observable signal.

**Fix:** Add a counter `signal_metrics_writer_events_total{event_type}` inside `_flush_batch()` to track per-event-type throughput.

---

## Finding T-12: `PLUGIN_FALLBACK_TOTAL` (Deprecated) Still Dual-Emitted, Grafana Dashboard Dependency Not Resolved

**Severity:** MEDIUM
**Category:** Feedback Loop Gap
**Files:** `src/observability/metrics.py:43-50`, `src/observability/plugin_observer.py:66-70`
**Description:**
`PLUGIN_FALLBACK_TOTAL` (old name: `plugin_fallbacks_total`) is marked `[DEPRECATED]` in its description at `metrics.py:45` with a comment "Remove old name in follow-on phase." It is still dual-emitted in `plugin_observer.py:69` — every incremental fallback fires both the deprecated and canonical counter. The comment says the Grafana dashboard `production/grafana/dashboards/pipeline-health.json` references the old name. This creates indefinite maintenance drag: the old metric is registered in the OTel exporter, consuming resources, and the migration is blocked on a Grafana dashboard update.

Additionally, `plugin_observer.py:67` calls `self._fallback_counter.add(0, attrs)` when the incremental path is taken — emitting a zero increment to a counter on every successful incremental execution. This is semantically wrong and wastes exporter bandwidth on the hot path (every successfully-incremental plugin call).

**Fix:** Update `production/grafana/dashboards/pipeline-health.json` to reference `intelligence_pipeline_plugin_fallback_total`, then remove `PLUGIN_FALLBACK_TOTAL` and the `add(0, attrs)` no-op from `plugin_observer.py`.

---

## Finding T-13: `otel.py` Silently Suppresses All OTel Initialization Errors

**Severity:** MEDIUM
**Category:** Feedback Loop Gap
**Files:** `src/observability/otel.py:49-50`, `src/observability/otel.py:63-64`
**Description:**
`init_otel_providers()` catches all exceptions during both `MeterProvider` and `TracerProvider` initialization with bare `except Exception: pass`. When the OTel collector endpoint is unreachable, misconfigured, or when a TLS certificate is invalid, the failure is completely silent — no log, no counter, no startup warning. Agents proceed with no-op providers, emitting metrics that are silently discarded. This means a misconfigured `OTEL_EXPORTER_OTLP_ENDPOINT` causes an entire production deployment to run dark with no indication in logs or metrics.

**Fix:** Replace `pass` with `logger.warning("otel.init_failed", error=str(exc), endpoint=endpoint)` in both except blocks.

---

## Finding T-14: `FeaturePipelineExecutor` Has No Metrics Despite Being the I1-I6 Orchestration Layer

**Severity:** MEDIUM
**Category:** Feedback Loop Gap
**Files:** `src/intelligence/pipeline/feature_pipeline_executor.py`
**Description:**
`FeaturePipelineExecutor.run()` is the 6th DAG node that executes all I1-I6 tiers and constructs `IntelligenceEvent`. It has no OTel instrumentation at all — no span, no histogram, no counter. The module uses `perf_counter` only for the `pipeline_latency_ms` field in the returned `FeaturePipelineResult` (line 252 sets `pipeline_latency_ms=0.0` as a placeholder). Key failure modes that are currently invisible: `ValidationError` on `IntelligenceEvent` construction (raises, propagates to orchestrator error counter but with no tier attribution), and I6 confluence tier returning `None` for all signals (silent data loss).

**Fix:** Add `observed_span("feature_pipeline.run")` wrapping the execution, and a counter `feature_pipeline_event_null_total{symbol, tf}` when `fp_result.event is None`.

---

## Finding T-15: `SwarmLedgerWriterAgent` DB Retry Exhaustion Not Counted as Error

**Severity:** MEDIUM
**Category:** Information Destruction
**Files:** `services/swarm_ledger_writer_agent.py:196-256`
**Description:**
`_apply_projection()` retries the signal_ai_enrichment UPSERT up to 5 times with exponential backoff when the `signal_ledger` row is not yet visible (race condition with `signal_writer`). When all 5 retries are exhausted, it calls `SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.add(1, {"status": "miss"})` and logs a warning. However, "miss" status conflates two different outcomes: (1) UUID validation failure (instant non-retry error at line 247) and (2) retry exhaustion (signal truly lost). There is no dedicated counter for retry-exhausted cases vs. malformed UUIDs. When the signal_writer is slow under load, retry exhaustions appear as "miss" alongside the UUID errors — you cannot distinguish a systemic race condition from malformed data.

**Fix:** Add a separate counter `swarm_ledger_retry_exhausted_total` for the retry-exhaustion path at line 251.

---

## Finding T-16: No Span Coverage on the Critical `_process_bar_inner()` I7→SignalProcessor→4-way Routing Path

**Severity:** HIGH
**Category:** Alpha Leakage
**Files:** `services/intelligence_pipeline_agent.py:473-541`
**Description:**
`_process_bar_inner()` is the innermost DAG execution unit — it runs on every bar for every (symbol, tf) combination. It contains the most latency-sensitive code path in the system: `FeaturePipelineExecutor.run()`, `PluginExecutor.run_i7_complete()`, `SignalProcessor.process()`, and 4-way Kafka routing. There is no span wrapping this function. Without a span, distributed traces from bar arrival (in `_process_loop`) to Kafka signal publication are not connected. The worker pool runs `_process_bar_inner` via `PerKeyWorkerManager` — concurrent executions for different (symbol, tf) pairs are indistinguishable in logs.

**Fix:** Wrap `_process_bar_inner()` body with `async with observed_span("pipeline.process_bar_inner", symbol=bar.symbol, tf=bar.tf):`.

---

## Finding T-17: `ML_TRAINING_SECONDS` Historgram Records Only on Success, Not on Error

**Severity:** LOW
**Category:** Feedback Loop Gap
**Files:** `src/intelligence/services/ml_training_compute_agent.py:108-121`
**Description:**
`ML_TRAINING_SECONDS.record()` is called in the `finally` block at line 121, so it fires on both success and exception. However, when `_train_all_segments()` raises, the exception is caught at line 117-118, logged, and execution returns early at line 119. `ML_TRAINING_SECONDS` then records the time at line 121. This is actually correct behavior. However, there is no label on the histogram to distinguish successful runs from errored ones — a failed run that took 2s and a successful run that took 2s are identical data points in the histogram.

**Fix:** Change to `ML_TRAINING_SECONDS.record(elapsed, {"status": "success" if not errored else "error"})` with a local flag.

---

## Summary — All Findings Ranked by Severity

| # | Title | Severity | Category |
|---|-------|----------|----------|
| T-1 | All 37 services have zero OTel span coverage | CRITICAL | Feedback Loop Gap |
| T-2 | Three latency metrics use `up_down_counter` instead of `histogram` | CRITICAL | Alpha Leakage |
| T-3 | `_i1_latency_ms` and `_pipeline_latency` are dead instruments never called | HIGH | Feedback Loop Gap |
| T-4 | Per-stage latency (I2-I6) is completely absent | HIGH | Alpha Leakage |
| T-5 | Shadow metrics use `up_down_counter` with absolute values — dashboard permanently wrong | HIGH | Feedback Loop Gap |
| T-6 | `BarWriterAgent` custom `_run()` never calls `_record_message_consumed()` | HIGH | Feedback Loop Gap |
| T-7 | `LLMWriterService` stall watchdog reads an attribute that is never set | HIGH | Feedback Loop Gap |
| T-8 | `"agent"` vs `"agent_id"` label key inconsistency across 83 emission sites | HIGH | Feedback Loop Gap |
| T-16 | No span on `_process_bar_inner()` — hottest path in system | HIGH | Alpha Leakage |
| T-9 | `DB_POOL_SIZE`/`DB_POOL_IDLE` written once at startup and never updated | MEDIUM | Feedback Loop Gap |
| T-10 | `DLQDrainAgent` has zero metrics — DLQ volume invisible | MEDIUM | Information Destruction |
| T-11 | `SignalMetricsWriterAgent` has zero custom metrics | MEDIUM | Feedback Loop Gap |
| T-12 | `PLUGIN_FALLBACK_TOTAL` deprecated counter still dual-emitted with `add(0)` no-op | MEDIUM | Feedback Loop Gap |
| T-13 | `otel.py` silently suppresses all OTel initialization errors | MEDIUM | Feedback Loop Gap |
| T-14 | `FeaturePipelineExecutor` has no metrics despite being I1-I6 orchestration layer | MEDIUM | Feedback Loop Gap |
| T-15 | `SwarmLedgerWriterAgent` retry exhaustion conflated with UUID errors in "miss" counter | MEDIUM | Information Destruction |
| T-17 | `ML_TRAINING_SECONDS` histogram has no status label | LOW | Feedback Loop Gap |

### Confirmed Clean

- **No `prometheus_client` imports** — Phase 83 removal is complete and verified across all `services/` and `src/` files.
- **`agent_last_message_timestamp_seconds` label key is `"agent"`** — correctly documented in `service_auditor_agent.py:644` and consistent with `base.py:120`.
- **`BaseWriterAgent._do_flush()` span** — `writer.flush` span correctly instruments all flush operations via `self.tracer.start_as_current_span` at `base_writer.py:268` with `StatusCode.ERROR` on exception.
- **`SIGNAL_REPLAY_UNRESOLVED_GAUGE` delta pattern** — `signal_replay_auditor_agent.py:457` correctly computes `delta = cnt - self._last_unresolved_count` and calls `.add(float(delta))` — the previous OTel delta bug is fixed here.
- **`PluginObserver`** — `PLUGIN_DURATION_MS` is correctly a histogram with `{plugin_name, tier}` labels. Per-plugin latency visibility is good.
- **`LLM_CALL_DURATION` and `LLM_TOKENS_USED`** — both are used via `record_llm_call()` helper in `src/core/llm/chain.py`.
- **`LANGGRAPH_WORKFLOW_*` metrics** — used via `record_langgraph_workflow()` in `src/core/plugin_circuit_breaker.py`.
