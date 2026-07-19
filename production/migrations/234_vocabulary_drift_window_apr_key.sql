-- Migration 234: infra.vocabulary_drift.window_days APR key — Phase 161 Plan 03
--
-- Note on numbering: this plan's frontmatter originally targeted migration number 239,
-- but by the time this plan executed, wave 1 of Phase 161 (161-01) had already claimed
-- 239 for the controlled_vocabulary schema (production/migrations/239_controlled_vocabulary_
-- schema.sql), and a concurrent, unrelated plan had ALSO independently claimed 239 for
-- 239_ic_engine_cross_sectional_bootstrap_threads.sql — a genuine two-file collision on the
-- same number, pre-existing on main and out of scope for this plan to fix. 240 is also taken
-- (controlled_vocabulary_seed_namespaces). 241 is the next free number.
--
-- Seeds the recent-window length (days) for the column-backed vocabulary drift audit
-- (src/config/vocabulary_drift.py). Every bounded per-namespace SELECT DISTINCT binds this
-- value as a query parameter — never a hardcoded interval literal (CLAUDE.md APR mandate:
-- infrastructure performance constants live under infra.*).
--
-- Mirrors migration 219 (alpha.ic.staleness_alert_days) exactly: config_schema +
-- config_state + config_history triple-INSERT, ON CONFLICT DO NOTHING, [initial_estimate]
-- provenance.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.vocabulary_drift.window_days',
    'int',
    '30',
    1, 365,
    '[initial_estimate] Recent-window length (days) for the column-backed vocabulary '
    'drift audit; not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.vocabulary_drift.window_days', '30', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'infra.vocabulary_drift.window_days', 1, '30', 'migration_241',
    'Initial estimate: vocabulary drift audit recent-window length [initial_estimate]'
)
ON CONFLICT DO NOTHING;

COMMIT;
