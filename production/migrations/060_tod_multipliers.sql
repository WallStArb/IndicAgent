-- Migration 060: Create tod_multipliers table
-- Stores learned TOD (time-of-day) confidence multipliers per regime_type/tf/hour_et cell.
-- Loaded by IntelligencePipelineComputeAgent at startup; refreshed every 4h.
-- Empty table is valid — pipeline falls back to hardcoded session priors in tod_adjuster.py.

CREATE TABLE IF NOT EXISTS tod_multipliers (
    regime_type TEXT NOT NULL,
    tf          TEXT NOT NULL,
    hour_et     SMALLINT NOT NULL CHECK (hour_et BETWEEN 0 AND 23),
    multiplier  FLOAT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (regime_type, tf, hour_et)
);

COMMENT ON TABLE tod_multipliers IS
    'Learned TOD multipliers per (regime_type, tf, hour_et) cell. '
    'Loaded by IntelligencePipelineComputeAgent; falls back to session priors when empty.';
