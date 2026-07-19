-- Migration 094: dlq_events hypertable
-- DLQ history substrate: queryable record of all dead-letter queue messages.
-- Replaces the write-only black hole pattern with a 30-day retention hypertable.

CREATE TABLE IF NOT EXISTS dlq_events (
    id            BIGSERIAL,
    routed_at     TIMESTAMPTZ NOT NULL,
    agent         TEXT NOT NULL,
    source_topic  TEXT NOT NULL,
    dlq_topic     TEXT NOT NULL,
    error_type    TEXT NOT NULL,
    error_message TEXT NOT NULL,
    payload       JSONB NOT NULL,
    retry_count   INT NOT NULL DEFAULT 0,
    PRIMARY KEY (id, routed_at)  -- id is unique; routed_at required by TimescaleDB hypertable
);

SELECT create_hypertable('dlq_events', 'routed_at', if_not_exists => TRUE);
SELECT add_retention_policy('dlq_events', INTERVAL '30 days', if_not_exists => TRUE);

-- No dedup index: dlq_events is a loss-of-information audit log; burst errors from the
-- same agent/topic within the same microsecond must all be preserved, not silently dropped.
