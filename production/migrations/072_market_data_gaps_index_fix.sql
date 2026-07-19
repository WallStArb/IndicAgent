-- 066_market_data_gaps_index_fix.sql
-- Fix redundant index and add partial index for open gap lookups.
--
-- 1. The UNIQUE (symbol, tf, gap_start_ts) constraint already creates an implicit
--    B-tree index. The explicit market_data_gaps_symbol_tf_start index is an exact
--    duplicate — same 3 columns, same order. Drop it to eliminate double write overhead.
--
-- 2. _resolve_market_data_gap queries WHERE resolved_at IS NULL on every audit cycle.
--    A partial index covering only open gaps is far smaller than a full index and
--    enables index-only scans for the common read path.

DROP INDEX IF EXISTS market_data_gaps_symbol_tf_start;

CREATE INDEX IF NOT EXISTS market_data_gaps_open
    ON market_data_gaps (symbol, tf, gap_start_ts)
    WHERE resolved_at IS NULL;
