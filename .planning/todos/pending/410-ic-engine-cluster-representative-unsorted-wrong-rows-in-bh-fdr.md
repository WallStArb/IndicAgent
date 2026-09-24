---
status: pending
priority: P0
filed: 2026-09-24
source: AGY adversarial review of the Phase 179 pre-registration (finding 3), verified against code and live data
---

# ic_engine cluster representative selection puts the wrong rows into the corpus BH-FDR family

## What

`services/ic_engine.py` (per-symbol path ~3631 and cross-sectional path ~5201) picks
`rep_result_idx = max(candidates, key=abs_ic)` correctly, but then marks `candidates[1:]` as
non-representatives (`passes_fdr=False`, `bh_adjusted_p=None`) without sorting `candidates`.
When the max-|IC| row is not first in insertion order:

- the true representative is marked `passes_fdr=False` at compute time, and
- `candidates[0]` (a non-representative) is left `passes_fdr IS NULL`, so `_backfill_bh_fdr`
  (which selects pending rows and uses their own `p_value`) puts it into the corpus family.

The in-memory `pvals_flat` does hold the right p-value, but the DB backfill never uses it.

Live, 2026-09-24: 681,851 `feature_ic_scores` rows carry a `bh_adjusted_p` although a same-cluster
peer (same symbol, tf, regime, lookahead_bars, cluster_id) has higher |IC|; 2,842 of them have
`passes_fdr = true`. Every consumer of `passes_fdr` is affected: ensemble eligibility,
meta-FDR rates, the lifecycle node, every gate verdict that cited FDR passes.

## Fix direction

Mark every candidate except `rep_result_idx` (not `candidates[1:]`), in both places, via one
shared helper with a test that puts the max second. The correction itself does not need a full
recompute: `p_value`, `ic_value` and `cluster_id` are stored, so representatives can be
re-derived from stored rows and BH re-run for the window as an UPDATE. Land with the Phase 178
bundle and re-run shrinkage, the trainer and the publisher after it. Phase 179's harness uses the
corrected helper (pre-registration deviation D6).
