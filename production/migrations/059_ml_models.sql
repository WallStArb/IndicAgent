-- 059_ml_models.sql
-- Phase 56-06: ML model registry table.
-- ModelRegistry (src/core/ml/registry.py) reads/writes here.
-- MLflow is the artifact store; this table is the routing layer.

CREATE TABLE IF NOT EXISTS ml_models (
    model_id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type         TEXT        NOT NULL,        -- 'lightgbm', 'random_forest'
    segment            JSONB       NOT NULL,        -- {regime, setup_type, tf}
    mlflow_run_id      TEXT,                        -- MLflow run ID for artifact retrieval
    status             TEXT        NOT NULL DEFAULT 'shadow',  -- 'shadow' | 'production' | 'retired'
    shadow_correlation FLOAT,                       -- Pearson(predicted, actual) from shadow period
    promoted_at        TIMESTAMPTZ,                 -- NULL until status='production'
    artifact_path      TEXT,                        -- MLflow artifact URI
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookup: latest production model per segment
CREATE INDEX IF NOT EXISTS idx_ml_models_segment_status
    ON ml_models (((segment->>'regime')::text), ((segment->>'tf')::text), status, created_at DESC);

COMMENT ON TABLE ml_models IS
    'ML model registry. ModelRegistry (src/core/ml/registry.py) wraps this table. '
    'MLflow stores artifacts; this table routes inference to the right artifact. '
    'shadow_correlation >= 0.4 required before status can be set to production.';
