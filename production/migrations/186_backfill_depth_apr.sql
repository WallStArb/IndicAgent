-- Migration 186: backfill depth (days) constants → infra.backfill.depth_days.*
--
-- Migrates _TF_FETCH_CONFIG day-counts from module-level constants in
-- infrastructure_run_historical_pipeline.py to APR. These control training-corpus
-- depth directly. 2026-07-02 investigation found 1h/15m/5m were all artificially
-- capped well below actual IBKR retention (15yr, 10yr, 4.5yr respectively) — SPY
-- probes confirmed all four intraday+daily timeframes reach the same 20yr ceiling
-- as 1d. Making this tunable via APR means future depth changes don't require a
-- code deploy.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
  ('infra.backfill.depth_days.1d', 'int', '7300',
   'Backfill depth (calendar days) for 1d bars. [rca_analysis] Confirmed available via SPY '
   'probe 2026-06-19 (7300d exact, 2006-2026). ML target: No.'),
  ('infra.backfill.depth_days.1h', 'int', '7300',
   'Backfill depth (calendar days) for 1h bars. [rca_analysis] Confirmed available via SPY '
   'probe 2026-07-02 (175,191 bars back to 2006-07-07); prior 5475d (15yr) was a deliberate '
   'cap, not a proven ceiling. ML target: No.'),
  ('infra.backfill.depth_days.15m', 'int', '7300',
   'Backfill depth (calendar days) for 15m bars. [rca_analysis] Confirmed available via SPY '
   'probe 2026-07-02 (700,770 bars back to 2006-07-07); prior 3650d (10yr) was a deliberate '
   'cap, not a proven ceiling. ML target: No.'),
  ('infra.backfill.depth_days.5m', 'int', '7300',
   'Backfill depth (calendar days) for 5m bars. [rca_analysis] Confirmed available via SPY '
   'probe 2026-07-02 (2,102,364 bars back to 2006-07-07); prior 1631d (4.5yr) was a '
   'deliberate cap, not a proven ceiling. ML target: No.'),
  ('infra.backfill.depth_days.1m', 'int', '90',
   'Backfill depth (calendar days) for 1m bars. [initial_estimate] Deliberate storage/compute '
   'tradeoff, not a retention constraint — 1m patterns (time-of-day, day-of-week) repeat on '
   'weekly/monthly cycles so 90d captures full repetition. IBKR confirmed 10yr+ retention '
   '(SPY probe 2026-06-19). ML target: No.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('infra.backfill.depth_days.1d', '7300', 1),
  ('infra.backfill.depth_days.1h', '7300', 1),
  ('infra.backfill.depth_days.15m', '7300', 1),
  ('infra.backfill.depth_days.5m', '7300', 1),
  ('infra.backfill.depth_days.1m', '90', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
