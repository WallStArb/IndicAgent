---
status: pending
priority: P1
filed: 2026-09-24
source: council review 2026-09-24, docs/plans/2026-09-24-edge-proof-program.md "Phase 181 queue"
---

# Phase 181 candidate 1: TSMOM on the 13-symbol sleeve through the phase 179 evaluator

## What

Classic time-series momentum (Moskowitz, Ooi and Pedersen 2012) has never been tested here. The
2026-09-13 "TSMOM screen" measured `ctf_momentum`, which at 1d is a 14-period daily RSI, against
a 2-session forward return (ledger note corrected 2026-09-24). TSMOM is the best-documented
cross-asset premium and the sleeve is a cross-asset basket, so it is the highest-prior untested
candidate.

## Plan

1. Signal source in the harness: a pure function from sleeve closes to
   `alpha[session, symbol]` (12-month trailing log return), and a run stage that writes an
   S2-shaped artifact from an S0 snapshot so S3/S4 run unchanged.
2. Synthetic V2 (null calibration) and V3 (power) with the signal computed from synthetic
   prices, as in the real run: a 252-session trailing return is far more persistent than V2's
   AR(1) phi 0.98 alpha.
3. Pre-registration committed before any real-data number:
   `docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md`.
4. One real run, S5 holdout sign check if ACT-level, ledger row.

Independent of todo 418 (no refit, no production fidelity question). Data: the sleeve's price
arrays from the S0 snapshot phase 179 uses, so both verdicts share one data version.
