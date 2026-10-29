-- Migration 542: the bar reconciliation audit waits for the fetcher lock (coverage_cache starvation)
--
-- The coverage_cache verdict rebuilds the coverage ledger under the IBKR history fetcher lock. The
-- fetcher timer (OnUnitInactiveSec=15min) now runs back-to-back windows of about 3 to 5 hours, so a
-- single non-blocking try almost never succeeds and the verdict went stale (last written
-- 2026-10-26, past the 30 h freshness the rebuild gate requires). The audit now polls the try-lock
-- every coverage_cache_lock_poll_s seconds for up to coverage_cache_lock_wait_s seconds, then skips loudly as before. Read by
-- services/bar_reconciliation_audit.py (_IntegrityParams). Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.bar_integrity.coverage_cache_lock_wait_s',
        'int', '21600', 0, 28800,
        '[initial_estimate] Longest the bar reconciliation audit waits for the fetcher lock before the coverage_cache verdict is skipped. 21600 s (6 h) covers one fetcher window of up to about 5 h plus the 15 min gap between windows, so the audit gets the lock at the next gap. 0 restores the single try. Not an ML learning target.'
    ),
    (
        'infra.bar_integrity.coverage_cache_lock_poll_s',
        'int', '30', 1, 3600,
        '[initial_estimate] Seconds between the audit''s non-blocking tries for the fetcher lock while it waits. The gap between fetcher windows is 15 min, so 30 s catches it within about 3 percent of its length; each try opens and closes its own short connection. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.bar_integrity.coverage_cache_lock_wait_s', '21600', 1),
    ('infra.bar_integrity.coverage_cache_lock_poll_s', '30', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:542',
       'seed (coverage_cache verdict starved by the fetcher lock)'
  FROM config_state s
 WHERE s.config_key IN ('infra.bar_integrity.coverage_cache_lock_wait_s',
                        'infra.bar_integrity.coverage_cache_lock_poll_s')
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:542'
   );

COMMIT;
