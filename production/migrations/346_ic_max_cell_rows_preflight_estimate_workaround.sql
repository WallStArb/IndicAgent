-- Migration 346: alpha.ic.max_cell_rows temporarily raised to clear a pre-flight estimate artifact
--
-- The 2026-09-17 full corpus ic_engine run (233 symbols x 4 tfs) finished its per-symbol and
-- pooled passes and the 1d/1h cross-sectional cells, then died 2026-09-20 09:19 UTC on the first
-- 15m cross-sectional cell: "pre-flight estimate tf=15m regime=high_bear has 21523866 rows,
-- exceeding alpha.ic.max_cell_rows=15000000".
--
-- The estimate is not a row count. Commit 100f0602b (2026-09-15, Phase 174-05, todo 371) computes
-- it as len(regime_timestamps) * len(symbol_list), which assumes every symbol has a feature row at
-- every regime timestamp. Most symbols have far less feature history than the 2006 regime
-- timestamps, so it overstates by 2-6x. Real counts measured 2026-09-20 by joining market_regimes
-- to feature_vectors over all 233 symbols (an upper bound for the 182-symbol equity group):
--   15m high_bear   4,100,729  (estimate 21,523,866)
--   5m mid_neutral 12,542,631  (estimate 26,468,988; largest real cell)
--   5m high_bear   11,435,299  (estimate 64,030,512)
-- Every remaining cell is under the 15M ceiling by its real count.
--
-- Why an APR change and not the code fix (an exact pre-flight count): max_cell_rows is an
-- OPERATIONAL field, excluded from the cell fingerprint (services/ic_engine.py
-- _COMPUTATIONAL_CONFIG_FIELDS), so changing it keeps every completed cell valid. Any edit to
-- ic_engine.py moves code_content_key (AST hash of every imported first-party module) and would
-- discard the completed 2.6 day per-symbol pass.
--
-- New ceiling: 100,000,000, just above the largest estimate (5m low_bull, 98,055,230), so the
-- estimate cannot trip. The post-materialization check uses the same ceiling against the real
-- count, so the crash-loud guard is loose for this rerun only. Restore 15,000,000 when the exact
-- pre-flight count lands (bundled with the next change that forces a recompute anyway).
-- The disk headroom pre-check uses the same estimate (2.2 x rows x features x 4 bytes, about
-- 250 GB for 5m low_bull) and passes against roughly 560 GB free on /var/tmp.

BEGIN;

UPDATE config_schema
SET max_value = 150000000
WHERE config_key = 'alpha.ic.max_cell_rows' AND max_value < 150000000;

UPDATE config_state
SET config_value = '100000000', version = version + 1, updated_at = NOW()
WHERE config_key = 'alpha.ic.max_cell_rows';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.ic.max_cell_rows', version, config_value, 'migration_346',
       'Raised from 15,000,000 to 100,000,000 so the Phase 174-05 pre-flight estimate '
       '(regime timestamps x symbols, assumes full density) stops tripping on cells whose real '
       'row count is at most 12.5M. Operational field, not in the cell fingerprint, so completed '
       'cells stay valid. Temporary: restore 15,000,000 when the exact pre-flight count lands. '
       '[rca_analysis], todo 371.'
FROM config_state WHERE config_key = 'alpha.ic.max_cell_rows';

COMMIT;
