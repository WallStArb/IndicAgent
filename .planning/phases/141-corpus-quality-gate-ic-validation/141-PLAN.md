# Phase 141 — Corpus Quality Gate + IC Validation + HMM JIT

**Status:** IN PROGRESS  
**Plan:** `docs/plans/2026-06-28-validity-fixes-and-phase-141.md`  
**Milestone:** v3.1 AlphaEngine Validation + Alpha Scoring

## Scope

Three validity fixes + corpus rerun + IC validation analysis + HMM Numba JIT.

| Milestone | Task | Description |
|---|---|---|
| 1 (V3) | Tasks 1-2 | BaseBatch JSONB codec — register via database_manager.create_pool; remove json.dumps() workarounds |
| 2 (V1) | Tasks 3-5 | equity_regime_model causal expanding rank (V1a) + TF-normalized windows (V1b) |
| 3 | Task 6 | Partial corpus rerun: truncate market_regimes/cs-IC/ensemble/alpha_events → rerun equity_regime_model → ic_engine --cross-sectional-only → ensemble_trainer → alpha_publisher |
| 3 | Task 7 | Phase 141 IC validation analysis → `docs/analysis/ic-validation-report-58sym.md` |
| 4 (S1) | Tasks 8-10 | HMM Numba JIT: `src/intelligence/hmm_jit.py` + wire into regime_writer |

## Gates

- Phase 141 analysis (Task 7) runs on V1-corrected corpus only — not current corpus
- Task 7 Step 7.5 produces V2 cost calibration constants (IC × return_scale per tf/regime)
- Phase 142 planning begins after Task 7 gate assessment = PASS
- V2 (cost-aware net scoring) gets its own plan using Task 7.5 constants

## V2 Deferred

alpha_score is in weighted z-score product units (X @ signed_weights), not log-return units.
Cost subtraction requires IC calibration constants from Task 7.5. V2 plan written after Phase 141.
