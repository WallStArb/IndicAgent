-- Migration 524: seed the two APR keys of the Tradier deletion script (phase 191 plan 20).
--
-- scripts/ops/bars/ops_tradier_delete.py deletes every Tradier-sourced row from ohlcv_raw,
-- market_data_ohlcv, ohlcv_load, ohlcv_revision and ohlcv_coverage in per-symbol batches, one
-- transaction per batch, under the owner exception of 2026-10-12 (design doc
-- docs/plans/2026-10-12-unified-raw-bar-table-design.md). Before every batch it reads the free
-- disk and stops below infra.tradier_delete.min_free_disk_gb; infra.tradier_delete.batch_symbols
-- is the number of symbols per batch.
--
-- The keys' only reader is that script, which retires with the backup at plan 191-25 (the
-- pending-retirement entry in tests/unit/test_table_and_apr_key_readers.py carries the retire
-- clause). Seeding is non-destructive.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'infra.tradier_delete.min_free_disk_gb',
        'int',
        '200',
        1, NULL,
        '[initial_estimate] Free-disk floor in GiB for the Tradier deletion (phase 191 plan 20): ops_tradier_delete.py reads the free space of the database volume before every symbol batch and stops (state saved, nonzero exit) below this floor; the batch run also refuses to start unless the trial''s disk growth extrapolated over the remaining rows fits above it. DML decompression on compressed chunks grows the disk before the compression policy recompresses. Not an ML learning target.'
    ),
    (
        'infra.tradier_delete.batch_symbols',
        'int',
        '20',
        1, NULL,
        '[initial_estimate] Symbols per batch for the Tradier deletion (phase 191 plan 20): one transaction per batch across the five tables, so a batch bounds the decompressed rows a single transaction holds and the work lost to an abort. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.tradier_delete.min_free_disk_gb', '200', 1),
    ('infra.tradier_delete.batch_symbols', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
    (now(), 'infra.tradier_delete.min_free_disk_gb', 1, '200', 'migration_524',
     'seed: free-disk floor for the Tradier deletion batches (phase 191 plan 20, design step 10)'),
    (now(), 'infra.tradier_delete.batch_symbols', 1, '20', 'migration_524',
     'seed: symbols per Tradier deletion batch (phase 191 plan 20, design step 10)');

COMMIT;
