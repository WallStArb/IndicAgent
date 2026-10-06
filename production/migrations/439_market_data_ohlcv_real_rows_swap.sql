-- 439: market_data_ohlcv real-rows swap (todo 462 step 6, phase 185 plan 25).
--
-- Part 1 (plan 25 task 1, this section): the APR keys scripts/ops/bars/ops_real_rows_swap.py
-- reads for its read-only preflight. Until this file is applied the script falls back to the
-- same defaults and prints `"source": "default"` beside each value, so the fallback is never
-- silent.
--
-- Part 2 (plan 25 task 2, not written yet): the new table with the same columns, hypertable
-- partitioning, compression settings, indexes, grants and policies; the swap transaction that
-- renames the tables and recreates the dependent views (market_data_ohlcv_tradeable,
-- market_data_ohlcv_scrub_input, market_data_5m). The old table is dropped only after the
-- post-swap checks pass, followed by a bare VACUUM (compressed-hypertable rule).
--
-- Not applied as of 2026-10-06. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.real_rows_swap.disk_margin',
    'float',
    '2',
    1, 10,
    '[initial_estimate] Multiplier on the estimated peak size of the real-rows copy (the real rows uncompressed, before their chunks compress) that free disk must cover before the market_data_ohlcv swap may run (scripts/ops/bars/ops_real_rows_swap.py). Covers WAL, index builds and the estimate''s error (row-share apportioning of chunk bytes). Not an ML learning target.'
),
(
    'infra.real_rows_swap.statement_timeout_s',
    'int',
    '600',
    10, 86400,
    '[initial_estimate] statement_timeout in seconds for each preflight and verify statement of the market_data_ohlcv real-rows swap. A per-chunk count measured 0.1 to 0.4 s on 2026-10-06; a per-symbol digest of a 20-year 5m series is the longest statement. Not an ML learning target.'
),
(
    'infra.real_rows_swap.masked_audit_max_age_hours',
    'int',
    '48',
    1, 720,
    '[conventional] Oldest D7 masked-slot fact (plan 185-23, integrity_monitor masked_slots_derived_symbols) the real-rows swap accepts as proof that no derived 15m/1h slot is masked. The audit runs nightly, so 48 hours tolerates one missed night. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.real_rows_swap.disk_margin', '2', 1),
    ('infra.real_rows_swap.statement_timeout_s', '600', 1),
    ('infra.real_rows_swap.masked_audit_max_age_hours', '48', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.real_rows_swap.disk_margin', 1, '2', 'migration_439',
     'Initial value: free disk must cover twice the copy peak [initial_estimate]'),
    (NOW(), 'infra.real_rows_swap.statement_timeout_s', 1, '600', 'migration_439',
     'Initial value: ten minutes per preflight or verify statement [initial_estimate]'),
    (NOW(), 'infra.real_rows_swap.masked_audit_max_age_hours', 1, '48', 'migration_439',
     'Initial value: accept a masked-slot fact up to two days old [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
