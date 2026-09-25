---
status: pending
priority: P2
filed: 2026-09-24
source: reading scripts/ops/alpha/ops_ic_shrinkage.py while fixing 417
---

# ops_ic_shrinkage's out-of-fold gate scores against a different universe than the cells it grades

## What

`_STRATUM_FETCH_SQL_TEMPLATE` builds the realized cross-sectional series for every (tf, regime)
stratum by joining `market_regimes` on `regime_group = 'equity'` and averaging every symbol's
`feature_vectors` row, with no symbol filter. Two consequences:

1. Non-equity strata are never evaluated. At the 2025-12-24 window, 38,997 of 69,346 pooled
   reliable cells are commodity/fx/rates labels; their equity-joined fetch returns nothing and they
   drop out (the Phase 178 run evaluated 30,868 cells, all equity). The trainer only weights equity
   strata, so this is aligned with consumption today, but it is implicit, not stated.
2. The equity strata's realized target averages ALL symbols (commodity, fx, rates ETFs included),
   while the pooled equity cells being graded are computed over equity-group symbols only (ic_engine
   `symbol_list`, the Phase 144 D-01 contamination fix). Shrunk and raw predictions are scored
   against the same target, so the comparison is internally fair, but it does not test the cells
   the trainer consumes.

## What to do

Restrict the fetch to the stratum's own group symbols (production routing,
`_build_symbol_regime_class`) and join `market_regimes` on that group; state explicitly which
groups the gate covers. Then re-run the gate (the ic_input flip is one-way and already `ic_shrunk`,
so a FAIL here would be a finding to act on, not an automatic revert). ~2h run.
