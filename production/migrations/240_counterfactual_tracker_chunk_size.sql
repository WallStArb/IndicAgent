BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.counterfactual_tracker.chunk_size',
    'int',
    '5000',
    100, 50000,
    '[conventional] CounterfactualTracker (Plan 02): per-symbol UPDATE flush chunk size. '
    'Prior code passed a whole symbol''s closed-frame rows (tens of thousands on a busy '
    'symbol) to one executemany() call, which asyncpg wraps in a single implicit '
    'transaction -- nothing became visible/committed until the entire symbol finished, '
    'so a restart after any interruption re-scanned every symbol from scratch even though '
    'closes were already computed. Chunking bounds transaction size and commits '
    'incrementally, matching infra.alpha_frame_writer.chunk_size''s established precedent '
    'for the same table. NOT an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.counterfactual_tracker.chunk_size', '5000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.counterfactual_tracker.chunk_size', 1, '5000', 'migration_240',
     'Seed chunked-commit flush size for CounterfactualTracker backfill, closes the '
     'single-giant-transaction stall found while investigating 143.1-08''s 3 zero-progress '
     'backfill attempts [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
