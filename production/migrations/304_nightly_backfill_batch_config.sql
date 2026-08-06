-- Migration 304: infra.ibkr.nightly_backfill_batch_size /
-- infra.ibkr.nightly_backfill_completeness_threshold
--
-- New APR keys for scripts/infrastructure/backfill/infrastructure_nightly_backfill.py,
-- introduced 2026-08-06 as a sustainable alternative to one-off multi-day foreground backfill
-- sprints (the 129-symbol client-id 43 run this same session): a systemd timer picks
-- batch_size least-backfilled active symbols each night and delegates to the existing
-- infrastructure_run_historical_pipeline.py, which does the actual gap-accounting.
--
-- batch_size=20 [initial_estimate]: matches the user's own proposed pacing. At the observed
-- ~35-40 min/symbol full-depth fetch rate (post todo-259-session bar_normalizer O(n x m) fix),
-- 20 symbols/night is roughly 12-13 hours -- fits an overnight window with margin against the
-- ~00:05 UTC IBKR gateway nightly restart. Not benchmarked against a full night's real
-- throughput yet; first cut.
--
-- completeness_threshold=150000 [initial_estimate]: rows on the 1h timeframe (the ranking
-- proxy _select_next_batch uses -- see that function's docstring) above which a symbol is
-- treated as "already backfilled" and excluded from nightly candidate selection. Chosen with
-- margin below the ~182k 1h rows a full 20yr fetch produces; a rough proxy, not a strict
-- completeness guarantee -- the delegate script's own detect_gaps() is the real correctness
-- check, this only controls what gets a slot each night.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.ibkr.nightly_backfill_batch_size',
    'int',
    '20',
    1, 200,
    '[initial_estimate] Number of least-backfilled active symbols the nightly '
    'incremental backfill job (infrastructure_nightly_backfill.py) processes per '
    'run. Not an ML learning target.'
),
(
    'infra.ibkr.nightly_backfill_completeness_threshold',
    'int',
    '150000',
    1, 10000000,
    '[initial_estimate] 1h-timeframe row count above which a symbol is treated as '
    'already backfilled and excluded from nightly candidate selection '
    '(infrastructure_nightly_backfill.py). A ranking proxy, not a correctness '
    'check -- the delegate script''s detect_gaps() is the real gap accounting. '
    'Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.ibkr.nightly_backfill_batch_size', '20', 1),
    ('infra.ibkr.nightly_backfill_completeness_threshold', '150000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.ibkr.nightly_backfill_batch_size', 1, '20', 'migration_304',
     'Seed nightly backfill batch size, todo/session 2026-08-06 [initial_estimate]'),
    (NOW(), 'infra.ibkr.nightly_backfill_completeness_threshold', 1, '150000', 'migration_304',
     'Seed nightly backfill completeness ranking threshold, todo/session 2026-08-06 '
     '[initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
