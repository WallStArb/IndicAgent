---
status: pending
priority: P2
filed: 2026-09-24
source: todo 407 closure (council review)
---

# The feature lifecycle cannot act while only one training window exists

Demotion needs alpha.decay.demotion_min_consecutive (2) failing windows and promotion needs
recovery_min_passes (2) passing windows, but alpha.validation.oos_start pins one training window
(2025-12-24 05:15 UTC). So feature_lifecycle records evidence and can never transition anything.
That is correct behaviour, not a bug. It means feature governance is a planning decision: when
and how training windows advance (for example yearly walk-forward), and how that interacts with
the holdout. Governance must never read the post-oos_start holdout, or it leaks into every later
verdict. Decide the cadence as part of the Phase 179/180 walk-forward work.
Related: 414 (guard statistic, needs >= 2 windows), 405 (trainer reads must pin a window).
