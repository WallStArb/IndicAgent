-- Migration 431: retire alpha.ic.cluster_max_corr (phase 186 plan 23 follow-up).
--
-- The BH-FDR feature-clustering threshold; its only runtime reader was the old
-- services/ic_engine.py, deleted in the same plan (migration 430's drop). The key was
-- missed by 430's retirement list because the Task 1 enumeration query grouped by
-- namespace prefixes and this key's literal was not in any of them; the repo-wide
-- reader grep during 186-23's docs pass surfaced it. No surviving reader (grep over
-- src/services/scripts, 2026-10-02). Idempotent, literal DELETE only.
--
-- KEEP note: alpha.ic.hac_max_lag stays — services/ic_measure.py reads it
-- (src/intelligence/measure/params.py).

BEGIN;

DELETE FROM config_history
 WHERE config_key IN ('alpha.ic.cluster_max_corr');
DELETE FROM config_state
 WHERE config_key IN ('alpha.ic.cluster_max_corr');
DELETE FROM config_schema
 WHERE config_key IN ('alpha.ic.cluster_max_corr');

COMMIT;
