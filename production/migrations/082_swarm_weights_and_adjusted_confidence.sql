-- Phase 80: Swarm Intelligence Layer — new columns + weight table
-- Idempotent: safe to re-apply.

ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS adjusted_confidence FLOAT;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS swarm_multiplier FLOAT;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS swarm_agent_count INT;

CREATE TABLE IF NOT EXISTS swarm_agent_weights (
    agent_id          TEXT        NOT NULL,
    timeframe         TEXT        NOT NULL,
    weight            FLOAT       NOT NULL DEFAULT 1.0,
    sample_size       INT         NOT NULL DEFAULT 0,
    spearman_rho      FLOAT,
    calibration_error FLOAT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_ledger_adjusted_confidence
    ON signal_ledger (adjusted_confidence)
    WHERE adjusted_confidence IS NOT NULL;
