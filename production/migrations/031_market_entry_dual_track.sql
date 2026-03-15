-- 031_market_entry_dual_track.sql
-- Adds 8 new columns for the market-entry parallel outcome track.
-- Safe to re-run: all ADD COLUMN IF NOT EXISTS.
--
-- Context: Every signal in signal_ledger now tracks two parallel outcome paths:
--   1. Zone track (existing): wait for price to re-enter entry zone
--   2. Market track (new): immediate fill at signal fire price
--
-- The market track captures what WOULD have happened if we filled at market price
-- (signal_fire_price) instead of waiting for zone re-entry. This enables:
--   - Post-trade analysis: compare zone vs. market outcomes
--   - Edge comparison: does patience (zone wait) outperform immediacy (market)?
--   - Risk assessment: what's the downside of immediate execution?

ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS market_entry_price          DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS market_entry_exit_price     DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS market_entry_pnl_r          DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS market_entry_mae            DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS market_entry_mfe            DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS market_entry_bars_in_trade  INTEGER,
  ADD COLUMN IF NOT EXISTS market_entry_outcome        TEXT,
  ADD COLUMN IF NOT EXISTS market_entry_gap_bars       INTEGER;

-- Analytics index: mirrors idx_ledger_outcome for market track queries
-- Enables fast filtering by market_entry_outcome, useful for:
--   - Comparing win rates (zone vs. market)
--   - Filtering outcome-specific analysis (e.g., "show me TTL-expired market entries")
--   - Performance attribution by outcome type
CREATE INDEX IF NOT EXISTS idx_ledger_market_outcome
ON signal_ledger (market_entry_outcome, setup_plugin, timeframe)
WHERE market_entry_outcome IS NOT NULL;

-- Note: idx_ledger_sym_ts is NOT dropped here — audit usage separately.
-- Existing indexes on signal_ledger remain untouched to avoid lock contention.
