-- Migration 467: retire the six alpha.survivorship.* APR keys (todo 514).
--
-- Numbered 467, applied live as 466 on 2026-10-09 before the collision with
-- 466_alpaca_source_check.sql was noticed (2026-10-10): the two are independent
-- (different tables and keys), so replay order does not matter.
--
-- Owner, 2026-10-08 and 2026-10-09: survivorship bias is not an issue; the
-- survivorship bound leaves the live system and its documentation. The only
-- reader was the D0 survivorship label (src/intelligence/bars/labels.py,
-- SurvivorshipRule.from_apr) and the D-28 gate's condition 6
-- (scripts/ops/bars/ops_data_bar_check.py); both removed in the same commit.
-- Migration 382, which seeded them, stays as applied history.
--
-- Reader check, 2026-10-09 (after this plan's code changes):
--   grep -rn "alpha\.survivorship" src scripts services tests -> only the
--   retirement notes in labels.py and the bar-check docstring.
--
-- History, then state, then schema (the order of migrations 349, 431 and 434),
-- by literal key, in one transaction. Idempotent: a rerun deletes nothing.
-- Rollback: re-run the seeding statements of migration 382 (schema, state,
-- history, in that order).

BEGIN;

DELETE FROM config_history
 WHERE config_key IN (
    'alpha.survivorship.delisting_return.nasdaq',
    'alpha.survivorship.delisting_return.nyse_amex',
    'alpha.survivorship.hazard.nasdaq_annual',
    'alpha.survivorship.hazard.nyse_amex_annual',
    'alpha.survivorship.haircut.small_cap_annual',
    'alpha.survivorship.trading_days_per_year'
);

DELETE FROM config_state
 WHERE config_key IN (
    'alpha.survivorship.delisting_return.nasdaq',
    'alpha.survivorship.delisting_return.nyse_amex',
    'alpha.survivorship.hazard.nasdaq_annual',
    'alpha.survivorship.hazard.nyse_amex_annual',
    'alpha.survivorship.haircut.small_cap_annual',
    'alpha.survivorship.trading_days_per_year'
);

DELETE FROM config_schema
 WHERE config_key IN (
    'alpha.survivorship.delisting_return.nasdaq',
    'alpha.survivorship.delisting_return.nyse_amex',
    'alpha.survivorship.hazard.nasdaq_annual',
    'alpha.survivorship.hazard.nyse_amex_annual',
    'alpha.survivorship.haircut.small_cap_annual',
    'alpha.survivorship.trading_days_per_year'
);

COMMIT;
