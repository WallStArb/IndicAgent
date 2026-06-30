# HMM Rolling Refit Pilot — Parameter Look-ahead Bias Test

Date: 2026-06-29
Status: IN PROGRESS
Phase: P4a experiment from HMM Regime Audit & Optimization Plan

## Thesis

Current HMM regime labels have **parameter look-ahead bias**: emission parameters and transition matrix learned from full history (2019-2026), then causally decoded via forward-filter. While the forward-filter is causally correct, the parameters were estimated using future data relative to early training bars — contaminating regime labels for 2019-2021 periods with 2024-2026 market structure.

This is distinct from decoder look-ahead (which we fixed with forward-filter). This is **parameter** look-ahead: the model itself was trained on test data.

## Hypothesis

Rolling refit (3-year window, annual step) will produce materially different regime labels compared to current full-history fit, and IC scores stratified by rolling-refit regimes will show significantly better separation because parameters are estimated only from data available at each point in time.

**Null hypothesis (H0):** Parameter look-ahead bias is empirically negligible — IC scores don't materially improve under rolling refit.

**Alternative hypothesis (H1):** Parameter look-ahead bias is real — IC scores improve ≥10% under rolling refit, regime boundaries shift meaningfully.

## Experimental Design

### Scope

**Symbols:** SPY, TLT (2 symbols — high-volume ETFs, diverse market exposure)
**Timeframes:** 5m, 1h (intraday — where regime detection matters most)
**History:** 2019-2024 (5m) / 2014-2024 (1h) — actual backfill depths

### Method

**Current approach (baseline):**
1. Fit HMM once on full available history (all bars 2014-2024)
2. Extract emission parameters and transition matrix
3. Causally decode via forward-filter (Numba JIT)
4. Write regime labels to `feature_vectors.regime` (current canonical labels)

**Rolling refit approach (treatment):**
1. For each time point (annual step): fit HMM on 3-year rolling window
2. Extract parameters from that window only
3. Causally decode bars in that year using forward-filter
4. Write regime labels to shadow column `feature_vectors.regime_rolling`

**Comparison:**
1. Compute IC scores stratified by `regime` (current) vs `regime_rolling` (rolling refit)
2. Compare IC value per regime, regime separation, statistical significance
3. Analyze label disagreement rate — where do boundaries shift?

### Metrics

| Metric | Definition | Pass Gate |
|--------|------------|-----------|
| **Regime IC separation** | Mean absolute IC difference between regimes | ≥10% improvement |
| **IC delta p-value** | Statistical significance of IC difference | p < 0.05 |
| **Label disagreement** | Fraction of bars where regime_current ≠ regime_rolling | ≥20% (meaningful shift) |
| **Per-regime IC delta** | IC change per regime (trending_up, ranging, etc.) | Directionally consistent |

### Success Criteria

**PASS — Implement P4a full corpus:**
- Regime IC separation improves ≥10% under rolling refit
- p-value < 0.05 for IC difference (statistically significant)
- Regime boundaries shift meaningfully (≥20% label disagreement)
- Per-regime IC deltas are directionally consistent (not noise)

**FAIL — Drop P4a and P4b:**
- IC delta < 5% and not statistically significant (p ≥ 0.05)
- Regime labels highly similar (≥80% agreement) — boundaries don't shift
- Bias is theoretically real but empirically negligible

**INCONCLUSIVE — Run broader test:**
- Marginal significance (0.05 < p < 0.10)
- Mixed signals (some regimes improve, others degrade)
- Expand to 5 symbols, 4 TFs

## Implementation Plan

### Code Changes

1. **`services/regime_writer_rolling_pilot.py`** (new)
   - Subset to 2 symbols, 2 TFs
   - Rolling refit logic: 3-year window, annual step
   - Write to `regime_rolling` column (not canonical `regime`)

2. **Schema migration**
   - Add `feature_vectors.regime_rolling` TEXT (nullable, for pilot)
   - Index on `(symbol, tf, regime_rolling)` for IC queries

3. **`scripts/experiments/run_rolling_refit_pilot.py`** (new)
   - Call regime_writer_rolling_pilot
   - Run IC engine comparison
   - Generate results report

### Runtime Estimate

- Rolling refit (172 HMM fits): ~15 min
- IC engine comparison (4 symbol-TF cells): ~15 min
- **Total: ~30 minutes**

## Results

_To be filled after experiment runs_

### Regime IC Separation

[Current: X | Rolling: Y | Delta: Z%]

### Label Disagreement Rate

[Same: A% | Different: B%]

### Per-Regime IC Delta

| Regime | Current IC | Rolling IC | Delta |
|--------|------------|------------|-------|
| trending_up | ... | ... | ... |
| ranging | ... | ... | ... |
| trending_down | ... | ... | ... |

### Statistical Significance

[p-value: ... | CI: ...]

### Decision

[PASS / FAIL / INCONCLUSIVE]

### Follow-up Actions

[If PASS: Full corpus rollout plan]
[If FAIL: Close todos 026-P4a and 026-P4b]
[If INCONCLUSIVE: Expanded test design]

## References

- Parent plan: `docs/plans/2026-06-28-hmm-regime-audit-optimization.md`
- Todo: `.planning/todos/pending/026-hmm-regime-audit-optimization.md` (items P4a, P4b)
- HMM improvement background: `project_hmm_improvement_decisions.md`
