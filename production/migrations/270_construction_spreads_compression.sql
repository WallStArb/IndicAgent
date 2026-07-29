-- Migration 270: construction_spreads compression policy
--
-- construction_spreads (migration 260) was created without a compression policy, the
-- same class of oversight migration 214 fixed for alpha_frames -- discovered during a
-- 2026-07-29 DB health pass (153GB total, up from a recent ~70GB baseline). Unlike
-- alpha_frames, construction_spreads is genuinely write-once: cross_sectional_spread_
-- tracker.py's only write is `INSERT ... ON CONFLICT (construction_name, tf, bar_ts)
-- DO NOTHING`, no UPDATE anywhere in the codebase -- so the standard 30-day convention
-- (matching ensemble_alpha/alpha_events/forward_returns, its append-only siblings) is
-- safe with no decompress-on-write risk.
--
-- segmentby/orderby: construction_name is this table's natural symbol-equivalent
-- (identifies which spread construction the row belongs to); tf is the other
-- low-cardinality dimension every sibling policy segments by; orderby mirrors the
-- house convention of bar_ts DESC.
--
-- Table is small today (97MB, 1044 chunks) -- this is about closing a silent
-- config gap for consistency (every hypertable should have a deliberate policy, not
-- a missing one), not an urgent space reclaim.

BEGIN;

ALTER TABLE construction_spreads SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'construction_name, tf',
    timescaledb.compress_orderby = 'bar_ts DESC'
);

SELECT add_compression_policy('construction_spreads', compress_after => INTERVAL '30 days', if_not_exists => TRUE);

COMMIT;
