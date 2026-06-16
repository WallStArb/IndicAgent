-- Migration 139: Drop FK from trade_frames → signal_events and dead index.
--
-- Two changes, one root cause: both block signal_events compression.
--
-- 1. fk_trade_frames_signal: TimescaleDB cannot compress signal_events chunks
--    because truncating a chunk fails when a regular-table FK references it.
--    The FK was load-bearing during the Phase 129 data migration to catch orphaned
--    rows; now that migration is complete and verified, integrity is maintained at
--    the writer layer (SignalWriter populates signal_events before trade_frames).
--
-- 2. idx_trade_frames_entry_type_pnl: 53 MB, 0 scans. All 1.44M rows have
--    entry_type = 'at_close' (CounterfactualTracker not yet live), giving the
--    index zero selectivity. Re-create after Phase 130 adds real entry_type
--    diversity and the distribution is empirically known.

ALTER TABLE trade_frames DROP CONSTRAINT IF EXISTS fk_trade_frames_signal;

DROP INDEX IF EXISTS idx_trade_frames_entry_type_pnl;
