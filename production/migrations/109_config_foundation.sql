-- Phase 109 OPS config. INFRA in .env. STRUCT in code.
-- Creates config foundation tables for hot-reloadable OPS configuration only.
-- INFRA keys (DATABASE_URL, KAFKA_BROKERS) must be set via .env.
-- STRUCT keys (plugin tiers, DAG order) must be changed via code deployment.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- config_schema: defines valid OPS config keys and their validation rules
-- NO category column (OPS-only invariant)
-- NO depends_on column (per Codex LOW finding: semantics unclear, avoid confusion)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS config_schema (
    config_key      TEXT PRIMARY KEY,
    value_type      TEXT NOT NULL,
    default_value   TEXT,
    min_value       FLOAT,
    max_value       FLOAT,
    allowed_values  TEXT[],
    is_secret       BOOLEAN DEFAULT FALSE,
    version         INT DEFAULT 1,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- config_state: current live values for each OPS config key
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS config_state (
    config_key      TEXT PRIMARY KEY,
    config_value    TEXT NOT NULL,
    version         INT NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- config_history: immutable time-series audit log for all config changes
-- Hypertable partitioned by timestamp for efficient time-range queries
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS config_history (
    timestamp       TIMESTAMPTZ NOT NULL,
    config_key      TEXT NOT NULL,
    version         INT NOT NULL,
    config_value    TEXT NOT NULL,
    changed_by      TEXT NOT NULL,
    reason          TEXT,
    PRIMARY KEY (timestamp, config_key, version)
);

SELECT create_hypertable('config_history', 'timestamp', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_config_history_key_time
    ON config_history (config_key, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_config_history_user
    ON config_history (changed_by, timestamp DESC);

SELECT add_retention_policy('config_history', INTERVAL '1 year', if_not_exists => TRUE);

ALTER TABLE config_history SET (timescaledb.compress = true, timescaledb.compress_segmentby = 'config_key');
SELECT add_compression_policy('config_history', INTERVAL '7 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- config_outbox: transactional outbox for Kafka propagation
-- OutboxDispatcher (109-02) polls pending rows and publishes to Kafka
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS config_outbox (
    id              BIGSERIAL PRIMARY KEY,
    config_key      TEXT NOT NULL,
    config_value    TEXT NOT NULL,
    version         INT NOT NULL,
    changed_at      TIMESTAMPTZ DEFAULT NOW(),
    status          TEXT DEFAULT 'pending',
    retry_count     INT DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON config_outbox (next_attempt_at)
    WHERE status = 'pending';

-- ---------------------------------------------------------------------------
-- Seed OPS schema rows for keys present in settings.py
-- ON CONFLICT DO NOTHING guarantees idempotency (safe to re-run)
-- ---------------------------------------------------------------------------

-- Regime gate parameters
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('regime.prob_min', 'float', '0.30', 0.0, 1.0, FALSE, 'Minimum regime probability to pass gate (safety floor)')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('regime.dur_min', 'int', '1', 1, 100, FALSE, 'Minimum regime duration in bars to pass gate')
ON CONFLICT (config_key) DO NOTHING;

-- Swarm intelligence parameters
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('swarm.min_confidence', 'float', '0.6', 0.0, 1.0, FALSE, 'Minimum winner_confidence for swarm enrichment gate')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('swarm.min_tf_minutes', 'int', '5', 1, 1440, FALSE, 'Minimum timeframe in minutes for swarm enrichment (skip 1m bars)')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('swarm.weight_min_samples', 'int', '30', 1, 10000, FALSE, 'Minimum resolved predictions before weight learning activates')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('swarm.weight_floor', 'float', '0.05', 0.0, 1.0, FALSE, 'Minimum agent weight before formal demotion')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('swarm.max_concurrent_calls', 'int', '8', 1, 64, FALSE, 'Max concurrent LLM calls (asyncio.Semaphore capacity)')
ON CONFLICT (config_key) DO NOTHING;

-- Roll monitoring parameters
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('roll.monitor_window_size', 'int', '100', 10, 10000, FALSE, 'Rolling window size for roll monitoring')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('roll.threshold_default', 'float', '1.2', 0.1, 10.0, FALSE, 'Default volume ratio threshold for roll detection')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('roll.postroll_bars', 'int', '10', 0, 1000, FALSE, 'Bars to monitor after a roll event')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('roll.cooldown_min', 'int', '30', 0, 1440, FALSE, 'Cooldown in minutes between roll events')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('roll.confirmation_bars', 'int', '3', 1, 100, FALSE, 'Bars required to confirm a roll')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, allowed_values, is_secret, description)
VALUES ('roll.time_of_day_gated', 'bool', 'true', ARRAY['true', 'false'], FALSE, 'Gate roll detection to market open/close windows')
ON CONFLICT (config_key) DO NOTHING;

-- Cross-asset intelligence parameters
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('cross_asset.window_bars', 'int', '20', 1, 1000, FALSE, 'Rolling window bars for cross-asset correlation')
ON CONFLICT (config_key) DO NOTHING;

-- Macro factors parameters
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, is_secret, description)
VALUES ('macro.window_bars', 'int', '10', 1, 1000, FALSE, 'Rolling window bars for macro factor computation')
ON CONFLICT (config_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Seed matching config_state rows with current values + version=1
-- ON CONFLICT DO NOTHING guarantees idempotency
-- ---------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version)
VALUES ('regime.prob_min', '0.30', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('regime.dur_min', '1', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('swarm.min_confidence', '0.6', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('swarm.min_tf_minutes', '5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('swarm.weight_min_samples', '30', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('swarm.weight_floor', '0.05', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('swarm.max_concurrent_calls', '8', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('roll.monitor_window_size', '100', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('roll.threshold_default', '1.2', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('roll.postroll_bars', '10', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('roll.cooldown_min', '30', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('roll.confirmation_bars', '3', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('roll.time_of_day_gated', 'true', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('cross_asset.window_bars', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('macro.window_bars', '10', 1)
ON CONFLICT (config_key) DO NOTHING;
