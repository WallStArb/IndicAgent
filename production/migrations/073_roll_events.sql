-- Migration 073: roll_events table for dual-detector roll tracking
--
-- Stores every roll detection event from both detectors:
--   detection_method='volume'   — confirmed by volume z-score (RollMonitor)
--   detection_method='calendar' — fired at scheduled roll_end date (CalendarRollScheduler)
--
-- is_authoritative=true marks the event that actually triggered the operational roll
-- (first event per (base_symbol, new_contract) in ContractMetadataWriterAgent).
-- Subsequent events for the same roll cycle are stored with is_authoritative=false.
--
-- ML query: delta between calendar scheduled date and volume detection:
--   SELECT base_symbol, detection_method,
--          AVG(EXTRACT(EPOCH FROM (detected_at - scheduled_roll_date::timestamptz)) / 86400) AS avg_delta_days
--   FROM roll_events GROUP BY base_symbol, detection_method ORDER BY base_symbol;

CREATE TABLE IF NOT EXISTS roll_events (
    id                  BIGSERIAL PRIMARY KEY,
    detected_at         TIMESTAMPTZ NOT NULL,
    base_symbol         TEXT        NOT NULL,
    old_contract        TEXT        NOT NULL,
    new_contract        TEXT        NOT NULL,
    detection_method    TEXT        NOT NULL CHECK (detection_method IN ('volume', 'calendar')),
    volume_zscore       DOUBLE PRECISION,           -- NULL for calendar events
    confirmation_count  INTEGER,                    -- NULL for calendar events
    scheduled_roll_date DATE,                       -- roll_end date from get_roll_window()
    is_authoritative    BOOLEAN     NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_roll_events_base_detected
    ON roll_events (base_symbol, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_roll_events_detection_method
    ON roll_events (detection_method);

COMMENT ON TABLE roll_events IS
    'All roll detection events (volume + calendar) for ML training and operational audit.';
COMMENT ON COLUMN roll_events.is_authoritative IS
    'True for the first event that triggered the operational front-month promotion.';
COMMENT ON COLUMN roll_events.scheduled_roll_date IS
    'Calendar-scheduled roll_end date (expiry-3 days) from contracts.py get_roll_window().';
