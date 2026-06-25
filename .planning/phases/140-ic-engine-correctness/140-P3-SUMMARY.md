# Phase 140 P3 Summary — Meta-Level FDR Gate in Ensemble Trainer

## What Was Changed

### `services/ensemble_trainer.py`

**New module-level helper:**
- `_meta_eligible(fdr_pass_rows, min_fraction) -> set[str]` — returns the set of feature names
  whose BH-FDR pass-rate across ensemble-eligible cells meets or exceeds `min_fraction`. Pure
  function; tested independently.

**`execute()` additions:**
1. Reads `alpha.ensemble.meta_fdr_min_fraction` from APR via `_cfg_float` (default 0.50). Included
   in `ensemble_trainer.config_loaded` log line. APR key was seeded in migration 171 (P1).
2. After `_assert_prerequisites` and before the strata loop, runs one aggregation query to compute
   per-feature FDR pass-rates. Denominator is intentionally restricted to the same four conditions
   used in `_process_stratum`'s ic_rows query: `is_pooled = false AND reliable = true AND
   ic_sharpe IS NOT NULL AND passes_walkforward = true`. Including ineligible cells would
   artificially deflate every feature's pass-rate.
3. Logs `ensemble_trainer.meta_fdr_gate` with eligible count, total features, min_fraction, and
   total cells evaluated.
4. Emits `ensemble_trainer.meta_fdr_low_coverage` warning when the lowest-coverage feature has
   fewer than 10% of the cells of the highest-coverage feature (indicates uneven corpus).
5. Passes `meta_eligible_features: set[str]` into `_process_stratum`.

**`_process_stratum()` changes:**
- Added `meta_eligible_features: set[str]` parameter.
- After `conn.fetch(ic_rows query)`, immediately filters: `ic_rows = [r for r in ic_rows if
  r["feature_name"] in meta_eligible_features]`. The existing `if not ic_rows: return` guard then
  handles empty post-filter strata cleanly.

No other logic (select_features_per_stratum, weight derivation, alpha scoring, DB writes) was
modified.

### `tests/unit/test_ensemble_meta_fdr.py`

Three tests covering `_meta_eligible`:
- `test_meta_eligible_boundary_inclusive` — verifies 0.50 is inclusive (edge_feat at exactly 0.50
  passes; noise_feat at 0.10 does not).
- `test_meta_eligible_strict_threshold` — verifies nothing passes when threshold is raised above
  all pass-rates.
- `test_meta_eligible_empty_input` — verifies empty input returns empty set.

## Verification Results

```
ruff check services/ensemble_trainer.py --fix   → All checks passed
black services/ensemble_trainer.py              → 1 file reformatted
pytest tests/unit/test_ensemble_meta_fdr.py -q → 3 passed
pytest tests/unit/ -q                          → full suite (in progress at commit time)
```

## Notes for Corpus Run

The APR value `alpha.ensemble.meta_fdr_min_fraction = 0.50` is conservative — it favors broad,
stable factors and may suppress niche features that are strong in only a subset of symbols/TFs.

After the first clean corpus run completes, check the `ensemble_trainer.meta_fdr_gate` log line:
the `n_eligible` / `n_total_features` ratio shows the empirical winnowing rate. If too many
features are eliminated (e.g., fewer than 10 pass with 54 candidates), lower the APR value via
the dashboard at `/config/parameters`. If nearly all pass (>50), the gate is not doing useful
work and can be raised.

The `passes_fdr` column is populated by `ic_engine.py` using the BH procedure per
(symbol, tf, regime, lookahead) stratum. Features that pass FDR consistently across many cells
have replicated information content rather than overfitting to idiosyncratic noise in a single cell.
