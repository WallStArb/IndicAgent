# 035 — market_data_ohlcv "active bars" filter belongs at one boundary, not 4 call sites

**Found:** 2026-07-01, during /simplify review of the volume>0 bar-filtering fix.

`market_data_ohlcv` is a continuous calendar grid — ~83% of intraday bars and all
weekend/holiday daily bars are zero-volume placeholder rows (market closed, no
trades). The fix applied this session adds `AND volume > 0` inline to 4 raw SQL
query sites across 3 files:

- `services/backfill_feature_factory.py` — `_FETCH_BARS_SQL`, `_FETCH_BARS_SINCE_SQL`, `_FETCH_BARS_WINDOW_SQL`
- `services/regime_writer.py` — `_compute_symbol_tf` bar fetch
- `services/forward_return_writer.py` — windowed CTE

**Update 2026-07-07:** this todo's own file list was incomplete — `services/equity_regime_model.py`
(the LIVE cross-sectional regime system, `market_regimes` table) had the exact same leak in
2 query sites (SPY realized-vol fetch, cross-sectional breadth query) and was missed by both
the original fix and this todo. Found and fixed same day (added `volume > 0` to both), ahead
of a full corpus rerun so no separate `market_regimes` recompute/invalidation was needed. Now
5 query sites across 4 files. This is exactly the failure mode the "single boundary" fix below
is meant to prevent — a 5th file already slipped through per-callsite discipline.

This works but is the wrong altitude long-term: it's a data-quality invariant
about the whole table, not a per-query concern. Every future bar-reading call
site (and `grep -rln "FROM market_data_ohlcv"` currently shows 18 files) has to
independently remember to add this predicate or silently re-admit contamination.

**Fix:** push the filter to a single boundary — either:
1. A view `market_data_ohlcv_active` (`WHERE volume > 0`) that all compute
   services select from instead of the raw table, or
2. A `market_data_ohlcv_repository.py` Ring 0/1 module exposing
   `fetch_bars(symbol, tf, since=None, window=None)` that bakes in the filter
   once, replacing the inline psycopg2 SQL in the 3 services above.

Raw table stays untouched either way (writers own the full calendar grid;
readers get one canonical "tradeable bars" surface). Not urgent — current
inline fix is correct and already validated against a live corpus rebuild;
this is a maintainability follow-up, not a bug.
