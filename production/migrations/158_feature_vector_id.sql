-- Migration 158: Add feature_vector_id content-key column to feature_vectors.
--
-- Every row written by FeatureVectorWriter (live path) and backfill_feature_factory
-- (batch path) must carry a stable content-addressed identifier so IC scores can
-- reference feature_vector rows and replay can distinguish rows produced by different
-- algorithm versions.
--
-- feature_vector_id = SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] as UUID.
--
-- NULL for rows written before this migration (currently 0 rows -- backfill has not run).
-- All rows written after this migration will populate feature_vector_id.
--
-- NOTE: TimescaleDB hypertable unique indexes must include the partitioning column (bar_ts).
-- A partial non-unique index is used here instead of a unique index. The content_key
-- function guarantees uniqueness at the application layer (SHA-256 is collision-resistant
-- for the key space in use). Application-level uniqueness is sufficient for provenance.
--
-- All statements are idempotent (IF NOT EXISTS).
-- Safe to re-run.

ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS feature_vector_id UUID;

CREATE INDEX IF NOT EXISTS feature_vectors_content_key_idx
    ON feature_vectors (feature_vector_id)
    WHERE feature_vector_id IS NOT NULL;

COMMENT ON COLUMN feature_vectors.feature_vector_id IS
    'SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] as UUID. Content-addressed row key.
     Idempotent across replays. NULL for rows written before migration 158.
     Uniqueness guaranteed at application layer (SHA-256 collision resistance).';
