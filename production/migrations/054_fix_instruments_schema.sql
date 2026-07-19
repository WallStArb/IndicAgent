-- Migration 054: Fix instruments table schema for Renaissance design
-- Principle: Single source of truth (contract=symbol), compute base at read time
-- Author: Phase 50.1 execution
-- Date: 2026-04-01

-- Step 1: Add base and expiry columns (populate from contract_details)
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS base TEXT;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS expiry DATE;

-- Populate base from contract_details
UPDATE instruments
SET base = (contract_details->>'base')
WHERE base IS NULL AND contract_details ? 'base';

-- Populate expiry from contract_details (parse YYYYMM format)
UPDATE instruments
SET expiry = TO_DATE((contract_details->>'expiry') || '01', 'YYYYMMDD')
WHERE expiry IS NULL AND contract_details ? 'expiry';

-- Step 2: Make base NOT NULL after population
ALTER TABLE instruments ALTER COLUMN base SET NOT NULL;

-- Step 3: Create index for base lookups (critical for roll detection)
CREATE INDEX IF NOT EXISTS idx_instruments_base ON instruments(base);

-- Step 4: Add comment documenting design decision
COMMENT ON TABLE instruments IS 'Contract registry: symbol=contract code (PK), base=derived symbol. Preserves all historical contracts for research.';
COMMENT ON COLUMN instruments.symbol IS 'Contract code (e.g., ESM6) - immutable identifier of what actually trades';
COMMENT ON COLUMN instruments.base IS 'Base symbol (e.g., ES) - continuous strategy unit, derived from contract definition';
COMMENT ON COLUMN instruments.expiry IS 'Contract expiration date - enables roll detection and historical analysis';

-- Verification query: should show contract codes as PK
SELECT symbol, base, expiry, is_active
FROM instruments
WHERE contract_details->>'asset_class' = 'futures'
ORDER BY base, expiry DESC;
