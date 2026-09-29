"""The fresh IC engine's three jobs as pure functions: proposer, IC term structure, monitoring.

Contract (phase 186 D-17, D-18, D-19, D-02):

- Pure functions over `src.intelligence.statistics.ic_math` and the research kernel. No database
  write, no ConfigService or APR read (the 186-14 writer loads APR and passes values in through
  `MeasureParams`), no module-global mutable state.
- Every target comes from `src.intelligence.research.panel.forward_returns` on S0 panels built
  with `end_exclusive = alpha.validation.oos_start`.
- Regime-stratified IC exists only for `regime_volatility` (disclosure).
- `services/ic_engine.py` never imports this package (strangler); the old engine stays untouched
  until the parity harness in 186-20 accepts the new one.

Submodules are not re-exported here, so importing the package costs nothing.
"""
