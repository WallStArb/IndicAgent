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

## Decision rule (preregistered 2026-10-02, committed before any candidate run)

Instrument: `scripts/infrastructure/features_regime_kernel_coverage_sweep.py`, read-only, one JSON
report per arm under `evidence/478-*.json` (untracked, the 186-18 convention). Every arm runs
`--symbols @compute_eligible_1d --tfs 1d --families volatility --workers 6` at the live schedule
(refit 252, warmup 504) and the live floor (`feature.hmm.min_state_occupation` 0.05). The floor is
held identical in every arm: it is the degeneracy detector this decision exists to satisfy, not a
lever, and lowering it would admit exactly the collapsed fits the gate exists to refuse. The first
boundary is max(504, K x 50) = 504 obs rows in every arm, so attempted-segment grids coincide;
post-boundary denominators differ slightly across arms because a shorter `valid_start` (window sum
minus 2) leaves more early history observable. Each arm is judged on its own post-boundary rows,
which is what the rebuild would write, so that difference is the measurement, not a confound.

Arms (live baseline verified in `config_state` 2026-10-02):

- A control: live config (250/250, K=3)
- B: 60/60, K=3
- C: 20/20, K=3
- D: 60/120, K=3
- E: 60/60, K=2
- F: 20/20, K=2

Instrument check: arm A must reproduce the 186-18 collapse (pooled skip fraction >= 0.95). If it
does not, halt and investigate before reading any candidate arm: the data or the instrument
changed and the premise of this decision no longer holds.

Qualification: an arm qualifies when its pooled `labeled_fraction_after_first_boundary` >= 0.50 and
it has zero errored cells. 0.50 is the floor at which the axis carries book-input value: trend
labels 0.84 of 1d rows, so half of that is the minimum worth relabeling for, against 0.017 today.

Decision: among qualifying arms take the first in this fixed preference order, each step the more
conservative change: B > C > D > E > F. K=3 over K=2 keeps the calm/elevated/turbulent vocabulary
and its CVR codes intact (171-FINAL validated both; K=2 leaves `elevated` a dead code). The 1:1
window ratio changes exactly one design dimension from live (length, not ratio); within that, 60
bars over 20 keeps the axis slow (monthly, not weekly, realized vol). If no arm qualifies, drop 1d
from the volatility family in the 186-26 rebuild and measure the family's intraday coverage in a
follow-up all-tf pass for the record; forcing labels out of a degenerate configuration is not an
option.
