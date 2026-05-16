# Milestone v2.6 Requirements — Foundation Hardening & Signal Transform

**Milestone:** v2.6 — Foundation Hardening & Signal Transform
**Status:** Active
**Created:** 2026-05-16
**Previous milestone:** v2.5 (archived, Phases 69-83)

---

## Active Requirements

### INFRA — Base Agent Hardening

- [ ] **INFRA-01**: Developer can subclass BaseWriterAgent and declare a Pydantic payload model; the base validates each message and auto-DLQs malformed payloads without any per-writer boilerplate
- [ ] **INFRA-02**: BaseWriterAgent._flush_batch() contract enforces raise-or-DLQ on error; swallowing exceptions is no longer possible by default
- [ ] **INFRA-03**: BaseAgent._setup_with_retry() provides configurable retry logic that eliminates the 3x duplicated retry scaffolding across current agent subclasses
- [ ] **INFRA-04**: BaseAIAgent._on_error() emits an OTel counter on every agent error (call site exists; body is currently `pass`)
- [ ] **INFRA-05**: Developer can opt any BaseAgent subclass into circuit-breaker protection via a single class attribute (no per-agent wiring)
- [ ] **INFRA-06**: Dead graduation loop and LineageRecorder are either fully wired and tested or deleted; no silent dead code remains in base classes

### PERSIST — Persistence Writer Migration

- [ ] **PERSIST-01**: lineage_writer_agent adopts BaseWriterAgent contracts; all messages either persist or land in DLQ; silent data loss is eliminated
- [ ] **PERSIST-02**: feature_snapshot_writer_agent replaces clear-on-error with bounded retry via the new base contract
- [ ] **PERSIST-03**: llm_writer_service re-raises outcome errors instead of swallowing them; failures are visible in logs and metrics
- [ ] **PERSIST-04**: signal_metrics_writer_agent writes in batches rather than per-record
- [ ] **PERSIST-05**: All positional-tuple writers migrated to named parameter style (contract_metadata_writer_agent is the reference template)

### PIPE — Pipeline Hardening

- [ ] **PIPE-01**: PluginCircuitBreaker is wired per-plugin in the intelligence pipeline; a breached plugin opens the breaker and is skipped rather than crashing the bar
- [ ] **PIPE-02**: validate_signal() is called at the I7 output boundary in SignalWriterAgent; invalid signal payloads are DLQ'd before persisting
- [ ] **PIPE-03**: Checkpoint write failure raises an exception; errors are not swallowed silently
- [ ] **PIPE-04**: Output queue uses block/retry instead of put_nowait; a full queue no longer silently drops bars

### SIGXFM — Signal Transform Architecture Phases 2-4

- [ ] **SIGXFM-01**: Signal transform Phase 2 implemented (graduation from dual-write to unified schema); gated on ~May 25 data accumulation
- [ ] **SIGXFM-02**: Signal transform Phase 3 implemented
- [ ] **SIGXFM-03**: Signal transform Phase 4 implemented; full transform pipeline active and validated

### ARCH — God Class Decomposition

- [ ] **ARCH-01**: PluginExecutor class extracted from IntelligencePipelineComputeAgent; owns tiers, thread pool, and plugin cache
- [ ] **ARCH-02**: PluginStateManager class extracted; owns _plugin_states, per-key locks, checkpoint save/restore
- [ ] **ARCH-03**: SignalProcessor class extracted; owns I7 execution, regime gating, ranking, and aggregation
- [ ] **ARCH-04**: CacheManager class extracted; owns all 6 refresh loops and DB cache reads
- [ ] **ARCH-05**: OutputQueue class extracted; owns asyncio.Queue, drain loop, enqueue, and Kafka publish

### OBS — Observability Completeness

- [ ] **OBS-01**: Per-plugin OTel latency histogram tracked in the intelligence pipeline; developers can see which plugin is the slowest at the p50/p95 level without adding instrumentation
- [ ] **OBS-02**: Single `/api/health/system` endpoint returns machine-readable JSON covering consumer lag by group, DLQ depth, signal_replay_unresolved gauge, and agent last-heartbeat timestamps
- [ ] **OBS-03**: BaseAgent exposes a `last_processed_at` heartbeat timestamp; service_auditor detects stalled agents (process alive, no bar progress) and triggers restart

### QUAL — First Qualitative Intelligence Lane

- [ ] **QUAL-01**: One qualitative intelligence lane (earnings or macro events) is implemented and produces intelligence events on the canonical typed bus
- [ ] **QUAL-02**: The new qualitative lane runs in shadow mode by default; validated over N bars before promotion gate can be triggered

### PERF — Compute Performance Optimization

- [ ] **PERF-01**: `_build_features_from_event()` is called once per bar and its result reused across all I7 plugins; the current per-call 7× Pydantic `model_dump()` allocations are eliminated
- [ ] **PERF-02**: The flat `features` dual-write path (maintained in parallel with the tiered dict across every wave merge) is profiled and removed if no active plugin requires it; per-bar wave merge overhead is reduced
- [ ] **PERF-03**: Plugin state is passed as a parameter to `compute_full()`/`compute_next()` rather than mutating `plugin._state` before thread pool dispatch; the race condition on concurrent symbol/tf submissions is eliminated
- [ ] **PERF-04**: OBS-01 histogram data is used to identify plugins executing O(N) full bar-history recomputation on every bar; each identified plugin is converted to incremental O(1) compute where an algorithmic incremental form exists
- [ ] **PERF-05**: `IntelligenceEvent` construction comprehensions (`{k: v ... if v is not None}` × 7 tiers) are replaced with pre-filtered dicts assembled during wave merging; None-filtering no longer happens at event construction time

---

## Future Requirements

*(Deferred from this milestone — well-understood, not yet scheduled)*

- Multi-lane qualitative expansion (news sentiment, earnings calendar, macro calendar) — validate one lane first per QUAL-01/02
- Auth layer / Cloudflare Tunnel — no external consumers yet
- Portfolio-level signal aggregation — intelligence platform scope boundary

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Order execution / position sizing | Intelligence platform only |
| Real-time latency SLAs / co-location | Not a HFT system |
| Kubernetes / HPA | Systemd + Prometheus lag monitoring is the scaling model |
| Additional broker adapters beyond IBKR | Deferred until provider abstraction fully validated |

---

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| INFRA-01 | Phase 084 | Pending |
| INFRA-02 | Phase 084 | Pending |
| INFRA-03 | Phase 084 | Pending |
| INFRA-04 | Phase 084 | Pending |
| INFRA-05 | Phase 084 | Pending |
| INFRA-06 | Phase 084 | Pending |
| OBS-01 | Phase 084 | Pending |
| PERSIST-01 | Phase 085 | Pending |
| PERSIST-02 | Phase 085 | Pending |
| PERSIST-03 | Phase 085 | Pending |
| PERSIST-04 | Phase 085 | Pending |
| PERSIST-05 | Phase 085 | Pending |
| PIPE-01 | Phase 086 | Pending |
| PIPE-02 | Phase 086 | Pending |
| PIPE-03 | Phase 086 | Pending |
| PIPE-04 | Phase 086 | Pending |
| OBS-02 | Phase 086 | Pending |
| OBS-03 | Phase 086 | Pending |
| SIGXFM-01 | Phase 087 | Pending (gated ~May 25) |
| SIGXFM-02 | Phase 087 | Pending (gated ~May 25) |
| SIGXFM-03 | Phase 087 | Pending (gated ~May 25) |
| ARCH-01 | Phase 088 | Pending |
| ARCH-02 | Phase 088 | Pending |
| ARCH-03 | Phase 088 | Pending |
| ARCH-04 | Phase 088 | Pending |
| ARCH-05 | Phase 088 | Pending |
| QUAL-01 | Phase 089 | Pending |
| QUAL-02 | Phase 089 | Pending |
| PERF-01 | Phase 090 | Pending |
| PERF-02 | Phase 090 | Pending |
| PERF-03 | Phase 090 | Pending |
| PERF-04 | Phase 090 | Pending |
| PERF-05 | Phase 090 | Pending |
