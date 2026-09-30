-- Migration 409: concept_evaluation.guard_status is set exactly on feature_ic rows
-- (phase 186 debt closure, pass C9; the CHECK the migration 389 review asked for)
--
-- Migration 389 made guard_status nullable and added evidence_kind. The intended shape is that
-- the IC-era regime-shift guard verdict is present on every feature_ic row and absent on every
-- data_quality row (services/feature_lifecycle.py writes no guard_status). Nothing enforced it,
-- so a writer bug could store a feature_ic row without a verdict or a data_quality row with a
-- fabricated one. The CHECK enforces it.
--
-- Guarded: the migration refuses, changing nothing, if any live row violates the rule.
-- concept_evaluation is a plain table, not a hypertable: no VACUUM step applies.

BEGIN;

DO $$
DECLARE
    n_violations bigint;
BEGIN
    SELECT count(*) INTO n_violations
      FROM concept_evaluation
     WHERE (evidence_kind = 'feature_ic') <> (guard_status IS NOT NULL);
    IF n_violations > 0 THEN
        RAISE EXCEPTION
            'concept_evaluation has % rows where guard_status presence does not match evidence_kind = feature_ic; refusing to add the CHECK',
            n_violations;
    END IF;
END $$;

ALTER TABLE concept_evaluation
    DROP CONSTRAINT IF EXISTS concept_evaluation_guard_status_matches_kind;
ALTER TABLE concept_evaluation
    ADD CONSTRAINT concept_evaluation_guard_status_matches_kind
    CHECK ((evidence_kind = 'feature_ic') = (guard_status IS NOT NULL));

COMMENT ON CONSTRAINT concept_evaluation_guard_status_matches_kind ON concept_evaluation IS
    'guard_status is present exactly on feature_ic rows (IC-era guard verdict) and NULL on data_quality rows.';

COMMIT;
