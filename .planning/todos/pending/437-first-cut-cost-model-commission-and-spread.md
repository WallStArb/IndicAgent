---
status: pending
priority: P2
filed: 2026-09-26
source: adopted unified design (todo 436), sections 4.4, 7.3 and 9; E18
---

# First-cut cost model: commission plus spread, validated on a quoted overlap

## What

E18 makes promotion to a forward span require positive net expectation, and kappa is derived from costs (design section 4.4). Today the only cost input is the flat `alpha.construction.cost_hurdle_bps_round_trip = [1, 3, 5, 10]` (`alpha.quant.cost_hurdle.*` are emission thresholds, not costs; todo 393 folded in here).

Build `cost(symbol, t, Q, side, clock)` as a pure function behind one interface:

1. Commission: the execution broker is Alpaca at zero commission (2026-10-09), so this term is the sell-side SEC/FINRA fee only; IBKR is removed (todo 600) and is no component.
2. Spread: quoted spread where a quote history exists (the Massive cost-calibration tape slice kept on ubuntu1, todo 600; Alpaca quotes going forward); otherwise Abdi-Ranaldo (2017) from high, low and close. Validate the estimator against quoted spreads on the overlap before trusting it and record the error distribution.
3. Fill timing per clock: daily books pay opening-auction slippage, intraday books cross the spread at the next bar open.
4. Every component returns a distribution (point plus band); promotion and sizing use a conservative quantile, an APR key.

Impact, the borrow constraint and the capacity curve come in phase 188. Once spread and dollar volume are measured, derive `instruments.live_tradeable` by a written rule from them (APR keys, one writer); nothing sets it today, and the capacity curve and capital tier need it.

## Done when

The function exists with tests, the spread estimator's validation is recorded, and a family's net expectation can be computed.
