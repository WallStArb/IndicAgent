-- Migration 350: Earnings-Season Calendar Primitive (todo 353, Phase 176 Plan 02)
--
-- Adds the two new feature_vectors columns behind the earnings-season calendar primitive
-- (earnings_season_flag, days_since_quarter_end), the three APR keys that define the
-- in-season window and gate the ic_engine conditioning pass, the concept_registry/
-- concept_gate genesis seed for both features at tier 1_interaction, and widens
-- feature_ic_scores.regime_scope's CHECK constraint to admit 'earnings_season' --
-- without this widening the first earnings-season-conditioned cell INSERT crashes
-- (Pitfall 1, 176-RESEARCH.md).
--
-- Column type: real (float32), matching the current live schema convention established
-- by migration 312 -- every feature_vectors column added since then follows it. ADD
-- COLUMN IF NOT EXISTS with no DEFAULT is metadata-only against the compressed
-- hypertable -- no decompress/recompress/VACUUM step required (confirmed via migration
-- 197/206/216/255/266/267/293/316 precedent; only a decompress -> ALTER COLUMN TYPE ->
-- recompress on EXISTING data needs the VACUUM step documented in
-- docs/foundation/timescaledb-compressed-column-migration.md, not a plain ADD COLUMN).
--
-- CRITICAL correction to 176-RESEARCH.md's drafted concept_registry INSERT (this plan's
-- objective): it omitted the 'broadcast' metadata key. Every existing calendar feature
-- (dow_sin, month_position, quarter_position, opex_flag, quad_witching_flag) carries
-- metadata->>'broadcast' = 'true', and ic_engine.py reads exactly that key (joined to
-- concept_gate) to build broadcast_features. Both new fields are symbol-invariant pure
-- functions of bar_ts, so omitting the flag would pool one observation across ~231
-- symbols and massively overstate their cross-sectional IC significance -- the exact
-- Phase 173 bug class this project already paid to fix. The broadcast metadata key set
-- to true is mandatory in both metadata objects below.
--
-- concept_registry is the sole feature-lifecycle system (feature_registry DROPped by
-- migration 311, Phase 170) -- this migration seeds it directly, no parity-mirror step.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_vectors: 2 new columns
-- ---------------------------------------------------------------------------

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS earnings_season_flag real;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS days_since_quarter_end real;

COMMENT ON COLUMN feature_vectors.earnings_season_flag IS
    '1.0 iff days_since_quarter_end falls within [feature.earnings_season.start_days, '
    'feature.earnings_season.end_days] of the most recent calendar quarter end, else 0.0. '
    'Window boundaries are APR-gated (feature.earnings_season.start_days, '
    'feature.earnings_season.end_days) -- changing either invalidates every previously '
    'computed value and requires a feature recompute. Todo 353, Phase 176.';
COMMENT ON COLUMN feature_vectors.days_since_quarter_end IS
    'Raw calendar-day count since the most recent quarter end (Mar 31/Jun 30/Sep 30/Dec '
    '31). Correlates 0.935 (Spearman) with quarter_position, which is why '
    'quarter_position is one of its parent_features. Todo 353, Phase 176.';

-- ---------------------------------------------------------------------------
-- 2. APR keys: feature.earnings_season.start_days, feature.earnings_season.end_days,
--    alpha.ic.earnings_season_conditioned
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.earnings_season.start_days',
    'int',
    '14',
    0, 91,
    '[initial_estimate] Start of the earnings-season window, in calendar days since the '
    'most recent quarter end. Seeded from D-04''s corrected proxy test (1.90x in-season/'
    'off-season ratio, p=5.05e-05, 67% of symbols). Changing this value invalidates '
    'every previously computed earnings_season_flag value and requires a feature '
    'recompute. Todo 353, Phase 176. ML learning target: yes.'
),
(
    'feature.earnings_season.end_days',
    'int',
    '42',
    1, 91,
    '[initial_estimate] End of the earnings-season window, in calendar days since the '
    'most recent quarter end. Seeded from D-04''s corrected proxy test (1.90x in-season/'
    'off-season ratio, p=5.05e-05, 67% of symbols). Changing this value invalidates '
    'every previously computed earnings_season_flag value and requires a feature '
    'recompute. Todo 353, Phase 176. ML learning target: yes.'
),
(
    'alpha.ic.earnings_season_conditioned',
    'bool',
    'true',
    NULL, NULL,
    '[user_preference] Run-level switch gating an additional IC stratification pass '
    'conditioned on earnings_season_flag. Cost scales with cross-sectional cell count -- '
    'disable to skip the extra pass entirely. Todo 353, Phase 176. Not an ML learning '
    'target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.earnings_season.start_days', '14', 1),
    ('feature.earnings_season.end_days', '42', 1),
    ('alpha.ic.earnings_season_conditioned', 'true', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.earnings_season.start_days', 1, '14', 'migration_350',
     'Seed earnings-season window start, D-04 corrected proxy test [initial_estimate]'),
    (NOW(), 'feature.earnings_season.end_days', 1, '42', 'migration_350',
     'Seed earnings-season window end, D-04 corrected proxy test [initial_estimate]'),
    (NOW(), 'alpha.ic.earnings_season_conditioned', 1, 'true', 'migration_350',
     'Seed ic_engine earnings-season conditioning switch, default on [user_preference]')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. concept_registry genesis seed: 2 new rows (domain='feature',
--    group_name='calendar', tier='1_interaction', added_phase='176')
-- ---------------------------------------------------------------------------

INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, added_phase, metadata)
VALUES
    ('feature', 'earnings_season_flag',
     '1.0 iff bar_ts falls feature.earnings_season.start_days-feature.earnings_season.end_days '
     'after the most recent calendar quarter end, else 0.0', 'active', true, 'calendar', false,
     '176',
     jsonb_build_object('tier', '1_interaction', 'formula_short',
         'days_since_quarter_end BETWEEN start_days AND end_days',
         'normalization', 'bounded_unsigned', 'linear_ready', false, 'requires_htf', false,
         'broadcast', true,
         'apr_namespace', 'feature.earnings_season.',
         'parent_features', jsonb_build_array('quarter_position', 'quarter_cycle_sin'))),
    ('feature', 'days_since_quarter_end',
     'Raw calendar days since the most recent quarter end (Mar 31/Jun 30/Sep 30/Dec 31)',
     'active', true, 'calendar', false, '176',
     jsonb_build_object('tier', '1_interaction', 'formula_short',
         'bar_ts.date() - last_quarter_end.date()',
         'normalization', 'unbounded_unsigned', 'linear_ready', true, 'requires_htf', false,
         'broadcast', true,
         'apr_namespace', 'feature.',
         'parent_features', jsonb_build_array('quarter_position', 'quarter_cycle_cos')))
ON CONFLICT (domain, name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. concept_gate seed: without these rows ic_engine.py's broadcast resolver
--    (an inner JOIN on concept_gate) will not see the new features at all.
-- ---------------------------------------------------------------------------

INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_n, fdr_required, fdr_alpha)
SELECT cr.concept_id, 'ic_sharpe_hac', 'bootstrap_ci', 100, true, 0.05
FROM concept_registry cr
WHERE cr.domain = 'feature'
  AND cr.name IN ('earnings_season_flag', 'days_since_quarter_end')
ON CONFLICT (concept_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5. feature_ic_scores.regime_scope CHECK widening: admit 'earnings_season'
-- ---------------------------------------------------------------------------

ALTER TABLE feature_ic_scores DROP CONSTRAINT IF EXISTS feature_ic_scores_regime_scope_chk;

ALTER TABLE feature_ic_scores ADD CONSTRAINT feature_ic_scores_regime_scope_chk
    CHECK (regime_scope IN ('cross_sectional', 'symbol_hmm', 'pooled', 'earnings_season'));

-- ---------------------------------------------------------------------------
-- 6. Self-asserting verification block
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    missing_columns int;
    missing_apr_keys int;
    missing_concept_rows int;
    missing_gate_rows int;
    missing_check_constraint int;
BEGIN
    SELECT count(*) INTO missing_columns
    FROM (VALUES ('earnings_season_flag'), ('days_since_quarter_end')) AS expected(column_name)
    WHERE NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'feature_vectors' AND column_name = expected.column_name
    );
    IF missing_columns > 0 THEN
        RAISE EXCEPTION 'migration_350: % expected feature_vectors column(s) missing', missing_columns;
    END IF;

    SELECT count(*) INTO missing_apr_keys
    FROM (VALUES
        ('feature.earnings_season.start_days'),
        ('feature.earnings_season.end_days'),
        ('alpha.ic.earnings_season_conditioned')
    ) AS expected(config_key)
    WHERE NOT EXISTS (
        SELECT 1 FROM config_state WHERE config_state.config_key = expected.config_key
    );
    IF missing_apr_keys > 0 THEN
        RAISE EXCEPTION 'migration_350: % expected APR key(s) missing from config_state', missing_apr_keys;
    END IF;

    SELECT count(*) INTO missing_concept_rows
    FROM (VALUES ('earnings_season_flag'), ('days_since_quarter_end')) AS expected(name)
    WHERE NOT EXISTS (
        SELECT 1 FROM concept_registry cr
        WHERE cr.domain = 'feature' AND cr.name = expected.name
          AND cr.metadata->>'broadcast' = 'true'
          AND cr.metadata->>'tier' = '1_interaction'
    );
    IF missing_concept_rows > 0 THEN
        RAISE EXCEPTION 'migration_350: % expected concept_registry row(s) missing or malformed', missing_concept_rows;
    END IF;

    SELECT count(*) INTO missing_gate_rows
    FROM (VALUES ('earnings_season_flag'), ('days_since_quarter_end')) AS expected(name)
    WHERE NOT EXISTS (
        SELECT 1 FROM concept_registry cr
        JOIN concept_gate cg USING (concept_id)
        WHERE cr.domain = 'feature' AND cr.name = expected.name
    );
    IF missing_gate_rows > 0 THEN
        RAISE EXCEPTION 'migration_350: % expected concept_gate row(s) missing', missing_gate_rows;
    END IF;

    SELECT count(*) INTO missing_check_constraint
    FROM pg_constraint
    WHERE conname = 'feature_ic_scores_regime_scope_chk'
      AND pg_get_constraintdef(oid) LIKE '%earnings_season%';
    IF missing_check_constraint = 0 THEN
        RAISE EXCEPTION 'migration_350: feature_ic_scores_regime_scope_chk missing or not widened to earnings_season';
    END IF;
END $$;

COMMIT;
