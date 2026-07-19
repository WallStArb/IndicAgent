-- Migration 202: drop new_high_flag/new_low_flag -- proven redundant with
-- dist_from_high/dist_from_low
--
-- Found 2026-07-09 via tools/scan_binary_patterns.py flagging both as
-- np.where(..., 1.0, 0.0) binary-scoring violations. Investigation showed
-- this isn't a style nit: new_high_flag[i] = 1{close[i] >= rolling_high[i] - eps}
-- is the exact same rolling_high (same window, same _sliding_rolling_max call)
-- and the exact same comparison (close vs rolling_high) already computed
-- continuously as dist_from_high[i] = (rolling_high[i] - close[i]) / atr[i].
-- Since rolling_high is inclusive of the current bar, dist_from_high is always
-- >= 0 and new_high_flag is just an indicator on dist_from_high sitting near
-- its own minimum -- zero orthogonal information beyond what dist_from_high
-- already carries. Same argument for new_low_flag/dist_from_low. This
-- violates the Feature Factory's own design contract ("54 orthogonal
-- primitives, one per distinct information dimension, zero redundancy").
--
-- The single-bar _new_high_flag/_new_low_flag functions were additionally
-- found to be dead code (zero call sites; only the vectorized
-- _series_full versions were ever wired in), removed in the same commit as
-- this migration.
--
-- feature_registry treats 'deprecated' as a soft-retirement state where the
-- field/row is expected to keep existing (feature_registry_service.py's own
-- get_all_features() docstring: "a deprecated feature still has a row in
-- feature_registry AND a field in FeatureVector"). That lifecycle is for
-- features that ran, got measured, and lost on IC merit -- worth keeping the
-- row for audit history. This is a different case: a structural design
-- mistake (redundant by construction, not by measurement), so the field is
-- removed from FeatureVector entirely and the registry row is deleted to
-- match, preserving the registry's own invariant that it exactly mirrors
-- dataclasses.fields(FeatureVector). A transition-log row records the event
-- for audit continuity before the registry row is removed.
--
-- feature_vectors currently has 36.7M rows across 83 compressed chunks (this
-- corpus rebuild's Step 1/7 already ran). TimescaleDB refuses ALTER TABLE
-- DROP COLUMN on compressed chunks (same restriction migration 210 hit for
-- ALTER COLUMN TYPE), so this decompresses, drops, then recompresses,
-- following migration 210's exact pattern. Neither column is read by any
-- downstream step (regime_writer, forward_return_writer, ic_engine,
-- ic_shrinkage, ensemble_trainer, alpha_publisher all confirmed to reference
-- neither name), so this is safe to run without invalidating the in-flight
-- rebuild or requiring a re-run -- just don't run it concurrently with a
-- long-running query against feature_vectors (ACCESS EXCLUSIVE lock).

BEGIN;

-- Audit trail before removal (feature_transition_log is immutable/append-only
-- per its own table comment; trigger_reason CHECK constraint doesn't have a
-- literal "removed" value, so 'operator_override' -> 'deprecated' is the
-- closest fit for a manual, non-IC-driven retirement).
INSERT INTO feature_transition_log (feature_name, from_status, to_status, trigger_reason)
VALUES
    ('new_high_flag', 'active', 'deprecated', 'operator_override'),
    ('new_low_flag',  'active', 'deprecated', 'operator_override');

DELETE FROM feature_registry WHERE feature_name IN ('new_high_flag', 'new_low_flag');

COMMIT;

DO $$
DECLARE
  c record;
BEGIN
  FOR c IN
    SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS chunk
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'feature_vectors' AND is_compressed
  LOOP
    PERFORM decompress_chunk(c.chunk);
  END LOOP;
END $$;

BEGIN;

ALTER TABLE feature_vectors
    DROP COLUMN IF EXISTS new_high_flag,
    DROP COLUMN IF EXISTS new_low_flag;

COMMIT;

-- Recompression is intentionally a separate statement (outside the DDL
-- transaction), matching migration 210: compress_chunk() takes its own
-- per-chunk locks and this way a failure partway through recompression
-- can't roll back the (already-verified) column drop.
DO $$
DECLARE
  c record;
BEGIN
  FOR c IN
    SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS chunk
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'feature_vectors' AND NOT is_compressed
  LOOP
    PERFORM compress_chunk(c.chunk);
  END LOOP;
END $$;
