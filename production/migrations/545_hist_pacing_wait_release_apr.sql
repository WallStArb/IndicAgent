-- Migration 545: APR seed for the IBKR history pacing-wait release threshold (todo 485)
--
-- _hist_acquire_paced in src/providers/ibkr.py logs one ibkr.hist_pacing_wait line per
-- history request the pacing limiter actually blocked, and adds an
-- ibkr.hist_pacing_wait_released line once the total wait crosses this threshold so a
-- nightly log scan can sum real throttling time (lane pauses at the 58 req/10 min ceiling
-- previously read as hangs; AGL/APH 2026-10-01). 60 s sits above the common single-chunk
-- waits (the limiter's minimum sleep is about 1 s) but well below the 25 min lane watchdog,
-- so only genuine multi-slot throttle episodes cross it. Read by
-- scripts/infrastructure/backfill/_history_fetch.py (_load_ibkr_rate_limit_config) onto
-- ibkr._HIST_PACING_WAIT_RELEASE_S at fetcher startup. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.ibkr.hist_pacing_wait_release_s',
        'float', '60.0', 1, 1500,
        '[initial_estimate] Total pacing-limiter wait (seconds) above which ibkr.hist_pacing_wait_released is logged, so nightly log scans can sum throttling time. 60 s separates routine single-chunk waits (>=1 s each) from real saturation episodes and stays under the fetcher lane watchdog. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.ibkr.hist_pacing_wait_release_s', '60.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:545',
       'seed (pacing-wait logging, todo 485)'
  FROM config_state s
 WHERE s.config_key = 'infra.ibkr.hist_pacing_wait_release_s'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:545'
   );

COMMIT;
