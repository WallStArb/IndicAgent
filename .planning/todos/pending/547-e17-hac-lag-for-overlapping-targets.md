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
