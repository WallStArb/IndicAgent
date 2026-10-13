-- Migration 476: one bar_kind code per IBKR listing-venue route (phase 191 plan 04)
--
-- Raw is stored per source and agnostic to every other source. An IBKR listing-venue route
-- (AMEX, ARCA, BATS, ISLAND, NYSE) is a different source of the same day, so the route belongs
-- in the kind: venue_amex, venue_arca, venue_bats, venue_island, venue_nyse. One shared `venue`
-- kind made a route switch look like IBKR revising itself (about 575k fabricated revisions).
-- The label-level `venue` code stays for the archive and canonical rows, which carry no route.
-- Within-vendor selection precedence equals `venue` (sort_order 2); ties break by code.
-- Data only; idempotent.

BEGIN;

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order)
VALUES
    ('bar_kind', 'venue_amex', 'venue_amex', 'IBKR AMEX listing-venue route daily answer (volume is not consolidated)', 2),
    ('bar_kind', 'venue_arca', 'venue_arca', 'IBKR ARCA listing-venue route daily answer (volume is not consolidated)', 2),
    ('bar_kind', 'venue_bats', 'venue_bats', 'IBKR BATS listing-venue route daily answer (volume is not consolidated)', 2),
    ('bar_kind', 'venue_island', 'venue_island', 'IBKR ISLAND listing-venue route daily answer (volume is not consolidated)', 2),
    ('bar_kind', 'venue_nyse', 'venue_nyse', 'IBKR NYSE listing-venue route daily answer (volume is not consolidated)', 2)
ON CONFLICT (namespace, code) DO NOTHING;

COMMIT;
