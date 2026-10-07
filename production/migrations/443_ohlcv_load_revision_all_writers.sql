-- 443: ohlcv_load and ohlcv_revision become the write record of every canonical writer (plan 185-31).
--
-- Data layer integrity design (docs/plans/2026-10-06-data-layer-integrity-design.md), sections 3
-- and 4. ohlcv_load widens from "one Tradier daily load" to the write record of every canonical
-- writer: source tradier, ibkr or derived; any stored timeframe; destination d1,
-- market_data_ohlcv or archive; the batch it ran in; and the write contract's counts (n_new,
-- n_changed, n_unchanged, n_removed). ohlcv_revision becomes the one revision table, with an
-- origin: 'load' (the old value of a row a load changed or removed) or 'archive_segment' (a stored
-- vendor intraday row the archive does not hold equal, recorded when the derived grid replaces
-- it; todo 490).
--
-- Why the existing tables and not a sibling ohlcv_intraday_raw_revision: one parent row for every
-- timeframe and one revision table is one place to look for a replaced value (design section
-- 10). The archive is a compressed hypertable keyed (timestamp, symbol, timeframe) and kept
-- append-only, so giving it an observation key cannot be done cheaply; a second observation of
-- an archived bar goes here instead.
--
-- Existing rows: every load before 185-38 wrote canonical bars, so destination defaults to
-- 'market_data_ohlcv'; n_unchanged and n_removed stay NULL (not recorded) on them, and existing
-- revisions are origin 'load'. Readers that mean "Tradier owns this name" require
-- source = 'tradier' from this plan on (bar_derivation, the Tradier loader, D7).
--
-- APR: threshold.bar_integrity.max_revision_ratio generalizes infra.tradier.max_changed_bar_ratio
-- (that key keeps its reader until 185-38; 185-43 retires it). The grid stage's write method
-- moves from segment_delete_copy to write_contract.
-- Idempotent.

BEGIN;

ALTER TABLE ohlcv_load DROP CONSTRAINT IF EXISTS ohlcv_load_source_check;
ALTER TABLE ohlcv_load
    ADD CONSTRAINT ohlcv_load_source_check CHECK (source IN ('tradier', 'ibkr', 'derived'));

ALTER TABLE ohlcv_load DROP CONSTRAINT IF EXISTS ohlcv_load_timeframe_check;
ALTER TABLE ohlcv_load
    ADD CONSTRAINT ohlcv_load_timeframe_check
    CHECK (timeframe IN ('1d', '5m', '1m', '15m', '1h', '4h'));

ALTER TABLE ohlcv_load DROP CONSTRAINT IF EXISTS ohlcv_load_outcome_check;
ALTER TABLE ohlcv_load
    ADD CONSTRAINT ohlcv_load_outcome_check
    CHECK (outcome IN ('loaded', 'short_history', 'no_data', 'failed', 'gated',
                       'applied', 'refused'));

ALTER TABLE ohlcv_load ADD COLUMN IF NOT EXISTS batch_id uuid;
ALTER TABLE ohlcv_load ADD COLUMN IF NOT EXISTS n_unchanged integer;
ALTER TABLE ohlcv_load ADD COLUMN IF NOT EXISTS n_removed integer;
ALTER TABLE ohlcv_load
    ADD COLUMN IF NOT EXISTS destination text NOT NULL DEFAULT 'market_data_ohlcv';

ALTER TABLE ohlcv_load DROP CONSTRAINT IF EXISTS ohlcv_load_n_unchanged_check;
ALTER TABLE ohlcv_load
    ADD CONSTRAINT ohlcv_load_n_unchanged_check CHECK (n_unchanged >= 0);
ALTER TABLE ohlcv_load DROP CONSTRAINT IF EXISTS ohlcv_load_n_removed_check;
ALTER TABLE ohlcv_load
    ADD CONSTRAINT ohlcv_load_n_removed_check CHECK (n_removed >= 0);
ALTER TABLE ohlcv_load DROP CONSTRAINT IF EXISTS ohlcv_load_destination_check;
ALTER TABLE ohlcv_load
    ADD CONSTRAINT ohlcv_load_destination_check
    CHECK (destination IN ('d1', 'market_data_ohlcv', 'archive'));

ALTER TABLE ohlcv_revision
    ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'load';
ALTER TABLE ohlcv_revision DROP CONSTRAINT IF EXISTS ohlcv_revision_origin_check;
ALTER TABLE ohlcv_revision
    ADD CONSTRAINT ohlcv_revision_origin_check CHECK (origin IN ('load', 'archive_segment'));
-- A fallback 1d head carries no volume (design section 2), so its old value may not either.
ALTER TABLE ohlcv_revision ALTER COLUMN old_volume DROP NOT NULL;

-- The grid stage records its loads and old values under SET LOCAL ROLE bar_derivation_writer
-- (it had SELECT on ohlcv_load only; 185-30 decision 3 kept it off ohlcv_revision until a writer
-- needed it).
GRANT SELECT, INSERT ON ohlcv_load, ohlcv_revision TO bar_derivation_writer;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('threshold.bar_integrity.max_revision_ratio', 'float', '0.02', 0, 1,
 '[initial_estimate] Largest (changed + removed) / stored fraction a canonical or raw write may revise before it is refused as a finding; a recorded corporate action or source-policy change waives it. Generalizes infra.tradier.max_changed_bar_ratio. Not an ML learning target.'),
('threshold.bar_integrity.revision_ratio_min_stored', 'int', '500', 0, NULL,
 '[initial_estimate] Fewest stored rows a write must touch before the revision-ratio refusal applies; below it every restatement is written and recorded (a fetcher tail window holds about 78 5m bars, and IBKR restates recent bars). Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.max_revision_ratio', '0.02', 1),
    ('threshold.bar_integrity.revision_ratio_min_stored', '500', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_443',
       'Initial value for the write contract revision refusal [initial_estimate]'
  FROM config_state
 WHERE config_key IN ('threshold.bar_integrity.max_revision_ratio',
                      'threshold.bar_integrity.revision_ratio_min_stored')
ON CONFLICT DO NOTHING;

-- The grid stage's write method (plan 185-31): compare derived rows with stored rows and write
-- only new and changed ones, instead of deleting and rewriting the whole segment.
UPDATE config_schema
   SET default_value = 'write_contract',
       description = '[rca_analysis] Write method the grid stage uses for a (symbol, 15m/1h) segment: write_contract (classify derived rows against stored rows by exact value; write new and changed rows only, record old values in ohlcv_revision, archive and verify vendor rows before they leave; plan 185-31). Replaced segment_delete_copy (185-01 measurements c/d). Changing this key does not switch code paths; it records the implemented method. Not an ML learning target.'
 WHERE config_key = 'infra.bar_derivation.grid_write_method';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version + 1, 'write_contract', 'migration_443',
       'Grid stage writes by the write contract (plan 185-31) [rca_analysis]'
  FROM config_state
 WHERE config_key = 'infra.bar_derivation.grid_write_method'
   AND config_value <> 'write_contract'
ON CONFLICT DO NOTHING;

UPDATE config_state
   SET config_value = 'write_contract', version = version + 1
 WHERE config_key = 'infra.bar_derivation.grid_write_method'
   AND config_value <> 'write_contract';

COMMIT;
