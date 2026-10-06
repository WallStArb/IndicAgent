-- 440: the nightly Tradier 1d leg (phase 185 plan 26, D-21).
--
-- 1. corporate_action admits inferred_by 'tradier_refetch': a nightly Tradier refetch whose changes are
--    one constant close ratio across every earlier bar is the vendor back-adjusting a split
--    (scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py records it with the load's
--    request id as evidence and the load id in detail).
-- 2. APR switch infra.tradier.nightly_enabled: the nightly runs the Tradier 1d leg first and its IBKR
--    1d legs skip every Tradier-owned name. false restores the IBKR-only nightly in one switch.
-- Idempotent.

BEGIN;

ALTER TABLE corporate_action DROP CONSTRAINT IF EXISTS corporate_action_inferred_by_check;
ALTER TABLE corporate_action
    ADD CONSTRAINT corporate_action_inferred_by_check
    CHECK (inferred_by IN ('seam_audit', 'nightly_overlap', 'tradier_refetch'));

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.tradier.nightly_enabled', 'bool', 'true', NULL, NULL,
 '[user_preference] Operator switch (owner decision 2026-10-03: near-term nightly 1d comes from Tradier). true: the nightly backfill runs the Tradier 1d leg first (every Tradier-owned name refetched in full, plus active equities with no 1d bars) and its IBKR legs skip 1d for every name Tradier owns. false: the IBKR-only nightly of plan 185-22. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.tradier.nightly_enabled', 'true', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_440',
       'Initial value for the nightly Tradier 1d leg switch [user_preference]'
  FROM config_state
 WHERE config_key = 'infra.tradier.nightly_enabled'
ON CONFLICT DO NOTHING;

COMMIT;
