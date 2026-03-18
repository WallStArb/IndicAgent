-- Migration 038: Confidence calibration table + signal_ledger calibration columns
-- Phase 35: Isotonic regression calibration for signal confidence

-- New table: stores per-(plugin_name, timeframe) isotonic regression curves
CREATE TABLE IF NOT EXISTS confidence_calibration (
    plugin_name   TEXT         NOT NULL,
    timeframe     TEXT         NOT NULL,
    breakpoints   DOUBLE PRECISION[] NOT NULL,
    values        DOUBLE PRECISION[] NOT NULL,
    ece           DOUBLE PRECISION   NOT NULL,
    sample_size   INT          NOT NULL,
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (plugin_name, timeframe)
);

COMMENT ON TABLE confidence_calibration IS
    'Isotonic regression calibration curves per (plugin_name, timeframe). '
    'Refreshed every 30 min by confidence_calibrator.py when N >= 100 resolved signals.';

-- Extend signal_ledger with calibration tracking columns
-- All nullable: NULL = not yet calibrated or insufficient history
ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS raw_cis_score        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS filtered_cis_score   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS calibrated_confidence DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS regime_type_at_fire  TEXT;

COMMENT ON COLUMN signal_ledger.raw_cis_score IS
    'Raw CIS composite score from CISScorer, before Kalman filtering. Phase 35.';
COMMENT ON COLUMN signal_ledger.filtered_cis_score IS
    'Kalman-filtered CIS score. Phase 35 fire condition uses filtered_cis > 0.35.';
COMMENT ON COLUMN signal_ledger.calibrated_confidence IS
    'Isotonic regression calibrated probability [0,1]. NULL when N < 100 for (plugin_name, timeframe). '
    'Never stores raw confidence as a passthrough — ML pipeline isolates calibrated rows via IS NOT NULL.';
COMMENT ON COLUMN signal_ledger.regime_type_at_fire IS
    'regime_type from the winning signal at fire time (trend|mean_reversion|any). '
    'Used by TOD multiplier SQL to group win rates by regime. Phase 35.';
