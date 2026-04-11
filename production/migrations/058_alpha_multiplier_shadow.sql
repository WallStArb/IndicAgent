-- 058_alpha_multiplier_shadow.sql
-- Phase 56-06: Shadow prediction table for swarm agent validation.
-- TimescaleDB hypertable on ts for time-based querying + compression.
-- NOTE: TimescaleDB does not allow UNIQUE indexes on non-partitioning columns.
-- Uniqueness (signal_id, agent_id) is enforced at the application layer (ON CONFLICT DO NOTHING).

CREATE TABLE IF NOT EXISTS alpha_multiplier_shadow (
    ts                   TIMESTAMPTZ     NOT NULL,
    signal_id            UUID            NOT NULL,
    agent_id             TEXT            NOT NULL,
    symbol               TEXT            NOT NULL,
    tf                   TEXT            NOT NULL,
    hmm_regime           INT,                        -- 0=ranging, 1=trending_up, 2=trending_down
    path                 TEXT            NOT NULL,   -- 'path_a' | 'path_b'
    predicted_multiplier FLOAT           NOT NULL,   -- [0.0, 2.0]
    confidence           FLOAT           NOT NULL,   -- [0.0, 1.0]
    features             JSONB                       -- FeatureVector snapshot for training
);

SELECT create_hypertable('alpha_multiplier_shadow', 'ts', if_not_exists => TRUE);

-- Lookup index: (signal_id, agent_id) for dedup and JOIN queries
CREATE INDEX IF NOT EXISTS idx_shadow_signal_agent
    ON alpha_multiplier_shadow (signal_id, agent_id);

-- Pearson validation query index: (agent_id, symbol, tf, hmm_regime) + JOIN signal_ledger
CREATE INDEX IF NOT EXISTS idx_shadow_agent_segment
    ON alpha_multiplier_shadow (agent_id, symbol, tf, hmm_regime, ts DESC);

-- Retention: keep forever (training dataset — Renaissance principle)
COMMENT ON TABLE alpha_multiplier_shadow IS
    'Shadow multiplier predictions per swarm agent per signal. '
    'One row per (signal_id, agent_id) by application convention. Keep forever — training dataset. '
    'JOIN signal_ledger ON (signal_id) for outcome-labeled rows. '
    'Pearson(confidence, win_flag) per segment for promotion validation.';
