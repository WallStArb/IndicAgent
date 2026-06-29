# Phase 141 — Corpus Quality Gate + IC Validation + HMM JIT

**Status:** IN PROGRESS  
**Plan:** `docs/plans/2026-06-28-validity-fixes-and-phase-141.md`  
**Milestone:** v3.1 AlphaEngine Validation + Alpha Scoring

## Scope

Three validity fixes + corpus rerun + full CORPUS-01..07 validation + HMM Numba JIT.

| Plan | Wave / Task | CORPUS req | Description |
|---|---|---|---|
| P0 | T0 | — | APR migration 182 — equity_regime_model windows in existing `alpha.regime.*` namespace + `alpha.validation.oos_start` (CORPUS-02) + `alpha.ic.min_obs_per_regime=3000` (CORPUS-06) |
| P0 | T1 | — | V3 BaseBatch JSONB codec — replace bare asyncpg.create_pool with `database_manager.create_pool`; remove alpha_publisher json.dumps()/::jsonb workaround (atomic) |
| P0 | T2 | — | V1 equity_regime_model causal expanding rank (NaN-propagating, average-rank ties) + TF-normalized windows |
| P0 | T3 | — | Partial corpus rerun: truncate market_regimes/cs-IC/ensemble/alpha_events → rerun equity_regime_model → ic_engine --cross-sectional-only → ensemble_trainer → alpha_publisher |
| P1 | T0 | CORPUS-01 | Feature distribution audit (variance/NaN/cliff) → `docs/analysis/corpus-01-feature-audit.md` |
| P1 | T1 | CORPUS-04/05 | IC validation queries (top features, per-TF, per-regime, NULL rate, calibration, gate) |
| P1 | T1.5 | CORPUS-02/03 | OOS holdout split (writes `alpha.validation.oos_start`) + null-model baseline (IC-weighted vs equal-weight, >0.1 advantage gate) |
| P1 | T2 | CORPUS-04 | IC validation report → `docs/analysis/ic-validation-report-58sym.md` |
| P1 | T2b | CORPUS-06 | Per-regime observation floor check (cells below 3000 independent obs) appended to report |
| P1 | T3 | CORPUS-07 | I7→feature dimension mapping → `docs/analysis/i7-feature-mapping.json` |
| P2 | T1-T3 | — | HMM Numba JIT: `src/intelligence/hmm_jit.py` + wire into regime_writer (main-process pre-compile, no worker race); declare `numba>=0.65.0` |

## Gates

- Phase 141 analysis (P1) runs on V1-corrected corpus only — not the stale corpus
- P1-T1 Step 7 produces V2 cost calibration constants (IC × return_scale per tf/regime)
- CORPUS-03 null-model gate: IC-weighted IC Sharpe must exceed equal-weight by >0.1 on OOS data
- Phase 141 gate (P1-T2): GLOBAL ≥5 features per TF (5m, 1h) with |ic_sharpe_hac|>0.5 AND ic_ci_lower>0; sparse minority regimes do not block PASS
- Phase 142 planning begins after the gate assessment = PASS
- V2 (cost-aware net scoring) gets its own plan using the P1-T1 calibration constants

## V2 Deferred

alpha_score is in weighted z-score product units (X @ signed_weights), not log-return units.
Cost subtraction requires IC calibration constants from P1-T1 Step 7. V2 plan written after Phase 141.
