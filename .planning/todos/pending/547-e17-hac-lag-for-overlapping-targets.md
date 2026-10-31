---
status: pending
priority: P1
filed: 2026-10-27
source: daily residual prereg (docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md section 4), Codex review round 1
---

# E17: a HAC lag that covers overlapping multi-session targets

## Status (2026-10-31)

The E17 daily statistic is landed and battery-certified (`d2f3ff0b1`); the daily path is cleared.
One pre-registered S1-drift failure pattern went to the owner (option A or B below) and is the
only thing between here and the first counted daily residual run. No real-data number for any
daily member exists.

## Decision

For daily targets only (bars_per_session = 1), `timing_test(..., overlap_sessions=horizon - 1)`
uses a flat-top kernel (weight 1 on the overlapped lags, then the Bartlett taper) on the HAC of
the influence series (`timing_influence`, `hac_total_test`). Books and every intraday caller keep
the original statistic, so `repro_frozen` is bit-identical and no recorded run moves. Open
follow-up: books over a daily series still use the original statistic; close before one exists.

## Why (three causes, verified by paired probes on synthetic H0)

1. The Bartlett taper under-weights the MA(h-1) overlap: at h = 5, D_s is MA(4) and Bartlett at
   L = 9 understates the long-run variance by about 15% (sd of t about 1.08). A kernel bias, not
   a short-sample effect. Fixed by the flat-top kernel; at q = 0 it is the old statistic.
2. The expanding mean subtracted in D_s carries a slowly changing estimation error that a
   lag-9 HAC cannot see. Fixed by HAC on the influence series (sums exactly to the sum of D_s,
   so mean and Sharpe are unchanged; only the standard error moves).
3. S1 leaks a slowly varying per-name drift (mean shift +0.18 momentum / -0.21 reversal in
   `s1_hostile`, +2.26 in a gaussian-plus-S1 cell): a property of the S1 vintage, not of the
   statistic. No minimal fix; needs an owner S1 decision. Not fixed.

Cross-sectional dependence ruled out (HAC runs on the cross-sectional sum); the six arms behave
like about 2.3 independent ones, so battery intervals must be clustered by simulation.

## Verdict numbers

- E17 as originally adopted (Newey-West lag only) fails size on the daily battery outright at
  h = 21 (11.9% / 10.9% rejection at 0.05, gaussian/hostile; the 20-session overlap exceeds the
  lag), and the full 1,000-simulation battery at h = 5 also failed (40+ size failures, sd of t
  1.05 to 1.30, worst 12.1% at 0.05).
- First certified run (1,000 sims, 4,736 sessions, h = 5, flat battery
  `logs/research/e17_battery_daily_residual_flat_20261030.json`): sd of t 0.88 to 1.03 in every
  cell; three marginal exceedances - `daily_gaussian/reversal_5_skip1` 71 > 67 at 0.05 (20 > 18
  at 0.01), `daily_s1_hostile/residual_momentum_12_1` 69 > 67 at 0.05, `_z` 66 (holds by 1).
- Pre-registered B2 v2 (2,000 sims, 4,736 sessions, seed base 90,000,000, run once 2026-10-30,
  journal only; the driver exited non-zero so no JSON): every cell passes except
  `daily_s1_hostile/residual_momentum_12_1_z`, 124 > 123 at 0.05 and 9 > 8 at 0.00167. Its twin
  sits at the bound (123/123, 7/8); mean t +0.15 for both momentum members; reversal members and
  `book_equal` at or below nominal. This is exactly the pre-registered cause-3 pattern
  (a momentum member fails in `daily_s1_hostile` and nothing else does). Not rerun on other
  seeds.

## Owner decision (blocks the first daily run)

(a) accept the statistic as certified for the reversal members and the book, holding
`reversal_5_skip1` and both momentum members until a fresh pre-registered seed base or an S1
decision; or (b) hold the whole family until S1's drift is decided. Also open: B3 power, and the
daily-book statistic path above. The amendment lands as a methodology-change-ledger entry under
E17, owner-approved.
