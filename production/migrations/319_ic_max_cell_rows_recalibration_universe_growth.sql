-- Migration 319: alpha.ic.max_cell_rows recalibration (todo TBD, follow-up to todo 183)
--
-- The 4,000,000 ceiling set by migration 259 (2026-07-26) was measured against
-- that day's largest cell (equity/5m/mid_neutral, ~2.96M rows, 171 features,
-- ~11.87GB peak RSS). Two things have grown since without a re-baseline:
-- FeatureVector went from 171 -> 298 fields (+74%), and the corpus recompute
-- launched 2026-08-15 (post-768GB-disk-full-incident relaunch) is the first
-- full run to sweep all 4 alpha.regime.groups (equity/rates/commodity/fx), not
-- just equity/rates. commodity's tag-filtered peer set (20 symbols) turns out
-- denser per-timestamp than equity's larger-but-more-sparsely-backfilled
-- universe -- commodity/5m/up_primary_contango hit 4,687,380 rows and tripped
-- the ceiling for real on 2026-08-19 (CellTooLargeError, same crash-loud path
-- as migrations 249/259).
--
-- Measured empirically, not extrapolated -- and the first measurement attempt
-- was itself wrong and had to be corrected before trusting it: a synthetic
-- allocation probe that sized the per-scale rank/bootstrap arrays at the full
-- cell row count overstated peak RSS by ~2x, because ic_engine.py actually
-- strides BEFORE that step (scale_stride = max(subsample_min_stride, lookahead_bars);
-- services/ic_engine.py:3227-3238) -- only X_raw/X_nd are genuinely full-cell-sized,
-- everything downstream operates on ~n_raw/scale_stride rows (worst case: the
-- 'fast' 5m scale, stride=5, ~937K rows). Corrected probe run at the REAL failing
-- cell's exact size (4,687,380 rows x 298 features, worst-case 100%-complete/
-- zero-degenerate-columns assumptions) peaked at 17.7GB RSS on this host's 29GB
-- total RAM (~20-21GB available at idle) -- comfortably safe, though with a
-- tighter margin than migration 259's precedent (17.7GB/~20GB available here vs.
-- 11.87GB/~22GB available then).
--
-- Cross-checked against ground truth, not just the synthetic probe: queried every
-- other unprocessed cell in the in-flight run directly (market_regimes x
-- feature_vectors x forward_returns, real tag-filtered symbol lists) --
-- commodity/up_primary_contango (4,687,380) is already the largest cell left in
-- the ENTIRE run; nothing bigger is waiting downstream in commodity's remaining
-- up_primary_neutral (1,282,936) or fx's two regimes (1,527,419 / 476,683).
--
-- New ceiling given real margin above the measured largest cell (4,687,380), not
-- pushed to the exact edge given the tighter RSS/headroom margin found this time.
-- rates and equity groups already completed cleanly under the old 4,000,000
-- ceiling and are unaffected.
--
-- Unlike migration 259, this migration does NOT bump config_schema.max_value --
-- confirmed via psql that alpha.ic.max_cell_rows' max_value is already 10,000,000,
-- comfortably above this migration's new value. A future recalibration approaching
-- that ceiling should check config_schema.max_value itself, not assume this
-- migration's absence of that step means it's never needed.

BEGIN;

UPDATE config_state
SET config_value = '6000000', version = version + 1, updated_at = NOW()
WHERE config_key = 'alpha.ic.max_cell_rows';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.ic.max_cell_rows', version, config_value, 'migration_319',
       'Recalibrated from 4,000,000 to 6,000,000 after the 2026-08-19 full-sweep '
       '(equity/rates/commodity/fx) corpus recompute hit commodity/5m/'
       'up_primary_contango at 4,687,380 rows -- migration 259''s 2026-07-26 baseline '
       'predates FeatureVector''s 171->298 field growth and never covered a full '
       '4-group sweep. Empirically measured (corrected after an initial flawed '
       'probe overstated memory by ~2x by not replicating ic_engine.py''s real '
       'per-scale stride subsampling): peak RSS 17.7GB at the exact failing cell''s '
       'size (4,687,380 rows x 298 features, worst-case assumptions), comfortably '
       'within this host''s ~20-21GB available headroom. Confirmed via direct query '
       'against every other unprocessed cell in the run that this is already the '
       'global largest cell remaining. [rca_analysis], todo TBD.'
FROM config_state WHERE config_key = 'alpha.ic.max_cell_rows';

COMMIT;
