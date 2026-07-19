-- Add flight-to-quality columns to macro_features (Plan 64-03B)
-- These were commented out in 074 pending implementation; now shipping.

ALTER TABLE macro_features
    ADD COLUMN IF NOT EXISTS ftq_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ftq_regime VARCHAR(32);

COMMENT ON COLUMN macro_features.ftq_score IS
    'Flight-to-quality score [-1, +1]. Positive = risk-on (SPY outperforming TLT). Negative = risk-off.';
COMMENT ON COLUMN macro_features.ftq_regime IS
    'FTQ regime label: risk_on | risk_off | neutral';
