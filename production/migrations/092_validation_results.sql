-- Migration 092: Feature Validation Results — Phase 82 D-05
--
-- Purpose: Create validation_results hypertable for daily IC/p-value decisions
--          produced by FeatureValidationComputeAgent, and seed the
--          shadow_registry.promotion_evidence JSONB column used by the
--          Phase 75 ShadowAuditorAgent governance contract.
--
-- Idempotency: All statements use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS so
--              replaying this migration is safe and produces no errors.
--
-- Dependencies: 077_shadow_governance.sql (shadow_registry table must exist),
--               TimescaleDB extension must be enabled.
--
-- Produces:
--   validation_results hypertable  — per-plugin VALIDATED/TWEAK/KILL rows
--   shadow_registry.promotion_evidence JSONB — latest decision evidence per plugin

-- ---------------------------------------------------------------------------
-- validation_results: daily IC/p-value decision rows per (plugin, tf, regime)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS validation_results (
    plugin_name          TEXT             NOT NULL,
    timeframe            TEXT             NOT NULL,
    regime_type          TEXT,                        -- NULL = global slice (all regimes)
    ic                   DOUBLE PRECISION NOT NULL,
    p_value              DOUBLE PRECISION NOT NULL,
    n                    INTEGER          NOT NULL,
    decision             TEXT             NOT NULL
        CHECK (decision IN ('VALIDATED', 'TWEAK', 'KILL')),
    bonferroni_corrected BOOLEAN          NOT NULL DEFAULT TRUE,
    computed_at          TIMESTAMPTZ      NOT NULL DEFAULT now()
);

-- Partition by computed_at (daily runs; TimescaleDB manages chunk boundaries)
SELECT create_hypertable('validation_results', 'computed_at', if_not_exists => TRUE);

-- Covering index for the primary API query pattern:
--   latest per-plugin decisions filtered/ordered by (plugin_name, timeframe, computed_at)
CREATE INDEX IF NOT EXISTS validation_results_plugin_tf_idx
    ON validation_results (plugin_name, timeframe, computed_at DESC);

-- ---------------------------------------------------------------------------
-- shadow_registry: add promotion_evidence column (Phase 75 contract seed)
--
-- FeatureValidationComputeAgent writes a JSONB document here with the latest
-- decision, IC, p-value, n, and computed_at for each component_name.
-- ShadowAuditorAgent (Phase 75) reads this column to execute promotion/demotion
-- — this phase produces evidence only; Phase 75 acts on it.
-- ---------------------------------------------------------------------------

ALTER TABLE shadow_registry ADD COLUMN IF NOT EXISTS promotion_evidence JSONB;

COMMENT ON COLUMN shadow_registry.promotion_evidence IS
    'Latest validation evidence written by FeatureValidationComputeAgent. '
    'Contains decision (VALIDATED/TWEAK/KILL), ic, p_value, n, computed_at. '
    'Read by ShadowAuditorAgent (Phase 75) to execute promotion/demotion actions.';
