-- Migration 484: bar_session_choice.n_primary_grid_slots (phase 191, third review of plan 07)
--
-- The backfill of migration 480's table recorded 3,061,340 fallback sessions of 3,081,879
-- choices. Nearly all are IBKR-first names whose IBKR 5m backfill has not reached the date (260
-- names hold IBKR 5m bars after 2020; the policy ranks IBKR first for 1,585): the primary held
-- nothing that session. A fallback by absence and a fallback by shortfall (the primary held part
-- of the session) differ for a feature that conditions on the vendor, so the record carries the
-- primary's regular-hours slot count. NULL for a timeframe without a grid. Rows are rewritten by
-- the backfill (ops_session_choice_backfill.py) through the table's one writer.
--
-- Small nullable column on a new table; no rewrite.

BEGIN;

SET LOCAL lock_timeout = '10s';

ALTER TABLE bar_session_choice ADD COLUMN IF NOT EXISTS n_primary_grid_slots integer
    CHECK (n_primary_grid_slots >= 0);

COMMENT ON COLUMN bar_session_choice.n_primary_grid_slots IS
    'The ranked-first vendor''s regular-hours slots of the session: 0 is a fallback by absence '
    '(the primary held nothing), more is a shortfall. NULL without a grid. Migration 484.';

COMMIT;
