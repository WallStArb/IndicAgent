# Phase 140-P2 Summary: Collinearity Clustering + Representative-Only BH-FDR

## What Was Changed

### `services/ic_engine.py`

**Imports added (lines 58-59):**
- `from scipy.cluster.hierarchy import fcluster, linkage`
- `from scipy.spatial.distance import squareform`

**`_load_apr` — new APR key:**
- `cluster_max_corr`: loaded from `alpha.ic.cluster_max_corr` (seeded at 0.70 in migration 171)

**`_INSERT_BODY` — new column:**
- Added `cluster_id` to the column list and `%(cluster_id)s` to VALUES
- ON CONFLICT clauses unchanged (cluster_id is not a key column)

**`_cluster_features()` — new pure helper:**
- Distance-threshold dendrogram clustering (average linkage) on non-degenerate feature columns
- Distance metric: `sqrt(0.5 * (1 - corr))` — maps correlation to [0, 1] distance
- Threshold: `sqrt(0.5 * (1 - cluster_max_corr))`
- Returns 1-based int cluster labels (one per column of X_nd)
- NOTE: dendrogram distance cutoff, not a pairwise correlation guarantee -- transitive
  linkage can merge features whose direct pairwise correlation is below cluster_max_corr

**`_compute_symbol_tf` — per-regime clustering:**
- Extracts `cluster_max_corr` from `apr` dict alongside other APR values
- After degenerate detection produces `X_sub_nd` and `non_degenerate_mask`, calls
  `_cluster_features(X_sub_nd, cluster_max_corr)` once per (symbol, tf, regime)
- Builds `cluster_id_full[n_features]`: None for degenerate columns, int cluster label
  for non-degenerate columns
- Logs cluster count and feature count via `ic_engine.clustering` structlog event
- Each result dict now includes `"cluster_id": cluster_id_full[feat_idx]`

**BH-FDR block -- representative-only selection:**
- Previous: all non-degenerate features entered `multipletests`
- New: within each `(regime_label, lookahead_bars, cluster_id)` group, only the feature
  with max(abs(ic_value)) is submitted to BH-FDR
- Non-representatives: `bh_adjusted_p=None`, `passes_fdr=False` written directly
- Degenerate features (cluster_id is None, p_value is None): `passes_fdr=False` as before
- `multipletests` called on representatives only; results written back via `pval_result_idxs`

### `tests/unit/test_ic_engine_clustering.py` — new test file

Three unit tests:
1. `test_correlated_pairs_cluster_together` -- two perfectly-correlated pairs + one
   independent feature yields 3 distinct clusters with pairs grouped together
2. `test_single_feature` -- single column returns length-1 label array
3. `test_all_identical_features` -- all identical columns collapse to one cluster

## Verification Results

```
ruff check services/ic_engine.py --fix   -> All checks passed!
black services/ic_engine.py              -> 1 file left unchanged.
python3 -c "ast.parse(...)"              -> OK
pytest tests/unit/test_ic_engine_clustering.py -v  -> 3 passed
pytest tests/unit/ -q                   -> all passing (no new failures)
```

## Re-Run Required

**IC scores must be re-run after this change.** BH-FDR results will differ:
- Feature rows that were previously FDR-passing representatives of collinear clusters may
  now be non-representatives (passes_fdr=False, bh_adjusted_p=None)
- The effective multiple-testing burden is reduced (fewer hypotheses enter multipletests)
- cluster_id column is now populated for all new rows

Truncate `feature_ic_scores` and re-run `services/ic_engine.py` after deploying P2.
