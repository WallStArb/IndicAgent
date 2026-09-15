-- Migration 340: streaming-correlation row-block APR key (Phase 174, plan 09).
--
-- APR category 3 (infrastructure performance constant, docs/foundation/
-- adaptive-parameter-registry.md) -- this key selects HOW MANY rows are read per
-- pass-block while accumulating the feature correlation matrix for cross-sectional
-- cell clustering. It is block-size-invariant by construction: a different block
-- size must produce the identical correlation matrix (pinned by
-- tests/unit/test_ic_engine_streaming_correlation.py's block-size-invariance case),
-- so this key never changes a computed IC value or cluster label -- it changes only
-- wall time and peak transient memory during the correlation pass.
--
-- Todo 371 follow-on (Plan 05 fixed X_raw's whole-cell accumulation; this migration
-- backs the fix for the second, larger allocation Plan 05 left in place):
-- `_cluster_features`'s `np.corrcoef(X_nd.T)` internally casts to float64 -- at the
-- 15M-row `alpha.ic.max_cell_rows` ceiling with ~250 features that is a 30GB
-- transient, larger than the accumulation Plan 05 already fixed and the likeliest
-- true cause of the 2026-09-07 OOM. Plan 09 replaces it with a blocked two-pass
-- streaming correlation whose peak transient is `corr_row_block x n_features x 8`
-- bytes (float64) rather than `n_rows x n_features x 8`.
--
-- Registers exactly one new APR key, under the `infra.` prefix (consistent with
-- migration 336's ic_engine scratch/threshold keys):
--
--   - infra.ic_engine.corr_row_block: rows processed per pass-block when
--     accumulating the feature correlation matrix. Default 1,000,000 -- at
--     ~250 features, peak transient is ~2GB per block, versus ~30GB for a whole-
--     cell float64 correlation cast at the row ceiling.
--
-- [initial_estimate] -- no measurement run has calibrated this value yet. Not an
-- ML learning target.
--
-- Idempotent: APR uses ON CONFLICT (config_key) DO NOTHING (migration 292's pattern).
-- Safe to re-run.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.ic_engine.corr_row_block',
    'int',
    '1000000',
    1000, NULL,
    '[initial_estimate] Phase 174 (D-04, todo 371 follow-on): number of rows '
    'processed per pass-block when accumulating the feature correlation matrix for '
    'cross-sectional cell clustering. Peak transient memory for that step is '
    'corr_row_block x n_features x 8 bytes (float64) rather than n_rows x '
    'n_features x 8. This is an infrastructure throughput knob that does not '
    'change the computed correlation values -- a different block size must '
    'produce the identical correlation matrix. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.ic_engine.corr_row_block', '1000000', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
