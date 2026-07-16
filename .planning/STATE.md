---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: Phase 143.1 (Measurement and Eligibility Integrity) in progress, corpus re-run running
stopped_at: Phase 161 context gathered
last_updated: "2026-07-16T23:31:54.182Z"
progress:
  total_phases: 12
  completed_phases: 6
  total_plans: 36
  completed_plans: 34
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Alpha must be demonstrated empirically before any ensemble weight is assigned.

**Current focus:** Phase 143.1 (Measurement and Eligibility Integrity) is 7/8 plans complete. The corpus re-run (143.1-07) is in progress: per-symbol IC pass finished 80/80 at 2026-07-16 18:36 UTC; the cross-sectional POOLED pass is now running (duration uncertain — the first regime group alone historically takes ~9h, and this pass covers many more regime×tf groups). `feature_ic_scores` is 0 rows until this pass flushes. Plan 08 (shadow-mode validation + E1-vs-E2 A/B re-run) and Phase 144's D-05 acceptance gate are both blocked on this run finishing.

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
| 160 | Concept Registry MVP | COMPLETE (4/4 plans) — 4-table schema + `ConceptRegistryService`/`ConceptRegistryAPI`/`ConceptRegistryDashboard` live |
| 161 | Controlled Vocabulary System | PLANNED, not started — fully unblocked, safe to plan now |

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

## Session

**Last session:** 2026-07-16T23:31:54.145Z
**Stopped At:** Phase 161 context gathered
**Resume File:** .planning/phases/161-controlled-vocabulary-system-planned/161-CONTEXT.md
