-- 406: nightly overlap re-fetch and split re-fetch depth (phase 185 plan 22, D-21).
--
-- The nightly 1d fetch re-asks the last overlap_sessions sessions, so each fresh observation
-- overlaps an earlier one in D1; a constant price ratio across the overlap is a split IBKR
-- re-scaled history for (src/intelligence/bars/seams.py, corporate_actions.py), recorded in
-- corporate_action as inferred_by nightly_overlap. On a detected split the symbol's full 1d
-- history is re-fetched split_refetch_years back and re-derived by the daily stage.
-- The seam thresholds (threshold.seam.*) were seeded by plan 15. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'infra.bar_derivation.overlap_sessions',
        'int',
        '20',
        5, 250,
        '[initial_estimate] Sessions the nightly 1d fetch re-asks beyond what D1 already holds, so a fresh observation overlaps an earlier one and a split shows as a constant price ratio (D-21). About 931 extra requests a night at 20; the 185-01/RESEARCH sizing is about 9M D1 rows a year. Not an ML learning target.'
    ),
    (
        'infra.bar_derivation.split_refetch_years',
        'int',
        '20',
        1, 40,
        '[conventional] Years of 1d history re-fetched into D1 for a symbol after a split is detected, so canonical history is on one scale again (matches the 20-year single-shot depth of the 1d backfill). Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.bar_derivation.overlap_sessions', '20', 1),
    ('infra.bar_derivation.split_refetch_years', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.bar_derivation.overlap_sessions', 1, '20', 'migration_406', 'Initial value [initial_estimate] RESEARCH sizing'),
    (NOW(), 'infra.bar_derivation.split_refetch_years', 1, '20', 'migration_406', 'Initial value [conventional] full 1d depth')
ON CONFLICT DO NOTHING;

COMMIT;
