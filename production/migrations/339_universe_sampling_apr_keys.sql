-- Migration 339: alpha.universe.* sampling APR keys (Phase 174 Plan 08, D-01/D-02)
--
-- Registers the three APR keys the market-cap-stratified Russell 3000 sampling
-- script (scripts/infrastructure/universe_expansion_stratified_sourcing.py) reads
-- at the start of every run: the RNG seed, the number of market-cap strata, and
-- the target sample size.
--
-- Why `alpha.` and not `universe.`: ConfigService.OPS_PREFIXES (src/config/
-- config_service.py) has no `universe.` prefix in its allowlist -- a key outside
-- that allowlist raises ConfigValidationError on read. Sampling-methodology keys
-- for this phase live under `alpha.universe.*` instead, matching the pattern
-- already used for other alpha.* sub-namespaces (alpha.ic.*, alpha.hmm.*).
--
-- `alpha.universe.target_sample_size` DELIBERATELY defaults to 0 (= UNSET), per
-- D-01: this phase does not lock a target instrument count. The sourcing script
-- fails loud naming this key if it is still 0 at run time, rather than drawing an
-- arbitrarily-sized sample. It is set for real only in Plan 11, from a measured
-- scale-up result (the ic_engine OOM fix's actually-supported scale) -- never from
-- a guess made before that measurement exists.
--
-- Follows migration 307's Block 2 paired config_schema/config_state INSERT
-- pattern (production/migrations/307_regime_volatility_schema_apr_cvr.sql,
-- lines 85-138): both INSERTs use ON CONFLICT (config_key) DO NOTHING, safe to
-- re-run.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.universe.stratified_sample_random_state',
    'int',
    '42',
    0, NULL,
    '[user_preference] Phase 174 (D-02): RNG seed for the market-cap-stratified '
    'random draw from the Russell 3000 population. Changing this value invalidates '
    'the reproducibility of any sample already drawn with the old value -- '
    're-running the sourcing script with a different seed draws a different, '
    'non-comparable sample. Not an ML learning target.'
),
(
    'alpha.universe.cap_bucket_count',
    'int',
    '10',
    2, 50,
    '[initial_estimate] Phase 174 (D-02): number of equal-population market-cap '
    'strata (deciles at the default) pandas.qcut() bins the addressable population '
    'into for the stratified draw. Changing this value changes the sample''s '
    'composition (which names are eligible to be drawn together within a stratum). '
    'Not an ML learning target.'
),
(
    'alpha.universe.target_sample_size',
    'int',
    '0',
    0, NULL,
    '[initial_estimate] Phase 174 (D-01): number of symbols the stratified sampler '
    'draws in one run. 0 means UNSET -- the sourcing script fails loud naming this '
    'key rather than drawing an arbitrarily-sized sample. D-01 forbids locking a '
    'target count before the ic_engine memory fix''s actually-supported scale is '
    'measured (Plan 11); this key stays 0 until that measurement sets it for real. '
    'Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.universe.stratified_sample_random_state', '42', 1),
('alpha.universe.cap_bucket_count', '10', 1),
('alpha.universe.target_sample_size', '0', 1)
ON CONFLICT (config_key) DO NOTHING;

-- Idempotency: both blocks use ON CONFLICT (config_key) DO NOTHING (migration
-- 307/292's pattern). Safe to re-run -- zero errors, zero row changes.
