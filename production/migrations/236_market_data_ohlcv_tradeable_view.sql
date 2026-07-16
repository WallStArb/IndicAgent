-- Migration 236: market_data_ohlcv_tradeable view (todo 035)
--
-- market_data_ohlcv is a continuous calendar grid: bar_normalizer.py inserts flat-OHLC,
-- zero-volume placeholder rows (source='synthetic_fill') to fill weekend/holiday/gap slots,
-- and IBKR itself separately returns flat-OHLC, zero-volume carry-forward bars
-- (source='ibkr_named') when no trade occurs in a window -- empirically confirmed
-- (2026-07-16) that 99.998% of "real" ibkr_named/volume=0 rows are perfectly flat OHLC,
-- informationally identical to synthetic_fill. volume > 0 excludes both classes with a
-- single NOT NULL integer comparison -- no source-column dependency, no NULL handling
-- needed. See docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md for
-- the full audit and the predicate-choice rationale (Decision 1).
--
-- This is a plain (non-materialized) view: Postgres inlines it into the query plan, so
-- callers get identical chunk-exclusion and index usage to an inline WHERE volume > 0 --
-- verified via EXPLAIN (COSTS OFF) against live SPY 5m data before this migration was
-- written: same compressed-chunk index scan, same vectorized columnar filter, in both
-- forms.
--
-- Named _tradeable, not _active: 'active' is already a loaded lifecycle-status term in
-- this codebase (feature_registry/concept_registry/trade_frames: candidate -> active ->
-- shadow_only/expired -> deprecated). 'tradeable' is unused elsewhere and is the term
-- todo 035 itself already used.

BEGIN;

CREATE VIEW market_data_ohlcv_tradeable AS
SELECT *
FROM market_data_ohlcv
WHERE volume > 0;

COMMIT;
