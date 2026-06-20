---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Intelligence Vectors — AlphaEngine
status: Phase A planned — ready to execute (6 plans, 4 waves)
last_updated: "2026-06-20T21:00:00.000Z"
last_activity: 2026-06-20
progress:
  total_phases: 3
  completed_phases: 0
  total_plans: 6
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** v3.0 AlphaEngine — replace binary signal plugins with continuous IC-weighted score producers

## v2.8 AI Platform Phases (7/13 complete)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 094 | LiteLLM + Instructor Structured Output | LLM-INFRA-01–05, STRUCT-OUT-01–04 | Complete (3/3 plans, 2026-05-29) |
| 095 | Pydantic AI Agent Execution Layer | AGENT-EXEC-01–05 | Complete (5/5 plans, 2026-05-31) |
| 096 | Agent Registry | AGENT-REG-01–04 | Complete (3/3 plans, 2026-06-03) |
| 097 | Zep Episodic Memory | MEM-01–04 | 6/6 plans (reviewed, ready to execute) |
| 098 | DSPy Offline Optimizer | OPT-01–04 | 0/TBD plans |
| 099 | Guardrails AI (conditional: parse failure > 1%) | GUARD-01–03 | 0/TBD plans |
| 110 | Renaissance Rename | REN-01–04 | Complete (4/4 plans, 2026-05-30) |
| 111 | Full Naming Alignment | NAME-01–04 | Complete (4/4 plans, 2026-05-31) |
| 112 | Intelligence Pipeline Signal Integrity | SIGINT-01–05 | Complete (5/5 plans, 2026-06-02) |
| 113 | Architecture Hardening | ARCH-01 | Complete (1/1 plan, 2026-06-03) |
| 114 | Occam's Razor | OCCAM-01–04 | 4/4 plans (revised with review feedback, ready to execute) |
| 115 | Framing Audit Trail | FRAME-01–05 | Complete (5/5 plans, 2026-06-05) |
| 116 | SR Consensus | SR-01–03 | Complete (3/3 plans, 2026-06-05) |
| 101 | Composite Fitness Function | FIT-01–06 | 6/6 plans (reviewed, ready to execute) |
| 102 | Genetic Infrastructure (gated on FIT-06) | GENE-01–04 | 0/4 plans |
| 103 | Reproductive Operators (gated on FIT-06 + GENE) | REPRO-01–04 | 0/4 plans |

**Coverage:** 53/53 v2.8 requirements mapped + Phase 115 (5 FRAME reqs) + Phase 116 (3 SR reqs).

## v2.9 Signal Quality Renaissance — SHIPPED 2026-06-13

| Phase | Name | Status |
|-------|------|--------|
| 117 | PatternCompletion Fix + Data Pipeline Validation | Complete (5/5 plans, 2026-06-08) |
| 118 | Confidence Integrity + Top 5 Setup Refactoring | Complete (7/7 plans, 2026-06-09) |
| 119 | Remaining 16 Setup Refactoring | Complete (4/4 plans, 2026-06-10) |
| 120 | Shadow Mode Validation | Complete (3/3 plans, 2026-06-10) |
| 121 | Lifecycle Replay & Validation | Complete (3/4 plans, 2026-06-11); 121-02 report deferred to Phase 126 |
| 122 | I2 Tier Persistence Fix + Param Store | Complete (10/10 plans, 2026-06-13) |

## Evidence Gates

| Gate | Condition | Blocks |
|------|-----------|--------|
| GUARD gate | Post-Instructor parse failure rate > 1% | Phase 099 executes only if condition true |
| FIT-06 gate | Cross-agent composite score stddev >= 0.2 | Phases 102 and 103 |
| Zep compute gate | Recall p95 latency <= 50ms; RAM footprint documented | Phase 097 enablement |
| DSPy data gate | >= 500 labeled rows per agent in llm_calls | Phase 098 first run |

## Accumulated Context

### Decisions

- v2.8 ordering: infrastructure debt first (106-107), then AI platform stack in dependency order (094 → 095 → 096 → 097/098 parallel → 099 conditional), then evolvable agents (101 → 102 → 103).
- Phase 099 is conditional — skip if Instructor brings parse failures below 1%.
- Phases 102-103 are gated on FIT-06 discriminative power; if all agents score within 0.1 of each other, genetic work does not begin.
- All new AI agent behavior runs shadow_only=True; no auto-promotion; operator must confirm fitness gate.
- No new Kafka topics without named producer-consumer pair; no new systemd daemons without justification.
- [Phase 095]: response_format forwarded via conditional dict insert; semantic cache skipped for structured calls; LLMProviderChain in TYPE_CHECKING only.
- [Phase 123]: SIGNAL_SCHEMA_VERSION bumped to v3 to mark ECL field addition in signal payloads
- [Phase 123]: _nullable_float() pattern: None=cold-start, 0.0=genuine neutral — never or 0.0 fallback (ML training integrity)
- [Phase 123]: _PHASE_119_PLUGINS frozenset dissolved: boundary concept no longer needed once all plugins emit ECL annotations
- [Phase 123]: Phase 128 DB persistence deferred: signal_writer reads ECL fields end-to-end but LedgerEntry not extended until 3-table migration
- [Phase 136]: ctf_score=NULL is table-wide in intelligence_features: replay script never wrote Phase-130 CTF dedicated columns; deferred to future fix
- [Phase 136]: Migration 130 Statement 3 UPDATE 0 rows: W2b exclusion at write time already eliminated all ctf_score keys from cross_timeframe_context; cleanup is durable

### Blockers / Concerns

- Phase 099 (Guardrails): do not implement unless post-094 parse failure rate > 1%

## Session Continuity

### Last session (2026-06-20, session 4) — Phase A planned (6 plans, 4 waves)

Phase A: Feature Factory planning complete. All 10 success criteria covered. Verification passed.

Wave structure:
- Wave 1 (parallel): A-P1 schema+APR migration 155 + A-P2 contracts (stream key + dataclasses)
- Wave 2: A-P3 FeatureFactory TDD (35 primitives + FeatureCache; VXX/VIXY absent, SPY/TLT/SHY proxies)
- Wave 3 (parallel): A-P4 feature_writer retarget + A-P5 backfill oneshot (IBKR fetch + checkpoint/resume)
- Wave 4: A-P6 cutover (pipeline wire + I5/I6/I7 archive + smoke test + done-gate)

Key discoveries from research:
- `market_data_ohlcv` is empty — IBKR fetch is Wave 1/P5's first step, planned explicitly
- `alpha.` prefix missing from OPS_PREFIXES — blocker in A-P1 T1, resolved before migration runs
- VXX/VIXY not in 58-ETF universe — cross-asset proxies: vix_z via SPY realized-vol, flight_quality via TLT/SPY divergence, yield_slope_z via TLT/SHY ratio

**Next session:** `/gsd-execute-phase A`

### Last session (2026-06-20, session 3) — Phase A context updated, ready to plan

Three open items from the methodology session resolved:

- **I7 cutover timing locked:** Phase A ends with the cutover (D-09 updated). I7 runs live until Phase A's final deliverable. No shadow/parallel period — atomic wire-and-cut once backfill and unit tests pass. Done gate: feature_vectors within 5% of theoretical max + live bar smoke test + I5-I7 in archive + zero plugin dispatch refs.
- **Canonical refs updated:** `v30-alphaengine-strategy.md` and `v30-i7-transition.md` added. I7 archival approach confirmed: all of I5-I7 archived intact without modification; Phase B IC discovery handles the alpha scorer transformation.
- **pipeline_version migration resolved (D-13):** IC spec §IV.1 confirms no migration on `intelligence_features` needed — `feature_vectors` has it in DDL natively. STATE note from session 2 is closed.

### Last session (2026-06-20, session 2) — AlphaEngine V1 methodology spec written

Deep brainstorming on Renaissance alignment. Council-of-engineers review found and resolved six
critical gaps: lookahead bias in forward returns, HMM regime smoothing bias, serial
autocorrelation in IC standard errors, multiple testing scale, direction encoding in ensemble
weights, and feature_matrix research-vs-production conflation.

**Key decisions:**

- Regime-conditional IC mandatory from start — pooled IC is not a fallback, it is excluded
- IC Sharpe requires 20,000 independent obs — no interim proxy; get the data
- Forward returns via LEAD() on `bar->>'o'` within `intelligence_features` — no join to OHLCV
- `feature_candidates` (long) for research; `feature_matrix` (wide) for promoted-only production
- `ensemble_weights.weight` non-negative; direction via `ic_sign` column; applied as
  `sign(ic) × centered_score × weight` at ensemble time

- `has_gap_before_entry` flag on outcome_labels; gap and non-gap IC measured separately
- `pipeline_version` migration required on `intelligence_features` before Phase A

**Doc written:** `docs/plans/2026-06-20-alphaengine-v1-methodology.md`

**DB facts confirmed (intelligence_features):**

- Column names: `tf` (not timeframe), `ts`, `smc` (HMM fields), `bar` (OHLCV: o/c)
- HMM state in `smc`: `hmm_prob_trending_up`, `hmm_prob_ranging`, `hmm_prob_trending_down`
- Data: 1m 2mo, 5m 6mo, 15m 10mo, 1h 5.5yr — needs ETF backfill for IC Sharpe minimum

**Next session:**

1. Update stale docs (from previous session pending list in memory)
2. Plan Phase A — backfill requirement first, then IC measurement batch jobs

### Last session (2026-06-20, session 1) — v2.10 complete; starting v3.0 AlphaEngine build

v2.10 milestone closed. Phase 133 (corpus rebuild) CANCELLED — superseded by Intelligence Vectors architecture. In the new model IC measurement runs on `intelligence_features` (all bars), not `signal_events` (selection-biased). The corpus rebuild would have produced training data for the OLD binary-signal paradigm; that paradigm is being replaced.

**v3.0 design docs:**

- `docs/ideas/signal-08-intelligence-refactor.md` — north star, phasing A-E
- `docs/plans/2026-06-20-intelligence-vectors-architecture.md` — AlphaEngine technical design
- `docs/plans/2026-06-20-v30-reference-architecture.md` — v3.0 reference architecture

**Starting with AlphaEngine only (not AnalogEngine).**

**Next:** Plan Phase A — IC measurement on existing signal_events corpus (737 signals, 21+ plugins)

## Current Position

Milestone: v2.10 — COMPLETE (2026-06-20)
Milestone: v3.0 — STARTING — AlphaEngine (Intelligence Vectors, V1 Quant)
Phase: 133 (clean-corpus-rebuild) — CANCELLED (superseded by v3.0 architecture)
Phase: 135 (controlled-vocabulary-system) — deferred
Last activity: 2026-06-20

**Phase 126 research artifact**: `docs/plans/2026-06-14-phase-126-signal-universe-hardening.md`

## Performance Metrics

| Phase | Plan | Duration | Notes |
|-------|------|----------|-------|
| Phase 123 P01 | 20 | 5 tasks | 26 files |
| Phase 136 P05 | 12 | 3 tasks | 0 files |
| Phase 136 P06 | 5 | 3 tasks | 0 files |
