-- Migration 533: feature composition replaces the tier taxonomy; register the HMM columns
-- (phase 187 plan 12, todo 459; unified design 10.2.5, 14.6 item 6).
--
-- concept_registry.metadata->>'tier' (0_atomic, 1_interaction, 2_theory) becomes
-- metadata->>'composition' (base, interaction): 0_atomic and 2_theory rows are base
-- measurements from a name's own bars or the timestamp, 1_interaction rows are built from
-- other features. The CVR namespace tier is replaced by composition. The two deprecated
-- flag rows with no tier (new_high_flag, new_low_flag) stay without the key.
--
-- Eleven numeric feature_vectors columns (the HMM probability, churn and volatility columns
-- the regime writer owns) have no concept_registry row. They are registered active, composition
-- base, with the concept_gate row of their sibling hmm_entropy. Their version 1 recipes are
-- written by the S6 ledger command scripts/research/seed_hmm_recipes.py, not here.
--
-- Counts recorded 2026-10-28 (the migration raises if they differ when it runs):
--   tier 0_atomic 169, 1_interaction 25, 2_theory 106, no tier 2; CVR tier 3 codes.

BEGIN;

SET LOCAL lock_timeout = '30s';
LOCK TABLE concept_registry, concept_gate, controlled_vocabulary IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE
    got record;
BEGIN
    SELECT
        count(*) FILTER (WHERE metadata->>'tier' = '0_atomic') AS atomic,
        count(*) FILTER (WHERE metadata->>'tier' = '1_interaction') AS interaction,
        count(*) FILTER (WHERE metadata->>'tier' = '2_theory') AS theory,
        count(*) FILTER (WHERE NOT metadata ? 'tier') AS untiered
    INTO got FROM concept_registry WHERE domain = 'feature';
    IF (got.atomic, got.interaction, got.theory, got.untiered) <> (169, 25, 106, 2) THEN
        RAISE EXCEPTION 'migration 533: feature tier counts changed: %', got;
    END IF;
    IF (SELECT count(*) FROM concept_registry
        WHERE domain = 'feature' AND name IN (
            'hmm_prob_trending_up', 'hmm_prob_trending_down', 'hmm_prob_ranging', 'hmm_churn',
            'hmm_vol_regime_prob', 'hmm_vol_prob_calm', 'hmm_vol_prob_elevated',
            'hmm_vol_prob_turbulent', 'hmm_vol_entropy', 'hmm_vol_duration', 'hmm_vol_churn')) <> 0 THEN
        RAISE EXCEPTION 'migration 533: an HMM column is already registered';
    END IF;
    IF (SELECT count(*) FROM concept_gate g JOIN concept_registry r USING (concept_id)
        WHERE r.domain = 'feature' AND r.name = 'hmm_entropy') <> 1 THEN
        RAISE EXCEPTION 'migration 533: hmm_entropy has no gate row to copy';
    END IF;
END $$;

UPDATE concept_registry
SET metadata = (metadata - 'tier') || jsonb_build_object(
        'composition', CASE metadata->>'tier' WHEN '1_interaction' THEN 'interaction' ELSE 'base' END)
WHERE domain = 'feature' AND metadata ? 'tier';

DELETE FROM controlled_vocabulary WHERE namespace = 'tier';
INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
    ('composition', 'base', 'Base',
     'A measurement computed from a name''s own bars or the timestamp', 1),
    ('composition', 'interaction', 'Interaction',
     'A feature built from other features', 2);

WITH new_features (name, description) AS (
    VALUES
    ('hmm_prob_trending_up', 'HMM trending-up state probability'),
    ('hmm_prob_trending_down', 'HMM trending-down state probability'),
    ('hmm_prob_ranging', 'HMM ranging state probability'),
    ('hmm_churn', 'HMM state changes over the churn window'),
    ('hmm_vol_regime_prob', 'HMM volatility regime posterior probability'),
    ('hmm_vol_prob_calm', 'HMM calm volatility state probability'),
    ('hmm_vol_prob_elevated', 'HMM elevated volatility state probability'),
    ('hmm_vol_prob_turbulent', 'HMM turbulent volatility state probability'),
    ('hmm_vol_entropy', 'HMM volatility state distribution entropy'),
    ('hmm_vol_duration', 'Bars in current HMM volatility regime'),
    ('hmm_vol_churn', 'HMM volatility state changes over the churn window')
)
INSERT INTO concept_registry
    (domain, name, description, status, enabled, metadata, added_phase, group_name)
SELECT 'feature', name, description, 'active', true,
       jsonb_build_object('composition', 'base', 'apr_namespace', 'feature.',
                          'registered_by', 'migration_533'),
       '187', 'regime'
FROM new_features;

INSERT INTO concept_gate (concept_id, gate_metric_name, gate_eval_method, min_gate_n,
                          fdr_required, fdr_alpha)
SELECT r.concept_id, g.gate_metric_name, g.gate_eval_method, g.min_gate_n,
       g.fdr_required, g.fdr_alpha
FROM concept_registry r
CROSS JOIN (SELECT gg.* FROM concept_gate gg JOIN concept_registry s USING (concept_id)
            WHERE s.domain = 'feature' AND s.name = 'hmm_entropy') g
WHERE r.domain = 'feature' AND r.metadata->>'registered_by' = 'migration_533';

DO $$
BEGIN
    IF (SELECT count(*) FROM concept_registry
        WHERE domain = 'feature' AND metadata ? 'tier') <> 0 THEN
        RAISE EXCEPTION 'migration 533: a feature row still carries tier';
    END IF;
    IF (SELECT count(*) FROM concept_registry
        WHERE domain = 'feature' AND metadata->>'registered_by' = 'migration_533') <> 11 THEN
        RAISE EXCEPTION 'migration 533: expected 11 registered HMM columns';
    END IF;
END $$;

COMMIT;
