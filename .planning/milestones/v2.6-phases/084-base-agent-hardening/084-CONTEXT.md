# Phase 84: Base Agent Hardening - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Harden `BaseAgent`, `BaseWriterAgent`, and `BaseAIAgent` so malformed payloads, swallowed exceptions,
and silent dead code are structurally impossible across all subclasses. Every error at every layer
must be quantified (OTel counter or histogram), not just logged. This phase delivers the base class
contracts that Phase 085 (Persistence Writer Migration) will apply to the full writer fleet.

Out of scope: per-plugin performance optimization (Phase 089), signal transform architecture (Phase 087),
per-symbol plugin histogram granularity (Phase 089 using OBS-01 data).

</domain>

<decisions>
## Implementation Decisions

### _flush_batch() Error Contract (INFRA-02)
- **D-01:** `_do_flush()` re-raises `_flush_batch()` exceptions by default — no swallowing.
  Buffer stays intact so systemd restart recovers cleanly. No DLQ routing for flush failures.
  The `_flush_errors_total` counter already exists; the exception propagates after incrementing it.

### Pydantic Payload Validation (INFRA-01)
- **D-02:** Each `BaseWriterAgent` subclass declares `payload_model: ClassVar[type[BaseModel]]`.
  The base validates the raw Kafka dict with `model_validate()`, catches `ValidationError`, and
  routes to DLQ. `_parse_payload()` receives the already-validated Pydantic object (not a raw dict).
  If a subclass omits `payload_model`, the base falls back to the current unvalidated behavior
  (backward compatibility for the migration phase).

### _setup_with_retry() Configurability (INFRA-03)
- **D-03:** Class attributes on `BaseAgent` replace hardcoded values:
  `SETUP_RETRY_ATTEMPTS: int = 3` and `SETUP_RETRY_BACKOFF_S: float = 2.0`.
  Subclasses that need different retry budgets override these class attrs.

### Circuit Breaker Opt-in (INFRA-05)
- **D-04:** `circuit_breaker: bool = False` class attribute on `BaseAgent`.
  When `True`, `start()` calls `_setup_with_retry()` instead of `_setup()` directly,
  AND adds an open-gate: if setup fails all retries, the circuit opens and blocks future
  restart attempts until reset. Single class attr enables both retry and open-gate.

### Dead Code Disposition (INFRA-06)
- **D-05:** Delete `_graduation_loop()`, `has_graduation`, and all TODO comments from
  `BaseGroupService`. Shadow governance runs through the `shadow_registry` DB table
  (Phase 75 design). The empty loop is never activated (`has_graduation` is never `True`
  in any production service). Renaissance-quality codebase = no placeholder stubs.
- **D-06:** Wire `LineageRecorder` (`src/core/ai/lineage.py`) into `BaseGroupService`.
  The class is complete (batched Kafka publish, start/stop, flush loop). `BaseGroupService._setup()`
  instantiates `LineageRecorder`; `BaseAIAgent._on_error()` publishes `agent_prediction` events
  via it. Satisfies D-48 design intent. Must have tests.

### BaseAIAgent._on_error() (INFRA-04)
- **D-07:** `_on_error()` emits an OTel counter increment: `ai_agent_errors_total` with
  `{agent_id, error_type}` labels. The `pass` body is replaced. Counter name chosen to be
  additive to existing `AI_AGENT_INVOCATIONS_TOTAL` pattern.

### Additional OTel Signals (OBS-01 + Renaissance standard)
- **D-08:** `PLUGIN_DURATION_MS` histogram already exists with `{plugin_name, tier}` labels
  in `intelligence_pipeline_agent.py`. OBS-01 is satisfied by adding a Grafana panel showing
  p50/p95 ranking — no code change to the pipeline metric itself.
- **D-09:** Four additional OTel signals to add to base agents (what a senior quant architect demands):
  1. `agent_dlq_total` counter with `{agent_id}` — per-agent DLQ event count (critical quality signal)
  2. `agent_last_processed_timestamp` gauge with `{agent}` — machine-readable stall detection
     (already tracked as `_last_message_ts` monotonic but not as OTel wall-clock gauge)
  3. `agent_setup_retries_total` counter with `{agent}` — setup instability signal
  4. `agent_circuit_breaker_state` gauge with `{agent}` — 0=closed, 1=half-open, 2=open

### Claude's Discretion
- Grafana panel layout for the OBS-01 plugin latency histogram (p50/p95 ranking by plugin_name)
- Circuit breaker reset logic implementation detail (timer-based vs. manual reset)
- `LineageRecorder` flush interval and batch size defaults (current: 2.0s, 50 records)
- Test approach for circuit breaker open-gate behavior

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Base Agent Infrastructure
- `src/core/agent/base.py` — BaseAgent lifecycle, _setup_with_retry(), _send_to_dlq(), OTel setup
- `src/core/agent/base_writer.py` — BaseWriterAgent buffer/flush/commit pattern, _do_flush()
- `src/core/ai/base_agent.py` — BaseAIAgent, compute(), _on_error(), _llm_generate()
- `src/core/ai/base_group_service.py` — BaseGroupService, graduation_loop (to be deleted), has_graduation

### Dead Code to Resolve
- `src/core/ai/lineage.py` — LineageRecorder implementation (to be wired in)
- `src/core/ai/base_group_service.py` — _graduation_loop() + has_graduation (to be deleted)

### OTel and Metrics
- `src/observability/metrics.py` — PLUGIN_DURATION_MS definition, existing OTel metric registry
- `src/observability/spans.py` — span/attribute helpers (ATTR_* constants)
- `services/intelligence_pipeline_agent.py` — PLUGIN_DURATION_MS recording at line 1077 (reference for OBS-01 Grafana panel)

### Requirements
- `.planning/REQUIREMENTS.md` — INFRA-01 through INFRA-06, OBS-01 (full acceptance criteria)
- `.planning/ROADMAP.md` — Phase 084 success criteria (7 numbered items)

### Patterns to Follow
- `src/core/plugin_circuit_breaker.py` — existing circuit breaker state machine (pattern reference for BaseAgent CB)
- `src/core/schemas/dlq_payload.py` — DLQPayload schema for DLQ routing

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BaseAgent._send_to_dlq()` — already implemented, routes to DLQ topic if `_dlq_topic()` returns non-None.
  The new Pydantic validation layer in `BaseWriterAgent` calls this on `ValidationError`.
- `BaseAgent._setup_with_retry()` — exists at line 446 of `base.py`, just needs class attr configurability.
- `_flush_errors_total` counter — already incremented in `_do_flush()`; just remove the exception swallow.
- `PLUGIN_DURATION_MS` histogram — already records `{plugin_name, tier}` at line 1077 of
  `intelligence_pipeline_agent.py`. OBS-01 needs only a Grafana panel.
- `LineageRecorder` — fully implemented in `src/core/ai/lineage.py`. Has `start()`, `stop()`, `record()`,
  `flush()`. Ready to instantiate in `BaseGroupService._setup()`.

### Established Patterns
- OTel instrument creation: use `_bw_meter.create_counter()` / `create_histogram()` / `create_up_down_counter()`
  with module-level caching (see `_get_or_create_gauge` pattern in `base_writer.py`).
- Class attribute config: `BATCH_SIZE: int = 100`, `FLUSH_INTERVAL_SECS: float = 5.0` style already used
  in `BaseWriterAgent` — apply same pattern for retry/CB config.
- `ClassVar` for type-level class attributes: use `from typing import ClassVar`.

### Integration Points
- `_do_flush()` in `base_writer.py` — change lines 281-285 (the except block) to re-raise after metrics.
- `start()` in `base.py` line 190 — branch on `circuit_breaker` to call `_setup_with_retry()` vs `_setup()`.
- `BaseGroupService._setup()` — add `LineageRecorder` instantiation and `self._lineage.start()`.
- `BaseGroupService._teardown()` — add `await self._lineage.stop()`.
- `BaseAIAgent._on_error()` line 266 — replace `pass` with OTel counter increment.

</code_context>

<specifics>
## Specific Ideas

- "What would Renaissance do?" framing: every error at every layer is quantified, not just logged.
  Silent failures are structurally impossible. DLQ events are monitored flows, not black holes.
- The `circuit_breaker` class attribute should feel like a single switch: `circuit_breaker = True`
  in the subclass definition opts you in to retry + open-gate + CB state gauge — no additional wiring.
- INFRA-06 dead code: "Renaissance-quality codebase = no placeholder stubs." Delete the graduation
  loop entirely; it was the wrong design (Phase 75 moved to shadow_registry).
- OBS-01 Grafana panel should show p95 plugin latency ranking — "which plugin is the bottleneck"
  is the core question, so sort by p95 descending with plugin_name as the label.

</specifics>

<deferred>
## Deferred Ideas

- **Per-symbol plugin histogram granularity** (`{plugin_name, tier, symbol}`) — 18K series vs
  current 792. The data from OBS-01 (Phase 084) drives which plugins to investigate; per-symbol
  drill-down belongs in Phase 089 after OBS-01 data accumulates.
- **Using OBS-01 data to improve intelligence speed and latency** — Phase 089 scope. OBS-01 in
  Phase 084 is instrumentation only; optimization based on the data is Phase 089.
- **Plugin error budget metric** (% of bars processed cleanly vs. with plugin errors) — useful but
  can be derived from existing `PLUGIN_ERRORS_TOTAL` in Grafana without new instrumentation.

</deferred>

---

*Phase: 084-base-agent-hardening*
*Context gathered: 2026-05-16*
