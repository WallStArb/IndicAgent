---
status: pending
priority: P2
filed: 2026-07-19
source: /simplify altitude review of todo 148 (services/forward_return_writer.py's
  return_{scale}_suspect guard) -- the review agent flagged that the fix landed two
  layers downstream of where the defect actually enters the system.
---

# Corrupt IBKR prints have no plausibility guard at bar ingestion -- every OHLCV
# consumer inherits them, not just `forward_returns`

## Problem

Todo 148 added a price-sanity guard (`return_{scale}_suspect`, sqrt-scaled per-tf
ceilings) to `forward_returns`, catching the specific failure mode that poisoned the
EM-CAL sweep: a corrupt IBKR print (UUP 5m 2007-06-20: `open=1000` on a ~$25 ETF,
`volume=200`) that passes `market_data_ohlcv_tradeable` (`WHERE volume > 0` only --
no price check) and fabricates a 368% "executable" forward return.

That fix protects `forward_returns` and its own downstream consumers
(`ops_emission_threshold_sweep.py`, `ops_ic_shrinkage.py`, `EnsembleICEngine`,
`ops_cost_hurdle_calibration.py` -- all patched same-session). But the corrupt bar
itself still flows unguarded through `market_data_ohlcv` into every OTHER consumer
that reads OHLCV directly, none of which get any protection from the 148 fix:
`services/backfill_feature_factory.py`, `services/equity_regime_model.py`,
`services/cross_sectional_regime_model.py`, `services/regime_writer.py`,
`services/counterfactual_tracker.py`, and any future consumer. `ProviderMerger` (the
sole writer to `market.bars` per DAG Invariant 1) currently applies no price
plausibility check at all.

## Fix

Add an outlier/plausibility check at bar ingestion (in `ProviderMerger` or a
validator immediately downstream of it), producing one guaranteed-clean signal per
bar -- either extend `market_data_ohlcv_tradeable`'s filter or add a new `is_suspect`
bar-level flag -- so every consumer inherits protection for free instead of each
derived-value writer reinventing its own ceiling (as `forward_returns` now does).

Candidate detection signals (todo 148's own Fix section 2 named this same class of
check, never implemented): intra-bar high/low ratio implausibility, bar-over-bar
jump-and-revert pattern (the UUP row's neighbors show a a single-bar spike then
immediate reversion -- classic bad-print signature, not a real price level).

## Sizing

Larger than todo 148 -- touches the sole writer to `market.bars`, a DAG-invariant-
protected component. Needs its own design pass (where exactly the check lives,
whether it holds/flags/drops, migration for the new flag if bar-level) rather than
a todo-sized patch. Not urgent (148's guard already stops mean-based poisoning at
the specific measurement layer that mattered for the EM-CAL finding) but is the
deeper fix 148 deferred.

## References

- `.planning/todos/completed/148-forward-return-corrupt-print-guard.md` (or
  `pending/`, depending on when this lands) -- the downstream patch this generalizes
- `services/provider_merger.py` -- sole writer to `market.bars`, DAG Invariant 1
- `production/migrations/228_market_data_ohlcv_tradeable_view.sql` -- current view,
  volume-only filter
