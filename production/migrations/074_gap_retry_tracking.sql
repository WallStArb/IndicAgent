-- Migration 074: gap retry tracking for market_data_gaps
--
-- Adds retry state columns so bar_auditor can enforce exponential-backoff
-- re-emission and DLQ escalation after MAX_GAP_RETRIES attempts.
-- Replaces the in-memory _requested_today set (which didn't survive restarts
-- and blocked all retries for 24 h regardless of IBKR fetch outcome).

ALTER TABLE market_data_gaps
    ADD COLUMN IF NOT EXISTS gap_requests_sent     integer   NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_request_sent_at  timestamptz,
    ADD COLUMN IF NOT EXISTS last_request_id       text;

COMMENT ON COLUMN market_data_gaps.gap_requests_sent    IS 'Number of BarGapRequests emitted for this gap';
COMMENT ON COLUMN market_data_gaps.last_request_sent_at IS 'UTC timestamp of most recent BarGapRequest emission';
COMMENT ON COLUMN market_data_gaps.last_request_id      IS 'request_id of most recent BarGapRequest (for DLQ correlation)';
