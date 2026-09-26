---
status: pending
priority: P1
filed: 2026-09-25
source: Phase 179 frozen run, S3 FIDELITY BROKEN (pre-reg 12.3)
---

# Phase 179: frozen run BROKEN, calibration coverage rule voided by no-weight-stratum NaN alpha

## What

The frozen run (code a64af3d1a) ended FIDELITY BROKEN with no token: S3 raised on a
zero-variance shifted series. Cause (pre-reg 12.3): alpha is NaN on no-weight-stratum days
(section 6), and calibration gives IC 0 unless 95% of the trailing 504 sessions pair finite alpha
and returns (section 7). Only the 2023 and 2024 calibration segments pass, so the book trades 447
of 3,265 days. No performance number has been read.

## Decision needed (the owner's: it reopens a frozen pre-registration)

- A. Defect fix under a methodology-change-ledger entry: define calibration coverage over the
  days alpha is defined (count paired rows among finite-alpha days, keep the 95% bar on returns),
  pin it before any run, rerun V2/V3/V3b and S1-S4 once. Same hypothesis, N_tested stays 18.
- B. Treat the frozen test as spent: a new pre-registration (N_tested 19), free to revisit the
  arms too (V3b showed they are blind to slow return-built edges).

Recommendation: A. The defect is structural and was found from coverage counts alone, with no
Sharpe seen, so fixing it is not outcome-driven; B spends a test on a harness bug.

## Triage 2026-09-26 (backlog review with the owner)

Closed: done. E14 fix 5fa10430a counts calibration coverage over finite-alpha days; the 179 rerun ended FIDELITY OK (verdict FAIL).
