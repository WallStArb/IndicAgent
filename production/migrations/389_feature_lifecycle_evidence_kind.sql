-- Migration 389: concept_evaluation drops its guard_status requirement and gains evidence_kind
-- (phase 186 debt closure, pass B1)
--
-- (a) guard_status was the regime-shift guard verdict of the IC-era lifecycle. The data-quality
--     rule (186-09) has no guard and used to write the literal 'ok' only to satisfy the
--     NOT NULL and CHECK of migration 357. The column becomes nullable (the CHECK already
--     admits NULL): the historical IC-era rows keep their recorded verdicts (never drop data
--     that could contain signal), and new rows leave it unset.
-- (b) evidence_kind names what a row measured, replacing the detail ? 'per_tf' key test that
--     told data-quality rows from IC-era rows. Existing rows are labeled from that same test.
--     Every row must be in domain 'feature' (the only domain either writer used); anything
--     else has unknown provenance and the migration refuses.
-- (c) One APR key, infra.feature_lifecycle.max_concurrent_tfs (was the module constant
--     _MAX_CONCURRENT_TFS).
--
-- concept_evaluation is a plain table, not a hypertable: no VACUUM step applies.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM concept_evaluation WHERE domain <> 'feature') THEN
        RAISE EXCEPTION 'concept_evaluation has rows outside domain feature; refusing to label them';
    END IF;
END $$;

ALTER TABLE concept_evaluation ALTER COLUMN guard_status DROP NOT NULL;

ALTER TABLE concept_evaluation ADD COLUMN IF NOT EXISTS evidence_kind text;
UPDATE concept_evaluation
   SET evidence_kind = CASE WHEN detail ? 'per_tf' THEN 'data_quality' ELSE 'feature_ic' END
 WHERE evidence_kind IS NULL;
ALTER TABLE concept_evaluation ALTER COLUMN evidence_kind SET NOT NULL;
ALTER TABLE concept_evaluation DROP CONSTRAINT IF EXISTS concept_evaluation_evidence_kind_check;
ALTER TABLE concept_evaluation ADD CONSTRAINT concept_evaluation_evidence_kind_check
    CHECK (evidence_kind = ANY (ARRAY['feature_ic', 'data_quality']));

COMMENT ON COLUMN concept_evaluation.guard_status IS
    'IC-era regime-shift guard verdict; NULL on data_quality rows (no guard applies).';
COMMENT ON COLUMN concept_evaluation.evidence_kind IS
    'What the row measured: feature_ic (IC-era, retired) or data_quality (services/feature_lifecycle.py, 186-09).';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    ('infra.feature_lifecycle.max_concurrent_tfs', 'int', '3', 1, 10,
     '[initial_estimate] Timeframes feature_lifecycle measures at once; each holds one pool connection for aggregate queries over the feature_vectors hypertable (BaseBatch pool has ten). Cannot move a verdict. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.feature_lifecycle.max_concurrent_tfs', '3', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'infra.feature_lifecycle.max_concurrent_tfs', 1, '3', 'migration',
        'phase 186 debt closure B1: initial value [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
