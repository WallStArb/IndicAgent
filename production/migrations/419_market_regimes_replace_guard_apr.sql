-- Migration 419: alpha.regime.cross_sectional.max_orphan_delete_fraction APR key
-- (phase 186 plan 186-18, todo 420)
--
-- cross_sectional_regime_model.py used to upsert market_regimes (ON CONFLICT DO UPDATE), so a
-- stored row the run no longer produced (an older writer's weekend bars, a symbol that left the
-- peer set) survived every rerun. The run now replaces each (regime_group, tf) history in one
-- transaction (`_replace_group_tf`): stage, diff, DELETE + INSERT, commit once. This key is the
-- shrink guard on that replace: the largest fraction of a (group, tf)'s stored rows a run may
-- delete as orphans. Above it the run refuses, writes nothing and names the counts; the reviewed
-- cleanup run passes --accept-orphan-delete.
--
-- 0.01: a partial bar fetch or a broken peer set is the failure the guard exists for, and it
-- orphans far more than 1% of a history. The todo 420 weekend orphans (1,223,265 rows over the
-- equity and rates cells) may exceed it on some cells, which is why the first cleanup is a
-- reviewed run with --accept-orphan-delete.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.regime.cross_sectional.max_orphan_delete_fraction',
    'float',
    '0.01',
    0, 1,
    '[initial_estimate] Largest fraction of a (regime_group, tf) market_regimes history that '
    'cross_sectional_regime_model.py may delete as orphans (stored timestamps the run no longer '
    'produces) without --accept-orphan-delete; guards against a partial bar fetch silently '
    'deleting labeled history. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.regime.cross_sectional.max_orphan_delete_fraction', '0.01', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.regime.cross_sectional.max_orphan_delete_fraction', 1, '0.01',
       'migration_419',
       'Initial value [initial_estimate]: shrink guard on the atomic (regime_group, tf) replace (todo 420)'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = 'alpha.regime.cross_sectional.max_orphan_delete_fraction'
      AND h.changed_by = 'migration_419'
);

COMMIT;
