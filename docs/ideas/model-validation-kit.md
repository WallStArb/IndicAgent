# Model validation kit, mapped to the evidence framework - Idea

**Status:** Reference, 2026-11-09. Not queued; a lookup table for when each model class first arrives here. Nothing here overrides E15-E18 or the methodology ledger.
**Author:** Claude session, 2026-11-09, from the owner's pasted 16-model validation primer (source not stated).
**Informed by:** `docs/plans/2026-09-24-evidence-framework.md` (E15-E18); `docs/ideas/signal-equity-stat-arb-method-map.md`; todo 559; the book-stage bullet in `.planning/IDEAS.md`; `docs/research/construction-verdict-ledger.md`.

## How to read external validation checklists

Three dispositions, decided per check, never per checklist:

1. Subsumed: E15-E18 already enforce a stronger form (counted looks, write-once OOS, StepM selection, forward-span confirmation). Repeated resampling of one span is itself looks; post-hoc deflation assumes you can reconstruct how many you took.
2. Estimator diagnostic, never a gate: checks of an estimator's health (whiteness, stationarity, stability) are stated in the pre-registration and reported; the test unit stays the family's trading statistic through the runner.
3. Capital-stage or out: risk, allocation and execution machinery parked until a book exists, or rejected by standing rulings.

External backtests with uncounted search get discounted with deflated Sharpe or PBO when compared against ours; ours is counted at the look, so the discount does not apply to our own results.

## The table

| Model | Breaks (primer) | Validation (primer) | Disposition here |
|---|---|---|---|
| OLS / factor regression | outliers, regime shifts break betas | Newey-West t-stats, rolling beta stability, OOS R2 | E17 already runs HAC; regime-conditioned betas are the TAG-02 idea (ITR extension list) |
| Elastic net | lambda tuning leaks future info | nested purged walk-forward CV | Subsumed; repeated tuning is looks. ML enters only as counted looks after the first counted test |
| GARCH(1,1) | slow after jumps, symmetric | Ljung-Box on std residuals, QLIKE, VaR exceedances | Risk scaling only (book-stage bullet); not a feature source |
| Kalman filter | Q/R tuning, Gaussian only | innovations whiteness, OOS residual stationarity | Todo 559 diagnostics for the stat arb hedge ratios |
| Cointegration pairs | relationship breaks permanently | OOS ADF on spread, stable half-life, testing correction | Todo 559 diagnostics (never a cointegration-null gate, ledger section 2); StepM subsumes the correction; fragile-divergence states address the break |
| HMM | lagging signals, unstable states | filtered probabilities only, OOS regime persistence | Deployed (todo 248, walk-forward, pinned seed); quadrant and fragile-divergence designs cover the breaks |
| PCA | unstable, hard to interpret | eigenvector stability across windows, OOS risk bias | Research-layer residual construction only (stat arb map methods 1 and 6) |
| VaR / expected shortfall | underestimates tails | Kupiec, Christoffersen exceedance tests | Book-stage disclosure, parked |
| Mean-variance | error maximizer, extreme weights | input sensitivity, turnover | Rejected as the construction default; simple construction rule stands |
| Risk parity / HRP | needs leverage, rate sensitivity | realized vs target risk contributions | Ledger-recorded equal-risk-contribution variant (2026-11-03), parked |
| Black-Scholes | ignores smile, jumps, costs | IV surface calibration, put-call parity, hedge P&L | No options vendor; the listed-derivatives ideas are blocked the same way |
| Monte Carlo | slow, error shrinks as 1/sqrt(N) | standard-error check, analytic benchmark, variance reduction | Named tool for the sequential-confirmation synthetic power study |
| Gradient boosting | overfits low signal-to-noise | purged k-fold with embargo, deflated Sharpe, stable importance | Deleted ML chain (todo 509); re-enters only as counted looks |
| LSTM / transformer | data hungry, opaque | walk-forward, multi-seed, ablations, cost-adjusted P&L | Out of the design |
| Reinforcement learning | sim-to-real gap, unstable | realistic sim, shortfall vs TWAP/VWAP | Out; no execution research |
| Almgren-Chriss | simple impact model | implementation shortfall vs arrival, recalibration | Out; fixed cost plus slippage covers net expectation at personal capital and extend-horizon holds |
