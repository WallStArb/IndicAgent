-- 056_signal_metrics.sql
-- Phase 60: Renaissance-aligned signal performance metrics
-- Three tables: per-segment stats (two tracks), IC, and DQ audit log.

CREATE TABLE IF NOT EXISTS signal_metrics (
    track               TEXT        NOT NULL,
    setup_plugin        TEXT        NOT NULL,
    tf                  TEXT        NOT NULL,
    regime_type         TEXT        NOT NULL,
    window_days         INT         NOT NULL,
    n                   INT         NOT NULL,
    n_outliers          INT         NOT NULL DEFAULT 0,
    never_activated_pct FLOAT,
    win_rate            FLOAT,
    avg_r               FLOAT,
    std_r               FLOAT,
    sharpe              FLOAT,
    p_value             FLOAT,
    avg_mae             FLOAT,
    avg_mfe             FLOAT,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (track, setup_plugin, tf, regime_type, window_days)
);

COMMENT ON TABLE signal_metrics IS
    'Per-segment signal performance. track=zone (structural quality) or market (tradeable alpha). '
    'regime_type from hmm_regime_at_fire: 0->mean_reversion, 1/2->trend. '
    '''all'' row = regime rollup for bootstrap phase (n<30 per regime).';

CREATE TABLE IF NOT EXISTS signal_metrics_ic (
    setup_plugin        TEXT        NOT NULL,
    tf                  TEXT        NOT NULL,
    regime_type         TEXT        NOT NULL,
    window_days         INT         NOT NULL,
    n                   INT         NOT NULL,
    ic                  FLOAT,
    p_value             FLOAT,
    is_significant      BOOL,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (setup_plugin, tf, regime_type, window_days)
);

COMMENT ON TABLE signal_metrics_ic IS
    'Information Coefficient: Pearson r(confidence, binary_outcome) per setup x regime x window. '
    'Measures whether confidence scores are predictive of zone outcomes (setup quality).';

CREATE TABLE IF NOT EXISTS signal_metrics_dq_failures (
    id          BIGSERIAL   PRIMARY KEY,
    signal_id   UUID        NOT NULL,
    reason_code TEXT        NOT NULL,
    entry_price FLOAT,
    stop_loss   FLOAT,
    pnl_r       FLOAT,
    direction   INT,
    hmm_regime  INT,
    setup_plugin TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signal_metrics_dq_signal_id
    ON signal_metrics_dq_failures (signal_id);
CREATE INDEX IF NOT EXISTS idx_signal_metrics_dq_reason
    ON signal_metrics_dq_failures (reason_code);

COMMENT ON TABLE signal_metrics_dq_failures IS
    'Permanent audit log for signal_ledger rows that fail data quality validation. '
    'Never delete or truncate. Raw signal_ledger rows are never modified.';
