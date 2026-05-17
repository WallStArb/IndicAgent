---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: completed
stopped_at: Phase 085 context gathered
last_updated: "2026-05-17T13:25:41.964Z"
last_activity: 2026-05-17 -- Phase 085 marked complete
progress:
  total_phases: 32
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** Phase 085 — persistence-writer-migration

## Current Position

Phase: 085 — COMPLETE
Plan: 1 of 4
Status: Phase 085 complete
Last activity: 2026-05-17 -- Phase 085 marked complete
Last completed: Phase 083 — Observability Hardening (7 plans, 2026-05-16)

Progress: [░░░░░░░░░░] 0% (0/6 phases)

## Phase Overview

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 084 | Base Agent Hardening | INFRA-01–06, OBS-01 | Not started |
| 085 | Persistence Writer Migration | PERSIST-01–05 | Ready to execute (4 plans) |
| 086 | Pipeline Hardening | PIPE-01–04, OBS-02–03 | Not started |
| 087 | Signal Transform Architecture Phases 2-4 | SIGXFM-01–03 | Not started (gated ~May 25) |
| 088 | God Class Decomposition | ARCH-01–05 | Not started |
| 089 | Compute Performance Optimization | PERF-01–05 | Not started |

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

### Analysis Docs (produced 2026-05-16)

- `docs/ideas/architectural-weakness-assessment.md` — 12 entries, Phase 084 priority list, god class decomposition detail
- `docs/ideas/persistence-layer-fragility-assessment.md` — full 13-writer audit table
- `docs/ideas/service-resilience-patterns.md` — Pattern 1 (circuit breaker) elevated to Phase 084 scope
- `docs/ideas/latency-and-persistence-audit-design.md` — Phase 084 relevant items flagged; DragonflyDB refs noted as stale

### Blockers/Concerns

- Signal Transform phases 2-4 gated on data (~May 25) — don't block 084-086 on this
- God class decomposition (088) is high effort — size it carefully before committing

## Session Continuity

Last session: --stopped-at
Stopped at: Phase 085 context gathered
Resume file: --resume-file
Next: /gsd:plan-phase 84

**Planned Phase:** 84 (Base Agent Hardening) — 4 plans — 2026-05-16T18:51:26.583Z
**Planned Phase:** 085 (Persistence Writer Migration) — 4 plans — 2026-05-17
