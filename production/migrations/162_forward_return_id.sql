-- Migration 162: Add forward_return_id content-key column to forward_returns.
--
-- forward_return_id = SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] as UUID.
--
-- Mirrors migration 158 (feature_vector_id) exactly. forward_returns is a
-- TimescaleDB hypertable — UNIQUE indexes must include the partitioning column
-- (bar_ts), making a surrogate content key the correct handle for downstream
-- tables (alpha_events) that need a single-column stable reference to a return row.
--
-- NULL for rows written before this migration (currently 0 rows — backfill has
-- not run). All rows written after this migration will populate forward_return_id.
--
-- All statements are idempotent (IF NOT EXISTS).
-- Safe to re-run.

ALTER TABLE forward_returns
    ADD COLUMN IF NOT EXISTS forward_return_id UUID;

CREATE INDEX IF NOT EXISTS forward_returns_content_key_idx
    ON forward_returns (forward_return_id)
    WHERE forward_return_id IS NOT NULL;

COMMENT ON COLUMN forward_returns.forward_return_id IS
    'SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] as UUID. Content-addressed row key.
     Idempotent across replays. NULL for rows written before migration 166.
     Uniqueness guaranteed at application layer (SHA-256 collision resistance).
     Mirrors feature_vector_id on feature_vectors (migration 158).';
