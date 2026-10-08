-- 451: the fetcher's two lanes and the weekly parity sample (phase 189 plan 189-10 Task 1, as
-- amended by 185-46 Task 1 and its two 2026-10-07 amendment blocks).
--
-- scripts/infrastructure/backfill/ibkr_history_fetcher.py works one queue with two span rules
-- (scripts/infrastructure/backfill/_fetch_queue.py reads every key below through load_lane_config):
--
-- - update lane: each due series is asked since its latest stored bar, widened to overlap the
--   stored tail (1d: the last N sessions; 5m: the last N days); the overlap is compared to the
--   stored bars and a breach escalates the name to a full-depth re-fetch in the same run.
--   A name's 1d item is due when its latest answered SMART TRADES 1d request predates the close of
--   the Nth latest completed NYSE session (N = the reconcile interval), or its latest canonical
--   1d bar is not the last completed session and it was not asked since that close.
-- - gap-fill lane: a due series plans its full depth (interior holes, short starts) on one
--   session in every gap_fill_interval_days, chosen per series by a stable hash.
-- - parity sample: grid_parity_sample_names_per_week names a week (stable hash per ISO week)
--   among names holding 5m and archive rows get their vendor 15m and 1h asked into the archive.
--
-- infra.bar_derivation.overlap_sessions is renamed (state and history kept), not copied: its only
-- reader was the fetcher, and two keys for one overlap would drift apart.
-- Deferred item 6 of the phase 189 deferred-items list: the descriptions of
-- infra.ibkr.historical_request_timeout_sec and infra.backfill.default_scopes named deleted
-- machinery (the retry-loop watchdog, the nightly legs, the todo 449 campaign, PAUSE_5M).
-- Overlap tolerance: no new key; the comparison reads threshold.bar_integrity.fallback_basis_tolerance_bp
-- (10 bp). Measured 2026-10-07 over 5,558 pairs of repeated IBKR SMART TRADES 1d observations of
-- completed sessions (931 names, bar dates from 2026-08-01): 0 closes moved by more than 10 bp,
-- 1 close moved at all, 150 volumes moved.
-- Idempotent: inserts are ON CONFLICT DO NOTHING, the rename matches only the old key, history
-- rows are written once.

BEGIN;

UPDATE config_schema
   SET config_key = 'infra.backfill.update_overlap_sessions_1d',
       min_value = 0,
       description = '[initial_estimate] Sessions the update lane re-asks behind a name''s latest stored 1d observation, so each fresh SMART TRADES answer overlaps stored ones: a split shows as a constant close ratio (services/split_detection.py) and a restated close escalates the name to a full-depth 1d re-fetch in the same run. Was infra.bar_derivation.overlap_sessions (migration 406, value kept). Below threshold.seam.min_run plus one no split can be judged. Not an ML learning target.'
 WHERE config_key = 'infra.bar_derivation.overlap_sessions';
UPDATE config_state
   SET config_key = 'infra.backfill.update_overlap_sessions_1d'
 WHERE config_key = 'infra.bar_derivation.overlap_sessions';
UPDATE config_history
   SET config_key = 'infra.backfill.update_overlap_sessions_1d'
 WHERE config_key = 'infra.bar_derivation.overlap_sessions';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.backfill.ibkr_1d_reconcile_interval_days', 'int', '1', 1, 30,
 '[user_preference] Completed NYSE sessions between update-lane IBKR 1d asks for one name: its 1d item is due when its latest answered SMART TRADES 1d request predates the close of the Nth latest completed session. 1 asks every name once after every session close (owner decision 2026-10-07: Tradier unfunded, IBKR is the 1d primary; the 7-day cadence of the design doc section 7 assumed Tradier was primary). A name whose latest canonical 1d bar trails the last completed session and that was not asked since its close is due whatever N is. Not an ML learning target.'),
('infra.backfill.update_overlap_days_5m', 'int', '3', 0, 30,
 '[initial_estimate] Calendar days the update lane re-asks behind a series'' latest stored 5m bar (IBKR restates recent intraday bars: 185-31 found 15 to 40 differing rows per name). Restated rows are written and recorded in ohlcv_revision by the ingress write contract; a median stored/fresh close ratio outside threshold.bar_integrity.fallback_basis_tolerance_bp escalates the name to a full-depth 5m re-fetch in the same run. Three days reach the prior session across a weekend inside the one request the 150-day chunk already makes; calibrate from ohlcv_revision ages once the update lane runs. Not an ML learning target.'),
('infra.backfill.gap_fill_interval_days', 'int', '7', 1, 90,
 '[initial_estimate] Sessions between gap-fill passes for one series: on one session in every N (the weekday index of the last completed session, offset per series by a stable hash so the work spreads evenly; a holiday slot skips that cycle) the series plans its full depth window (interior holes, short starts) instead of the update lane''s tail. Answered and empty windows are never re-asked, so a pass costs requests only where history is missing. Not an ML learning target.'),
('infra.backfill.grid_parity_sample_names_per_week', 'int', '10', 0, 500,
 '[initial_estimate] Names a week whose vendor 15m and 1h are asked into the archive as the grid parity sample (design section 7): chosen by a stable hash of the ISO week among names holding both 5m and archive rows, the same names on every run of that week. 0 queues no 15m or 1h item. Replaces the unbounded vendor 15m/1h fetch that 189-07 stopped. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.backfill.ibkr_1d_reconcile_interval_days', '1', 1),
    ('infra.backfill.update_overlap_days_5m', '3', 1),
    ('infra.backfill.gap_fill_interval_days', '7', 1),
    ('infra.backfill.grid_parity_sample_names_per_week', '10', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_451',
       CASE config_key
           WHEN 'infra.backfill.ibkr_1d_reconcile_interval_days'
               THEN 'Initial value [user_preference]: owner decision 2026-10-07, IBKR is the 1d primary'
           WHEN 'infra.backfill.update_overlap_sessions_1d'
               THEN 'Renamed from infra.bar_derivation.overlap_sessions, value kept [initial_estimate]'
           ELSE 'Initial value [initial_estimate]'
       END
  FROM config_state
 WHERE config_key IN ('infra.backfill.ibkr_1d_reconcile_interval_days',
                      'infra.backfill.update_overlap_sessions_1d',
                      'infra.backfill.update_overlap_days_5m',
                      'infra.backfill.gap_fill_interval_days',
                      'infra.backfill.grid_parity_sample_names_per_week')
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_451');

UPDATE config_schema
   SET description = '[rca_analysis] Outer asyncio.wait_for() timeout wrapping each reqHistoricalDataAsync call, on top of ib_async''s own internal timeout. Added after a 2026-07-05 backfill hang where the internal timeout never fired despite 25+ minutes elapsed (py-spy/strace: the process was idle, not blocked). Not a guaranteed fix for asyncio timer reliability: the fetcher''s per-item stall bound (infra.ibkr.history_request_timeout) and the indicagent-ibkr-history-fetcher unit''s WatchdogSec are the safety nets. Not an ML target.'
 WHERE config_key = 'infra.ibkr.historical_request_timeout_sec';

UPDATE config_schema
   SET description = '[user_preference] The (eligibility dimension -> timeframes) union the IBKR history fetcher queues when run without --dimension/--timeframes/--symbols. Since 189-07: 1d and 5m for compute_1d; vendor 15m and 1h are asked only as the weekly parity sample (infra.backfill.grid_parity_sample_names_per_week) and the grid derives 15m and 1h from 5m. 1m is out (todo 455). A timeframe is added by an APR edit, not code. Not an ML learning target.'
 WHERE config_key = 'infra.backfill.default_scopes';

COMMIT;
