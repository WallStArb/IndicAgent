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

Amended 2026-09-29, after the first proxy result was seen (the replication result was not yet
read). The original step measured spreads with the Corwin-Schultz high-low estimator on 15m bars.
It returned median half-spreads of 8.7 bp (opening, 233 names), 3.2 to 3.5 bp (midday) and 4.3 bp
(closing), and 10.5, 3.7 to 4.0 and 5.4 bp on the 203 names. Those levels are not spreads for
liquid names: the estimator reads price movement as spread, and the opening bar carries the
auction and overnight news. Only the ratio (open about 2.5x midday, close about 1.2x) is kept as
weak evidence that the open costs more than midday. The proxy is dropped as a cost measure and
its pass rule ("above 1.5 bp per side at the open") is not applied to it.

Replacement:

- Floor: half a cent over the average price of each name (2025-06 to 2025-12-23), which is the
  half-spread of a name one tick wide. Median 0.49 bp on the 233 names (p25 0.25, p75 0.93) and
  0.69 bp on the 203 names (p25 0.33, p75 1.65); median prices $102 and $72.
- Opening estimate: no measurement exists. A 2x to 3x widening of a one-tick midday spread at the
  open is a general market expectation, not a measured number here; it would put the open at about
  1 to 2 bp per side on these names.
- Measurement: an IBKR BID_ASK history sample for the opening, midday and closing windows on a
  fixed 40-name subset (20 per set, drawn by symbol hash), taken when the `ibkr_history_stream`
  lease is free (todo 449 holds it now). The sample replaces the estimate.

Criteria, set before the sample exists:

- Cost per unit traded for a slot is the weight-averaged measured half-spread of its traded names
  at the 75th percentile across sessions.
- The opening slot is worth building only if E from question 2 (replication sample) minus that
  cost is above 0 at keep 0.5 and at keep 0.1. If only keep 0.1 clears, the slot is worth
  building at that concentration only.
- A measured opening half-spread above 2.0 bp at the median ends the opening-slot idea at any
  keep. (Raised from 1.5 bp: the in-sample E at keep 0.1 is 1.5 bp, so a measured 1.5 to 2.0 bp
  needs the replication E to decide.)

## What this does not decide

A subset that passes questions 2 and 3 is worth a pre-registered book (`ConstructionRule`, phase
187, plus the E17 battery in todo 442) and its own forward span. This iteration is not that test.
Because it runs outside the runner, its series are not in the selection universe; anything built
from it is rerun through the runner in exploration mode, where E18 counts it.

## Build requirement

The replication needs a panel over the non-`compute_eligible` names. `build_panel` and the spec's
`universe` field must accept it as a named universe (a code change; the frozen `family1_*` specs do
not change).

## Result, question 2 (2026-09-29): name replication

Panel: 201 active equity names outside the 233-name `compute_eligible` set with 15m bars (203 at
filing; 2 dropped in panel preparation), 4839 sessions, snapshot `panel_f7fd3a15bc645e5f` built to
scratch (not committed). Same spec, S1 vintage-1 residualization built on this panel, horizon 2.
Scratch script, not committed. E in bp per unit traded.

| Slot | Member | keep | E | HAC t | E by sub-period (2010-14, 2015-19, 2020-25) |
|---|---|---|---|---|---|
| open | mean5 | 0.5 | 1.169 | 12.0 | 0.897, 0.851, 1.617 |
| open | mean20 | 0.5 | 0.977 | 11.0 | 0.832, 0.596, 1.393 |
| open | mean5 | 0.1 | 1.789 | 9.1 | 1.196, 1.333, 2.566 |
| open | mean20 | 0.1 | 1.899 | 9.8 | 1.474, 1.182, 2.784 |
| close | mean5 | 0.5 | 0.624 | 23.8 | 0.698, 0.678, 0.530 |
| close | mean20 | 0.5 | 0.552 | 21.5 | 0.547, 0.640, 0.482 |
| close | mean5 | 0.1 | 1.280 | 19.4 | 1.337, 1.415, 1.128 |
| close | mean20 | 0.1 | 1.126 | 17.2 | 1.020, 1.327, 1.029 |
| all slots | mean5 | 0.5 | 0.201 | 18.5 | 0.178, 0.205, 0.214 |
| all slots | mean5 | 0.1 | 0.344 | 14.7 | 0.251, 0.371, 0.384 |

Against the criteria: the opening slot replicates (E 0.98 to 1.17 against a bar of 0.30, t 11 to 12,
positive in all three sub-periods, both members) and the closing slot replicates (E 0.55 to 0.62
against 0.12, t 21 to 24). E rises from keep 0.5 to keep 0.1 in both members for both slots.

Not resolved by this result:
- Cost. These names are less liquid than the 233 (tick floor 0.69 bp median, p75 1.65 bp), and
  their effect is larger (all-slot E 0.20 against 0.10), so edge and cost both rise. Question 3
  decides whether the slots clear cost.
- The opening slot's E rose in 2020-25 (1.6 against 0.9) and the closing slot's fell (0.53 against
  0.70). Two slots, three periods; noted, not read.
- Survivorship (todo 376) applies to both name sets.

## Result, question 3 (2026-09-29): measured IBKR bid/ask spreads

IBKR historical BID and ASK 15m bars (RTH), last 30 sessions to 2026-09-29, 39 names (20 from the
233-name set, 19 from the replication set; BRK.B failed to resolve and was skipped), chosen by
symbol hash. Half-spread = (ask - bid) / 2 / mid at each bar's open, median over days per name,
then median across names. Unweighted by trade weight; a quote snapshot, not an executed price.
Scratch script and data in the session scratchpad, not committed.

| Time (ET) | 233-name set (bp) | replication set (bp) |
|---|---|---|
| 09:30 (first quote, pre-auction) | 27.4 | 133.4 |
| 09:45 | 4.8 | 15.1 |
| 10:00 | 3.9 | 9.5 |
| 10:30 | 3.0 | 6.6 |
| 11:00 to 14:00 (midday median) | 1.9 | 4.9 |
| 15:30 | 1.7 | 3.6 |
| 15:45 | 1.5 | 3.8 |

Quartiles across names for the 233 set at 15:30: p25 0.78 bp, p75 2.6 bp.

Reading, given how the books trade: the opening slot enters at the 09:30 open (an auction fill has
no spread crossing) and exits at the 10:00 open on a continuous quote; the closing slot enters at
15:30 on a continuous quote and exits at the close (auction). Cost per unit traded is then about
half the continuous-side half-spread:

| Slot | 233 set: cost / E at keep 0.5 / E at keep 0.1 | replication set: cost / E at 0.5 / E at 0.1 |
|---|---|---|
| open | 1.9 / 0.72 / 1.52 | 4.8 / 1.17 / 1.79 |
| close | 0.9 / 0.28 / 0.63 | 1.8 / 0.62 / 1.28 |

Every cell is below zero net at median cost (best: close, 233 set, keep 0.1, about -0.2 bp per unit).
The criterion "measured opening half-spread above 2.0 bp at the median ends the opening-slot idea
at any keep" is met on either reading (27 bp at the first quote, 3.9 bp at the 10:00 exit): the
opening slot as built is ended. The 0.7 bp half-spread used in earlier docs is too low for this
universe; the tick floor (0.49 bp) is a floor, not the level.

Open items: cost varies about 3x across names within the 233 set (p25 0.78 bp at 15:30), and E by
name liquidity is not measured, so a liquidity-restricted closing slot is untested; the auction
fill assumption (backtest open and close prices are the opening and closing auction prices) is not
verified; effective spread with retail price improvement is not measured.

## Question 4 (2026-09-29): the closing slot on liquid names, criteria set before any run

Motivation: the measured cost of the closing slot (0.9 bp per unit on the 233 set) is above its E,
but cost varies about 3x across names. Dollar volume predicts measured spread: on the 36 sampled
names with panel history, rank correlation -0.58 between trailing dollar volume and the median
15:15-15:45 half-spread; a log-log fit has slope -0.30 and R2 0.40; by dollar-volume quartile the
median half-spread is 4.9, 2.6, 2.7 and 0.6 bp (9 names each, top quartile median about $1.4B a day).
Seen before this test: the E of the closing slot on the full 233 and 201 names, not E by liquidity.

Test. Slot: closing only (signal row 23; enter 15:30, exit at the close). Members mean5 and mean20.
Liquidity gate L: each session, trade only names in the top L fraction (by rank) of trailing
60-session mean dollar volume (close x volume summed over the session's bars, prior sessions only),
within the panel's names that session; alpha and volatility outside it are NaN before ranking.
Grid: L in {1.0, 0.5, 0.25, 0.1} x keep in {0.5, 0.2} x 2 members x 2 name sets (233 seen, 201
clean) = 32 cells, all printed, no cell picked afterwards. Coverage floor 20 names stays.

Cost model (fixed now): each name's half-spread is exp(a + b log dollar volume) from the log-log
fit above (refit on the same 36 names, coefficients printed with the result). Per unit traded the
closing slot pays half the traded-weight-averaged half-spread of its entry names (the exit is an
auction fill with no spread crossing). Net E = E minus that cost. The fit comes from 2026
quotes and is applied to 2010-2025 bars; spreads were likely wider before about 2015, so early
sub-period net E is flattered. Reported, not corrected.

Criteria:
- Worth building (a closing-slot ConstructionRule and its own pre-registration): net E of at least
  +0.15 bp per unit traded, at some L of 0.25 or below and one keep, in both members and both name
  sets, and net E positive in all three sub-periods on the 201 set.
- Ends the liquid-names idea: net E at or below zero in every cell with L of 0.5 or below.
- Otherwise inconclusive.
- Expectation stated in advance: edge is larger in less liquid names (all-slot E was 0.20 on the
  201 set against 0.10 on the 233), so E falls as L falls; the idea works only if cost falls faster.
  The 201 set has fewer liquid names, so its top L may still be wide.
