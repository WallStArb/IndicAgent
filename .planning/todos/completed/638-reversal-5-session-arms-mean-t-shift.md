---
status: completed
priority: P3
filed: 2026-11-18
source: todo 636 (daily residual battery), amendment A3
---

# Find the source of the +0.035 mean t in the 5-session reversal arms

## What

Under the battery's own statistic the dropped arms `reversal_5` and `reversal_5_skip1` carry a small persistent positive mean t (about +0.035, about 4 standard errors pooled; 5.62 and 5.63 percent rejections at 0.05 over 12,000 fresh simulations, record `research/calibrations/e17_reversal_static_means_2026-11-18.json`) in `daily_static_means`; `reversal_21`, M1, M2, M3 and the book hold. Static means are not the cause (paired run: static sd 0.06 versus 0 gives the same mean t; the market mean cancels in the rank weights). Isolate the source (candidates: the overlap of the 5-session window with the h = 5 target, the memory reach L = 10, the flat-top lag choice), and decide whether it is a defect that also touches other short-window arms.

## Done when

The source is named with a paired experiment on the battery's own path, and either fixed (a recorded methodology-change entry, `repro_frozen` handled) or documented as a property of 5-session windows. The arms may then be re-registered by a counted amendment.

## Why it matters

It does not block a counted test (A3 dropped the arms); it protects the E17 statistic for any later short-window member.

## Outcome 2026-11-18

Source named: E17's L counted the signal window while the weights also read the 60-session vol window (ledger E17 amendment 2026-11-18 (b)). Fixed in `timing.e17_memory`; `repro_frozen` result and the paired numbers are in the landing commit. Re-registering the two arms is a separate counted amendment.
