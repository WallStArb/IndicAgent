-- 381: bar_quality_flag quarantine side table, bar_derivation_batch provenance,
-- scrub-input view, tradeable-view anti-join, legacy price-sanity copy, scrub APR
-- seeds (phase 185 plans 04/05/10; D-08, D-09, D-12; folds todo 347's unused index).
--
-- D-09 flag-never-delete: quarantine hides a bar from every reader through
-- market_data_ohlcv_tradeable's anti-join; the bar itself is never UPDATEd or
-- deleted. A side table (not a status column) because row UPDATEs on compressed
-- chunks are the expensive path (todo 155 measured 7.55 s per 500-row UPDATE
-- batch) and RESEARCH finding 4 measured no read cost for the anti-join.
--
-- Baseline EXPLAIN (ANALYZE) 2026-09-27, before this migration:
--   S0 1d read shape (tradeable, timeframe='1d', timestamp >= '2016-01-01'):
--     Execution Time: 1042.819 ms
--   SPY 5m read for 2024: Execution Time: 10.162 ms
-- Anti-join proxy (CTE of the 67 confirmed_corrupt keys standing in for the
-- quarantine table; the proxy re-scans the hypertable for the keys, the real
-- partial-indexed side table is strictly cheaper):
--   S0 1d: Execution Time: 705.333 ms
--   SPY 5m: Execution Time: 65.808 ms
-- After-apply numbers appended below in the same edit series (task 2).
--
-- Not a compressed-hypertable column change: no decompress_chunk anywhere; the
-- legacy status copy is a read over compressed chunks and an INSERT into a plain
-- table. No VACUUM step applies.

BEGIN;

-- Provenance: one row per derivation-side run (D-08). Created first: the flag
-- table's batch_id references it.
CREATE TABLE IF NOT EXISTS bar_derivation_batch (
    batch_id uuid PRIMARY KEY,
    stage text NOT NULL CHECK (stage IN ('scrub','grid','daily','seam_audit','listing_venue','legacy')),
    rule_version text NOT NULL,
    code_commit text NOT NULL,
    apr_snapshot jsonb NOT NULL,
    n_symbols integer,
    status text NOT NULL CHECK (status IN ('running','completed','failed')),
    started_at timestamptz NOT NULL,
    finished_at timestamptz NULL,
    detail jsonb NOT NULL DEFAULT '{}'
);
COMMENT ON TABLE bar_derivation_batch IS 'Provenance for every derivation-side run (scrub, grid, daily, seam audit, listing venue, legacy imports): stage, rule version, code commit, APR snapshot, status. Single writer role bar_derivation_writer.';

CREATE TABLE IF NOT EXISTS bar_quality_flag (
    symbol text NOT NULL,
    timeframe text NOT NULL,
    "timestamp" timestamptz NOT NULL,
    rule text NOT NULL,
    rule_version text NOT NULL,
    fields text[] NOT NULL DEFAULT '{}',
    quarantine boolean NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}',
    flagged_at timestamptz NOT NULL DEFAULT now(),
    batch_id uuid NULL REFERENCES bar_derivation_batch(batch_id),
    PRIMARY KEY (symbol, timeframe, "timestamp", rule)
);
COMMENT ON TABLE bar_quality_flag IS 'D-09 flag-never-delete quarantine side table: one row per (bar, rule) verdict. quarantine=true hides the bar from market_data_ohlcv_tradeable; the bar row itself is never modified. Single writer role bar_derivation_writer.';

CREATE INDEX IF NOT EXISTS idx_bar_quality_flag_quarantine
    ON bar_quality_flag (symbol, timeframe, "timestamp") WHERE quarantine;

-- Writer role (NOLOGIN; reached through SET LOCAL ROLE by the postgres login,
-- design 14.5, same shape as migration 380).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bar_derivation_writer') THEN
        CREATE ROLE bar_derivation_writer NOLOGIN;
    END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON bar_quality_flag, bar_derivation_batch TO bar_derivation_writer;
GRANT SELECT ON market_data_ohlcv, market_data_ohlcv_tradeable, config_state, instruments TO bar_derivation_writer;

-- Legacy copy: every non-null price_sanity_status becomes a flag row (D-12).
-- confirmed_corrupt quarantines; ambiguous/plausible are recorded, not
-- quarantining. 567 rows measured (67 confirmed_corrupt) 2026-09-27.
INSERT INTO bar_quality_flag (symbol, timeframe, "timestamp", rule, rule_version, fields, quarantine, detail)
SELECT symbol, timeframe, "timestamp", 'legacy_price_sanity_status', 'legacy', '{}',
       price_sanity_status = 'confirmed_corrupt',
       jsonb_build_object('price_sanity_status', price_sanity_status)
FROM market_data_ohlcv
WHERE price_sanity_status IS NOT NULL
ON CONFLICT DO NOTHING;

-- Todo 347's partial index was never used by any query; D-12 folds the todo.
DROP INDEX IF EXISTS idx_market_data_ohlcv_price_sanity_unaudited;

-- Scrub-stage read boundary: every traded bar, quarantined included, so D2a and
-- D5 can re-judge bars the tradeable view hides without a raw-table read.
CREATE OR REPLACE VIEW market_data_ohlcv_scrub_input AS
SELECT "timestamp", symbol, timeframe, open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE volume > 0;
COMMENT ON VIEW market_data_ohlcv_scrub_input IS 'For the D2a scrub and D5 seam stages only: every traded bar (volume > 0, all sources, quarantined bars included). Every other reader uses market_data_ohlcv_tradeable.';
GRANT SELECT ON market_data_ohlcv_scrub_input TO bar_derivation_writer;

-- The read boundary gains the quarantine anti-join. Column list and order are
-- unchanged (11 columns; RESEARCH finding 2: readers depend on the shape).
CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS
SELECT "timestamp",
       symbol,
       timeframe,
       open,
       high,
       low,
       close,
       CASE WHEN source = 'ibkr_venue' THEN NULL ELSE volume END AS volume,
       source,
       base,
       price_sanity_status
FROM market_data_ohlcv
WHERE volume > 0
  AND price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'
  AND NOT EXISTS (
      SELECT 1 FROM bar_quality_flag q
      WHERE q.quarantine
        AND q.symbol = market_data_ohlcv.symbol
        AND q.timeframe = market_data_ohlcv.timeframe
        AND q."timestamp" = market_data_ohlcv."timestamp"
  );
COMMENT ON VIEW market_data_ohlcv_tradeable IS 'Compute/measurement read boundary: traded bars (volume > 0), venue volume nulled, confirmed_corrupt and quarantine-flagged bars (bar_quality_flag) excluded. Raw-table access outside this needs a test_market_data_ohlcv_boundary.py allow-list entry.';

-- APR seeds (threshold.bar_scrub.* + infra.bar_scrub.*): D-08. Scrub rules
-- (plan 05) and the pass (plan 10) read exactly these keys.
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    ('threshold.bar_scrub.jump_sigma', 'float', '8.0', '1', '1000', '[initial_estimate] Abs log return over rolling sigma above which vol_scaled_jump flags a bar. Informational (not quarantining) until validated. Not an ML learning target.'),
    ('threshold.bar_scrub.jump_vol_window', 'int', '60', '5', '10000', '[conventional] Rolling window (bars) for the vol_scaled_jump sigma estimate. Not an ML learning target.'),
    ('threshold.bar_scrub.stale_run_min', 'int', '5', '2', '1000', '[initial_estimate] Consecutive identical-OHLC traded bars (volume > 0) before stale_print flags a run. Informational until validated. Not an ML learning target.'),
    ('threshold.bar_scrub.volume_outlier_mad', 'float', '10.0', '1', '1000', '[initial_estimate] Robust z of log volume above which volume_outlier flags a bar. Informational until validated. Not an ML learning target.'),
    ('threshold.bar_scrub.volume_window', 'int', '60', '5', '10000', '[conventional] Rolling window (bars) for the volume_outlier MAD estimate. Not an ML learning target.'),
    ('threshold.bar_scrub.corroboration_max_clearable_ratio', 'float', '2.5', '0.1', '100', '[rca_analysis] D-11 ceiling: corroboration can clear at most this multiple of the magnitude threshold (inverse of the 2010-05-06 60% break rule); below alpha.quant.price_sanity.magnitude_threshold 10.0 so no CONFIRMED_CORRUPT print is ever cleared. Not an ML learning target.'),
    ('threshold.bar_scrub.view_disagreement_rel', 'float', '0.02', '0', '1', '[initial_estimate] Relative price disagreement above which view_disagreement flags a bar (TRADES vs ADJUSTED_LAST pairing). Not an ML learning target.'),
    ('threshold.bar_scrub.quarantine_rules', 'json', '["ohlc_invariant","non_positive_price","price_sanity","split_seam","legacy_price_sanity_status"]', NULL, NULL, '[user_preference] Rules whose flags quarantine a bar (D-09 flag-never-delete). jump/stale/volume rules stay informational until validated (Pitfall 5). Not an ML learning target.'),
    ('infra.bar_scrub.symbol_batch', 'int', '50', '1', '10000', '[initial_estimate] Symbols per batch in the D2a scrub pass (plan 10). Bounded to keep per-batch memory small. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_scrub.jump_sigma', '8.0', 1),
    ('threshold.bar_scrub.jump_vol_window', '60', 1),
    ('threshold.bar_scrub.stale_run_min', '5', 1),
    ('threshold.bar_scrub.volume_outlier_mad', '10.0', 1),
    ('threshold.bar_scrub.volume_window', '60', 1),
    ('threshold.bar_scrub.corroboration_max_clearable_ratio', '2.5', 1),
    ('threshold.bar_scrub.view_disagreement_rel', '0.02', 1),
    ('threshold.bar_scrub.quarantine_rules', '["ohlc_invariant","non_positive_price","price_sanity","split_seam","legacy_price_sanity_status"]', 1),
    ('infra.bar_scrub.symbol_batch', '50', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'threshold.bar_scrub.jump_sigma', 1, '8.0', 'migration_381', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_scrub.jump_vol_window', 1, '60', 'migration_381', 'Initial value [conventional]'),
    (NOW(), 'threshold.bar_scrub.stale_run_min', 1, '5', 'migration_381', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_scrub.volume_outlier_mad', 1, '10.0', 'migration_381', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_scrub.volume_window', 1, '60', 'migration_381', 'Initial value [conventional]'),
    (NOW(), 'threshold.bar_scrub.corroboration_max_clearable_ratio', 1, '2.5', 'migration_381', 'Initial value [rca_analysis]'),
    (NOW(), 'threshold.bar_scrub.view_disagreement_rel', 1, '0.02', 'migration_381', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_scrub.quarantine_rules', 1, '["ohlc_invariant","non_positive_price","price_sanity","split_seam","legacy_price_sanity_status"]', 'migration_381', 'Initial value [user_preference]'),
    (NOW(), 'infra.bar_scrub.symbol_batch', 1, '50', 'migration_381', 'Initial value [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
