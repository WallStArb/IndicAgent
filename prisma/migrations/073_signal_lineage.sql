-- 073: Unified signal lineage hypertable
-- Merges alpha_multiplier_shadow + signal_transform_log into single table
-- D-01: single hypertable for all lineage events
-- D-02: schema with event_type, source, dag_order, multiplier, metadata JSONB

CREATE TABLE IF NOT EXISTS signal_lineage (
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_id     UUID NOT NULL,
    event_type    TEXT NOT NULL CHECK (event_type IN ('transform', 'agent_prediction', 'lifecycle')),
    source        TEXT NOT NULL,       -- transform_id or agent_id
    dag_order     SMALLINT,
    multiplier    FLOAT,
    metadata      JSONB DEFAULT '{}',  -- D-07: event-specific data
    is_shadow     BOOLEAN DEFAULT TRUE,
    symbol        TEXT,
    tf            TEXT
);

-- Hypertable for time-series partitioning
SELECT create_hypertable('signal_lineage', 'ts', if_not_exists => TRUE);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_lineage_signal_id ON signal_lineage (signal_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_lineage_event_source ON signal_lineage (event_type, source, ts DESC);
CREATE INDEX IF NOT EXISTS idx_lineage_symbol_tf ON signal_lineage (symbol, tf, ts DESC);

-- D-05: alpha_multiplier_shadow is deprecated
-- Old table kept for historical data; writes now go to signal_lineage
COMMENT ON TABLE signal_lineage IS 'Unified signal lineage: transforms, agent predictions, lifecycle events. Replaces alpha_multiplier_shadow + signal_transform_log.';
