-- 061_ml_data_quality_runs.sql
-- Phase 56: Data quality audit run results.
-- MLDataQualityAuditorAgent (services/ml_data_quality_agent.py) writes here weekly.
-- MLOrchestratorComputeAgent reads the latest row to determine quality gate pass/fail.

CREATE TABLE IF NOT EXISTS ml_data_quality_runs (
    run_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ts      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    score   FLOAT       NOT NULL,   -- composite quality score [0.0, 1.0]
    status  TEXT        NOT NULL DEFAULT 'complete'  -- 'complete'
);

-- Orchestrator reads latest row
CREATE INDEX IF NOT EXISTS idx_ml_data_quality_runs_ts
    ON ml_data_quality_runs (ts DESC);

COMMENT ON TABLE ml_data_quality_runs IS
    'Weekly ML training data quality audit results. '
    'MLDataQualityAuditorAgent writes one row per run with composite score. '
    'MLOrchestratorComputeAgent reads latest score to gate discovery pipeline. '
    'score >= 0.85 required to proceed (DATA_QUALITY_MIN_SCORE threshold).';
