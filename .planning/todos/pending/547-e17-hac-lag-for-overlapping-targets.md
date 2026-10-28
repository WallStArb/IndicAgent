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
