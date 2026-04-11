-- 060_ml_discovery_runs.sql
-- Phase 56-06: Feature discovery run results.
-- MLDiscoveryComputeAgent (services/ml_discovery_agent.py) writes here weekly.
-- Each row = one completed or partial tsfresh + IC analysis run.

CREATE TABLE IF NOT EXISTS ml_discovery_runs (
    run_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol        TEXT,               -- NULL = cross-symbol run
    tf            TEXT,               -- NULL = cross-timeframe run
    regime        INT,                -- NULL = cross-regime run; 0/1/2 when segmented
    top_features  JSONB       NOT NULL,  -- [{name, ic, icir, p_value}] top N by IC
    ic_scores     JSONB       NOT NULL,  -- full {feature_name: ic_score} map
    feature_count INT         NOT NULL,  -- number of features extracted by tsfresh
    status        TEXT        NOT NULL DEFAULT 'complete'  -- 'complete' | 'partial'
);

-- Time-ordered for dashboard/history queries
CREATE INDEX IF NOT EXISTS idx_ml_discovery_runs_ts
    ON ml_discovery_runs (ts DESC);

COMMENT ON TABLE ml_discovery_runs IS
    'Weekly tsfresh + alphalens IC analysis results. '
    'MLDiscoveryComputeAgent writes one row per run per (symbol, tf, regime) segment. '
    'top_features: top N by |IC| above ML_DISCOVERY_IC_THRESHOLD. '
    'ic_scores: full map for dashboard heatmap. '
    'status=partial if tsfresh timed out — next run starts fresh.';
