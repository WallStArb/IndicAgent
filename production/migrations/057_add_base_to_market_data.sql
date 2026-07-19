-- Migration 057: Add base column to market_data_ohlcv
-- Principle: Store both contract (immutable fact) and base (computed context)
-- Author: Phase 50.1 execution
-- Date: 2026-04-01

-- Step 1: Add base column
ALTER TABLE market_data_ohlcv ADD COLUMN IF NOT EXISTS base TEXT;

-- Step 2: Populate base from instruments table (contract→base join)
UPDATE market_data_ohlcv md
SET base = i.base
FROM instruments i
WHERE md.symbol = i.symbol
  AND md.base IS NULL;

-- Step 3: Create index for base queries (critical for roll detection)
CREATE INDEX IF NOT EXISTS idx_market_data_ohlcv_base ON market_data_ohlcv(base, timestamp);

-- Step 4: Add comments
COMMENT ON COLUMN market_data_ohlcv.symbol IS 'Contract code (e.g., ESM6) - what actually traded, immutable';
COMMENT ON COLUMN market_data_ohlcv.base IS 'Base symbol (e.g., ES) - continuous strategy unit, derived from instruments.base';

-- Verification: Should show populated base field
SELECT timestamp, symbol, base, timeframe, close
FROM market_data_ohlcv
WHERE timeframe = '5m'
  AND contract_details->>'asset_class' = 'futures'
ORDER BY timestamp DESC
LIMIT 10;
