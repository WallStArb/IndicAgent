-- Migration 141: Partial index for labeled ML training data on trade_frames.
--
-- CounterfactualTracker (Phase 130) will populate counterfactual_pnl_r once live.
-- All ML training queries filter WHERE counterfactual_pnl_r IS NOT NULL to select
-- the labeled subset. At 1.44M rows with full-table scans, this filter is expensive
-- without a partial index.
--
-- The partial index is empty until Phase 130 writes data (zero overhead now) and
-- grows automatically as CounterfactualTracker populates rows. No backfill needed.
--
-- Also adds signal_ts to the index for time-range scoping on training queries
-- (e.g. "labeled signals in the last 90 days for regime-stratified training").

CREATE INDEX IF NOT EXISTS idx_trade_frames_labeled
    ON trade_frames (signal_ts DESC, counterfactual_pnl_r)
    WHERE counterfactual_pnl_r IS NOT NULL;
