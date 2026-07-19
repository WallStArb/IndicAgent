-- Migration 037: Roll Monitor Integration
--
-- Purpose: Extend contract_metadata for roll monitoring state and add
-- system_events table for durable roll event audit log.
--
-- Renaissance Principle: Never drop data that could contain signal.
-- Every detected roll event is persisted for future analysis.

-- ============================================================
-- Extend contract_metadata with roll monitoring columns
-- ============================================================
--
-- is_front_month: true when this contract is the active front-month.
-- Used by get_active_contracts() DB query when ROLL_MONITOR_ENABLED=true.
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS is_front_month BOOLEAN DEFAULT false;

-- roll_direction: price direction of the roll ("up", "down", "flat", "unknown").
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS roll_direction VARCHAR(10) DEFAULT 'unknown';

-- roll_detected_at: when the roll was detected by the automated monitor.
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS roll_detected_at TIMESTAMPTZ DEFAULT NOW();

-- confirmation_count: number of consecutive bars that confirmed the roll.
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS confirmation_count INTEGER DEFAULT 0;

-- Note: roll_gap already exists from migration 036 — NOT re-added here.

-- ============================================================
-- Table: system_events
-- ============================================================
--
-- Durable audit log for all system-level events (roll detection,
-- pipeline resets, subscription changes).
--
CREATE TABLE IF NOT EXISTS system_events (
    id BIGSERIAL PRIMARY KEY,

    -- Event classification
    event_type VARCHAR(50) NOT NULL,

    -- For roll events: base and per-contract symbols
    base_symbol VARCHAR(10) NOT NULL,
    old_symbol  VARCHAR(10),
    new_symbol  VARCHAR(10),

    -- Roll economics (price gap at roll boundary)
    roll_gap DOUBLE PRECISION,

    -- Roll price direction ("up", "down", "flat", "unknown")
    roll_direction VARCHAR(10),

    -- When the event was detected
    detected_at TIMESTAMPTZ DEFAULT NOW(),

    -- Arbitrary JSON payload for extensibility
    event_data JSONB DEFAULT '{}'::jsonb
);

-- ============================================================
-- Indexes
-- ============================================================

-- Fast lookup of active front-month contracts per base symbol
CREATE INDEX IF NOT EXISTS idx_contract_meta_front_month
    ON contract_metadata (base_symbol, is_front_month);

-- Fast lookup of roll events by base symbol and recency
CREATE INDEX IF NOT EXISTS idx_system_events_base_detected
    ON system_events (base_symbol, detected_at DESC);

-- ============================================================
-- Comments
-- ============================================================

COMMENT ON COLUMN contract_metadata.is_front_month IS
    'True when this contract is the current active front-month';
COMMENT ON COLUMN contract_metadata.roll_direction IS
    'Price direction at roll boundary: up / down / flat / unknown';
COMMENT ON COLUMN contract_metadata.roll_detected_at IS
    'Timestamp when automated roll monitor detected this roll';
COMMENT ON COLUMN contract_metadata.confirmation_count IS
    'Number of consecutive bars that confirmed the volume-based roll signal';

COMMENT ON TABLE system_events IS
    'Durable audit log for system-level events: roll detection, pipeline resets';
COMMENT ON COLUMN system_events.event_type IS
    'Event class (e.g. ''roll'', ''pipeline_reset'', ''subscription_change'')';
COMMENT ON COLUMN system_events.base_symbol IS
    'Base futures symbol (e.g. ''ES'') — always present';
COMMENT ON COLUMN system_events.old_symbol IS
    'Previous contract symbol at roll (e.g. ''ESM6'')';
COMMENT ON COLUMN system_events.new_symbol IS
    'New front-month symbol after roll (e.g. ''ESU6'')';
COMMENT ON COLUMN system_events.roll_gap IS
    'Absolute price gap at roll boundary (close_old vs open_new)';
COMMENT ON COLUMN system_events.roll_direction IS
    'Roll price direction: up / down / flat / unknown';
COMMENT ON COLUMN system_events.event_data IS
    'Arbitrary JSON payload for extensibility (z_score, confirmation_bars, etc.)';
