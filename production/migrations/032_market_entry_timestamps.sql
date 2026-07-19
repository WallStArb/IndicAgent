-- Migration 032: Add market_entry_at and market_entry_exit_at timestamps to signal_ledger
-- These complete the price/time pairs for the market track (zone track already has
-- activated_at/exit_at). Without these, market_entry_exit_price has no associated
-- timestamp — violating the UTC price/time pair standard.

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS market_entry_at     timestamptz,
    ADD COLUMN IF NOT EXISTS market_entry_exit_at timestamptz;
