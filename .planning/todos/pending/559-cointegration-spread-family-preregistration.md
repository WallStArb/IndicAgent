---
status: pending
priority: P2
filed: 2026-10-28
source: owner decision 2026-10-28 to reopen the cointegration concept (ledger section 2)
---

# Pre-register the reopened spread family (cointegrated pairs, Kalman and OU)

Assistant draft, needs an Opus or Fable rigor pass before it is adopted.

## What

The owner reopened `cointegrated_pairs_residual` on 2026-10-28 (ledger section 2). The frozen verdict
(0/6 ETF pairs, 0/471 same-sector single-name pairs) stands; the new family is tested on its trading
statistic through the runner, not on a cointegration null. No look is taken until this
pre-registration exists. Mark the family's members and the universe, and state:

- Disclosure: the 2026-08-07 pilot and the 2026-09-11 screen (471 pairs, ITR `single_name_equity`
  by sector) are seen data; any pair or name drawn from them is flagged, and a fresh universe is
  named separately.
- Estimators: a static hedge ratio, a Kalman time-varying hedge ratio, and the OU half-life
  (`ln 2 / kappa`) as a holding-horizon filter. Daily bars only, multi-day holds (no hyper-traded forms).
- Diagnostics, stated in the pre-registration, never gates (the test unit is the trading statistic
  through the runner; a cointegration null is what the frozen verdict wrongly gated on): out-of-sample
  ADF on the spread and half-life stability across windows, where a drifting half-life is the stated
  falsification risk for spread members; Kalman innovations whiteness (autocorrelated innovations
  flag mistuned process or observation noise) and out-of-sample residual stationarity for the
  time-varying hedge ratio. Multiple testing is StepM's job at selection, not a per-pair correction.
- Construction: whether a pair spread fits the runner as a cross-sectional book of spread z-scores or
  needs the time-series book of todo 548 part B (the runner is R1 only today; check before choosing).
- Counted: every look under E18; costs never enter the statistic, promotion needs positive net
  expectation. Falsification: stated before the run, with the stated expectation that it is weak.
- Sibling: the residual reversion members in todos 441 and 423 and the PCA-residual idea in the
  stat arb map; share the S1 residual and avoid a duplicate look.

## Done when

The pre-registration is written under `docs/plans/`, reviewed, and linked from the ledger row; the
family runs after the data-completion gate lifts (the 191-20 1d re-derive landed 2026-10-30; corpus
compute is gated on todo 600 data completion, the 186-32 gate).
