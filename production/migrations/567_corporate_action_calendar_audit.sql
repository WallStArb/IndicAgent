-- Migration 567: corporate_action inferred_by 'calendar_audit' and the split tolerance APR (todo 587).
--
-- Canonical 1d breaks "stored equity bars are split-adjusted": against Yahoo's split calendar,
-- canonical steps by the split ratio on 404 split dates over 283 names (measured 2026-11-04; IBKR
-- smart_trades 1d before 2016 misses about half of its splits). Each confirmed split becomes one
-- corporate_action row written by scripts/ops/bars/ops_split_calendar_audit.py under the new
-- inferred_by value 'calendar_audit' (its own single-writer segment).
--
-- threshold.split_continuity.rel_tol: the fraction of |log f| inside which a log close step counts
-- as the split (confirmation: canonical steps by -log f and Yahoo's split-adjusted close stays
-- inside it; D7 split_continuity: a step within it of -log f is still unadjusted, of +log f
-- double-adjusted). [rca_analysis] 0.3 is the separation the 2026-11-04 audit measured: canonical
-- steps at Yahoo-dated splits cluster at 0 and 1 of the split's log ratio, with "other" between.
-- Not an ML learning target. Idempotent.

BEGIN;

ALTER TABLE corporate_action DROP CONSTRAINT IF EXISTS corporate_action_inferred_by_check;
ALTER TABLE corporate_action
    ADD CONSTRAINT corporate_action_inferred_by_check
    CHECK (inferred_by IN ('seam_audit', 'nightly_overlap', 'tradier_refetch', 'operator', 'calendar_audit'));

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.split_continuity.rel_tol',
        'float', '0.3', 0.05, 0.49,
        '[rca_analysis] Fraction of |log f| inside which a log close step counts as a split of factor f (todo 587). Used by ops_split_calendar_audit to confirm a calendar split (canonical steps by -log f, Yahoo split-adjusted close inside the band) and by the D7 split_continuity check (a step near -log f is still unadjusted, near +log f double-adjusted; either fails the name). Below 0.5 so the two bands and the continuous band never overlap. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.split_continuity.rel_tol', '0.3', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_567',
       'seed: split confirmation and continuity tolerance (todo 587)'
  FROM config_state s
 WHERE s.config_key = 'threshold.split_continuity.rel_tol'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_567'
 );

COMMIT;
