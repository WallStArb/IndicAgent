---
gsd_state_version: 1.0
milestone: v2.8
milestone_name: AI Platform & Evolvable Agents
status: executing
stopped_at: pipeline fixes + GSD cleanup
last_updated: "2026-05-27T16:51:47.682Z"
last_activity: 2026-05-27 -- Phase 107.5 planning complete
progress:
  total_phases: 16
  completed_phases: 0
  total_plans: 16
  completed_plans: 2
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** v2.8 AI Platform

## Current Position

Phase: 094 (next to plan)
Plan: Not started
Status: Ready to execute
Last activity: 2026-05-27 -- Phase 107.5 planning complete

## v2.7 Shipped Phases (COMPLETE — shipped 2026-05-26)

| Phase | Name | Status |
|-------|------|--------|
| 093 | Mathematical Correctness Audit | Complete (5/5 plans, 2026-05-21) |
| 100 | Plugin Shared Infrastructure | Complete (6/6 plans, 2026-05-22) |
| 100.5 | Plugin Infrastructure Hardening | Complete (1/1 plan, 2026-05-22) |
| 104 | Storage Architecture Redesign | Complete (4/4 plans, 2026-05-22) |
| 105 | Architecture Hotfix Sprint | Complete (5/5 plans, 2026-05-24) |
| 106 | Foundation Hardening | Complete (6/6 plans, 2026-05-25) |
| 107 | Infrastructure Hygiene | Complete (9/9 criteria, 2026-05-25) |

## v2.8 AI Platform Phases (0/9 complete)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 094 | LiteLLM + Instructor Structured Output | LLM-INFRA-01–05, STRUCT-OUT-01–04 | 0/TBD plans (2 written from v2.7) |
| 095 | Pydantic AI Agent Execution Layer | AGENT-EXEC-01–05 | 0/5 plans (8 written from v2.7) |
| 096 | Agent Registry | AGENT-REG-01–04 | 0/TBD plans |
| 097 | Zep Episodic Memory | MEM-01–04 | 0/TBD plans |
| 098 | DSPy Offline Optimizer | OPT-01–04 | 0/TBD plans |
| 099 | Guardrails AI (conditional: parse failure > 1%) | GUARD-01–03 | 0/TBD plans |
| 101 | Composite Fitness Function | FIT-01–06 | 0/6 plans |
| 102 | Genetic Infrastructure (gated on FIT-06) | GENE-01–04 | 0/4 plans |
| 103 | Reproductive Operators (gated on FIT-06 + GENE) | REPRO-01–04 | 0/4 plans |

**Phase 107 Renaissance Redesign (2026-05-25):**

- Expanded from 4 criteria (HYGIENE-01–04) to 9 criteria (HYGIENE-01–09)
- Organized in 3 waves: Service Consistency (30%), Silent Failure Elimination (35%), Complexity Reduction (35%)
- Measurement-driven: every criterion has quantified before/after metrics
- Root-cause focused: fixes include CI gates, pre-commit hooks, process changes
- Binary verification: single SQL query determines success (all 9 criteria must pass)
- Designed per Renaissance principles: zero tolerance for silent failures, instrumentation before optimization

**Coverage:** 53/53 v2.8 requirements mapped (FOUND-01–06, HYGIENE-01–09, LLM-INFRA-01–05, STRUCT-OUT-01–04, AGENT-EXEC-01–05, AGENT-REG-01–04, MEM-01–04, OPT-01–04, GUARD-01–03, FIT-01–06, GENE-01–04, REPRO-01–04)

## Evidence Gates

| Gate | Condition | Blocks |
|------|-----------|--------|
| GUARD gate | Post-Instructor parse failure rate > 1% (STRUCT-OUT-03) | Phase 099 executes only if condition true |
| FIT-06 gate | Cross-agent composite score variance >= 0.2 | Phases 102 and 103 |
| Zep compute gate | Recall p95 latency <= 50ms; RAM footprint documented | Phase 097 enablement |
| DSPy data gate | >= 500 labeled rows per agent in llm_calls | Phase 098 first run |

## Accumulated Context

### Decisions

- Phase 080 swarm agents extend `BaseMultiplierAgent`; shadow-only by default.
- `signal_replay_unresolved_gauge = 0` is the permanent health invariant post-081.
- ML training filter: `WHERE signal_schema_version >= 'v1' AND is_backfill=FALSE` (tracks `SIGNAL_SCHEMA_VERSION` constant, currently 'v2').
- The canonical shared state lives in `.planning/STATE.md`; `PROJECT.md` and `ROADMAP.md` remain the longer-form references.
- v2.6 approach: fix base classes first (084), then migrate writers (085), then pipeline (086). Renaissance principle — fix the leverage point, not each symptom individually.
- God class refactor: "one process" is correct for latency; "one class" is accidental complexity. Decompose within the process boundary.
- v2.8 ordering: infrastructure debt first (106-107), then AI platform stack in dependency order (094 → 095 → 096 → 097/098 parallel → 099 conditional), then evolvable agents (101 → 102 → 103).
- Phase 099 is conditional — skip it if Instructor brings parse failures below 1%; do not add validation layers without evidence.
- Phases 102-103 are gated on FIT-06 discriminative power; if all agents score within 0.1 of each other, the fitness function is not ready and genetic work does not begin.
- All new AI agent behavior runs shadow_only=True; no auto-promotion; operator must confirm fitness gate.
- No new Kafka topics without named producer-consumer pair; no new systemd daemons without justification.
- **Phase 107 Renaissance design (2026-05-25):** Expanded from 4 to 9 criteria based on architectural weakness assessment. 3-wave structure: Service Consistency (BaseAgent adoption, DatabaseManager standardization, Agent ID labels), Silent Failure Elimination (writer flush spans, metric types, data loss), Complexity Reduction (DAG correctness, dead code, shadow integrity). Measurement-driven with binary SQL verification query.

### Analysis Docs

- `docs/ideas/architectural-weakness-assessment.md` — **CRITICAL for Phase 107**: 36 findings (HF-1 through HF-11, #1 through #36), Renaissance priority rankings (P1-P4), complete inventory of technical debt. Source of truth for all 9 HYGIENE criteria.
- `docs/ideas/persistence-layer-fragility-assessment.md` — full 13-writer audit table
- `docs/ideas/service-resilience-patterns.md` — Pattern 1 (circuit breaker) elevated to Phase 084 scope
- `docs/ideas/latency-and-persistence-audit-design.md` — Phase 084 relevant items flagged; DragonflyDB refs noted as stale

### Blockers / Concerns

- weight-updater FAILED post-reboot — diagnose before v2.8 AI platform work begins (see MEMORY.md: project_failed_services_to_fix.md)
- feature-writer stuck activating post-reboot — diagnose before v2.8 AI platform work begins
- Phase 099 (Guardrails): do not implement unless post-094 parse failure rate > 1% — conditional gate must be evaluated after Phase 094 ships

## Session Continuity

Last session: 2026-05-26T10:30:00.000Z
Stopped at: pipeline fixes + GSD cleanup
Resume: `/gsd:discuss-phase 094` → `/gsd:plan-phase 094`

**Phase 107 archive:** `.planning/archive/phases/107-infrastructure-hygiene/`

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
| Phase 104 P03 | 45 | 3 tasks | 16 files |
| Phase 107 P00 | 469 | 5 tasks | 6 files |
