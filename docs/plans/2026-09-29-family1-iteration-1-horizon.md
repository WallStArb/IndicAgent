# Family 1 iteration 1: does the same-slot alpha persist beyond its slot?

Author: Brandon, Claude. Informed by: `docs/plans/2026-09-25-family1-intraday-periodicity-prereg.md`,
`docs/research/construction-verdict-ledger.md` section 1.

Status: exploration (owner, 2026-09-29: "this isn't prod yet"). Evidence-kind runs only; no book
test, so no M = 30 budget is spent and nothing here is a verdict. In-sample before `oos_start`;
the forward span is untouched.

## Question

Family 1 trades every half-hour slot and turns over about 26x per session. The recorded gross
edge is about 1.85 bp per session (annualized about 4.7%) against about 26 units of traded
notional, so about 0.07 bp per unit traded. One side costs about 0.7 bp at a zero-commission
broker (half-spread only). Cost is roughly 10x the edge per trade.

Turnover falls only if each trade earns more, so the question is whether the same alpha keeps
paying when held longer. Same members, same construction, only `horizon` changes.

## Variants

Baseline: horizon 2 bars (one slot). Run group `5a564f09` used the E16 statistic, which is biased toward zero for own-history members, so `family1_h2` reruns the baseline under E17 (its P&L and turnover are unchanged) and every variant is compared with it.

| Spec | horizon (15m bars) | hold |
|---|---|---|
| `family1_h2` | 2 | one slot (control, E17) |
| `family1_h4` | 4 | 1 hour |
| `family1_h8` | 8 | 2 hours |
| `family1_h26` | 26 | to the close (market-on-close exit; no target crosses the overnight gap) |

Later slots in a session exit at the close, so their holds are shorter than the nominal horizon.
Overlapping slot books stack: exposure is about horizon/2 times the baseline. That scales P&L and
risk together, so Sharpe is unaffected and edge per unit traded is still the right ratio.

## Readout

Per member and variant, from the recorded evidence: `E = mean_session_pnl / turnover_per_session`
(bp per unit traded), annualized Sharpe, HAC timing t, shift-null estimate. The runner counts
each slot book as opened and closed once, so E is comparable across horizons. Overlap netting
across books is not credited, so E understates the gain from stacking.

## Criteria, set before any result exists

- Baseline E is about 0.07 bp (lag1: 0.000185 / 26).
- E rising to 0.35 bp or more (half of one side at zero commission) for any member and horizon:
  worth iterating that combination further.
- E below 0.14 bp (2x baseline) at every horizon: extending the hold does not fix the economics;
  the next iteration is conviction gating (fewer, larger trades), not a longer hold.
- Expectation, stated in advance: the effect is slot-local and E decays with horizon. Getting
  this wrong in either direction is informative.

## Not tested here

Bands, partial adjustment, conviction gating and cost-aware weights need a construction rule the
runner does not have (phase 187 `ConstructionRule`; todo 442 item 2 requires the E17 H0 battery to
cover partial adjustment first). Those are iterations 2 and later.

## Result (2026-09-29)

All four variants recorded (run groups: h2 `48b7a104`, h4 `3492bf3f`, h8 `c962934b`, h26 `684a5aa7`),
in-sample before `oos_start`, E17 statistic, gross. E in bp per unit traded (turnover 25.9 units per
session at every horizon); Sharpe annualized; t is the HAC timing t.

| Member | h2 E / Sharpe / t | h4 | h8 | h26 |
|---|---|---|---|---|
| lag1 | 0.070 / 3.7 / 13.3 | 0.059 / 2.4 / 9.0 | 0.050 / 1.6 / 5.8 | 0.012 / 0.30 / 1.1 |
| mean5 | 0.100 / 5.2 / 18.2 | 0.087 / 3.6 / 12.7 | 0.065 / 2.2 / 7.6 | 0.020 / 0.54 / 1.9 |
| mean20 | 0.097 / 5.3 / 18.7 | 0.088 / 3.8 / 13.5 | 0.076 / 2.6 / 9.2 | 0.033 / 0.89 / 3.2 |
| mean40 | 0.085 / 4.7 / 18.2 | 0.075 / 3.2 / 11.9 | 0.061 / 2.1 / 7.5 | 0.016 / 0.43 / 1.5 |

Against the criteria: E is below 0.14 bp for every member at every horizon (maximum 0.100), so a
longer hold does not raise edge per unit traded, and the next step was conviction gating
(iteration 2). The stated expectation held: the effect is slot-local and E falls with horizon, to
about a fifth of the h2 value by the close. Gross P&L per session also falls (mean20: 2.52, 2.29,
1.96, 0.84 bp) while the exposure stacked by overlapping books rises about horizon / 2 times, so
Sharpe roughly halves by h8. The runner counts each slot book as opened once, and overlap netting
across books is not credited (see Readout), so turnover per session is unchanged across horizons.
Follow-on: iterations 2 and 3 (`docs/plans/2026-09-29-family1-iteration-2-conviction-gating.md`,
`docs/plans/2026-09-29-family1-iteration-3-open-close-slots.md`).
