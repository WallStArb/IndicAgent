-- Migration 027: drift_monitor hypertable
-- Stores KS and CUSUM distribution drift check results.
-- Used by drift_monitor_service (QUAL-09 KS + QUAL-10 CUSUM).

CREATE TABLE IF NOT EXISTS drift_monitor (
    id              BIGSERIAL       NOT NULL,
    check_type      TEXT            NOT NULL,   -- 'ks' or 'cusum'
    symbol          TEXT            NOT NULL,
    timeframe       TEXT,
    setup_plugin    TEXT,
    feature_name    TEXT,
    checked_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    ks_statistic    FLOAT,
    ks_pvalue       FLOAT,
    reference_n     INTEGER,
    current_n       INTEGER,
    cusum_pos       FLOAT,
    cusum_neg       FLOAT,
    cusum_threshold FLOAT,
    baseline_mean   FLOAT,
    baseline_std    FLOAT,
    total_outcomes  INTEGER,
    alert_triggered BOOLEAN         NOT NULL DEFAULT FALSE,
    alert_severity  TEXT,
    alert_message   TEXT
);

SELECT create_hypertable('drift_monitor', 'checked_at',
    chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);

-- No CONCURRENTLY on hypertable indexes (TimescaleDB constraint)
CREATE INDEX IF NOT EXISTS idx_drift_monitor_sym_type
    ON drift_monitor (symbol, check_type, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_drift_monitor_alerts
    ON drift_monitor (alert_triggered, checked_at DESC)
    WHERE alert_triggered = TRUE;
