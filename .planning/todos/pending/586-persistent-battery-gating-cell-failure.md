---
status: pending
priority: P1
filed: 2026-11-04
source: plan 184-05 battery report (184-05-BATTERY.md), 1,000 simulations per cell at 4,000 sessions
---

# Persistent-predictor E17 battery: gating cells exceed size

## What failed

Ten gating cells of `null_battery_persistent` exceed the upper 99% binomial bound at 0.05 (67) or 0.01 (18) in at least one arm. Nothing is reclassified; the cells stay gating.

| Certificate (route) | Failing gating cells |
|---|---|
| feature, 1d source, 1d book, no smoothing (bound 252) | f1d_tau60, f1d_tau200, f1d_static_tau200 |
| feature, 5m source, 1d book (bound 1,560) | f5m_tau200 |
| feature, 1d source, smoothing 21 | f1d_s21_tau5 |
| feature, 1d source, smoothing 63 | f1d_s63_tau5, f1d_s63_tau60 |
| feature, 1h source, smoothing 21 | f1h_s21_tau5 |
| rk_price_percentile window 126, 1d | rk_price_percentile_w126_1d |
| feature, 1d source, 1h book (bound 252) | book1h_f1d_tau200 |

Members needing any of these certificates stay refused (`PASSING_CERTIFICATES` in `null_battery_persistent.py`) until this is resolved.

## Observed pattern

Oversize grows with predictor persistence tau. In the book arm the sd of t is 0.9 to 1.0 at tau 1-20, 1.06 at tau 60 and 1.15 at tau 200 (1d source), and 1.12 to 1.18 for the 63-day smoother; the member arm (daily overlap statistic) stays near 1.0 and fails only at 5m tau 200 and on the hourly book. This is consistent with an HAC lag that does not scale with the persistence of the weights. Related: todo 547 (the horizon-tied lag amendment, which covers target overlap, not weight persistence). No fix is proposed here.

## Passing certificates

feature 1h and 15m sources (no smoothing), feature 1d with smoothing 5, rk_high_dist 126, rk_vwap_dev 20 on 1d and on 1h.
