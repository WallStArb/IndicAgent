-- Migration 192: IBKR historical-data chunk-size limits -> infra.ibkr.chunk_days.*
--
-- Migrates _MAX_CHUNK_DAYS from a hardcoded module-level dict in src/providers/ibkr.py
-- to APR. These are per-request duration ceilings for reqHistoricalDataAsync (how many
-- days of bars IBKR will return per single API call before timing out or erroring),
-- distinct from infra.backfill.depth_days.* (migration 191, how far back total history
-- should reach). 5m and 1h were re-verified via direct probes on 2026-07-02 (DBC/PPLT/
-- SDOG/SPHB/IPO) and raised from a conservative 29d; 15m's 59d ceiling has not had the
-- same re-verification pass and may be under-tuned relative to what IBKR actually
-- tolerates -- flagged as a follow-up, not resolved by this migration. Values seeded
-- here exactly match the current hardcoded defaults, so this migration changes no
-- runtime behavior until an operator edits a config_state row.
--
-- All statements idempotent: ON CONFLICT DO NOTHING per key insert. Safe to re-run.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
  ('infra.ibkr.chunk_days.1m', 'int', '6',
   'Per-request duration ceiling (days) for reqHistoricalDataAsync at 1m bar size. '
   '[rca_analysis] IBKR per-request limit ~7 days at this granularity; retention is '
   '10+ years but each single request must stay under this window. Not an ML target.'),
  ('infra.ibkr.chunk_days.5m', 'int', '89',
   '[rca_analysis] Verified 90D succeeds, 180D times out; 89D leaves margin. Was 29d -- '
   'the original cap predated the sliding-window rate limiter and likely conflated '
   'pacing (Error 162) with a true duration ceiling. Re-verified 2026-07-02 via direct '
   'probes on DBC/PPLT/SDOG. Not an ML target.'),
  ('infra.ibkr.chunk_days.15m', 'int', '59',
   '[initial_estimate] Per-request limit ~60 days. Unlike 5m/1h, this value has not had '
   'a 2026-07-02-style re-verification probe -- flagged as possibly under-tuned (15m '
   'bars are less dense than 5m, so a larger ceiling may be tolerable). Not an ML '
   'target; recalibrate empirically before trusting as a true ceiling.'),
  ('infra.ibkr.chunk_days.1h', 'int', '364',
   '[rca_analysis] Verified 364D succeeds cleanly, matching 1d. Was reduced to 29d after '
   '"some ETFs" failed on 2026-06-22 (commit 8472a074); re-verified 2026-07-02 via '
   'direct probes on DBC/SPHB/IPO/PPLT/SDOG, all succeeded -- likely the same pacing/'
   'duration conflation as 5m. Not an ML target.'),
  ('infra.ibkr.chunk_days.4h', 'int', '29',
   '[initial_estimate] Per-request duration ceiling (days) for 4h bar size. Not '
   're-verified alongside 5m/1h on 2026-07-02. Not an ML target.'),
  ('infra.ibkr.chunk_days.1d', 'int', '364',
   '[rca_analysis] 1-year chunks; daily bars support full-year requests cleanly. '
   '~20 chunks needed for 20yr depth. Not an ML target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('infra.ibkr.chunk_days.1m', '6', 1),
  ('infra.ibkr.chunk_days.5m', '89', 1),
  ('infra.ibkr.chunk_days.15m', '59', 1),
  ('infra.ibkr.chunk_days.1h', '364', 1),
  ('infra.ibkr.chunk_days.4h', '29', 1),
  ('infra.ibkr.chunk_days.1d', '364', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
  (NOW(), 'infra.ibkr.chunk_days.1m', 1, '6', 'migration_197',
   'Migrate-as-you-go: hardcoded _MAX_CHUNK_DAYS moved to APR, same default value [rca_analysis]'),
  (NOW(), 'infra.ibkr.chunk_days.5m', 1, '89', 'migration_197',
   'Migrate-as-you-go: hardcoded _MAX_CHUNK_DAYS moved to APR, same default value [rca_analysis]'),
  (NOW(), 'infra.ibkr.chunk_days.15m', 1, '59', 'migration_197',
   'Migrate-as-you-go: hardcoded _MAX_CHUNK_DAYS moved to APR, same default value [initial_estimate]'),
  (NOW(), 'infra.ibkr.chunk_days.1h', 1, '364', 'migration_197',
   'Migrate-as-you-go: hardcoded _MAX_CHUNK_DAYS moved to APR, same default value [rca_analysis]'),
  (NOW(), 'infra.ibkr.chunk_days.4h', 1, '29', 'migration_197',
   'Migrate-as-you-go: hardcoded _MAX_CHUNK_DAYS moved to APR, same default value [initial_estimate]'),
  (NOW(), 'infra.ibkr.chunk_days.1d', 1, '364', 'migration_197',
   'Migrate-as-you-go: hardcoded _MAX_CHUNK_DAYS moved to APR, same default value [rca_analysis]');

COMMIT;
