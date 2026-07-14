-- Migration 233: Concept Registry MVP - four-table schema + APR gate keys (todo 058)
--
-- Builds the Minimal Viable Version from docs/research/concept-unified-registry.md:
-- concept_registry / concept_gate / concept_transition_log / concept_annotation. Deliberately
-- NOT created (reference architecture only, per the canonical doc's "do not build the
-- ten-table version" and cluster-review F7): concept_gate_template, concept_gate_stack,
-- concept_eval_run, concept_eval_state (folded into concept_gate), concept_dependency,
-- concept_regime_ic, concept_correlation.
--
-- MVP deltas vs the canonical doc's sketches, each with provenance:
--   * concept_transition_log.corpus_build_ref (F3): invariant 2's re-evaluation guard needs
--     a corpus identity to compare against, not just triggered_at timestamps. Value is the
--     WEIGHT_EPOCH / CorpusManifest identity (e.g. 'run_2025122405150000'), never invented.
--   * concept_gate.min_new_observations (F3): evidence-mass re-eval floor; re-evaluation is
--     permitted only once >= N new independent observations accrued since the last eval.
--     NULL = inherit the per-domain APR default seeded below.
--   * concept_gate carries the folded eval-state cache (last_eval_*, baseline_metric,
--     decay_ratio, promotion counters) - the MVP merges concept_eval_state into concept_gate,
--     mirroring how feature_registry holds last_ic_* on the registry row today.
--   * concept_gate.promotion_eval_metrics (F8 winner's-curse guard): the gate metric of each
--     consecutive winning evaluation is appended here; at promotion, baseline_metric is the
--     MEAN of this array, never the final (selection-inflated) value.
--   * trigger_reason 'genesis_seed': establishes an incumbent at seeding time without
--     fabricating a promotion event.
--   * concept_transition_log is a TimescaleDB hypertable on triggered_at (canonical doc,
--     2026-07-06 stress-test pass), so its PK must include the partitioning column.
--
-- domain CHECK includes 'feature' per the canonical doc's sketch, but NO feature rows are
-- seeded here (todo 058 item 7): feature_registry stays the live governor for domain='feature'
-- until the follow-on migration item (todo 109) executes.

BEGIN;

-- concept_registry: the primary table (immutable rows, promotion/demotion via transition_log)
CREATE TABLE concept_registry (
    concept_id BIGSERIAL PRIMARY KEY,
    domain TEXT NOT NULL CHECK (domain IN ('feature', 'regime_model', 'hmm_variant', 'signal', 'ensemble_strategy', 'alpha_source', 'cost_model', 'exit_model')),
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'deprecated', 'rejected')) DEFAULT 'candidate',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB,
    added_phase TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (domain, name)
);

-- concept_gate: promotion criteria and evaluation state cache
CREATE TABLE concept_gate (
    concept_id BIGSERIAL PRIMARY KEY REFERENCES concept_registry(concept_id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    gate_metric_name TEXT NOT NULL,
    gate_eval_method TEXT NOT NULL CHECK (gate_eval_method IN ('ic_sharpe', 'oos_holdout', 'regime_stability', 'custom')),
    min_gate_metric NUMERIC,
    min_gate_n INTEGER,  -- NULL = inherit APR default
    fdr_required BOOLEAN DEFAULT FALSE,
    fdr_alpha NUMERIC,  -- NULL = inherit APR default
    min_promotion_consecutive INTEGER,  -- NULL = inherit APR default
    min_new_observations INTEGER,  -- NULL = inherit APR default
    last_evaluated_at TIMESTAMPTZ,
    last_eval_metric NUMERIC,
    baseline_metric NUMERIC,
    promotion_eval_metrics NUMERIC[],  -- winner's-curse guard: append consecutive eval metrics
    promotion_count INTEGER DEFAULT 0,
    demotion_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (concept_id) REFERENCES concept_registry(concept_id)
);

-- concept_transition_log: audit trail with corpus-build ref for re-eval guards (F3)
CREATE TABLE concept_transition_log (
    id BIGSERIAL PRIMARY KEY,
    concept_id BIGINT NOT NULL REFERENCES concept_registry(concept_id),
    domain TEXT NOT NULL,
    name TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    trigger_reason TEXT NOT NULL CHECK (trigger_reason IN ('gate_eval', 'manual', 'corpus_rebuild', 'regime_shift', 'genesis_seed')),
    notes TEXT,
    corpus_build_ref TEXT,  -- F3: corpus identity for re-evaluation guards
    eval_metrics JSONB,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create hypertable on triggered_at for time-series queries (2026-07-06 stress-test pass)
SELECT create_hypertable('concept_transition_log', 'triggered_at', if_not_exists => TRUE);

-- concept_annotation: operator notes and documentation
CREATE TABLE concept_annotation (
    id BIGSERIAL PRIMARY KEY,
    concept_id BIGINT NOT NULL REFERENCES concept_registry(concept_id) ON DELETE CASCADE,
    annotation_type TEXT NOT NULL CHECK (annotation_type IN ('note', 'warning', 'reference', 'thesis', 'implementation', 'observation')),
    content TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('human', 'ai', 'system')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- APR gate keys (migration 233 seeds these; policy hooks will gate on concept_registry writes)
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('concept.registry.ic_sharpe_threshold', 'numeric', '0.0', '-10.0', '10.0', '[ic_sharpe] Minimum IC Sharpe for concept promotion (default 0.0 = any positive IC)'),
('concept.registry.oos_validation_ratio', 'numeric', '0.7', '0.0', '1.0', '[oos_validation] Minimum OOS validation ratio (default 0.7)'),
('concept.registry.min_new_observations_default', 'integer', '1000', '100', '100000', '[min_new_observations] Default evidence-mass floor for re-evaluation (default 1000)')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
('concept.registry.ic_sharpe_threshold', '0.0', 1),
('concept.registry.oos_validation_ratio', '0.7', 1),
('concept.registry.min_new_observations_default', '1000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
(NOW(), 'concept.registry.ic_sharpe_threshold', 1, '0.0', 'migration_233', 'Initial value: any positive IC passes promotion gate [initial_value]'),
(NOW(), 'concept.registry.oos_validation_ratio', 1, '0.7', 'migration_233', 'Initial value: 70% OOS validation ratio required [initial_value]'),
(NOW(), 'concept.registry.min_new_observations_default', 1, '1000', 'migration_233', 'Initial value: 1000 obs default re-eval floor [initial_value]')
ON CONFLICT DO NOTHING;

COMMIT;