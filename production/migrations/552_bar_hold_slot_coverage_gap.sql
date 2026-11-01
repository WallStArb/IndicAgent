-- 552: the slot_coverage_gap hold reason (todo 565 part a).
--
-- The 5m slot_coverage verdict counts a slot with no trade as missing for the Alpaca SIP years
-- (D-191-P: a SIP aggregate exists only where a trade printed), so 44 thinly traded names fail
-- against the 0.995 worst-year threshold and gate the 186-26 intraday rebuild stage with no
-- disposition recorded anywhere. Todo 565's fix will count applied vendor loads as answers;
-- until it lands, the names the verdict still fails are real thin-trade gaps, and todo 565
-- names them holds: canonical 5m stays as it is, the verdict gate treats a held name as
-- dispositioned (part b, after the rebuild finishes), D7-style reports name it.
--
-- bar_hold was structurally unable to represent this: CHECK constraints pinned timeframe='1d'
-- and reason IN ('unclassified_rescale','release'). This migration admits timeframe '5m' and
-- the reason 'slot_coverage_gap' (no factor; the evidence, the failing share, its threshold and
-- the evaluated_at of the verdict row, lives in detail). The append-only trigger, the release
-- row rule and bar_hold_current are untouched; the one writer stays services/bar_hold.py.
--
-- Idempotent: constraints are dropped and re-added.

BEGIN;

ALTER TABLE bar_hold DROP CONSTRAINT bar_hold_timeframe_check;
ALTER TABLE bar_hold
    ADD CONSTRAINT bar_hold_timeframe_check CHECK (timeframe IN ('1d', '5m'));

ALTER TABLE bar_hold DROP CONSTRAINT bar_hold_reason_check;
ALTER TABLE bar_hold
    ADD CONSTRAINT bar_hold_reason_check
    CHECK (reason IN ('unclassified_rescale', 'slot_coverage_gap', 'release'));

COMMENT ON TABLE bar_hold IS
    'Held names (migration 461, plan 185-51; reason slot_coverage_gap by 552, todo 565): a '
    'name is held for a timeframe while bar_hold_current has a row for it, and its canonical '
    'bars stay as they are. Reason unclassified_rescale: a constant vendor rescale whose factor '
    'is no recognised split ratio (never a corporate_action row). Reason slot_coverage_gap: a '
    '5m name whose worst-year slot_coverage share sits below the threshold because Alpaca SIP '
    'has no bar for a slot in which no trade printed (todo 565); the failing share, threshold '
    'and verdict time are the detail. The daily stage skips held names, D7 reports them. One '
    'writer: services/bar_hold.py under bar_derivation_writer. Append-only; a release is a new '
    'row whose releases names the hold.';

COMMIT;
