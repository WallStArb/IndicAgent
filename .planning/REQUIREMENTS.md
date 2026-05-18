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

### PERF — Compute Performance Optimization

- [ ] **PERF-01**: `_build_features_from_event()` is called once per bar and its result reused across all I7 plugins; the current per-call 7× Pydantic `model_dump()` allocations are eliminated
- [ ] **PERF-02**: The flat `features` dual-write path (maintained in parallel with the tiered dict across every wave merge) is profiled and removed if no active plugin requires it; per-bar wave merge overhead is reduced
- [ ] **PERF-03**: Plugin state is passed as a parameter to `compute_full()`/`compute_next()` rather than mutating `plugin._state` before thread pool dispatch; the race condition on concurrent symbol/tf submissions is eliminated
- [ ] **PERF-04**: OBS-01 histogram data is used to identify plugins executing O(N) full bar-history recomputation on every bar; each identified plugin is converted to incremental O(1) compute where an algorithmic incremental form exists
- [ ] **PERF-05**: `IntelligenceEvent` construction comprehensions (`{k: v ... if v is not None}` × 7 tiers) are replaced with pre-filtered dicts assembled during wave merging; None-filtering no longer happens at event construction time
- [ ] **PERF-06**: `_drain_output` publishes Kafka messages in batches (drain up to N items per iteration) rather than one message per `await`; Kafka round-trip overhead is amortized across bursts
- [ ] **PERF-07**: Bar processing is parallelized per (symbol, tf) key — independent keys are dispatched to per-key workers concurrently rather than processed sequentially; a bar for ES:1m does not block NQ:5m
- [ ] **PERF-08**: `BarMessage(**msg)` hot-path parse uses `model_construct()` (skip validation) for messages from trusted internal producers; full Pydantic validation reserved for DLQ/error paths
- [ ] **PERF-09**: `bar.model_copy(update={"gap_preceding": True})` replaced with a zero-allocation alternative (gap flag passed as parameter or BarMessage constructed with field set at parse time)
- [ ] **PERF-10**: `_write_local_checkpoint()` moved off the hot path to a periodic background asyncio.Task; checkpoint writes never block bar processing

---

## Future Requirements

*(Deferred from this milestone — well-understood, not yet scheduled)*

**v2.7 Horizontal Intelligence Foundation (next milestone):**
- Qualitative lane: macro event calendar (FOMC/NFP/CPI), sector intelligence, company-specific (earnings dates, guidance, analyst ratings) — three sub-lanes, individual equities in scope for v2.7
- Fundamental lane: economic regime indicators, valuation context for equities (P/E, EPS, sector rotation), macro FCI
- Lane aggregation architecture: how qualitative/fundamental conviction combines with I7 timeseries signals
- All lanes shadow-only at launch; QUAL-01/02 requirements move here

**Other deferred:**
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

### INST — Instrument Registry

- [ ] **INST-01**: `instruments` DB table is the single source of truth for all instrument configuration; `contract_details` JSONB holds point_value, tick_size, session_id, exchange, sector, asset_class; settings.py contains only infrastructure config (kafka, db, ibkr connection params)
- [ ] **INST-02**: API endpoints (`POST /api/instruments`, `PUT /api/instruments/{symbol}`, `DELETE /api/instruments/{symbol}`) add/update/deactivate instruments without code deploy or service restart
- [ ] **INST-03**: Pipeline picks up instrument changes within 1 second via asyncpg LISTEN on `instruments` channel; `invalidate_active_contracts_cache()` is replaced by event-driven invalidation
- [ ] **INST-04**: Empty-DB bootstrap: `IBKR_CONTRACTS_JSON` env var seeds `instruments` table on first startup; subsequent startups read DB only
- [ ] **INST-05**: One-time migration populates `instruments.contract_details` from existing settings.py instrument objects; all callers of `get_active_contracts()` unchanged

### LEDGER — Signal Ledger Hardening

- [ ] **LEDGER-01**: `LedgerEntry.to_insert_params()` replaced with `_to_row()` named-field helper; adding a new column requires one line edit, not positional reordering of a 65-element tuple
- [ ] **LEDGER-02**: All signal_ledger lifecycle update queries (exit_at, outcome, mae, mfe) use named-field style consistent with `_to_row()`

### THREAD — Thread Safety

- [ ] **THREAD-01**: `_settings_singleton` module-level global in settings.py protected with `threading.RLock`; concurrent reads from ThreadPoolExecutor threads are race-free
- [ ] **THREAD-02**: `_cross_asset_cache` and `_macro_cache` in intelligence pipeline protected with `asyncio.Lock`; concurrent async reads/writes from per-key workers (PERF-07) are safe

### RISK — Portfolio Risk Gates

- [ ] **RISK-01**: `SignalTrackerComputeAgent` enforces `max_active_per_direction` (default 5) and `max_active_per_symbol` (default 2) concentration limits before activating new signals
- [ ] **RISK-02**: Signals exceeding concentration limits are persisted as `risk_suppressed` in signal_ledger; status flows through the same lifecycle path as `regime_suppressed`
- [ ] **RISK-03**: OTel counter `signal_tracker_risk_suppressed_total` with `reason` label (direction_limit, symbol_limit) fires on every suppression event
- [ ] **RISK-04**: Limits overridable via `INDICAGENT_MAX_ACTIVE_PER_DIRECTION` and `INDICAGENT_MAX_ACTIVE_PER_SYMBOL` env vars; change takes effect on next signal activation check without service restart

### QUAL — Signal Quality Completeness

- [ ] **QUAL-01**: `signal_metrics` table adds skewness and kurtosis columns for R-multiple distribution shape; negative skewness flags left-tail blowup risk
- [ ] **QUAL-02**: `signal_metrics` table adds min_r (worst pnl_r in window) and recovery_factor (avg_mfe / abs(min_r)) columns
- [ ] **QUAL-03**: `SignalMetricsComputeAgent` produces per-symbol rows (symbol != '*') alongside global '*' aggregate; enables per-instrument quality evaluation for v2.7 lane evaluation
- [ ] **QUAL-04**: DB migration for new columns is idempotent (IF NOT EXISTS); all existing signal_metrics consumers work unchanged; new columns nullable with NULL default

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
| PERF-01 | Phase 089 | Pending |
| PERF-02 | Phase 089 | Pending |
| PERF-03 | Phase 089 | Pending |
| PERF-04 | Phase 089 | Pending |
| PERF-05 | Phase 089 | Pending |
| PERF-06 | Phase 089 | Pending |
| PERF-07 | Phase 089 | Pending |
| PERF-08 | Phase 089 | Pending |
| PERF-09 | Phase 089 | Pending |
| PERF-10 | Phase 089 | Pending |
| PERF-10 | Phase 089 | Pending |
| INST-01 | Phase 090 | Pending |
| INST-02 | Phase 090 | Pending |
| INST-03 | Phase 090 | Pending |
| INST-04 | Phase 090 | Pending |
| INST-05 | Phase 090 | Pending |
| LEDGER-01 | Phase 091 | Pending |
| LEDGER-02 | Phase 091 | Pending |
| THREAD-01 | Phase 091 | Pending |
| THREAD-02 | Phase 091 | Pending |
| RISK-01 | Phase 092 | Pending |
| RISK-02 | Phase 092 | Pending |
| RISK-03 | Phase 092 | Pending |
| RISK-04 | Phase 092 | Pending |
| QUAL-01 | Phase 093 | Pending |
| QUAL-02 | Phase 093 | Pending |
| QUAL-03 | Phase 093 | Pending |
| QUAL-04 | Phase 093 | Pending |
