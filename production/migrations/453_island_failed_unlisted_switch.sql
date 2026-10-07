-- 453: APR switch for the ISLAND-failed head rule (phase 185 plan 34).
--
-- infra.ibkr.venue_fallback.island_failed_unlisted: when true, ops_head_rerun.classify_head (and
-- the D-28 gate's condition 3, which shares it) counts a failed ISLAND (Nasdaq) answer on a name
-- whose recorded primary exchange is not Nasdaq as "no listing at that venue" for the head. 185-28
-- found ISLAND answering `failed` (no error code, every attempt) for eight NYSE/AMEX names (IDR,
-- SGHC, UUUU, BMNR, CPS, FUBO, QXO, SD) whose every other venue answered no_data. Orchestrator call
-- 2026-10-07, pending owner review: seeded true so the rule is active; false restores the strict
-- 185-28 classification in one switch. The empty-history reconcile does not apply this rule.
-- Numbers 445 to 452 are taken or reserved by other plans. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.ibkr.venue_fallback.island_failed_unlisted', 'bool', 'true', NULL, NULL,
 '[rca_analysis] Head classification switch (plan 185-34, orchestrator call 2026-10-07, pending owner review). true: a failed ISLAND answer on a late name whose recorded primary exchange is not Nasdaq counts as no listing at Nasdaq (ops_head_rerun.classify_head, D-28 condition 3). false: the strict 185-28 rule, where a failed answer leaves the name unresolved. A missing key reads as false. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.ibkr.venue_fallback.island_failed_unlisted', 'true', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_453',
       'Initial value for the ISLAND-failed head rule switch [rca_analysis], pending owner review'
  FROM config_state
 WHERE config_key = 'infra.ibkr.venue_fallback.island_failed_unlisted'
ON CONFLICT DO NOTHING;

COMMIT;
