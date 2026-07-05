-- Migration 198: Postgres/TimescaleDB hygiene pass
--
-- Findings from a Postgres best-practices audit (Supabase's rule set applied
-- against live pg_stat_user_indexes / pg_stat_statements / timescaledb_information
-- data, 2026-07-05). None of these are data-integrity issues -- all are
-- storage/write-overhead cleanup on a DB that is otherwise healthy (correct
-- batch/upsert patterns, correct FK indexing, correct hypertable partitioning).
--
-- Run with: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/198_db_hygiene_pass.sql
--
-- Timescale version in this environment is 2.27.1, which does NOT support:
--   - CREATE INDEX CONCURRENTLY on a hypertable (errors: "hypertables do not
--     support concurrent index creation")
--   - ALTER TABLE ... ADD CONSTRAINT ... USING INDEX on a hypertable (errors:
--     "hypertables do not support adding a constraint using an existing index")
-- Both were discovered empirically while first drafting this migration (an
-- earlier version of this file assumed standard Postgres CONCURRENTLY support
-- and briefly dropped market_data_ohlcv's unique constraint before its
-- replacement index could be built -- caught and fixed same session, no bad
-- data written). The sequence below is the corrected, verified-working form:
-- build the replacement index FIRST, confirm it exists, THEN drop the old one.
-- Every step in this file is written to be safe to re-run (IF EXISTS / IF NOT
-- EXISTS / if_not_exists throughout).

-- ---------------------------------------------------------------------------
-- 1. Drop unused indexes -- verified idx_scan = 0 across all chunks since
--    creation, and pg_stat_statements confirms the app's actual ON CONFLICT
--    targets (symbol, tf, bar_ts) never reference these columns. Each one adds
--    a btree-maintenance cost to every row write for zero read benefit.
--    Plain DROP INDEX (not CONCURRENTLY): dropping an index is a fast
--    catalog+unlink operation regardless of index size -- it does not scan
--    data, so the ACCESS EXCLUSIVE lock is held only briefly (confirmed: all
--    three completed in under a second against live tables).
-- ---------------------------------------------------------------------------
DROP INDEX IF EXISTS forward_returns_content_key_idx;
DROP INDEX IF EXISTS feature_vectors_content_key_idx;
DROP INDEX IF EXISTS idx_feature_vectors_regime_rolling;

-- ---------------------------------------------------------------------------
-- 2. Enable compression on hypertables that never had it configured
--    (compression_enabled = false, 0 of N chunks compressed -- confirmed via
--    timescaledb_information.hypertables / .chunks, not just "pending").
--    market_data_ohlcv and feature_vectors already compress correctly; these
--    three were missed. Compression only, no retention/drop_after policy --
--    consistent with "never drop data that could contain signal."
-- ---------------------------------------------------------------------------
BEGIN;

ALTER TABLE forward_returns SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, tf',
    timescaledb.compress_orderby = 'bar_ts'
);
SELECT add_compression_policy('forward_returns', INTERVAL '30 days', if_not_exists => true);

ALTER TABLE ensemble_alpha SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, tf, weight_version',
    timescaledb.compress_orderby = 'bar_ts'
);
SELECT add_compression_policy('ensemble_alpha', INTERVAL '30 days', if_not_exists => true);

ALTER TABLE alpha_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, tf',
    timescaledb.compress_orderby = 'bar_ts'
);
SELECT add_compression_policy('alpha_events', INTERVAL '30 days', if_not_exists => true);

-- ---------------------------------------------------------------------------
-- 3. Tighten autovacuum on feature_vectors. pg_stat_statements shows 182M+
--    calls to the per-row regime-writer UPDATE (symbol, tf, bar_ts keyed,
--    ~39 CPU-hours cumulative). Aggregate dead-tuple ratio across chunks is
--    ~14.4%, which never crosses Postgres's default 20% autovacuum_vacuum_
--    scale_factor trigger, so bloat accumulates unchecked between manual
--    vacuums. Set on the hypertable so new chunks inherit the override.
-- ---------------------------------------------------------------------------
ALTER TABLE feature_vectors SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_analyze_scale_factor = 0.02
);

-- ---------------------------------------------------------------------------
-- 4. Bound runaway queries. statement_timeout was unset (0 = unlimited).
--    pg_stat_statements showed a diagnostic COUNT(*) at ~2.2 hours with no
--    circuit breaker. 30 minutes comfortably exceeds legitimate corpus/
--    backfill query times observed (mean ~17.6s for the slowest normal
--    query) while still catching a truly stuck query.
-- ---------------------------------------------------------------------------
ALTER ROLE postgres SET statement_timeout = '30min';

COMMIT;

-- ---------------------------------------------------------------------------
-- 5. Replace market_data_ohlcv's UNIQUE CONSTRAINT with an equivalent UNIQUE
--    INDEX matching bar_writer.py's exact ON CONFLICT (timestamp, symbol,
--    timeframe) target. This is a downgrade from the original goal (a
--    declared PRIMARY KEY) to what Timescale 2.27.1 actually supports on a
--    hypertable: it will build a brand-new index for ADD CONSTRAINT ...
--    PRIMARY KEY (cols) rather than reuse an existing one (no USING INDEX
--    support), which would mean a second full-size blocking rebuild for a
--    purely cosmetic gain (NOT NULL + UNIQUE is already functionally
--    equivalent to a PK for every real purpose: dedup, ON CONFLICT
--    resolution, referential structure). Not worth a second lock on a
--    continuously-written 4GB+ hypertable. Left as a verified-working
--    UNIQUE INDEX instead.
--    Sequencing: build the new index and confirm it exists BEFORE dropping
--    the old constraint, so bar_writer.py's ON CONFLICT target is never left
--    without a matching index even transiently.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'market_data_ohlcv_pkey_idx') THEN
        CREATE UNIQUE INDEX market_data_ohlcv_pkey_idx
            ON market_data_ohlcv ("timestamp", symbol, timeframe);
    END IF;
END $$;

ALTER TABLE market_data_ohlcv
    DROP CONSTRAINT IF EXISTS market_data_ohlcv_timestamp_symbol_timeframe_key;
