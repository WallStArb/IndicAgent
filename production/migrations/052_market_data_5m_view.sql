-- Migration 052: Create market_data_5m View
-- Phase: 50 - Roll Monitor Graduation
-- Purpose: D-21 validation requires 5m data view for roll detection validation
-- Status: Applied 2026-04-02

-- View for 5m bar data (used by D-21 validation script)
CREATE VIEW market_data_5m AS
SELECT timestamp, symbol, timeframe, open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE timeframe = '5m';

-- Verification: SELECT COUNT(*) FROM market_data_5m WHERE timestamp > NOW() - INTERVAL '30 days';
-- Expected: > 88000 rows
-- Actual: 102983 rows (as of 2026-04-02)
