---
id: "031"
title: "Renaissance IC gate redesign — continuous weighting replaces binary Sharpe gate"
priority: P0
phase: A
status: pending
created: 2026-06-30
---

# Renaissance IC Gate Redesign

## Problem

The current ensemble_trainer gates on `passes_walkforward = true` (all 3 WF folds positive IC)
and the Phase 141 validation report used `ic_sharpe_hac > 0.5` as its qualifying criterion.
Both are binary filters that discard genuinely positive-expectation signals.

Jim Simons would not build this. Renaissance's entire edge comes from aggregating MANY WEAK
SIGNALS. A feature with IC=0.04 and ic_sharpe=0.2 that passes ci_lower > 0 and BH-FDR is
a real edge — at 58 symbols × ensemble scale it contributes meaningfully to alpha.

## Root cause findings (A1 investigation 2026-06-30)

- 5m has 721/2196 cells with ic_ci_lower > 0 (genuine positive IC at 95% CI)
- 0 of those pass passes_walkforward=true (all 3 folds positive) — too strict for noisy data
- ic_sharpe_hac > 0.5 was an analysis threshold, not a production gate
- The binary gates discard real edges; this is anti-Renaissance

## Files

- `services/ensemble_trainer.py` — WHERE clause on feature_ic_scores, startup gate
- `src/intelligence/ensemble/feature_selector.py` — select_features_per_stratum
- `src/intelligence/ensemble/__init__.py` — derive_weights, cluster_deflate_weights

## Design (Renaissance council prescription)

### Gate: statistical significance only

Replace `passes_walkforward = true` with:
```sql
ic_ci_lower > 0          -- IC is statistically significantly positive (95% CI)
AND passes_fdr = true    -- survives BH-FDR correction (corpus-level after A2 P2)
AND reliable = true      -- n_independent >= min_reliable_n
AND ic_sharpe_hac IS NOT NULL  -- enough windows to compute (completeness check only)
```

`passes_walkforward` becomes a weight DECAY factor, not a binary gate.
A feature where wf_pass_count=2/3 folds has lower consistency than wf_pass_count=3/3
but is NOT excluded.

### Weight: continuous quality-adjusted IC

Replace ic_sharpe_hac selection in select_features_per_stratum with quality-adjusted weight:

```
quality_weight = ic_ci_lower * max(sharpe_floor, ic_sharpe_hac)
```

where sharpe_floor ≈ 0.05 (APR: alpha.ensemble.sharpe_floor) ensures features with
positive CI but near-zero Sharpe still get a small positive weight.

The select_features_per_stratum lookahead selection should pick the lookahead with the
highest quality_weight (not just highest ic_sharpe).

derive_weights uses quality_weight as the raw weight input, then applies:
- Ledoit-Wolf cluster deflation (existing, keep)
- max_feature_weight cap (existing, keep)
- max_cluster_weight cap (existing, keep)

### Startup gate

Replace:
```sql
passes_walkforward = true
```
with:
```sql
ic_ci_lower > 0 AND passes_fdr = true
```

### APR keys to add

- `alpha.ensemble.sharpe_floor` = 0.05 (floor for ic_sharpe_hac in weight formula)
- `alpha.ensemble.wf_consistency_factor` = 0.5 (weight multiplier when wf_pass_count < walk_forward_folds)

## What stays the same

- Ledoit-Wolf cluster deflation
- max_feature_weight, max_cluster_weight caps
- meta_fdr_min_fraction gate (feature must pass FDR in >=50% of eligible cells)
- min_passing_features per stratum (but now more features will qualify)
- BH-FDR (corpus-level after A2 P2 fix)

## Expected outcome

- 5m features with ic_ci_lower > 0 (721 cells) become eligible
- They get low weights (small ic_ci_lower × small ic_sharpe_hac) — correct behavior
- 1h features keep their higher weights (stronger IC, higher Sharpe)
- Phase B gate PASS likely for 5m (features present, low weight is fine)
- Net: broader ensemble, more diversified alpha, Renaissance-grade design

## Do after A2 (P0/P2/P3/P4) — needs corpus re-run to validate weights
