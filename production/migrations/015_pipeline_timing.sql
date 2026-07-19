-- Migration 015: Pipeline Timing Observability
-- Adds bar_close_ts (always set) and computed_at fields (live-only) to enable
-- post-hoc SQL lag analysis from bar close to each pipeline stage.

-- intelligence_features: bar_close_ts (always), timing for live events
ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS bar_close_ts      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS i1_computed_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS computed_at       TIMESTAMPTZ;

COMMENT ON COLUMN intelligence_features.bar_close_ts   IS 'Actual bar close time (differs from ts for 5m+). Always set.';
COMMENT ON COLUMN intelligence_features.i1_computed_at IS 'When indicator_service finished I1. NULL for backfill.';
COMMENT ON COLUMN intelligence_features.computed_at    IS 'When market_analysis_service built this event. NULL for backfill.';

-- signal_ledger: signal processing timestamp (live only)
ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS signal_computed_at TIMESTAMPTZ;

COMMENT ON COLUMN signal_ledger.signal_computed_at IS 'When signal_generator_service fired this signal. NULL for backfill.';
