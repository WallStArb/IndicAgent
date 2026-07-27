-- Migration 260: construction_spreads hypertable + alpha.construction.*/
-- infra.cross_sectional_spread_tracker.* APR seeds (Phase 167, Plan 01)
--
-- Creates the construction_spreads table that services/cross_sectional_spread_tracker.py
-- (Plans 02-05) will write to: one row per (construction_name, tf, bar_ts) recording a
-- dollar-neutral cross-sectional decile-spread portfolio (top decile long / bottom decile
-- short, ranked by a single qualifying feature) — Phase 167's productionization of the T3
-- Edge Source Thesis falsification script
-- (scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py).
--
-- Follows migration 205_alpha_frames_schema.sql's two-section template (Section 1: hypertable
-- DDL, Section 2: config_schema/config_state/config_history INSERT triad) almost line-for-line,
-- per this plan's <read_first>.
--
-- Migration number resolution (todo 095's documented collision risk): `ls
-- production/migrations/ | sort -n | tail -5` in this worktree showed 258 as the highest
-- file-tree number, but the live `indicagent` database already has migration 259
-- (259_ic_max_cell_rows_recalibration.sql, todo 183) applied — that file exists on disk in
-- the primary repo checkout but was not yet committed/visible in this worktree at execution
-- time. To avoid a genuine collision with an already-applied migration, this file is
-- numbered 260, matching 167-RESEARCH.md's own (at-the-time illustrative) recommendation.
--
-- Two deliberate deviations from RESEARCH.md's migration template, both recorded in this
-- plan's <design_decisions> so no downstream executor "fixes" them back:
--   (1) TWO net_spread_*_by_cost_bps jsonb columns (fast/slow), not RESEARCH.md's single
--       net_spread_by_cost_bps — the construction measures two lookahead scales
--       (return_fast/return_slow) and cost applies to a scale-independent turnover, so net
--       spread genuinely differs per scale. Two flat columns are explicit; one nested
--       {"fast": {...}, "slow": {...}} column is harder to query and easy to mis-key.
--   (2) one_way_turnover is NULLABLE and NULL for the corpus's genuinely-first bar (no
--       predecessor exists). Persisting NULL instead of a faked 0.0 makes a broken
--       incremental implementation detectable: a NULL count greater than 1 in this table is
--       a bug, never a data property (Pitfall 4). The T3 script itself seeds 0.0 for its
--       first bar — correct for a one-off script, wrong for this incremental service.
--
-- All statements idempotent: CREATE TABLE IF NOT EXISTS, create_hypertable(if_not_exists =>
-- TRUE), CREATE INDEX IF NOT EXISTS, ON CONFLICT (config_key) DO NOTHING. Safe to re-run.

BEGIN;

-- -------------------------------------------------------------------------
-- Section 1: construction_spreads hypertable
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS construction_spreads (
    -- Logical construction identity. Phase 167 writes exactly one value:
    -- 'ctf_momentum_decile_ls'. text (not an enum) so future constructions (multi-feature
    -- composites, other timeframes) can be added without schema churn (D-02 defers those,
    -- but the column is deliberately future-proof).
    construction_name     text        NOT NULL,

    -- Timeframe. Phase 167 writes exactly one value: '15m' (D-04).
    tf                    text        NOT NULL,

    -- The cross-section's bar timestamp; hypertable partition column.
    bar_ts                timestamptz NOT NULL,

    n_universe            int         NOT NULL,   -- symbols in this bar's ranked cross-section
    n_leg                 int         NOT NULL,   -- symbols per leg, max(1, round(n_universe * decile_fraction))

    long_leg_symbols      text[]      NOT NULL,    -- top-decile symbols (highest ranking feature)
    short_leg_symbols     text[]      NOT NULL,    -- bottom-decile symbols (lowest ranking feature)

    gross_spread_fast     double precision,        -- mean(long return_fast) - mean(short return_fast)
    gross_spread_slow     double precision,        -- mean(long return_slow) - mean(short return_slow)

    -- NULLABLE — see COMMENT ON COLUMN below (Pitfall 4 / design decision 2).
    one_way_turnover      double precision,

    -- NULLABLE (NULL exactly when one_way_turnover is NULL) — see COMMENT ON COLUMN below.
    net_spread_fast_by_cost_bps jsonb,
    net_spread_slow_by_cost_bps jsonb,

    compute_version       text        NOT NULL,    -- writer's compute_version class attribute
    created_at            timestamptz NOT NULL DEFAULT now(),

    -- PK contains the partition column bar_ts (migration 205's review-H1 constraint:
    -- TimescaleDB requires every unique index, including the PK, to contain the
    -- hypertable's partitioning column).
    PRIMARY KEY (construction_name, tf, bar_ts)
);

SELECT create_hypertable('construction_spreads', 'bar_ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS construction_spreads_name_tf_idx
    ON construction_spreads (construction_name, tf, bar_ts DESC);

COMMENT ON COLUMN construction_spreads.one_way_turnover IS
    'mean(long_changed_frac, short_changed_frac) vs. the immediately prior bar''s legs. NULL '
    'means "no predecessor bar existed" -- true only for the single genuinely-first bar of the '
    'whole corpus. A NULL count greater than 1 in this table indicates a broken incremental '
    'run (Pitfall 4: never fake this as 0.0), never a data property. The T3 falsification '
    'script (scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py) seeds '
    '0.0 for its first bar -- correct for a one-off script, wrong for this incremental service.';

COMMENT ON COLUMN construction_spreads.net_spread_fast_by_cost_bps IS
    'gross_spread_fast minus (bps/10000) * one_way_turnover, keyed by round-trip basis points '
    'as a string: {"1": x, "3": x, "5": x, "10": x}. Computed LIVE from realized '
    'one_way_turnover on every run (D-05) -- never a cached/static conclusion. Deliberately a '
    'DIFFERENT mechanism from the flat per-tf alpha.quant.cost_hurdle.<tf> APR key (Pitfall '
    '5): that key is a single value derived from median-IC-implied E[R]; this construction''s '
    'cost treatment is a liquidity-tier sweep applied to this construction''s own actually '
    'measured turnover. That key must never be read or written by this construction. NULL '
    'exactly when one_way_turnover is NULL.';

COMMENT ON COLUMN construction_spreads.net_spread_slow_by_cost_bps IS
    'Same mechanism as net_spread_fast_by_cost_bps, computed against gross_spread_slow. See '
    'that column''s comment for the full NULL-semantics and Pitfall-5 explanation.';

-- -------------------------------------------------------------------------
-- Section 2: alpha.construction.* / infra.cross_sectional_spread_tracker.* APR seeds
-- (6 new keys)
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
(
    'alpha.construction.decile_fraction',
    'float',
    '0.10',
    '[initial_estimate] Phase 167: top/bottom fraction of the ranked equity universe forming '
    'each leg of the cross-sectional decile-spread construction -- matches T3''s validated '
    '_DECILE_FRACTION exactly. NOT an ML learning target.'
),
(
    'alpha.construction.cost_hurdle_bps_round_trip',
    'json',
    '[1, 3, 5, 10]',
    '[conventional] Phase 167: todo 030''s blended round-trip cost-floor sweep (bps), applied '
    'to this construction''s ACTUAL measured one-way turnover per bar (D-05) -- distinct from '
    'the flat, single-value alpha.quant.cost_hurdle.<tf> key (do not confuse the two; Pitfall '
    '5). Seeded as a JSON array literal -- json.loads(config_value) must parse to the exact '
    'Python list [1, 3, 5, 10] of ints, never consumed via the generic cfg() str-cast helper.'
),
(
    'alpha.construction.null_shuffles',
    'int',
    '40',
    '[conventional] Phase 167: shuffled-ranking-null draw count for the construction''s gate '
    'evaluation, re-run on every --evaluate-gate invocation (unlike '
    '_DEFAULT_BOOTSTRAP_RANDOM_STATE, which stays a plain reused Python constant per '
    'RESEARCH.md) -- runtime cost is linear in this value, an operator will genuinely want to '
    'tune it. Matches T3''s validated _N_NULL_SHUFFLES. NOT an ML learning target.'
),
(
    'alpha.construction.attribution_max_static_r2',
    'float',
    '0.50',
    '[initial_estimate] Phase 167: Validation Gate 2''s ceiling for "a fixed leg-membership '
    'benchmark explains most of the spread''s return" -- above this R^2, the construction is '
    'judged a disguised static factor tilt rather than a genuine time-varying forecast. No '
    'prior empirical basis exists in this codebase for this specific ceiling; treat as a '
    'starting point pending live measurement, not a settled statistical result.'
),
(
    'infra.cross_sectional_spread_tracker.itersize',
    'int',
    '5000',
    '[conventional] Phase 167: psycopg2 named server-side cursor itersize for '
    'CrossSectionalSpreadTracker''s incremental corpus scan. Matches '
    'infra.counterfactual_tracker.itersize (migration 205) precedent. NOT an ML learning target.'
),
(
    'infra.cross_sectional_spread_tracker.chunk_size',
    'int',
    '5000',
    '[conventional] Phase 167: accumulate-and-flush chunk size for CrossSectionalSpreadTracker''s '
    'per-bar write pass. Matches infra.alpha_frame_writer.chunk_size''s precedent shape '
    '(migration 205), sized smaller here since this is a per-bar cross-sectional pass (one '
    'row per bar_ts), not a per-symbol anti-join pass. NOT an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
('alpha.construction.decile_fraction',                    '0.10',          1),
('alpha.construction.cost_hurdle_bps_round_trip',          '[1, 3, 5, 10]', 1),
('alpha.construction.null_shuffles',                       '40',            1),
('alpha.construction.attribution_max_static_r2',           '0.50',          1),
('infra.cross_sectional_spread_tracker.itersize',          '5000',          1),
('infra.cross_sectional_spread_tracker.chunk_size',        '5000',          1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
(NOW(), 'alpha.construction.decile_fraction',              1, '0.10',          'migration_260', 'Initial estimate: matches T3''s validated decile fraction exactly [initial_estimate]'),
(NOW(), 'alpha.construction.cost_hurdle_bps_round_trip',    1, '[1, 3, 5, 10]', 'migration_260', 'Conventional: todo 030 blended round-trip sweep, applied to measured turnover per D-05 [conventional]'),
(NOW(), 'alpha.construction.null_shuffles',                 1, '40',            'migration_260', 'Conventional: shuffled-ranking-null draw count, re-run per --evaluate-gate invocation [conventional]'),
(NOW(), 'alpha.construction.attribution_max_static_r2',     1, '0.50',          'migration_260', 'Initial estimate: Validation Gate 2 static-tilt ceiling, no prior empirical basis in this codebase [initial_estimate]'),
(NOW(), 'infra.cross_sectional_spread_tracker.itersize',    1, '5000',          'migration_260', 'Conventional: matches infra.counterfactual_tracker.itersize precedent [conventional]'),
(NOW(), 'infra.cross_sectional_spread_tracker.chunk_size',  1, '5000',          'migration_260', 'Conventional: matches infra.alpha_frame_writer.chunk_size precedent shape [conventional]');

COMMIT;
