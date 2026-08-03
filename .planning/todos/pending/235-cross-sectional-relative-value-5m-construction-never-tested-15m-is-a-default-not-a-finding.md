---
status: pending
priority: P2
filed: 2026-08-03
source: user question mid-session -- "why only 15m, that doesn't seem Renaissance in spirit"
---

## What

Phase 167's live `CrossSectionalSpreadTracker` (`services/cross_sectional_spread_tracker.py:105`,
`_TF = "15m"`) trades the cross_sectional_relative_value dollar-neutral cross-sectional spread construction at 15m only.
Checked whether this is a measured choice or a default: **it's a default.** The hardcoded `_TF`
was inherited verbatim from the original ad hoc falsification script
(`t3_cross_sectional_long_short_ctf_momentum_check.py` -- deleted 2026-07-28, git-history only),
which happened to test 15m first. No comparative run at 5m exists for this construction.

The one existing 5m cost-hurdle result (todo 030, closed, table preserved in
`docs/research/data-edge-source-thesis.md`'s "What This Doc Demands From the Roadmap" section)
found 5m fast/mid **single-feature standalone IC** nets out negative-to-marginal against
realistic spread (0.26bp/0.84bp gross vs a 1-10bp cost floor). That is NOT evidence against 5m
for cross_sectional_relative_value specifically -- the doc's own text flags the distinction: "a spread portfolio's cost
dynamics differ from a directional trade's" (dollar-neutral netting can absorb costs a
directional trade can't). cross_sectional_relative_value's actual construction (paired long/short legs, netted) has never
been run at 5m with its own methodology (day-clustered bootstrap, shuffled-ranking null, cost
hurdle applied to the NETTED spread, not to a standalone feature).

This matters for a first-principles reason, not just completeness: this project's own
"Breadth Is the Binding Constraint" section (same doc) argues IR ≈ IC × √(effective breadth),
and Medallion's own historical edge came substantially from pushing frequency up, not from a
bigger per-trade edge. Defaulting to 15m without testing 5m is exactly the kind of unexamined
choice that arithmetic warns against -- more bars at 5m is both a breadth lever (more
independent cross-sectional draws) and a genuine execution-cost risk (turnover scales with
frequency), and only an actual cross_sectional_relative_value-methodology run at 5m can tell which effect dominates.

## Next step

Run `t3_cross_sectional_long_short_ctf_momentum_check.py`'s exact methodology (script itself
deleted 2026-07-28 -- reconstruct from git history or `services/cross_sectional_spread_tracker.py`'s
current construction logic) at `_TF="5m"` (day-clustered bootstrap CI, 40-draw shuffled-ranking
null, todo 030's cost-hurdle sweep applied to the NETTED spread, not a standalone feature) --
same discipline Phase 167's 15m result was held to. If 5m's netted spread clears its own bar (CI + shuffled null + cost hurdle) with a
larger or comparable IC/Sharpe to 15m's live result, that's a real case for either running both
timeframes in parallel or reconsidering which one the live tracker should trade. If it doesn't
clear, that's the actual evidence 15m's default was missing -- either way this closes a real gap,
not a formality.

Row-count note: 5m equity is roughly 3x 15m's per-symbol density, so expect roughly proportional
runtime; nowhere near nonlinear_interaction_combiner's per-row feature-matrix OOM risk (this is a single ranked feature and a
netted spread calc, not a 248-column LightGBM training matrix) -- todo 234's OOM class doesn't
apply here.
