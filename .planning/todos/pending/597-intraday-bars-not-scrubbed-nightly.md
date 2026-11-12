---
status: pending
priority: P2
filed: 2026-11-05
source: lead (indicagent-4d), from the todo 594 landing (aff4f022c)
---

# New intraday bars are not scrubbed nightly; quarantine rules only reach them on a manual pass

## What

The `isolated_wick` and `busted_trade_window` rules (migration 580) and the older scrub rules run
on 1d through the nightly daily derivation, but nothing runs the scrub on new 5m/15m/1h bars:
the 594 flags came from a manual `ops_scrub_historical_pass.py` run. A bad intraday print
captured tonight is served by `market_data_ohlcv_tradeable` until someone runs the pass. D7's
`isolated_wick` count reports it, but D7 is detection, not prevention.

Also open from 594: two adjacent bad prints widen each other's neighbour span, so both stay
served (CORT 2007-09-11). Measure how many such pairs exist before deciding whether the rule
needs a pairwise form.

## Decision (lead)

The grid derivation timer (`indicagent-bar-derivation-grid`, after the Alpaca nightly) runs the
scrub on the 5m bars it touched and the 15m/1h bars it derived, through the same bar_scrub path,
before the tradeable view serves them. One code path for every timeframe; no second scrub
service.

## Done when

A bad intraday print inserted into a test fixture is flagged by the nightly path in the
integration test; the adjacent-pair count is measured and either handled or recorded with its
number.
