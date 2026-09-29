# Family 1 iteration 3: do the opening and closing slots carry the effect?

Author: Brandon, Claude. Informed by: `docs/plans/2026-09-29-family1-iteration-2-conviction-gating.md`,
`docs/plans/2026-09-25-family1-intraday-periodicity-prereg.md`.

Status: exploration. Outside the runner, no `research_run` rows, no verdict. Criteria below are
set before any number for questions 2 and 3 exists.

## Disclosed prior look (seen data)

A per-slot split of `same_slot_mean5` on the 233-name panel, in-sample before `oos_start`, at
keep 0.5 and keep 0.1 (scratch script, not committed). Gross P&L in bp per session, E in bp per
unit traded:

| Slot | keep 0.5 P&L | keep 0.5 E | keep 0.1 P&L | keep 0.1 E |
|---|---|---|---|---|
| Opening half hour (signal row 25, entry at the 09:30 open) | 1.44 | 0.72 | 3.02 | 1.52 |
| Closing half hour (signal row 23, entry 15:30, exit at the close) | 0.56 | 0.28 | 1.25 | 0.63 |
| Other 11 slots | 0.02 to 0.12 each | 0.01 to 0.06 | 0.00 to 0.27 each | 0.00 to 0.14 |

The 13 slot means sum to the all-slot total (2.59 and 5.44 bp). The opening slot is about 56% of
profit and the closing slot about 22% at keep 0.5. The prereg expected the opening slot to be the
strongest (Heston, Korajczyk, Sadka), so the direction was predicted, but the size and the picking
of two of thirteen slots came from this look.

Re-running the open and close slots on the same 233 names adds no information: those numbers are
already seen. The tests below use data that were not part of the look.

## Questions and criteria

### 1. Stability inside the seen sample (descriptive, counts nothing new)

E per sub-period (2010-2014, 2015-2019, 2020-2025) for the opening and closing slots, mean5 and
mean20, keep 0.5 and 0.1. Reported, not a test. A slot whose E changes sign in a sub-period is
noted against it.

### 2. Name replication (the informative test)

Same construction, members `same_slot_mean5` and `same_slot_mean20`, keep 0.5 and 0.1, horizon 2,
slots restricted to the opening and closing slots, on active equity names with 15m bars that are
not in the 233-name `compute_eligible` set (203 at filing, 157 starting before 2016; intraday
backfill, todo 449, is still adding history). Same scored span (2010-01-04 through 2025-12-23),
same S1 residualization built on this panel, same coverage floor of 20 names.
8 cells for the opening slot, 8 for the closing slot (2 members x 2 keeps x 2 slots), all printed.

- Replicates: opening slot, keep 0.5, both members: E at least 0.30 bp per unit traded and HAC t at
  least 3, positive in every sub-period that has at least 20 names. (0.30 is about 40% of the
  in-sample 0.72, allowing for selection shrinkage and a thinner panel.)
- Does not replicate: opening slot E below 0.15 bp in either member at keep 0.5, or HAC t below 2.
  Then the in-sample concentration was selection and the subset is dropped.
- In between: inconclusive; rerun when the intraday backfill is complete.
- Closing slot: replicates at E at least 0.12 bp and t at least 3 (40% of 0.28).
- Concentration (keep 0.1): a dose-response is required, meaning E at keep 0.1 greater than at
  keep 0.5 in both members. It is not needed for the subset to replicate.

### 3. Cost of the opening and closing slots

No quote history is stored, so spreads are measured by proxy: the Corwin-Schultz high-low
estimator from consecutive 15m bars, per name, for the opening bars, the closing bars and midday
bars as a comparison, on the 233 and 203 name sets. Bias: the estimator rises with volatility,
which is highest at the open, so it will overstate the open spread; that is stated in the result.
If the gateway is up and the lease allows, one IBKR BID_ASK history sample for the same names
replaces the proxy for a spot check.

- Cost per unit traded for a slot is the weight-averaged half-spread of the traded names, taken at
  the 75th percentile across sessions.
- The subset is worth building only if E (question 2, replication sample) minus that cost is
  above 0 for the opening slot at keep 0.5 and keep 0.1. Otherwise the effect exists but cannot be
  captured at this cost.
- Measured cost above 1.5 bp per side at the open ends the opening-slot idea at any keep.

## What this does not decide

A subset that passes questions 2 and 3 is worth a pre-registered book (`ConstructionRule`, phase
187, plus the E17 battery in todo 442) and its own forward span. This iteration is not that test.
Because it runs outside the runner, its series are not in the selection universe; anything built
from it is rerun through the runner in exploration mode, where E18 counts it.

## Build requirement

The replication needs a panel over the non-`compute_eligible` names. `build_panel` and the spec's
`universe` field must accept it as a named universe (a code change; the frozen `family1_*` specs do
not change).
