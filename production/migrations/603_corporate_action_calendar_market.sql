-- Migration 603: corporate_action.inferred_by admits calendar_market (todo 630).
--
-- A calendar_market row is a market split the Yahoo calendar lists, IBKR and Alpaca read adjusted
-- by the same ratio, canonical (Massive, served unadjusted) steps by in full, and Massive's
-- reference omits. It is the meaning massive_reference already has (the incumbents carry it
-- adjusted, so it neither stales nor rescales them) with the calendar audit's evidence in detail
-- instead of a reference page; corporate_actions.SPLIT_SOURCES lists the code for every consumer.
--
-- Reversible: restore the previous list with the statement at the bottom, which fails while any
-- calendar_market row exists (void or delete those rows first; the table is append-only).
-- No table is rewritten, so no VACUUM clause is owed.

BEGIN;

ALTER TABLE corporate_action DROP CONSTRAINT IF EXISTS corporate_action_inferred_by_check;
ALTER TABLE corporate_action
    ADD CONSTRAINT corporate_action_inferred_by_check
    CHECK (inferred_by IN ('seam_audit', 'nightly_overlap', 'tradier_refetch', 'operator',
                           'calendar_audit', 'massive_reference', 'calendar_market'));

COMMIT;

-- Reverse (run by hand):
--   BEGIN;
--   ALTER TABLE corporate_action DROP CONSTRAINT corporate_action_inferred_by_check;
--   ALTER TABLE corporate_action ADD CONSTRAINT corporate_action_inferred_by_check
--       CHECK (inferred_by IN ('seam_audit', 'nightly_overlap', 'tradier_refetch', 'operator',
--                              'calendar_audit', 'massive_reference'));
--   COMMIT;
