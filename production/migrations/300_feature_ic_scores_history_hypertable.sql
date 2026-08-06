-- Migration 300: feature_ic_scores_history -> TimescaleDB hypertable (todo 271)
--
-- Same shape of gap migration 295 fixed for feature_ic_scores itself: feature_ic_scores_history
-- (todo 252's archive-before-delete target for ic_engine.py's fingerprint-invalidation
-- mechanism) was a plain Postgres table -- no chunking, no compression, no retention policy.
-- Already live and growing, not hypothetical: 29,382 rows as of 2026-08-05, despite the corpus
-- still being frozen at a single training_window_end -- fingerprint invalidation has already
-- fired for real.
--
-- migrate_data => true, NOT truncate-first (unlike migration 295's feature_ic_scores approach):
-- this table's entire purpose is being the permanent, never-recomputed audit record of what a
-- feature's IC looked like before each invalidating change. Truncating it would defeat the
-- reason todo 252 built it. Acceptable at this row count (29,382) -- the truncate-first
-- shortcut in migration 295 existed specifically because feature_ic_scores held millions of
-- rows about to be superseded by an imminent recompute; neither condition applies here.
--
-- No PK, no unique constraint at all on this table (confirmed via \d feature_ic_scores_history
-- -- genuinely append-only per todo 252's own design) -- simpler than feature_ic_scores'
-- conversion, no unique-constraint-must-include-partition-column requirement to satisfy.
--
-- Partition column: archived_at, not training_window_end. Rows arrive keyed to when an
-- invalidation event fires (real-world time), not the walk-forward data boundary they describe
-- -- archived_at is what actually grows monotonically with inserts and is what TimescaleDB
-- chunk exclusion should track.
--
-- Compression delay: 30 days, shorter than feature_ic_scores' 90 days. Archived rows are cold
-- from nearly the moment they land -- read only for retrospective/audit queries, never
-- re-touched by day-to-day operations -- closer to the 30-day precedent already used for
-- forward_returns/ensemble_alpha/alpha_events (migration 193) than feature_ic_scores' own
-- point-in-time-snapshot reasoning (which waits for a training_window_end to be superseded
-- before compressing, a condition that doesn't apply to an already-write-once archive row).
--
-- No retention/drop-chunks policy, and none should ever be added: even more directly than
-- feature_ic_scores itself, this table's entire purpose is being the permanent audit trail
-- behind every feature-measurement change ("never drop data that could contain signal").
--
-- segmentby/orderby: symbol,tf / archived_at DESC -- matches feature_ic_scores' own choice
-- (migration 295) for consistency, rather than the high-cardinality feature_name the existing
-- feature_ic_scores_history_cell_idx leads with (would fragment compressed segments, same
-- reasoning as migration 295's own header note on this exact tradeoff).
--
-- chunk_time_interval: 1 month, matching feature_ic_scores' own choice -- archival events are
-- invalidation-triggered (event-driven), not a steady tick, so this governs how many
-- invalidation events land in the same chunk rather than tracking a real arrival rate; 1 month
-- is a reasonable default with limited usage history to calibrate against yet.

BEGIN;

SELECT create_hypertable(
    'feature_ic_scores_history',
    'archived_at',
    chunk_time_interval => INTERVAL '1 month',
    migrate_data => true,
    if_not_exists => TRUE
);

ALTER TABLE feature_ic_scores_history SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,tf',
    timescaledb.compress_orderby = 'archived_at DESC'
);

SELECT add_compression_policy(
    'feature_ic_scores_history',
    INTERVAL '30 days',
    if_not_exists => TRUE
);

-- Deliberately no add_retention_policy() call -- see header note. Do not add one without an
-- explicit, separate project-owner decision to override "never drop data that could contain
-- signal" for this specific table.

COMMIT;
