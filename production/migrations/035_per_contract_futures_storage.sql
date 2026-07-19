-- Migration 035: Per-Contract Futures Storage with Roll Tracking
--
-- Purpose: Store raw per-contract futures data as canonical truth.
-- Continuous series are derived layers, not storage format.
-- This table tracks roll schedule for each futures contract.
--
-- Renaissance Principle: Store raw data first. Roll methodology is proprietary IP.
-- Baked-in continuous series prevent future optimization.

-- ============================================================
-- Table: contract_metadata
-- ============================================================
--
-- Tracks futures contract roll chain, expiry, and adjustment gaps.
-- Each row represents a single contract (e.g., "ESH6", "ESZ5").
--
CREATE TABLE IF NOT EXISTS contract_metadata (
    -- Primary key: contract symbol (e.g., "ESH6")
    symbol TEXT NOT NULL PRIMARY KEY,

    -- Base symbol for grouping (e.g., "ES" for ESH6, ESZ5)
    base_symbol TEXT NOT NULL,

    -- Asset class classification
    asset_class TEXT NOT NULL,

    -- Contract lifecycle
    expiry_date TIMESTAMPTZ,
    first_notice_date TIMESTAMPTZ,

    -- Roll chain navigation
    -- roll_from: previous contract in roll chain (e.g., "ESZ5" for ESH6)
    roll_from TEXT,
    -- roll_to: next contract in roll chain (e.g., "ESM6" for ESH6)
    roll_to TEXT,

    -- Roll timing
    -- roll_date: when this contract became the active front-month
    roll_date TIMESTAMPTZ,

    -- Roll adjustment
    -- roll_gap: price adjustment at roll (close of prev vs open of current)
    -- Positive = roll up, Negative = roll down
    roll_gap DOUBLE PRECISION,

    -- Exchange metadata
    exchange TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Indexes
-- ============================================================

-- Index for querying roll chain by base symbol and roll date
-- Used to determine which contract was active at any given timestamp
CREATE INDEX IF NOT EXISTS idx_contract_meta_base_roll
    ON contract_metadata (base_symbol, roll_date);

-- Index for expiry-based queries
CREATE INDEX IF NOT EXISTS idx_contract_meta_expiry
    ON contract_metadata (expiry_date);

-- Index for asset class queries
CREATE INDEX IF NOT EXISTS idx_contract_meta_asset_class
    ON contract_metadata (asset_class);

-- ============================================================
-- Comments (PostgreSQL DESCRIBE style)
-- ============================================================

COMMENT ON TABLE contract_metadata IS
    'Futures contract roll tracking. Each row is a single contract with roll chain links.';
COMMENT ON COLUMN contract_metadata.symbol IS
    'Contract symbol (e.g., "ESH6") - primary key';
COMMENT ON COLUMN contract_metadata.base_symbol IS
    'Base symbol grouping (e.g., "ES") for roll chain navigation';
COMMENT ON COLUMN contract_metadata.asset_class IS
    'Asset class (futures, equity, crypto, fx, option)';
COMMENT ON COLUMN contract_metadata.expiry_date IS
    'Contract expiration date';
COMMENT ON COLUMN contract_metadata.first_notice_date IS
    'First notice date - last day to close position without assignment';
COMMENT ON COLUMN contract_metadata.roll_from IS
    'Previous contract in roll chain (NULL for oldest)';
COMMENT ON COLUMN contract_metadata.roll_to IS
    'Next contract in roll chain (NULL for current front-month)';
COMMENT ON COLUMN contract_metadata.roll_date IS
    'Date this contract became active front-month';
COMMENT ON COLUMN contract_metadata.roll_gap IS
    'Price adjustment at roll (close of previous vs open of current)';
COMMENT ON COLUMN contract_metadata.exchange IS
    'Exchange name (e.g., CME, NYMEX, COMEX)';
