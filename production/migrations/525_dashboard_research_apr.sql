-- Migration 525: two Data and Research page bounds (dashboard v3.5,
-- docs/plans/2026-10-26-dashboard-v35-cockpit-design.md, Progress items for slices 2 and 5).
--
-- ui.dashboard.integrity_window_hours (reader: src/api/routes/data.py): an integrity check writes
-- one row per subject and commits per row, so one run spreads over many timestamps. The Data page
-- counts each subject's newest result within this many hours before the check's own newest row (a
-- check that last ran weeks ago still shows its last run). The checks run nightly, start a few
-- minutes apart from night to night, and a run spans under an hour, so 12 hours holds the newest
-- run and never reaches back into the night before (a whole day would, whenever tonight's run
-- starts earlier than last night's). Not an ML learning target.
--
-- ui.dashboard.research_rows (reader: src/api/routes/research.py): the newest research_run
-- attempts the Research page lists. The ledger is append-only and exploration mode (E18) records
-- every attempt, so the list is capped; counts and looks per vintage stay over the whole ledger.
-- Not an ML learning target.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'ui.dashboard.integrity_window_hours',
        'int',
        '12',
        1, NULL,
        '[initial_estimate] Hours before each integrity check''s newest row within which the Data page takes every subject''s newest result as the check''s current state. Checks run nightly and a run spans under an hour, so 12 hours holds the newest run and never the night before. Not an ML learning target.'
    ),
    (
        'ui.dashboard.research_rows',
        'int',
        '500',
        1, NULL,
        '[initial_estimate] Newest research_run attempts the Research page lists; the ledger grows without bound under exploration mode (E18). Counts and looks per vintage cover the whole ledger. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('ui.dashboard.integrity_window_hours', '12', 1),
    ('ui.dashboard.research_rows', '500', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), k, 1, v, 'migration_525', r
FROM (VALUES
    ('ui.dashboard.integrity_window_hours', '12',
     'seed: integrity per-subject window (dashboard Data page, slice 2 review item 1)'),
    ('ui.dashboard.research_rows', '500',
     'seed: Research page attempts cap (dashboard slice 5 review)')
) AS s(k, v, r)
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h WHERE h.config_key = s.k AND h.changed_by = 'migration_525'
);

COMMIT;
