-- Migration 259: alpha.ic.max_cell_rows recalibration (todo 183)
--
-- The 1,200,000 ceiling seeded by migration 249 was sized ~2x the largest known
-- cell at the time (5m/low_bull cross-sectional, ~599K rows, 2026-07-18 OOM
-- incident). Todo 092's regime-rebalance fix (migrations 257/258, causal-rank
-- cut-points) legitimately shrank population imbalance between regime cells
-- (STATE.md: 13.8x->7.1x at 5m for equity) -- which grows minority-regime cells
-- like high_bear that used to be small. The live corpus recompute hit this
-- ceiling for real on 2026-07-26 (equity/5m/high_bear, CellTooLargeError).
--
-- Investigation found the ceiling's 2026-07-18 baseline predates Phase 162's own
-- OOM root-cause fix (rankdata()'s float64 upcast, previously unbounded, now
-- chunked at alpha.ic.feature_block_columns=32) -- the reference incident's
-- ~20.5GB peak RSS no longer reflects current code's actual memory shape.
-- Measured empirically instead of extrapolating: a synthetic allocation test
-- mimicking ic_engine.py's exact cross-sectional assembly (X_raw -> X_nd ->
-- per-scale ranks_X_scale, block-chunked rankdata, same dtypes/shapes) at
-- 2,964,837 rows x 171 features -- the true largest cell after a full, clean
-- market_regimes recompute under the corrected causal-rank labels (equity/5m
-- mid_neutral, superseding the smaller high_bear cell that originally failed --
-- see [1] below) -- peaked well within this host's ~22GB free headroom.
-- Cross-sectional bootstrap threading uses ThreadPoolExecutor (shared process
-- memory), not ProcessPoolExecutor, so no per-worker duplication applies to this
-- pass (services/ic_engine.py ~line 1505, 2542-2543 comments).
--
-- New ceiling sized with real margin above the measured largest cell (~3.0M
-- rows), not just 2x an old, now-irrelevant reference point. rates group's
-- largest 5m cell (steep_wide, ~507K rows) stays comfortably under either value.
--
-- [1] The recompute that surfaced this also fixed an unrelated, independently
-- confirmed gap: cross_sectional_regime_model.py's 2026-07-24 run only reflected
-- ~49-symbol eq_*/intl_* tag resolution (correct) but a stale earlier snapshot of
-- market_data_ohlcv_tradeable; a clean 2026-07-26 re-run achieves ~99.85% of the
-- theoretical achievable regular-session coverage since 2007. Not a code bug --
-- see the todo 183 file for the full trace.

BEGIN;

UPDATE config_schema
SET max_value = 10000000
WHERE config_key = 'alpha.ic.max_cell_rows' AND max_value < 10000000;

UPDATE config_state
SET config_value = '4000000', version = version + 1, updated_at = NOW()
WHERE config_key = 'alpha.ic.max_cell_rows';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.ic.max_cell_rows', version, config_value, 'migration_259',
       'Recalibrated from 1,200,000 to 4,000,000 after todo 092''s regime rebalance '
       'legitimately grew minority-regime cross-sectional cells beyond the old '
       '2026-07-18-incident-derived ceiling. Empirically measured (not extrapolated) '
       'peak RSS for the true largest cell post-recompute (~3.0M rows, equity/5m '
       'mid_neutral) via a synthetic allocation test matching ic_engine.py''s exact '
       'assembly shape under the current (Phase-162-fixed) code -- comfortably within '
       'host headroom. [rca_analysis], todo 183.'
FROM config_state WHERE config_key = 'alpha.ic.max_cell_rows';

COMMIT;
