-- Migration 279: feature.cross_asset.role_symbols -- APR-migrate feature_vector_pipeline's
-- hardcoded cross-asset role-symbol set (todo 221/222 simplify pass)
--
-- services/feature_vector_pipeline.py hardcoded a module-level constant,
-- _CROSS_ASSET_SYMBOLS = frozenset({"SPY", "TLT", "SHY"}), as the sole driver of which
-- symbols' bars trigger a cross-asset broadcast-state refresh (_cross_asset_state_for_bar).
-- Per docs/foundation/adaptive-parameter-registry.md's "behavioral lists" APR category
-- (lists controlling WHAT the algorithm processes must be APR-backed JSON, not a Python
-- literal), this is an architecture violation independent of what the list currently
-- contains -- the same category migration 278 (todo 199) already fixed for
-- backfill_feature_factory.py's target-timeframe list two commits earlier in the same diff.
--
-- This migration does not change which symbols play the equity/long-bond/short-bond role;
-- it only moves the existing set's storage location from a Python literal to config_state,
-- seeded to the exact same 3 values so behavior is unchanged unless an operator edits this
-- key later.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.cross_asset.role_symbols',
    'json',
    '["SPY", "TLT", "SHY"]',
    null, null,
    '[conventional] JSON array of EXACTLY 3 ticker symbols in positional (equity, long_bond, short_bond) role order, read by services/feature_vector_pipeline.py. Position 0 (equity, e.g. SPY) is the sole trigger for a cross-asset broadcast-state refresh (_cross_asset_state_for_bar) -- vix_z is its realized-vol proxy. Position 1 (long_bond, e.g. TLT) and position 2 (short_bond, e.g. SHY) feed flight_quality/yield_slope_z. Order is load-bearing, not just membership -- feature_vector_pipeline fails loud at startup if this array does not have exactly 3 entries. Matches the long-standing hardcoded _CROSS_ASSET_SYMBOLS module constant this key replaces. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.cross_asset.role_symbols', '["SPY", "TLT", "SHY"]', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.cross_asset.role_symbols', 1, '["SPY", "TLT", "SHY"]', 'migration_279',
     'Seed feature_vector_pipeline cross-asset role-symbol set, /simplify altitude pass on todo 221/222 -- byte-identical to prior hardcoded _CROSS_ASSET_SYMBOLS constant.')
ON CONFLICT DO NOTHING;

COMMIT;
