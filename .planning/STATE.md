---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: Phase 143.1 (Measurement and Eligibility Integrity) in progress, corpus re-run running
stopped_at: Phase 161 complete (4/4), live-verified
last_updated: 2026-07-18T01:00:44.978Z
progress:
  total_phases: 12
  completed_phases: 6
  total_plans: 40
  completed_plans: 49
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Alpha must be demonstrated empirically before any ensemble weight is assigned.

**Current focus:** Phase 143.1 (Measurement and Eligibility Integrity) — corpus re-run in progress. Phase 161 (Controlled Vocabulary System) completed 2026-07-18, live-verified, does not change 143.1's blocking status. `gsd-sdk query phase.complete` incorrectly reported `is_last_phase: true`/`status: milestone_complete` after 161 closed — the same "next phase" heuristic false-positive already seen after Phase 146 (see git history); corrected inline. Milestone v3.1 is NOT complete: 143.1 is still active, and 144/145/147/148/149A/149B/150 remain ahead of it.

**Next actions, in order:** (1) 143.1-07 finishes → 143.1-08 (shadow-mode sign-symmetric validation, E1-vs-E2 A/B re-run). (2) Phase 144's D-05 acceptance gate (`scripts/analysis/phase144_regime_separation_gate.py`) re-runs against the corrected corpus — no code changes needed, just the re-run. (3) FRAME-04 (`alpha_frames`/`CounterfactualTracker` gate) re-evaluates once 143.1-07 lands. (4) Phase 148 (Alpha Scoring System OOS Proof Gates) needs ≥60 trading days of closed `alpha_frames` plus the corrected 143.1 corpus before its gates can evaluate. (5) todo 092 (equity/cross-sectional regime-model threshold calibration) is the live-path IC-tail suspect worth prioritizing once the corpus clears.
**Execution plan:** `docs/plans/2026-06-30-alphaengine-v1-execution-plan.md`

## v3.0 Phase Summary (SHIPPED 2026-06-25)

| Phase | Name | Status |
|-------|------|--------|
| 137 | Feature Factory | COMPLETE (7/7 plans, 2026-06-21) |
| 138 | IC Engine + Forward Returns | COMPLETE (9/9 plans, 2026-06-23) |
| 139 | Ensemble + Alpha Emission | COMPLETE (3/3 plans, 2026-06-24; 14/14 verification truths) |
| 140 | IC Engine Correctness | COMPLETE (4/4 plans, 2026-06-25) |

## v3.1 Phase Summary (IN PROGRESS)

| Phase | Name | Status |
|-------|------|--------|
| 140.5 | Corpus Foundations + Feature Governance | COMPLETE (5/5 plans) |
| 141 | Corpus Quality Gate + IC Validation | COMPLETE (3/3 plans) |
| 141.1 | Measurement and Decision Integrity Foundation | COMPLETE (4/4 plans) |
| 142A | Ensemble IC Measurement | COMPLETE (2/2 plans) — EIC-04 current verdict PASS 54/1425=3.79%, see [Corpus pipeline state](project_corpus_pipeline_state.md) for the live number |
| 142B.1 | Ensemble Weighting Methodology | COMPLETE (5/5 plans) — E1 (shrunk-IC) is champion; E2 (mean-variance) rejected |
| 142.5 | Renaissance Primitives | COMPLETE (8/8 plans) — 89 primitives live in Feature Factory, 150 total `FeatureVector` fields |
| 142B | Frame Simulation + Counterfactual Tracking | COMPLETE (2/2 plans) — `alpha_frames` hypertable + `AlphaFrameWriter` + `CounterfactualTracker` live |
| 143 | Feature Lifecycle Routing (merged with 149B) | COMPLETE (3/3 plans) — `feature_registry` evidence-based promotion/demotion + `integrity_monitor` table live |
| 143.1 | Measurement and Eligibility Integrity | IN PROGRESS (7/8 plans) — corpus re-run active, see "Current focus" above |
| 144 | Cross-Sectional Regime Model (`regime_group`) | Code-complete (6/6 plans); header stays PLANNED until D-05's acceptance gate re-runs post-143.1 |
| 146 | Empirical Instrument Tag Calibrator | COMPLETE (5/5 plans, 2026-07-17) — `TagCalibrator` live-verified: 11/12 measurable tags carry real `source='empirical'` rows |
| 160 | Concept Registry MVP | COMPLETE (4/4 plans) — 4-table schema + `ConceptRegistryService`/`ConceptRegistryAPI`/`ConceptRegistryDashboard` live |
| 161 | Controlled Vocabulary System | COMPLETE (4/4 plans, 2026-07-18) — schema + `VocabularyService` + `vocabulary_drift` audit + `/api/vocabulary/{namespace}` route, live-verified (VERIFICATION.md: passed, 23/24 truths, 1 accepted YAGNI override) |

Current row counts and every downstream measurement number live in
[Corpus pipeline state](project_corpus_pipeline_state.md) — that file is the single source of
truth; don't duplicate counts here.

**Dual regime system (both live):**

- `feature_vectors.regime` — 5 per-symbol HMM labels (trending_down/transition_down/ranging/transition_up/trending_up), written by `regime_writer.py` (K=5, causal forward-filter)
- `market_regimes` — cross-sectional labels keyed by `regime_group` (a named peer group with a pluggable regime signal: `breadth_vol` for equity, `curve_credit` for rates; commodity/fx modules ship disabled), written by `cross_sectional_regime_model.py` (Phase 144, replaced `equity_regime_model.py`); `ic_engine` stratifies on these

## Key Decisions (load-bearing — don't re-derive)

- **HMM_RANDOM_STATE = 42** — changing invalidates all feature_ic_scores, requires full re-run
- **Pooled IC (is_pooled=true)** — cross-sectional POOLED strata ARE the ensemble training eligibility source. `ensemble_trainer.py` reads `WHERE symbol='POOLED' AND is_pooled=true AND regime != '_pooled'` (lines 317, 430-431, 469, 540)
- **IC Sharpe gate** — sharpe_window_size=2000 RAW bars; gate is n_raw_bars >= 20,000; stride divides inside _compute_ic_rolling_metrics
- **regime_label_source DEFAULT** — 'forward_filter' (not 'filtered') in both forward_returns and feature_ic_scores
- **APR key** — alpha.ic.subsample_min_stride is a floor: actual_stride = max(min_stride, lookahead_bars)
- **Gradient naming** — return_fast/mid/slow/extended; momentum_z_fast/mid/slow; volatility_rank_z
- **ON CONFLICT for partial indexes** — use column list + WHERE clause, not ON CONSTRAINT (TimescaleDB)
- **Corpus re-run required** after Phase A ic_engine methodology fixes (028 P0/P2/P3/P4 change IC scores corpus-wide)

## Corpus Pipeline Gotcha

`--compute-only` silently skips all symbols if backfill_status is empty. After any truncation, seed first:

```sql
INSERT INTO backfill_status (symbol, tf, fetch_complete, status)
SELECT DISTINCT symbol, timeframe, true, 'pending'
FROM market_data_ohlcv WHERE timeframe IN ('5m', '15m', '1h', '1d')
ON CONFLICT (symbol, tf) DO UPDATE SET fetch_complete = true;
```

## Roadmap Evolution

- Phase 162 added (2026-07-18): ic_engine Corpus Pipeline Throughput — bundles todos 134/133/122. Not yet planned; hold `/gsd-discuss-phase 162` until the in-flight 143.1-07 corpus run finishes (resource contention).
- Phase 163 added (2026-07-20): VP/SR Structural Primitives — closes todo 153 (poc_dist_atr/va_position/sr_support_dist/sr_resist_dist permanently stuck at constant defaults since v3 rebuild). Sibling atomic-expansion item to Phase 151, not folded into it. No dependency on the in-flight todo-147 CV recheck or 094 shadow-mode validation running elsewhere — safe to plan/execute now. Scope widened same day: port ctx_VolumeProfile (I4, 18 fields) instead of the thinner i3_structure/market_profile.py originally identified — self-contained, no known bugs, same computation cost.
- Phase 164 added (2026-07-20): SMC Institutional Footprint Primitives — atomic distance/strength/duration/count primitives ported from the archived v2.x smc_context plugins (order blocks, FVG, liquidity sweeps/pools, supply/demand zones, AMD cycle, breaker/mitigation blocks, BOS/CHoCH). All self-contained on already-live shared utils, no cross-plugin dependency chain. Sequenced after Phase 163 for shared conventions, not a hard code dependency.

## Session

**Last session:** 2026-07-17T09:11:43.443Z
**Stopped At:** Phase 146 complete (5/5 plans), code-reviewed, live-verified (VERIFICATION.md: passed, 9/9)
**Resume File:** none — phase closed; next active thread is 143.1's corpus re-run (see "Current focus" above)
