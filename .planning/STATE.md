---
gsd_state_version: 1.0
milestone: v2.6
milestone_name: Foundation Hardening & Signal Transform
status: planning
stopped_at: ""
last_updated: "2026-05-16T14:00:00.000Z"
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** v2.6 — Foundation Hardening + Signal Transform Architecture. Scope agreed 2026-05-16, phases not yet planned.

## Current Position

Phase: Not started (defining requirements)
Plan: -
Status: Defining requirements
Last activity: 2026-05-16 — Milestone v2.6 started
Last completed: Phase 083 — Observability Hardening (7 plans, 2026-05-16)

Progress: [░░░░░░░░░░] 0% (v2.6 not started)

## v2.6 Agreed Scope (2026-05-16)

Phase order and focus agreed in session. Start milestone then plan phases.

### Phase 084 — Base Agent Hardening
Enhance `BaseWriterAgent`, `BaseAgent`, `BaseAIAgent` with enforced contracts:
- `BaseWriterAgent._parse_payload()` — declare Pydantic model, base validates + auto-DLQs
- `BaseWriterAgent._flush_batch()` — enforced contract: raise or DLQ, never swallow
- `BaseAgent._setup_with_retry()` — configurable, eliminates 3x duplication
- `BaseAIAgent._on_error()` — emit OTel counter by default (call site exists, body is pass)
- Circuit breaker opt-in via class attribute on BaseAgent
- Fix: dead graduation loop (implement or delete), LineageRecorder (wire or delete)

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

### Phase 087 — Signal Transform Architecture Phases 2-4
Gated on 30-day data accumulation (~May 25). Phase 72 (dual-write) already shipped.
Resume when gate lifts.

### Phase 088 — Intelligence Pipeline God Class Decomposition
Extract 9 responsibilities from 1892-line `IntelligencePipelineComputeAgent` into
focused in-process classes (zero latency overhead — no Kafka boundaries):
- `PluginExecutor` — tiers, thread pool, plugin cache
- `PluginStateManager` — _plugin_states, locks, checkpoint/restore
- `SignalProcessor` — I7, gating, ranking, aggregation
- `CacheManager` — 6 refresh loops, all DB cache reads
- `OutputQueue` — asyncio.Queue, drain, enqueue, publish
Enables: async parallel tier execution, isolated circuit breakers, easier testing.

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
- First qualitative lane: build one, validate, then expand. Don't build all three lanes simultaneously.
- Signal Transform phases 2-4: data gate ~May 25 — schedule 087 around that date.

### Analysis Docs (produced 2026-05-16)

- `docs/ideas/architectural-weakness-assessment.md` — 12 entries, Phase 084 priority list, god class decomposition detail
- `docs/ideas/persistence-layer-fragility-assessment.md` — full 13-writer audit table
- `docs/ideas/service-resilience-patterns.md` — Pattern 1 (circuit breaker) elevated to Phase 084 scope
- `docs/ideas/latency-and-persistence-audit-design.md` — Phase 084 relevant items flagged; DragonflyDB refs noted as stale

### Blockers/Concerns

- Signal Transform phases 2-4 gated on data (~May 25) — don't block 084-086 on this
- God class decomposition (088) is high effort — size it carefully before committing

## Session Continuity

Last session: 2026-05-16
Stopped at: context approaching limit. v2.6 scope fully agreed. Next: /gsd-new-milestone to start v2.6, then /gsd-plan-phase 84.
Resume file: None
