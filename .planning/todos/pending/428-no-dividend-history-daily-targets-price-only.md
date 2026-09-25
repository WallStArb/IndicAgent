---
status: pending
priority: P1
filed: 2026-09-25
source: adversarial review of docs/plans/2026-09-25-multi-timeframe-horizon-design.md (finding 4)
---

# No dividend history: daily targets and price-level features are price-only

## What

Equity bars are fetched as IBKR `TRADES` (`src/providers/ibkr.py::_hist_what_to_show`), which is
split-adjusted but not dividend-adjusted, and no table in the database holds dividends or
corporate actions. Every daily open-to-open target therefore carries the ex-dividend drop as a
negative return, and every price-level feature (52-week high distance, price percentile,
VWAP deviation) sees a high-yield name drift down in price terms.

## Why it matters

- Family 9 (anchoring, slow reversal): "far from the 52-week high predicts a lower return" can be
  produced by yield alone on high-dividend ETFs (HYG, TLT, utilities), since both the feature and
  the price-only residual return lean the same way. S1 keeps each name's drift
  (`src/intelligence/research/factors.py`), so it does not remove this.
- Family 2 (overnight versus intraday): ex-dividend drops land entirely in the overnight leg, so
  the overnight return is biased down for high-yield names.
- The intraday book is unaffected: its targets never cross a session.

## Done when

A point-in-time dividend history (ex-date, amount) is stored for the universe; S0 can emit a
total-return-adjusted open series for targets and kernels; a guard shows a synthetic high-yield
name with no alpha produces no family 9 signal. Until then, daily-clock books with price-level
members do not go to confirmation, and family 2 discloses the bias.
