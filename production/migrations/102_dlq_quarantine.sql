-- Migration 102: dlq_events quarantine column
-- Phase 108 (HEAL-04): Adds quarantined flag for DLQ messages that have exceeded
-- DLQ_MAX_RETRIES identical errors in a rolling 24h window.
-- Set by DLQDrainAgent in-memory counter logic; no backfill needed (existing rows default FALSE).

ALTER TABLE dlq_events
    ADD COLUMN IF NOT EXISTS quarantined BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS dlq_events_quarantine_lookup_idx
    ON dlq_events (agent, source_topic, error_type, routed_at DESC);
