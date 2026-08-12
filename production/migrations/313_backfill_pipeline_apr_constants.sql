-- Migration 313: APR-back two constants introduced by the gap-clustering /
-- batched-insert fix in infrastructure_run_historical_pipeline.py
--
-- That fix (todo 296's saga) introduced two new module-level hardcoded constants:
-- _STORE_BATCH_SIZE (market_data_ohlcv batched INSERT row count) and
-- _GAP_CLUSTER_MAX_DAYS (proximity threshold for cluster_gap_ranges()). CLAUDE.md's
-- migrate-as-you-go rule requires new numeric thresholds be APR-backed in the same
-- session. The file already has an established overlay-at-startup convention for
-- exactly this shape of constant (five _load_ibkr_* functions); this migration
-- follows the same convention rather than introducing a new one.
--
-- Named distinctly from the existing infra.backfill.insert_batch_size (that key is
-- feature_vectors-specific, owned by backfill_feature_factory.py's _compute_symbol_tf
-- per its own description) -- this script writes market_data_ohlcv, a different
-- table/writer, so it gets its own key rather than sharing one across two unrelated
-- call sites.

BEGIN;

INSERT INTO config_schema (config_key, value_type, description) VALUES
    ('infra.backfill.ohlcv_insert_batch_size', 'int',
     '[initial_estimate] Row batch size for market_data_ohlcv multi-row VALUES INSERT '
     'in scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py '
     '(store_bars). Pure infrastructure throughput knob -- output is invariant to '
     'this value. Not an ML learning target.'),
    ('infra.backfill.gap_cluster_max_days', 'int',
     '[initial_estimate] Proximity threshold (days) for cluster_gap_ranges() in '
     'scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py -- '
     'gap ranges separated by more than this many days of already-present data get '
     'their own IBKR fetch request instead of being coalesced into one request that '
     're-spans already-complete history. Pure infrastructure IBKR-budget knob -- '
     'output correctness is invariant to this value, only fetch efficiency varies. '
     'Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.backfill.ohlcv_insert_batch_size', '1000', 1),
    ('infra.backfill.gap_cluster_max_days', '90', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
