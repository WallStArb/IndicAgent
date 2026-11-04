-- Migration 569: discard the 186-26 rebuild output in feature_vectors_v2 (owner 2026-11-04).
--
-- The rows were computed on code pin 92e588385, which carries known stored-value defects
-- (todos 564, 583, 474), so they were never going to be swapped in (todo 584). The intraday
-- stage ran on incomplete 5m history (todo 534 is still backfilling pre-2016). Owner rule
-- 2026-11-04: data is complete before any corpus compute. The table held 298 GB uncompressed.
--
-- Derived data is cache; what the run taught is recorded: todo 564 (hma_slope_z placeholder,
-- dead 1d columns), todo 583 (HMM NULL on whole names), the 186-26 evidence JSONs under
-- .planning/phases/186-*/evidence/ and the column screen in todo 584.
--
-- Lineage: every completed provenance_batch record for the table flips to 'superseded' (the
-- one sanctioned transition, migration 416), so no record claims rows that no longer exist.
-- The table and its schema stay (empty) for the one-name rename before the rerun.
--
-- No decompress or recompress: the table has no compressed chunks; TRUNCATE frees the space
-- at commit, so no VACUUM step.

BEGIN;

UPDATE provenance_batch
SET status = 'superseded'
WHERE target_table = 'feature_vectors_v2' AND status = 'completed';

TRUNCATE feature_vectors_v2;

COMMIT;
