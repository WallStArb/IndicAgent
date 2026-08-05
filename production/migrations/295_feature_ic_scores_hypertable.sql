-- Migration 295: feature_ic_scores -> TimescaleDB hypertable (todo 250)
--
-- feature_ic_scores is the platform's core edge-measurement table: one row per
-- (feature_name, symbol, tf, regime, lookahead_bars, training_window_end), the empirical
-- evidence trail behind every feature promotion/demotion decision. It was a plain Postgres
-- table -- no chunking, no compression, no retention policy -- despite being exactly the
-- shape CLAUDE.md's performance-investigation-sop calls out (millions of rows, appended by a
-- batch writer, growing without bound as new training_window_end slices land).
--
-- Truncated first (not migrate_data => true): as of this migration, the table holds
-- 2,924,007 rows at a SINGLE training_window_end (2025-12-24), already known-contaminated
-- (the ctf_momentum batch-join lookahead leak, todo 243 -- Phase 167 Gate 1 flips PASS->FAIL
-- under the corrected join) and about to be superseded wholesale by the imminent full corpus
-- recompute (Phase 151 waves 6-7). ic_engine.py's own fingerprint-invalidation mechanism
-- (todo 252's _FINGERPRINT_INVALIDATE_DELETE_SQL) will delete+recompute the affected cells
-- for this training_window_end regardless of what this migration does. Converting to a
-- hypertable on an EMPTY table is instant; converting via migrate_data => true against
-- millions of soon-to-be-superseded rows would be the exact slow, lock-heavy batch DDL
-- docs/foundation/performance-investigation-sop.md exists to warn about, for data that isn't
-- going to survive the next corpus run anyway. No FK points into this table (verified live),
-- and ic_engine.py's own startup gates only require feature_vectors to be non-empty, never
-- feature_ic_scores -- safe to truncate with no downstream break.
--
-- The existing primary key and all three partial unique indexes already include
-- training_window_end as a column (verified via \d feature_ic_scores), so no constraint
-- changes are needed for TimescaleDB's hypertable-partitioning-column-must-be-in-every-
-- unique-constraint requirement -- unlike migration 030's signal_metrics_dq_failures, which
-- had to add its partition column to the PK first.
--
-- Compression precedent: matches migration 151's feature_vectors hypertable exactly
-- (compress_segmentby = 'symbol,tf', matching this table's own existing
-- feature_ic_scores_symbol_tf_ts_idx) -- the closest analog already in this schema, a big
-- append-mostly measurement corpus with compression enabled and deliberately NO retention
-- policy.
--
-- NO retention/drop-chunks policy, and none should ever be added: feature_ic_scores is the
-- permanent audit trail for "earn promotion through proof (p<0.05, sufficient N)" and "resist
-- overfitting" (CLAUDE.md principles) -- deleting an old training_window_end slice would
-- destroy the ability to ever re-examine or falsify a past feature promotion/demotion
-- decision. This is the same judgment call feature_vectors' own migration already made (it
-- has no retention policy either).
--
-- Compression delay: 90 days, not feature_vectors' 6 months. feature_ic_scores is a
-- point-in-time WALK-FORWARD SNAPSHOT table (bursty writes, one training_window_end per
-- corpus run) -- it goes cold the moment a NEWER training_window_end lands, not gradually
-- like feature_vectors' continuously-arriving bar series. The true trigger concept is
-- "superseded," not calendar age; TimescaleDB's compression policy is age-based only, and
-- building a bespoke supersede-triggered compression job now -- with a sample size of ONE
-- training_window_end in the whole table -- is premature complexity per the 5-step mandate.
-- 90 days is a generous floor chosen against this project's actual historical corpus-rerun
-- cadence (days-to-weeks apart, not months), wide enough to never risk compressing an
-- actively-iterated frontier slice. Revisit with a supersede-triggered job once real
-- multi-training_window_end cadence data exists.
--
-- chunk_time_interval: 1 month. training_window_end arrives in discrete bursts (one value per
-- corpus run, not a steady tick), so this governs how many corpus runs land in the same chunk
-- rather than tracking a real arrival rate -- 1 month is a reasonable default with zero usage
-- history to calibrate against yet, matching this project's convention of not over-engineering
-- a knob before there is data to tune it against.

BEGIN;

TRUNCATE TABLE feature_ic_scores;

SELECT create_hypertable(
    'feature_ic_scores',
    'training_window_end',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

ALTER TABLE feature_ic_scores SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,tf',
    timescaledb.compress_orderby = 'training_window_end DESC'
);

SELECT add_compression_policy(
    'feature_ic_scores',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

-- Deliberately no add_retention_policy() call -- see header note. Do not add one without an
-- explicit, separate project-owner decision to override "never drop data that could contain
-- signal" for this specific table.
--
-- Expected WARNINGs on apply: "column X should be used for segmenting or ordering" for
-- feature_name/regime/lookahead_bars -- TimescaleDB's compression advisor flags any unique-
-- constraint column not covered by segmentby/orderby. Verified via TimescaleDB's own docs
-- (docs.tigerdata.com/use-timescale/latest/hypertables/hypertables-and-unique-indexes) this is
-- a PERFORMANCE note, not a correctness gap: an insert into an already-compressed chunk with a
-- unique constraint always decompresses in-memory to check the constraint correctly, regardless
-- of segmentby -- no silent constraint violation is possible either way. Deliberately NOT
-- widening segmentby to feature_name: it is high-cardinality (many distinct feature names),
-- which would fragment compressed segments and hurt compression ratio for a table whose actual
-- write pattern (one batch insert per training_window_end, then done) rarely writes into an
-- already-compressed chunk under the 90-day delay chosen above.

COMMIT;
