---
phase: 183
plan: 08
status: complete
requirements: [D-04, D-12, D-16, D-17, D-18, D-19, D-20, D-23]
---

# 183-08 summary: synthetic generator and exact power estimator

Executed inline by the orchestrator.

## What was built

- `synthetic.py`: `SyntheticSpec`, `loading_scale_for_pr` (closed form), residual-space
  generator (low-rank common component at the pinned participation ratio, HKS-shaped
  same-slot persistence over L sessions, cross-sectionally demeaned, bars summing to the slot,
  target at the placement row), `combo_rank_ic` (D-19), `calibrate_plant` (bisection with
  common random numbers), `synthetic_price_panel` (market + group + residual, for the S1
  fidelity check and synthetic CLI runs).
- `power.py`: `PowerProblem`, `run_replicate` (scored exactly as S8: same construction,
  session scoring and shift set), `estimate_power` (serial, or one replicate per pool task
  fed to `curtail` in completion order, a Manager Event stop flag, clean shutdown).
- Performance (results unchanged, tests green): a fused numba kernel for
  `rank_vol_neutral_returns`, a fused numba kernel for the ridge's per-row moments (also
  returns the live-row mask, so the stack is scanned once), a tie-free fast path in
  `average_ranks`, and the member stack filled in float32 one member at a time.

## Verification

- `test_synthetic.py` (9): PR closed form to 1e-9 and unattainable targets rejected; sample
  PR of a 60,008-row x 233-name draw within 60 +- 5; bars, slots, target and mask consistent;
  determinism; zero plant gives IC near 0 and IC rises with the plant; calibration hits 0.02
  within 0.002; price panel residualizes and passes integrity.
- `test_power.py` (15): the plan-04 primitives plus run_replicate determinism in and out of a
  pool; estimate_power's decision equals the full-count fixed-R decision for three plant
  strengths, serial and with a 3-thread pool; a 2-process forkserver pool stops cleanly with no
  active children left; no plant not powered at a strict bar, strong plant powered; S1 passes
  the plant with an IC ratio inside 0.7-1.3 (slow).
- `test_portfolio_r1.py`: new kernel-versus-weights equivalence test with ties and NaNs.
- `repro_frozen.py`: three bit-identical lines.

## Full-size measurements (127,400 rows x 233 names x 4 members, K = 4,461 shifts, b_max 6)

Machine shared with other sessions' simulations; load average 19-37 throughout.

| Stage | Before | After |
|---|---|---|
| One book shift (ridge refit + R1 + session score) | 8.3 s | 1.6 s |
| of which R1 | 5.1 s | 0.75 s |
| of which ridge | 2.9 s | 0.67 s |
| Replicate setup (generate 1.4-1.9 s, members 18-22 s, vol 4-6 s) | about 30 s | about 30 s |
| Peak RSS per replicate process | 3.53 GB | 3.1 GB |

Projection at 1.6 s per shift: a passing replicate visits all 4,461 shifts, about 2.0 hours;
a failing one stops after a few hundred. At power near 0.5 the fixed-R decision needs about
50 passing replicates, so about 100 CPU-hours: about 8.5 hours on 12 workers, 12.5 hours on 8.
Memory is the binding constraint: 12 workers x 3.1 GB exceeds the 29 GB machine, and 8 workers
(APR `infra.research_runner.workers`) is about 25 GB. Plan 09/10 should run the power check
with at most 6-8 workers while other sessions are active, or reduce per-replicate memory
first (member computation dominates the peak).

## Deviations

- `combo_rank_ic` is cross-fitted (OLS on odd sessions scores even and the reverse) and takes
  `bars_per_session`. The in-sample fit the plan described is biased upward by about
  sqrt(K / N): 0.004 on the test panel with no plant, about 0.0005 at full size, a quarter of
  the 0.002 target, which would have under-planted and understated power.
- The bar-sum check uses a 1e-12 tolerance rather than bitwise equality (u - first + first is
  not always bitwise u in floating point).
