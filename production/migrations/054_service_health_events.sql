-- 054_service_health_events.sql
-- Applied: 2026-04-03
-- Purpose: Audit trail for ServiceAuditorAgent.
-- Every state transition is a labeled data sample for MTTR, failure pattern detection.

CREATE TABLE IF NOT EXISTS service_health_events (
    ts                   TIMESTAMPTZ      NOT NULL,
    service              TEXT             NOT NULL,
    event_type           TEXT             NOT NULL,  -- degraded|restart|recovered|escalated|heartbeat
    previous_state       TEXT,
    reason               TEXT,
    lag_messages         BIGINT,
    restart_count        INT,
    duration_degraded_s  DOUBLE PRECISION
);

SELECT create_hypertable('service_health_events', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_she_service_ts ON service_health_events (service, ts DESC);
CREATE INDEX IF NOT EXISTS idx_she_type_ts    ON service_health_events (event_type, ts DESC);

-- Verification:
-- SELECT ts, service, event_type, reason FROM service_health_events ORDER BY ts DESC LIMIT 5;
