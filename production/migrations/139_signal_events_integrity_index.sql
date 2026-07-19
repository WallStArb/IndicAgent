-- Migration 139: Two indexes to make _assert_backfill_integrity query-efficient at any
-- corpus size, eliminating the need for per-symbol Python batching.
--
-- INDEX 1: Invariant 2 — signal_id uniqueness per symbol.
--   Query: SELECT signal_id FROM signal_events WHERE symbol = ANY(%s) GROUP BY signal_id HAVING COUNT(*) > 1
--   Without index: full table scan.
--   With (symbol, signal_id): index-only scan — both filter and group key are in the index.
--
-- INDEX 2: Invariant 1 — was_selected uniqueness per (symbol, tf, bar_ts).
--   Query joins signal_events -> trade_frames ON (signal_id, signal_ts) WHERE was_selected = TRUE.
--   Existing idx_trade_frames_signal (signal_id, signal_ts) covers the JOIN columns but
--   must post-filter on was_selected, scanning all trade_frames rows per signal.
--   Partial index WHERE was_selected = TRUE is 5-20x smaller (selected rows are rare)
--   and turns the trade_frames side of the JOIN into an index-only scan on the subset
--   that actually matters. (Best Practice: use partial indexes for filtered queries.)

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_symbol_signal_id
    ON signal_events (symbol, signal_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trade_frames_selected_signal_ts
    ON trade_frames (signal_id, signal_ts)
    WHERE was_selected = TRUE;
