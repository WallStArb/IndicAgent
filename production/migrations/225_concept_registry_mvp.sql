-- Migration 225: Concept Registry MVP - four-table schema + APR gate keys (todo 058)
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
--
-- Review-driven corrections applied (phase 160 cross-AI review):
--   * M-3: config_history's PK is (timestamp, config_key, version) and this insert uses NOW(),
--     so ON CONFLICT can never fire on re-run. Each config_history insert is guarded by
--     WHERE NOT EXISTS (config_key, version=1) so re-applying this migration inserts zero new
--     config_history rows.
--   * M-6: concept_annotation.source's CHECK permits 'human', 'ai', AND 'empirical' - plan
--     160-03's durable loss/win trail writes source='empirical' annotation rows.
--   * L-7: concept_gate.fdr_required carries an advisory-only comment - ConceptRegistryService
--     does not read this column; BH-FDR enforcement lives entirely upstream in
--     ops_ensemble_weight_compare.py.
--
-- All statements idempotent: CREATE TABLE IF NOT EXISTS, ON CONFLICT DO NOTHING, or
-- WHERE NOT EXISTS guards where the PK does not support ON CONFLICT. Safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS concept_registry (
    concept_id        UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    domain            TEXT    NOT NULL
        CHECK (domain IN ('feature', 'ensemble_strategy')),
    name              TEXT    NOT NULL,
    description       TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'shadow_only', 'active', 'deprecated')),
    enabled           BOOLEAN NOT NULL DEFAULT false,
    parent_concept_id UUID    REFERENCES concept_registry(concept_id),
    redundancy_group  TEXT,
    metadata          JSONB,
    added_phase       TEXT,
    sensitivity       TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (domain, name)
);

COMMENT ON TABLE concept_registry IS
    'Unified Concept Registry (Type 2 lifecycle governance) - identity and current status per '
    'research recipe. status = recipe validity; per-stratum deployment stays a fact in domain '
    'fact tables (F2 resolution: ensemble_weights holds per-stratum champions, not this table). '
    'redundancy_group displacement is DISABLED for domain=ensemble_strategy (competing weighting '
    'strategies are the normal state, resolved per stratum by the A/B judge).';

CREATE TABLE IF NOT EXISTS concept_gate (
    concept_id                UUID PRIMARY KEY REFERENCES concept_registry(concept_id),
    gate_metric_name          TEXT NOT NULL,
    gate_eval_method          TEXT NOT NULL
        CHECK (gate_eval_method IN ('oos_holdout', 'walk_forward', 'bootstrap_ci')),
    min_gate_metric           DOUBLE PRECISION,
    min_gate_n                DOUBLE PRECISION,
    min_promotion_consecutive INTEGER,
    min_new_observations      DOUBLE PRECISION,
    demotion_threshold        DOUBLE PRECISION,
    decay_floor               DOUBLE PRECISION,
    regime_scope              TEXT,
    fdr_required              BOOLEAN NOT NULL DEFAULT false,
    fdr_alpha                 DOUBLE PRECISION,
    last_eval_metric          DOUBLE PRECISION,
    last_eval_n               DOUBLE PRECISION,
    last_eval_at              TIMESTAMPTZ,
    last_eval_corpus_build_ref TEXT,
    baseline_metric           DOUBLE PRECISION,
    decay_ratio                DOUBLE PRECISION,
    promotion_consecutive     INTEGER NOT NULL DEFAULT 0,
    promotion_eval_metrics    DOUBLE PRECISION[] NOT NULL DEFAULT '{}',
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE concept_gate IS
    'Per-concept promotion/demotion gate PLUS folded last-eval cache (MVP merges '
    'concept_eval_state here, mirroring feature_registry). min_gate_n and min_new_observations '
    'are EFFECTIVE-N floors (invariant 7): overlapping forward returns are autocorrelated, so '
    'raw bar counts never satisfy them. NULL gate columns inherit the per-domain APR default '
    '(alpha.concept_registry.<domain>_* keys). baseline_metric stores the MEAN of '
    'promotion_eval_metrics at promotion (F8 winner''s-curse guard), never the final eval alone.';

COMMENT ON COLUMN concept_gate.fdr_required IS
    'Advisory only. ConceptRegistryService does NOT read this column - BH-FDR enforcement lives '
    'entirely upstream in scripts/ops/alpha/ops_ensemble_weight_compare.py. This flag documents '
    'intent for a given concept''s gate; it does not itself enforce anything.';

CREATE TABLE IF NOT EXISTS concept_transition_log (
    id               BIGSERIAL,
    concept_id       UUID NOT NULL REFERENCES concept_registry(concept_id),
    domain           TEXT NOT NULL,
    name             TEXT NOT NULL,
    from_status      TEXT NOT NULL,
    to_status        TEXT NOT NULL,
    trigger_reason   TEXT NOT NULL
        CHECK (trigger_reason IN (
            'promotion', 'demotion_performance', 'demotion_decay',
            'demotion_redundancy', 'operator_override', 'parent_cascade',
            'candidate_timeout', 'implementation_change', 'genesis_seed'
        )),
    corpus_build_ref TEXT,
    gate_metric      DOUBLE PRECISION,
    gate_n           DOUBLE PRECISION,
    ci_lower         DOUBLE PRECISION,
    decay_ratio      DOUBLE PRECISION,
    regime_scope     TEXT,
    triggered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes            TEXT,
    PRIMARY KEY (id, triggered_at)
);

COMMENT ON TABLE concept_transition_log IS
    'Immutable append-only state-change audit trail. corpus_build_ref (F3) is the '
    'WEIGHT_EPOCH / CorpusManifest identity the deciding evaluation read from - invariant 2''s '
    're-evaluation guard compares against it. Hypertable on triggered_at (same storage engine '
    'as config_history / llm_calls, this project''s other append-only audit trails).';

SELECT create_hypertable(
    'concept_transition_log',
    'triggered_at',
    chunk_time_interval => INTERVAL '3 months',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS concept_transition_log_concept_idx
    ON concept_transition_log (concept_id, triggered_at);

CREATE TABLE IF NOT EXISTS concept_annotation (
    annotation_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id      UUID NOT NULL REFERENCES concept_registry(concept_id),
    annotation_type TEXT NOT NULL CHECK (annotation_type IN (
        'thesis', 'assumption', 'failure_mode', 'observation',
        'open_question', 'implementation', 'reference'
    )),
    content         TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('human', 'ai', 'empirical')),
    confidence      DOUBLE PRECISION CHECK (confidence BETWEEN 0 AND 1),
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS concept_annotation_concept_idx
    ON concept_annotation (concept_id, annotation_type);

COMMENT ON TABLE concept_annotation IS
    'Typed knowledge layer. The gate proves, the annotation explains - never invert: no gate '
    'decision may read annotation content, and no promotion may require an annotation to exist. '
    'source=empirical covers durable loss/win trail rows appended by plan 160-03, distinct from '
    'human-authored thesis/assumption content and any future ai-authored annotation.';

-- APR gate defaults for domain=ensemble_strategy. Per-concept concept_gate columns override
-- these when non-NULL; the service receives them caller-supplied (never hard-coded), same
-- pattern as feature_registry's alpha.feature_registry.min_ic_sharpe_default.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.concept_registry.ensemble_strategy_min_promotion_consecutive',
    'int', '2', 1, 10,
    '[initial_estimate] Consecutive winning A/B evaluation rounds required before a candidate '
    'ensemble_strategy concept promotes to active. Set below the canonical doc''s generic '
    'default of 3 because this domain''s per-round bar is already far stronger than a scalar '
    'p<0.05 gate: non-overlapping CIs (challenger ic_ci_lower > champion ic_ci_upper) AND '
    'walk_forward_stable AND BH-FDR survival across strata. ML learning target: no; operator '
    'may tune.'
),
(
    'alpha.concept_registry.ensemble_strategy_min_new_observations',
    'float', '2000', 100, 100000,
    '[conventional] Evidence-mass re-evaluation floor (F3, invariant 2): a concept may not be '
    're-evaluated until >= this many NEW independent observations (sum of n_independent across '
    'compared strata, delta vs the last recorded eval) have accrued. Mirrors '
    'alpha.decay.recovery_min_observations (2000), the identical standard Phase 143 applies to '
    'feature-recovery evidence. Corpus-advance (corpus_build_ref changed) remains a necessary '
    'but insufficient precondition. ML learning target: no.'
),
(
    'alpha.concept_registry.ensemble_strategy_min_observations',
    'float', '1000', 100, 100000,
    '[initial_estimate] Initial-promotion effective-N observation floor (invariant 7): no '
    'promotion fires until the evaluation carries >= this many independent observations, '
    'regardless of statistical significance. Value from the canonical doc''s Domains table '
    'floor for ensemble_strategy (1,000, per-TF fold minimum), stated against effective N '
    '(n_independent), never raw overlapping bars. ML learning target: no.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
('alpha.concept_registry.ensemble_strategy_min_promotion_consecutive', '2', 1),
('alpha.concept_registry.ensemble_strategy_min_new_observations', '2000', 1),
('alpha.concept_registry.ensemble_strategy_min_observations', '1000', 1)
ON CONFLICT (config_key) DO NOTHING;

-- M-3: config_history's PK is (timestamp, config_key, version); the insert below uses NOW(),
-- so ON CONFLICT can never fire on re-run. Guard each insert with WHERE NOT EXISTS on
-- (config_key, version) so re-applying this migration inserts zero new config_history rows.

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.concept_registry.ensemble_strategy_min_promotion_consecutive', 1, '2',
       'migration_233', 'Concept Registry MVP gate seed (todo 058) [initial_estimate]'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history
    WHERE config_key = 'alpha.concept_registry.ensemble_strategy_min_promotion_consecutive'
      AND version = 1
);

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.concept_registry.ensemble_strategy_min_new_observations', 1, '2000',
       'migration_233', 'Concept Registry MVP evidence-mass floor seed, mirrors '
       'alpha.decay.recovery_min_observations (todo 058, F3) [conventional]'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history
    WHERE config_key = 'alpha.concept_registry.ensemble_strategy_min_new_observations'
      AND version = 1
);

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.concept_registry.ensemble_strategy_min_observations', 1, '1000',
       'migration_233', 'Concept Registry MVP initial-promotion floor seed (todo 058, invariant 7) '
       '[initial_estimate]'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history
    WHERE config_key = 'alpha.concept_registry.ensemble_strategy_min_observations'
      AND version = 1
);

COMMIT;
