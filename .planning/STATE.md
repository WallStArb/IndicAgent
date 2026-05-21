---
gsd_state_version: 1.0
milestone: v2.7
milestone_name: AI Agent Platform Modernization
status: executing
stopped_at: context exhaustion at 76% (2026-05-21)
last_updated: "2026-05-21T13:47:16.348Z"
last_activity: 2026-05-21 -- Phase 093 planning complete
progress:
  total_phases: 8
  completed_phases: 0
  total_plans: 15
  completed_plans: 2
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** Phase 093 — LiteLLM Backend (v2.7 start)

## Current Position

Phase: 093 (not started)
Plan: —
Status: Ready to execute
Last activity: 2026-05-21 -- Phase 093 planning complete

## Phase Overview

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 093 | LiteLLM Backend | LLM-INFRA-01–05 | Not started |
| 094 | Instructor Structured Output | STRUCT-OUT-01–04 | Not started |
| 095 | Pydantic AI Agent Adapter | AGENT-EXEC-01–05 | Not started |
| 096 | Agent Registry | AGENT-REG-01–04 | Not started |
| 097 | Zep Episodic Memory | MEM-01–04 | Not started |
| 098 | DSPy Offline Optimizer | OPT-01–04 | Not started |
| 099 | Guardrails AI Validation | GUARD-01–03 | Not started |

## v2.6 Agreed Scope (2026-05-16)

Phase order and focus agreed in session. Roadmap written. Next: /gsd:plan-phase 84.

### Phase 084 — Base Agent Hardening

Enhance `BaseWriterAgent`, `BaseAgent`, `BaseAIAgent` with enforced contracts:

- `BaseWriterAgent._parse_payload()` — declare Pydantic model, base validates + auto-DLQs
- `BaseWriterAgent._flush_batch()` — enforced contract: raise or DLQ, never swallow
- `BaseAgent._setup_with_retry()` — configurable, eliminates 3x duplication
- `BaseAIAgent._on_error()` — emit OTel counter by default (call site exists, body is pass)
- Circuit breaker opt-in via class attribute on BaseAgent
- Fix: dead graduation loop (implement or delete), LineageRecorder (wire or delete)
- OBS-01: per-plugin OTel latency histograms in intelligence pipeline

### Phase 085 — Persistence Writer Migration

Writers adopt 084 base contracts — fixes become mechanical:

- `lineage_writer_agent` — CRITICAL: silent data loss today, no DLQ, no validation
- `feature_snapshot_writer_agent` — clear-on-error → bounded retry
- `llm_writer_service` — outcome errors swallowed → re-raise
- `signal_metrics_writer_agent` — per-record → batched
- All 6 positional-tuple writers → named params (contract_metadata is the template)

### Phase 086 — Pipeline Hardening

- Wire `PluginCircuitBreaker` into intelligence pipeline per-plugin (exists, unused)
- Wire `validate_signal()` at I7 output boundary in SignalWriterAgent (exists, unused)
- Checkpoint write → fail fast (currently swallowed)
- Output queue `put_nowait` → block/retry on full
- OBS-02: `/api/health/system` machine-readable JSON endpoint
- OBS-03: BaseAgent `last_processed_at` heartbeat + service_auditor stall detection

### Phase 087 — Signal Transform Architecture Phases 2-4

Gated on 30-day data accumulation (~May 25). Phase 72 (dual-write) already shipped.
Resume when gate lifts.

### Phase 088 — Intelligence Pipeline God Class Decomposition

Extract 5 responsibilities from 1892-line `IntelligencePipelineComputeAgent` into
focused in-process classes (zero latency overhead — no Kafka boundaries):

- `PluginExecutor` — tiers, thread pool, plugin cache
- `PluginStateManager` — _plugin_states, locks, checkpoint/restore
- `SignalProcessor` — I7, gating, ranking, aggregation
- `CacheManager` — 6 refresh loops, all DB cache reads
- `OutputQueue` — asyncio.Queue, drain, enqueue, publish

### Phase 089 — First Qualitative Intelligence Lane

One lane first (earnings or macro) — validate before building three.
Candidates: todo 013 (earnings), todo 014 (macro events).

## Accumulated Context

### Decisions

- Phase 080 swarm agents extend `BaseMultiplierAgent`; shadow-only by default.
- `signal_replay_unresolved_gauge = 0` is the permanent health invariant post-081.
- ML training filter: `WHERE signal_schema_version >= 'v1' AND is_backfill=FALSE` (tracks `SIGNAL_SCHEMA_VERSION` constant, currently 'v2').
- The canonical shared state lives in `.planning/STATE.md`; `PROJECT.md` and `ROADMAP.md` remain the longer-form references.
- v2.6 approach: fix base classes first (084), then migrate writers (085), then pipeline (086). Renaissance principle — fix the leverage point, not each symptom individually.
- God class refactor: "one process" is correct for latency; "one class" is accidental complexity. Decompose within the process boundary.
- Signal Transform phases 2-4: data gate ~May 25 — schedule 087 around that date.
- OBS-01 assigned to Phase 084 (co-located with base agent instrumentation work).
- OBS-02 and OBS-03 assigned to Phase 086 (system health endpoint and stall detection belong with pipeline hardening).
- Qualitative + fundamental horizontal lanes deferred to v2.7 "Horizontal Intelligence Foundation". Scope: macro event calendar, sector intelligence, company-specific (earnings/guidance/ratings) as qualitative sub-lanes; economic regime + equity valuation as fundamental lane. Individual equities in scope for v2.7. Architecture decision (how lanes aggregate with I7 timeseries) to be designed at v2.7 planning.
- [Phase 089]: FPE owns _prev_i1_features and _last_events carry-forward state, migrated from orchestrator
- [Phase 089]: HTF intel cached after 15m/1h/4h/1d bar processing via update_htf_intel — closes cross-tf context loop (D-19)
- [Phase 089]: PluginExecutor stores I7 state updates in _last_i7_state_updates for orchestrator to apply (D-15 compliance)
- [Phase 089]: PERF-02 flat features retained: 79 read-only consumers across plugin tree; removal would break I2-I7 plugins
- [Phase 089]: PERF-08 model_construct with fallback validation: trusted internal producer assumption consistent with DLQ wiring
- [Phase 089]: PERF-09 gap flag in frames['__gap__']: explicit parameter threading preserves future plugin access without object mutation
- [Phase 089]: 089-03: Batch drain preserves swallow-and-log for publish errors (existing test contract); CancelledError re-enqueues batch[handled+1:] before re-raise
- [Phase 089]: PERF-03: state threaded via functools.partial to run_in_executor, eliminating pre-dispatch plugin._state race
- [Phase 089]: Plugin protocol backward-compatible: state=None default; existing plugins fallback to compute_full until individually migrated
- [Phase 089]: MarketProfile incremental: volume_buckets dict with fixed tick_size from seed; O(K) POC/VAH/VAL vs O(N*K) full
- [Phase 089]: SessionLevels incremental: 390-bar count boundary detection for session rollover; O(1) per-bar high/low tracking
- [Phase 089]: BOCPD/HMM algorithmic bounds documented in source: O(R) and O(K^2) respectively; cannot be O(1) without approximation
- [Phase 091]: FX PK uses full symbol (USDJPY, USDCHF) not base currency (USD) - eliminates collision for shared-base FX pairs in upsert_instruments
- [Phase 091]: pg_notify trigger uses COALESCE(NEW.symbol, OLD.symbol) for INSERT/UPDATE/DELETE correctness - prevents NULL payload on DELETE
- [Phase 091-02]: Use asyncpg.connect() (raw dedicated connection) for LISTEN to prevent pool context manager from releasing subscription on exit
- [Phase 091-02]: Lazy import of invalidate_active_contracts_cache inside _reload_instruments_cache to avoid circular import at module level
- [Phase 091-06]: Soft-delete (is_active=false via UPDATE) used instead of hard DELETE so DB trigger fires pg_notify and audit history is preserved
- [Phase 091-06]: No explicit pg_notify call in route handlers; DB trigger from 091-01 fires automatically on INSERT/UPDATE
- [Phase 091-instrument-registry]: Use c.symbol (not c.base) as upsert PK for instruments table - fixes FX collision where USDJPY/USDCHF both had base=USD
- [Phase 091-instrument-registry]: Restored get_point_value() and get_tick_size() to settings.py (reimplemented via get_active_contracts) after signal_tracker_compute_agent import dependency discovered
- [Phase 091-instrument-registry]: Delete build_contracts() validator tests; port runtime contract-lookup tests to mock get_active_contracts()

### Analysis Docs (produced 2026-05-16)

- `docs/ideas/architectural-weakness-assessment.md` — 12 entries, Phase 084 priority list, god class decomposition detail
- `docs/ideas/persistence-layer-fragility-assessment.md` — full 13-writer audit table
- `docs/ideas/service-resilience-patterns.md` — Pattern 1 (circuit breaker) elevated to Phase 084 scope
- `docs/ideas/latency-and-persistence-audit-design.md` — Phase 084 relevant items flagged; DragonflyDB refs noted as stale

### Blockers/Concerns

- Signal Transform phases 2-4 gated on data (~May 25) — don't block 084-086 on this
- God class decomposition (088) is high effort — size it carefully before committing

## Session Continuity

Last session: 2026-05-21T00:21:26.947Z
Stopped at: context exhaustion at 76% (2026-05-21)
Last session: 2026-05-18T20:57:19.608Z
Stopped at: Completed 089-04-PLAN.md - PERF-03 plugin state race fix
Resume file: None
Next: /gsd:execute-phase 088

**Planned Phase:** 84 (Base Agent Hardening) — 4 plans — 2026-05-16T18:51:26.583Z
**Planned Phase:** 085 (Persistence Writer Migration) — 4 plans — 2026-05-17

---

## Pre-Reboot Resource Snapshot (2026-05-17 ~14:32)

**Context:** Captured before planned Ubuntu reboot for pending microcode update (`0x0b20401b` → `0x0b204037`). Uptime: 2 days 13h. Compare post-reboot to detect memory leaks or CPU regression.

### System

| Metric | Value |
|--------|-------|
| RAM total | 29GB |
| RAM used | 15.8GB |
| RAM free | 3.2GB |
| Buff/cache | 14.9GB |
| Available | 13.3GB |
| **Swap used** | **8.2GB / 22.8GB** |
| Load avg | 0.71, 0.72, 0.68 |
| CPU idle | 98.9% |

### Docker Containers

| Container | CPU% | RAM | RAM% |
|-----------|------|-----|------|
| timescaledb | 3.10% | 6.48GiB | 22.73% |
| redpanda | 2.18% | 2.31GiB | 38.56% (of 6GiB cap) |
| indicagent-mlflow | 2.32% | 123MB | 0.42% |
| indicagent-tempo | 1.33% | 133MB | 0.46% |
| indicagent-loki | 1.12% | 188MB | 0.65% |
| indicagent-prometheus | 0.24% | 339MB | 1.16% |
| ib-gateway | 0.41% | 762MB | 2.61% |
| indicagent-otel-collector | 0.17% | 78MB | 0.27% |
| indicagent-grafana | 0.08% | 94MB | 0.32% |
| indicagent-alertmanager | 0.19% | 27MB | 0.09% |
| ollama | 0.00% | 27MB | 0.09% |
| indicagent-langfuse | 0.00% | 9MB | 0.03% |

**Total Docker RAM (approx):** ~10.6GiB

### Service State

- **FAILED:** `indicagent-intelligence-pipeline.service` (pre-existing — not reboot-caused)
- **Inactive/dead (expected):** feature-writer, ml-training, ml-orchestrator, ml-data-quality, ml-discovery, shadow-auditor, weight-updater, redpanda-watchdog
- All other indicagent services: active/running

### Python Process RSS (largest indicagent processes)

| RSS | Notes |
|-----|-------|
| 279MB | largest indicagent venv process |
| 212MB | |
| 207MB | |
| 193MB | |
| 157MB | |
| 125MB | |

### PostgreSQL (TimescaleDB container processes)

| RSS | Notes |
|-----|-------|
| 2.9GB | largest postgres worker |
| 953MB | |
| 331MB | |
| 261MB | |
| 226MB | ×2 |

## Performance Metrics

| Phase | Plan | Duration | Notes |
|-------|------|----------|-------|
| Phase 089 P01 | 17 | 6 tasks | 9 files |
| Phase 089 P02 | 8 | 3 tasks | 5 files |
| Phase 089 P03 | 9 | 2 tasks | 4 files |
| Phase 089 P04 | 25 | 3 tasks | 6 files |
| Phase 089 P05 | 8 | 3 tasks | 12 files |
| Phase 091 P01 | 3 | 3 tasks | 3 files |
| Phase 091-instrument-registry P02 | 525563 | 3 tasks | 3 files |
| Phase 091 P06 | 4 | 2 tasks | 2 files |
| Phase 091-instrument-registry P04 | 90 | 2 tasks | 9 files |
| Phase 091-instrument-registry P05 | 3 | 4 tasks | 1 files |
