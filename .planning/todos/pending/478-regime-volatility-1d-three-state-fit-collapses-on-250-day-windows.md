---
status: pending
priority: P1
filed: 2026-09-30
source: plan 186-18, todo 289 measurement
---

# regime_volatility at 1d is gated off for about 98% of segments: the 3-state fit collapses on the 250-day windows

## What

The 186-18 sweep (`evidence/186-18-regime-coverage.json`, key `todo_289`, all 931
`compute_eligible_1d` names) measured the volatility family's pooled 1d skip fraction at 0.982 at
the live 252-bar schedule (0.984 at 126, 0.979 at 504), every skip a degenerate-occupation
verdict. Only 215 of 12,012 attempted segments are written; 145 of 931 names get any label. In 560
of the 742 names with no label the minimum state occupation of the training decode is exactly 0:
the 3-state model on `[realized_vol, vol_of_vol]` over 250-day windows (APR
`alpha.hmm_volatility.vol_window` and `vol_of_vol_window` 250, `n_components` 3) leaves a state
empty. The refit schedule is not the lever (todo 289 closed on that measurement).

## Why it matters

`regime_volatility` and its `hmm_vol_*` columns are book inputs through todo 435. The 186-25/186-26
rebuild reproduces this coverage unless the model configuration changes first: at 1d the column is
labeled on about 1.7% of rows after the first boundary.

## Next

Decide, on bars only, before the rebuild: observation windows (the 250/250 pair makes both
columns nearly constant inside a segment), `n_components` 2 versus 3 at 1d, and whether the
occupation floor (`feature.hmm.min_state_occupation` 0.05) is the right gate for a slow
volatility axis. Every change relabels the family, so it goes through the sweep script with
`--override` and a rule written before the run, then a golden regeneration in its own commit.
Decide whether 1d volatility belongs in the rebuild at all (the trend family labels 0.84 of rows).
