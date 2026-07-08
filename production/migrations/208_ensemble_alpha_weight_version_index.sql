-- Migration 208: leading-weight_version index on ensemble_alpha
--
-- Every hot-path query against ensemble_alpha filters on weight_version first:
--   - ensemble_trainer.py's full-replace DELETE FROM ensemble_alpha WHERE weight_version = $1
--   - ensemble_ic_engine.py's startup existence count, DISTINCT tf enumeration, and
--     DISTINCT symbol/tf enumeration (all WHERE weight_version = $1 [AND bar_ts < $2])
--   - ensemble_ic_engine.py's pooled cross-sectional fetch (_POOLED_WORKER_FETCH_SQL:
--     WHERE tf = %s AND weight_version = %s AND bar_ts < %s -- no symbol filter, so the
--     existing (symbol, tf, bar_ts) index cannot help it at all)
--
-- But weight_version is the LAST column in both existing indexes (PK (symbol, tf, bar_ts,
-- weight_version); secondary (symbol, tf, bar_ts DESC)) -- none of the above queries can
-- use an index leading edge. Against alpha_events (the small emission-gated table this
-- engine used to read from) that was cheap; against ensemble_alpha (the full scored
-- population, 30M+ rows for an active weight_version) it forces a full hypertable scan on
-- every single pipeline run, and grows every run as more weight_version epochs accumulate.
--
-- (weight_version, tf, bar_ts) serves every query above: the DELETE/count/DISTINCT-tf
-- queries filter on weight_version alone (leading column); DISTINCT symbol/tf and the
-- pooled fetch add tf as a second equality predicate (order between two leading equality
-- columns in a btree doesn't matter) plus bar_ts as the trailing range predicate.
--
-- Applied while ensemble_alpha is empty (2026-07-08 corpus rebuild truncate, not yet
-- repopulated) -- this CREATE INDEX is instant now. TimescaleDB propagates a hypertable
-- CREATE INDEX to every chunk automatically.

BEGIN;

CREATE INDEX IF NOT EXISTS ensemble_alpha_weight_version_tf_idx
    ON ensemble_alpha (weight_version, tf, bar_ts);

COMMIT;
