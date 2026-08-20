---
status: pending
priority: P0
filed: 2026-08-19
source: investigating why commodity/5m/up_primary_contango was large enough to breach alpha.ic.max_cell_rows (migration 259, then 319)
---

# `_bucket()`'s ascending-sort contract is violated by 2 of 4 regime_signals modules — commodity and fx tier1/tier2 labels are wrong, confirmed live in market_regimes

## What's broken

`services/cross_sectional_regime_model.py::_bucket()` requires its `tiers` argument sorted
**ascending** by upper_bound, with the last tuple's bound ignored (only its name used as the
catch-all default) — this is stated explicitly in `_bucket`'s own docstring. Two of the four
`REGISTRY` modules violate this:

**`commodity_momentum_ts.build_tiers()`** (`src/intelligence/regime_signals/commodity_momentum_ts.py:111`):
```python
tiers1 = [("up_primary", primary), ("up_secondary", 0.0), ("down_secondary", -primary)]
```
Sorted **descending** (primary=0.75 > 0.0 > -0.75). Fed through `_bucket()`, this produces:
`momentum_z < 0.75` → `"up_primary"` (swallows neutral AND all negative/down momentum),
`momentum_z >= 0.75` → `"down_secondary"` (only fires for strongly POSITIVE momentum — backwards).
`"up_secondary"` is mathematically unreachable — the last-applied `where()` clause (for
`up_primary`, upper=0.75) unconditionally overwrites it since 0.0 < 0.75. The module's own
docstring claims a 4th label `"down_primary"`, which doesn't exist anywhere in the actual
`tiers1` list — docstring and code have already diverged.

**`fx_dollar_carry.build_tiers()`** (`src/intelligence/regime_signals/fx_dollar_carry.py`):
```python
tiers1 = [("strong_dollar", dollar_thresh), ("weak_dollar", -dollar_thresh)]  # dollar_thresh=0.5
tiers2 = [("risk_on", carry_thresh)]  # carry_thresh=0.0, single entry
```
Same inversion on tiers1: `dollar_z < 0.5` → `"strong_dollar"` (backwards), `dollar_z >= 0.5` →
`"weak_dollar"` (backwards). tiers2 has only ONE tuple, so `tiers[:-1]` is empty, the loop never
executes, and `_bucket()` returns `tiers[-1][0] = "risk_on"` for literally every row regardless
of `carry_z` — `"risk_off"` is unreachable, not just rare.

## Confirmed empirically, not just by code-reading

Full historical `market_regimes` table, all timeframes, both groups:

```
commodity: only up_primary_* and down_secondary_* ever appear. Zero up_secondary rows.
           Zero down_primary rows. Ever. Any timeframe.
fx:        only *_risk_on ever appears. Zero *_risk_off rows. Ever. Any timeframe.
```
This is not "these states are rare" — a semantic simulation of `_bucket()` at the real APR
threshold values (`primary_threshold=0.75`, `dollar_strong_threshold=0.5`,
`carry_risk_on_threshold=0.0`) reproduces exactly this label space and no other, confirming the
code-level diagnosis rather than a coincidental data pattern.

**`breadth_vol` (equity) and `curve_credit` (rates) are NOT affected** — both modules' tier
lists are correctly ascending-sorted; equity's real 9-way and rates' real 6-way label
distributions both match their intended full vocabularies.

## Why this matters (and how it was found)

Directly implicated in the 2026-08-19 `alpha.ic.max_cell_rows` breach (see migration 319):
`commodity/5m/up_primary_contango` hit 4,687,380 rows — by far the largest cell in the entire
4-group corpus run — because it's a mislabeled catch-all swallowing most of the true momentum
distribution (up AND down), not a genuine minority-regime cell. The oversized-cell symptom is
downstream of this labeling bug, not an independent sizing issue.

More importantly: every `feature_ic_scores` row currently stratified by a `commodity` or `fx`
`regime_label`, and any `ensemble_weights`/`ensemble_alpha` trained from those regime-conditional
IC scores, has been measuring predictive power conditional on a **mislabeled** regime for as
long as these two groups have been enabled. This corrupts the "segment by regime" principle
specifically for these two groups — equity and rates are unaffected.

## Fix

1. Sort `tiers1`/`tiers2` ascending by upper_bound in both modules, matching `_bucket()`'s
   documented contract (`commodity`: `[("down_primary", -primary), ("down_secondary", 0.0),
   ("up_secondary", primary), ("up_primary", inf)]`-shaped, i.e. 4 real tiers, not 3; `fx`
   tiers2 needs a real second threshold to produce an actual `risk_off` state, not a
   single-entry list).
2. Reconcile `commodity_momentum_ts`'s docstring (claims 4 tier1 states) against the actual
   code (currently 3 tuples) once fixed — pick one, make them agree.
3. Once fixed, `commodity` and `fx` regime history needs a full recompute
   (`cross_sectional_regime_model.py`, both groups, all tfs) — old rows carry the wrong label.
4. Every `feature_ic_scores` row and `ensemble_weights`/`ensemble_alpha` row keyed to a
   `commodity`/`fx` `regime_label` is invalid and needs recomputing under corrected labels
   (mirrors the todo 092/183 precedent: a regime relabeling invalidates downstream IC measured
   under the old labels).
5. Add a startup-time or CI assertion that every `REGISTRY` module's `build_tiers()` output is
   ascending-sorted, so a 3rd module can't silently repeat this (the code has no automated check
   today — this was only caught by hand-tracing `_bucket()` against real data).

## References

- `services/cross_sectional_regime_model.py:196-244` — `_bucket()`, `_assign_labels()`
- `src/intelligence/regime_signals/commodity_momentum_ts.py:98-113`
- `src/intelligence/regime_signals/fx_dollar_carry.py:69-80`
- `production/migrations/319_ic_max_cell_rows_recalibration_universe_growth.sql` — the symptom
  this bug produced (oversized cell), fixed tactically there but root cause is here
