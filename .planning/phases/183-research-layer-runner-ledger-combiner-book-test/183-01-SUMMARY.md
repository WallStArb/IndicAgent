---
phase: 183
plan: 01
status: complete
requirements: [D-13, D-14, D-16, D-18, D-24]
---

# 183-01 summary: R1 construction and R2 session scoring

Executed inline by the orchestrator after the wave-1 executor stopped on an API limit (its
partial R1 test file was kept, with one assertion fixed: `np.isnan(...).all() is False` compared
a numpy bool by identity and could never pass).

## What was built

- `portfolio.py`: `RANK_VOL_NEUTRAL_ARM`, `trailing_vol` (causal ddof-1 rolling sd, the
  `_trailing_z` rolling-sum idiom, never the covariance plan), `rank_vol_neutral_weights` and
  `rank_vol_neutral_returns` (centred average ranks, direction * rank / vol, legs scaled to
  +0.5 and -0.5, coverage floor, all-tied rows carry no position, `plan` ignored). Work is done
  on rows with a position only. `fixed_sign_returns` is unchanged.
- `evaluate.py`: `aggregate_sessions`, `scored_sharpe`, `evaluate(..., session_scoring=False)`
  threaded through `_run_shifts` (observed and every shift alike), one `_readout_units` helper
  for the bootstrap, sub-period and shape readouts (sessions, 252 periods, block in sessions),
  `_bootstrap_sharpe_draws` split out of `_bootstrap_sharpe_ci`, and `EvaluationResult.excess_se`.

## Verification

- `pytest tests/unit/research -q`: all pass (109 tests), including the new
  `test_portfolio_r1.py` and `test_evaluate_session_scoring.py`.
- R1 on a 127,400 x 233 float32 panel with half the rows empty: 1.7-1.8 s (budget 2.0 s).
- `repro_frozen.py`: phase 179 S3, phase 181 S2 and S3 bit-identical; `excess_se` skipped as
  not recorded in the frozen artifacts.

## Deviations

- The performance test sits close to its 2.0 s budget under a loaded machine (2.2 s was seen
  once before the rows-only change). If it flakes, the fix is the rank step, not the budget.
