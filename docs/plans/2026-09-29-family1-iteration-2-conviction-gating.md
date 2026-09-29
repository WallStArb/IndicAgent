# Family 1 iteration 2: conviction gating

Author: Brandon, Claude. Informed by: `docs/plans/2026-09-29-family1-iteration-1-horizon.md`.

Status: exploration, prototype outside the runner (`scripts/research/family1_conviction_gating.py`).
No `research_run` rows, no M = 30 spend, in-sample before `oos_start`. The runner has no gated
construction (phase 187 `ConstructionRule`; todo 442 item 2 covers the E17 H0 battery for it), so
nothing here is a verdict.

## Question

Iteration 1 (in progress at filing) shows the same-slot alpha is slot-local, so a longer hold does
not raise edge per unit traded (E about 0.09 to 0.10 bp against about 0.7 bp per side at zero
commission). Can concentrating each slot's book on the most extreme alpha raise E, and can trading
only high-dispersion slots raise it further?

## Axes

- Name gate `keep`: trade only the top and bottom `keep` fraction of valid names per side, rank
  weighted over vol, each side scaled to 0.5. 0.5 is the runner's construction.
  Grid: 0.5, 0.3, 0.2, 0.1, 0.05.
- Slot gate `slots`: trade a slot only if its cross-sectional alpha standard deviation is in the
  top `slots` fraction of the same slot's previous 60 sessions (causal). Grid: 1.0, 0.5, 0.25.
- Members: same_slot_mean5 and same_slot_mean20 (the strongest at horizon 2). Horizon 2.

## Readout

E = mean E17 timing-series P&L per session / turnover per session (bp per unit traded), plus
Sharpe, HAC t, turnover and E in each of the spec's three sub-periods. All 30 cells are printed;
no cell is picked after the fact.

## Checks and criteria, set before any result exists

- Script check first: (keep 0.5, slots 1.0) must reproduce the runner's horizon-2 numbers
  (mean5 E 0.100, t 18.2; mean20 E 0.097, t 18.7). If it does not, the script is wrong and no
  other cell is read.
- A real effect needs a dose-response: E rising as `keep` falls (monotone or nearly), positive in
  all three sub-periods. One best cell is not evidence with 30 cells looked at.
- E of 0.35 bp or more with that shape: worth building as a `ConstructionRule` and testing
  properly. E below 0.14 bp in every cell: gating does not fix the economics.
- Expectation, stated in advance: for a rank-linear signal with a weak per-name edge, extremes
  carry somewhat more alpha per unit weight, so E rises modestly with concentration. It falls
  again at very small `keep` from noise and fewer names.

## Result (2026-09-29)

Script check passed first: (keep 0.5, slots 1.0) gave mean5 E 0.100 bp, t 18.18 and mean20 E 0.097 bp,
t 18.74, matching the runner. All 30 cells were read; grid output in
`logs/research/family1_iter2_grid.json` (git-ignored). Horizon 2, in-sample.

E in bp per unit traded, slots 1.0 (every slot traded):

| keep | mean5 E | mean20 E | mean5 Sharpe | turnover |
|---|---|---|---|---|
| 0.5 | 0.100 | 0.097 | 5.2 | 25.9 |
| 0.3 | 0.129 | 0.127 | 5.0 | 25.9 |
| 0.2 | 0.159 | 0.159 | 4.5 | 25.9 |
| 0.1 | 0.210 | 0.201 | 3.8 | 25.9 |
| 0.05 | 0.253 | 0.248 | 2.9 | 25.9 |

- Dose-response: E rises steadily as `keep` falls and is positive in all three sub-periods in every
  cell. The criterion for a real effect holds.
- Size: the best cells are 0.25 bp, above the 0.14 bp line and below the 0.35 bp build bar. The only
  cell at 0.35 is a single sub-period, which the criteria say not to read.
- Slot gate: trading the top quarter of slots cuts turnover from 26 to 7 per session but leaves E
  about unchanged (mean5 slightly lower, mean20 slightly higher) and lowers Sharpe (mean5 5.2 to
  2.5). It reduces trade count without improving each trade.
- Cost: 0.25 bp per unit traded is about a third of the 0.7 bp half-spread assumption, so the book
  still loses money at zero commission.
- Sharpe falls with `keep` because breadth shrinks to about 11 names per side at keep 0.05.

Conclusion: concentration raises edge per unit traded modestly, as expected in advance, and does not
close the gap to cost. Not built as a `ConstructionRule`. Nothing here is a verdict.
