---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Intelligence Vectors — AlphaEngine
status: executing
last_updated: "2026-06-23T22:33:21.244Z"
last_activity: 2026-06-23 -- Phase 138 P8 complete (IC pipeline data run + discovery report)
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 20
  completed_plans: 18
  percent: 75
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** Phase 138 — ic engine forward returns

## v3.0 AlphaEngine — Phase 138 IC Engine Forward Returns (2026-06-22 to 2026-06-23)

**Status:** Complete

| Plan | Name | Status | Date | Notes |
|------|------|--------|------|-------|
| P0 | Feature Vector ID + FeatureVectorWriter | Complete | 2026-06-22 | Migration 158, 61-param INSERT |
| P1 | Foundation Hardening | Complete | 2026-06-22 | NaN guard, feature_factory_version, 7 new fields |
| P2 | IC Engine Foundation | Complete | 2026-06-22 | BaseBatch, forward_returns, feature_ic_scores tables, APR keys |
| P3 | FeatureFactory Backfill | Complete | 2026-06-23 | 4-symbol full backfill (SPY/TLT/XLF/QQQ) |
| P4 | Regime Writer | Complete | 2026-06-22 | Causal HMM regime labeler |
| P5 | Forward Return Writer | Complete | 2026-06-22 | Writes forward_returns table |
| P6 | IC Engine | Complete | 2026-06-22 | Vectorized Spearman IC computation |
| P6.5 | IC Sortino/Win Rate | Complete | 2026-06-23 | Migration 164, OTel gauges |
| P7 | IC Math Helpers + Tests | Complete | 2026-06-23 | Pure functions, unit tests |
| P8 | IC Pipeline Data Run | Complete | 2026-06-23 | 12,444 IC scores; 683 passing features; discovery report |

**Data State:**

- feature_vectors: 3,787,423 rows (SPY/TLT/XLF/QQQ x 4 TFs; 100% regime coverage)
- forward_returns: 3,787,423 rows (1:1 match with feature_vectors)
- feature_ic_scores: 12,444 rows (1,022 pass walk-forward; 683 non-pooled passers)
- batch_job_checkpoints: rows present
- market_data_ohlcv: 52,438,690 rows (preserved)

**Known Issues (FIXED 2026-06-23):**

- Schema default for feature_ic_scores.regime_label_source was 'filtered', fixed to 'forward_filter' in migration 167
- IC Sharpe NULL bug: Gate used raw-bar window size against subsampled data; fixed by dividing window_size by stride in _compute_ic_rolling_metrics
- P3 backfill requires full corpus run (~20-30h estimated)
- alpha_events table not created (removed from scope during replan)

**Key Decisions (Council Review 2026-06-22):**

- regime_label_source DEFAULT is 'forward_filter' (not 'filtered')
- Pooled IC rows (is_pooled=true) are diagnostic artifacts only
- HMM_RANDOM_STATE = 42 (module-level constant)
- IC Sharpe gate: 20,000 independent observations minimum

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
- [Phase 138 council review 2026-06-22]: HMM_RANDOM_STATE = 42 — module-level constant in regime_writer.py; changing it invalidates all feature_ic_scores rows and requires full regime_writer + ic_engine re-run
- [Phase 138 council review 2026-06-22]: Pooled IC rows (is_pooled=true) are DIAGNOSTIC ARTIFACTS ONLY — written to feature_ic_scores for comparison; Phase 139+ ensemble reads exclusively WHERE is_pooled = false
- [Phase 138 council review 2026-06-22]: IC Sharpe sharpe_window_size = 2000 is in RAW bars (before subsampling); gate is n_raw_bars >= sharpe_min_windows * sharpe_window_size (= 20,000 raw bars), not n_independent
- [Phase 138 council review 2026-06-22]: ON CONFLICT for partial indexes must use column list + WHERE clause — CREATE UNIQUE INDEX produces an index not a named constraint; ON CONFLICT ON CONSTRAINT only works with ADD CONSTRAINT
- [Phase 138 council review 2026-06-22]: regime_label_source DEFAULT is 'forward_filter' (not 'filtered') in both forward_returns and feature_ic_scores
- [Phase 138 council review 2026-06-22]: APR key is alpha.ic.subsample_min_stride (seeded in migration 161), NOT alpha.ic.subsampling_n
- [Phase 138-P0]: TimescaleDB hypertables reject unique indexes unless partitioning column is included; use non-unique partial index + SHA-256 app-layer uniqueness
- [Phase 138-P0]: Content-key formula: SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] as UUID; bar_ts_ns = int(bar_ts.timestamp() * 1e9)
- [Phase 138-P0]: Migration 158 allocated for feature_vector_id; IC engine migrations shifted to 160/161
- [Phase 138 replan 2026-06-22]: Inserted P1 (foundation hardening — council review 12 findings); backfill extracted to standalone P3; now 7 plans (P0 done, P1-P7 pending). Migration 159 = foundation DDL (9 new feature_vectors columns + batch_job_checkpoints). P2 and P3 run in parallel (wave 2). TF-specific bootstrap block size APR keys replace single key.
- [Phase 138-P7]: _build_label_map() signature changed to accept means: np.ndarray instead of model: GaussianHMM -- more testable, call site passes model.means_
- [Phase 138-P7]: BH-FDR order-preservation test uses pairwise monotone check (p[i]<p[j] => q[i]<=q[j]) not argsort equality -- handles cummin ties correctly
- [Migration 167, 2026-06-23]: Fixed feature_ic_scores.regime_label_source DEFAULT from 'filtered' to 'forward_filter' per council review decision; forward_returns already had correct default
- [IC Sharpe bug fix 2026-06-23]: _compute_ic_rolling_metrics now divides sharpe_window_size by stride to convert from RAW bars to SUBSAMPLED bars. sharpe_window_size=2000 (raw) with stride=10 → 200 bars per window in subsampled data. Fix ensures 20,000 raw bars → 10 windows (not 1).

### Blockers / Concerns

- Phase 099 (Guardrails): do not implement unless post-094 parse failure rate > 1%

## Session Continuity

### Last session (2026-06-23) — Phase 138 P8 complete: IC pipeline data run + discovery report

IC engine corpus run completed for SPY, TLT, XLF, QQQ x 4 TFs. 12,444 IC score rows computed in 150s. 1,022 rows pass walk-forward; 683 non-pooled passers in JSON discovery report. Top feature: `quarter_position` (TLT, 15m, trending_up, IC Sharpe 0.870). 1d non-pooled rows empty (below 20K IC Sharpe gate per symbol). IC discovery report written atomically to `docs/analysis/ic-discovery-report.{md,json}`. Unit tests: 5165 passed, 1 pre-existing failure (test_pipeline_backpressure — stale intelligence_pipeline.py reference, unrelated to Phase 138 changes).

Key commits: `4b2fb375` (138-P8 summary + reports)

**Next session:** Execute Phase 139 (ensemble alpha emission)

### Sessions 2026-06-20 to 2026-06-23 (archived summary)

- v2.10 closed; v3.0 started — Feature Factory (Phase 137, 7 plans) complete; IC engine (Phase 138) P1-P7 complete; P3 backfill partial (VUG/1h test data only)
- I5/I6/I7 fully archived; I1-I4 replaced by Feature Factory; `feature_vectors` (not `intelligence_features`) is v3.0 training corpus
- `BaseBatch` Ring 0 base class: `src/core/agent/base_batch.py`; all Phase 138+ batch compute extends it
- AlphaEngine methodology doc: `docs/intelligence/intelligence-alphaengine.md`; IC methodology: `docs/plans/2026-06-20-alphaengine-v1-methodology.md`
- Regime-conditional IC only (pooled IC is diagnostic artifact, `is_pooled=true`); IC Sharpe gate: 20,000 independent obs

## Current Position

Milestone: v2.10 — COMPLETE (2026-06-20)
Milestone: v3.0 — IN PROGRESS — AlphaEngine (Intelligence Vectors, V1 Quant)
Phase: 138
Phase: 138 (ic-engine-forward-returns) — COMPLETE (P0-P8 all done; 12,444 IC scores; discovery report at docs/analysis/)
Phase: 135 (controlled-vocabulary-system) — deferred
Last activity: 2026-06-23 -- Phase 138 P8 complete; Phase 139 planned and ready

**Phase 126 research artifact**: `docs/plans/2026-06-14-phase-126-signal-universe-hardening.md`

## Performance Metrics

| Phase | Plan | Duration | Notes |
|-------|------|----------|-------|
| Phase 123 P01 | 20 | 5 tasks | 26 files |
| Phase 136 P05 | 12 | 3 tasks | 0 files |
| Phase 136 P06 | 5 | 3 tasks | 0 files |
| Phase 138 P07 | 25 | 2 tasks | 10 files |
