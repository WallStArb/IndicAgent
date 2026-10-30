---
status: pending
priority: P1
filed: 2026-10-27
source: daily residual prereg (docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md section 4), Codex review round 1
---

# E17: a HAC lag that covers overlapping multi-session targets

## What

E17 takes its HAC lag from Newey-West, floor(4 (n/100)^(2/9)), about 9 at 5,800 sessions. A
daily target over h sessions overlaps the next h - 1 rows' targets, so D_s has MA(h - 1)
structure, and the Bartlett weights under-cover it: in the daily battery's H0 runs (60
simulations, before the full battery) the 5-session reversal members had t sd 1.07 to 1.14 and
rejected about 8% at 0.05. At h = 21 the overlap exceeds the lag outright, so the canonical
monthly momentum test cannot run under E17 as adopted.

## Plan

1. Candidate rules, each certified on the daily battery before adoption: lag at least
   max(newey_west_lag(n), c (h - 1)) for a pinned c; a kernel without the Bartlett taper inside
   the overlap; or non-overlapping D_s (every h-th session), which costs power.
2. The rule must leave every intraday statistic unchanged (h stays inside the session there),
   so no recorded run moves; repro_frozen bit-identical.
3. A methodology-change-ledger amendment under E17, owner-approved, then the daily_residual h = 21
   spec as its own counted attempts.

## Done when

The daily battery holds at h = 5 and h = 21 under the adopted rule, and the ledger records it.

## Diagnostic 2026-10-28 (exploratory, synthetic H0, not a counted look)

Daily residual battery cells, h = 5, 300 simulations each (6 arms), fresh seeds from 9,300,000, n = 1,431
sessions (the cell default, not the real panel length), NW lag L = 7. One-sided rejection at 1.645 of the
E17 statistic under alternative Bartlett lags:

| Cell | L = 7 (current) | L + 4 | max(L, 8) | L + 12 | 2L |
|---|---|---|---|---|---|
| daily_gaussian | 5.94% | 5.61% | 5.89% | 5.39% | 5.56% |
| daily_hostile | 7.28% | 6.72% | 7.00% | 6.17% | 6.44% |
| daily_static_means | 6.94% | 6.17% | 6.72% | 5.72% | 5.94% |

D_s has MA(4) structure at h = 5 (mean ACF 0.74, 0.49, 0.29, 0.13, then about 0.00), so L = 7 already spans
the overlap; the excess is the short-panel Bartlett variance understatement, which a longer lag trims by 0.5 to
1.1 points here. The arms of a simulation share a panel, so the effective interval per cell is about +-1 point:
read the ordering, not the third digit. Not yet measured: the real panel length (about 5,800 sessions; the
excess shrinks with n, as todo 549's step A found for the intraday battery), h = 21 (the battery hard-codes
h = 5), and the cost in power of a longer lag.

Next: parametrize the daily battery by horizon, run h = 5 and h = 21 at the real length with a
cluster-robust interval under three candidate rules (L, L + c (h - 1), 2L), then an owner-approved E17
amendment. Diagnostic script (scratch): `scratchpad/d547/diag.py`; copy it into `scripts/research/` if kept.

## Diagnostic at the real panel length (2026-10-28, exploratory, not a counted look)

Daily residual battery, 150 simulations per cell (6 arms each), fresh seeds from 9,300,000, 6,000
sessions (n about 5,420 after warmup), NW lag L = 9. One-sided rejection at 1.645; the interval is a 99%
cluster interval with one cluster per simulation. The battery's horizon was hard-coded to 5; it now
takes `DailyScenario.horizon` (default 5, so existing results are unchanged).

| Rule (Bartlett lag) | gaussian h=5 | hostile h=5 | gaussian h=21 | hostile h=21 |
|---|---|---|---|---|
| L (current E17) | 5.89% [2.6, 9.2] | 5.33% [2.5, 8.2] | 11.89% [7.1, 16.7] | 10.89% [7.0, 14.7] |
| L + (h-1) | 5.33% | 5.11% | 7.22% [3.8, 10.7] | 6.00% [3.0, 9.0] |
| L + 3 (h-1) | 5.22% | 4.78% | 6.33% [3.1, 9.6] | 5.11% [2.3, 7.9] |
| 2 L | 5.22% | 4.78% | 8.33% [4.4, 12.2] | 7.56% [4.3, 10.8] |
| max(L, 2h) | 5.78% | 5.33% | 6.56% [3.3, 9.9] | 5.89% [2.9, 8.9] |

Reading: at h = 5 the current rule is acceptable on the real length (5.3% to 5.9%; the 8% in the first
note was a short-panel effect), so the h = 5 members can run under E17 as it stands. At h = 21 the
current lag fails outright (11% to 12%, interval excludes 5%) because the overlap (20 sessions) exceeds
L = 9. A lag of L + 3 (h - 1) is the best of the candidates tried here (5.1% to 6.3% at h = 21, 4.8% to
5.2% at h = 5); L + (h - 1) and max(L, 2h) are close behind. The intervals are wide (150 simulations,
+-3 points), so the choice among the three is not settled by this run.

Recommendation for the owner: adopt a horizon-tied lag, lag = L + c (h - 1) with c pinned, as an E17
amendment that leaves every intraday statistic and every h <= 5 daily run unchanged only if c (h - 1)
is added solely for daily targets with h > 5 (otherwise h = 5 moves by 12 lags; the table shows it
changes size by less than 1 point). Certify c = 3 on a full daily battery (1,000 simulations, the same
cells plus the S1 cell, h = 5 and 21) before the amendment; measure the power cost on a planted-signal
cell at the same time. Until then h = 21 momentum stays blocked and h = 5 runs may proceed.

## B2 battery result (2026-10-30, exploratory H0 on synthetic panels, not a counted look)

`scripts/research/e17_null_battery.py --battery src.intelligence.research.null_battery_daily_residual`,
1,000 simulations per cell, h = 5, current E17 lag. Size fails at both panel lengths:

- 2,000 sessions (cell default; `logs/research/e17_battery_daily_residual_20261029.json`): gaussian cell
  momentum members 7.8% at 0.05 (bound 67 of 1,000), hostile cells up to 12.1%.
- 4,736 sessions (the real panel's length; `logs/research/e17_battery_daily_residual_s4736_20261030.json`):
  still fails; gaussian reversal members 7.5% at 0.05 and 2.5% at 0.01, `s1_hostile` momentum members 12.1%
  at 0.05, 5.3% at 0.01 and 2.0% at 0.00167 (bounds 67, 18, 5).

So the 2026-10-28 reading that h = 5 is acceptable at real length does not survive the full battery. By
prereg section 4 the daily residual run waits for the second E17 amendment (a horizon-tied HAC lag), which is
the owner decision listed in STATE.md. Next step for whoever resumes: certify a candidate rule from the plan
above on this battery at 4,736 sessions (cells `daily_gaussian`, `daily_hostile`, `daily_s1_hostile` first),
with `repro_frozen` bit-identical for intraday statistics, then take the amendment to the owner. No real-data
number for any daily member exists.

## Paired lag scan at the real length (2026-10-30, exploratory, not a counted look)

`scripts/research/e17_lag_scan.py`: 200 simulations per cell at 4,736 sessions, h = 5, seeds from 70,000,000,
one set of D_s series scored under extra Bartlett lags (paired). Mean one-sided rejection at 0.05 over the six
arms, with sd of t:

| Cell | L (current) | L + 4 | L + 8 | L + 12 | L + 20 |
|---|---|---|---|---|---|
| daily_gaussian | 5.7% (1.11) | 5.1% (1.08) | 4.9% (1.07) | 4.8% (1.06) | 4.6% (1.06) |
| daily_hostile | 6.7% (1.11) | 6.1% (1.08) | 5.7% (1.07) | 5.3% (1.06) | 5.3% (1.05) |
| daily_s1_hostile | 7.4% (1.15) | 6.9% (1.13) | 6.8% (1.12) | 6.6% (1.11) | 6.3% (1.09) |

(The per-cell interval is about +-1.5 points at 200 simulations.) A longer lag brings gaussian and hostile to
about 5% but not the S1 cell, and sd of t stays above 1 even at L + 20. So the excess is not only the Bartlett
lag: there is a variance source in the statistic or in S1's residuals that serial correlation does not explain.
Do not take a lag-only amendment to the owner until that is found.
