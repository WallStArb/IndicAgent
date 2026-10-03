---
status: pending
priority: P1
filed: 2026-09-26
source: adopted unified design (todo 436), sections 4.4, 7.3 and 9; E18
---

# First-cut cost model: IBKR commission plus spread, validated on a quoted overlap

## What

E18 makes promotion to a forward span require positive net expectation, and the partial-adjustment
rate kappa is derived from costs (design section 4.4). Today the only cost input is the flat
`alpha.construction.cost_hurdle_bps_round_trip = [1, 3, 5, 10]`; `alpha.quant.cost_hurdle.*` are
emission thresholds, not costs (todo 393, folded in here).

Build `cost(symbol, t, Q, side, clock)` as a pure function behind one interface, first cut:

1. Commission: IBKR tiered schedule, exact.
2. Spread: quoted spread where IBKR serves historical BID_ASK bars (measure how far back that goes
   first); otherwise Abdi-Ranaldo (2017) from high, low and close. Validate the estimator against
   quoted spreads on the overlap before trusting it; record the error distribution.
3. Fill timing per clock: daily books pay opening-auction slippage, intraday books cross the spread
   at the next bar open.
4. Every component returns a distribution (point plus band); promotion and sizing use a
   conservative quantile, with the quantile an APR key.

Impact, the borrow constraint and the capacity curve are added in phase 188.

## Done when

The function exists with tests, the validation of the spread estimator is recorded, and family 1's
net expectation can be computed (its members turn over about 26x gross per session).

## Also (2026-10-03)

Once spread and dollar volume are measured, derive `instruments.live_tradeable` by a written rule from them (APR keys, one writer). It is false for all 1,529 names and nothing sets it; phase 188's capacity curve and the capital tier need the rule.
