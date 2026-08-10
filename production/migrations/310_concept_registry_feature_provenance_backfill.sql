-- Migration 310: backfill concept_registry provenance for Phase 151's 43 features
-- (Phase 170 Plan 08 re-check, todo 118 closure)
--
-- DATA-ONLY migration. Zero schema changes.
--
-- Context: migration 284 (Phase 170 Plan 03) seeded concept_registry's domain='feature' rows
-- from feature_registry's 249-row snapshot at the time, tagging each row
-- metadata->>'migrated_from'='feature_registry'. Phase 151 (shipped 2026-08-05, after migration
-- 284) added 43 new features directly to BOTH feature_registry (292 rows total now) and
-- concept_registry (294 domain='feature' rows: 249 migrated + 2 orphan tombstones + these 43),
-- but the 43 concept_registry rows were created without the migrated_from/migrated_by metadata
-- tag and without a genesis_seed concept_transition_log row.
--
-- Verified live before writing this migration (not assumed): all 43 have matching status
-- ('active'='active' for every one), enabled=true, a concept_gate row, and correct
-- concept_parent lineage edges against their feature_registry counterparts -- this is a
-- provenance/audit-trail gap, not a governance-data gap. `scripts/ops/alpha/
-- ops_concept_feature_migration_verify.py`'s row_count_parity/name_set_parity checks scope to
-- metadata->>'migrated_from'='feature_registry' (line 63's _REAL_ROW_SCOPE), so these 43 rows
-- were invisible to that check and reported as a false "only_in_feature_registry" gap.
--
-- Fix: (1) tag the 43 rows' metadata to reflect their real provenance, distinguishing them from
-- migration 284's batch by migrated_by; (2) add a genesis_seed transition-log row per concept,
-- mirroring migration 284's step 4 pattern, so these 43 have the same audit-trail completeness
-- as the original 249 before feature_registry is retired.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Backfill metadata->>'migrated_from'/'migrated_by' on the 43 Phase-151-seeded rows
-- ---------------------------------------------------------------------------

UPDATE concept_registry cr
SET metadata = cr.metadata || jsonb_build_object(
    'migrated_from', 'feature_registry',
    'migrated_by', 'migration_310_provenance_backfill'
)
WHERE cr.domain = 'feature'
  AND (cr.metadata->>'migrated_from' IS NULL OR cr.metadata->>'migrated_from' = '')
  AND EXISTS (SELECT 1 FROM feature_registry fr WHERE fr.feature_name = cr.name);

-- ---------------------------------------------------------------------------
-- 2. genesis_seed transition-log rows for the same 43 concepts
-- ---------------------------------------------------------------------------

INSERT INTO concept_transition_log
    (concept_id, domain, name, from_status, to_status, trigger_reason, triggered_at, notes)
SELECT
    cr.concept_id, 'feature', cr.name, 'candidate', cr.status, 'genesis_seed', cr.created_at,
    'Backfilled genesis row (migration 310): concept was seeded directly into concept_registry '
    'when Phase 151 shipped (2026-08-05), bypassing migration 284''s batch seed and its genesis '
    'row. This establishes the same incumbent-status record migration 284 gave the original 249 '
    'features, without fabricating a promotion event.'
FROM concept_registry cr
WHERE cr.domain = 'feature'
  AND cr.metadata->>'migrated_by' = 'migration_310_provenance_backfill'
  AND NOT EXISTS (
      SELECT 1 FROM concept_transition_log t
      WHERE t.domain = 'feature' AND t.name = cr.name
  );

-- Hard assertion: every row this migration tagged must now have exactly one transition-log row.
DO $$
DECLARE tagged_count INT; genesis_count INT;
BEGIN
    SELECT count(*) INTO tagged_count FROM concept_registry
        WHERE domain = 'feature' AND metadata->>'migrated_by' = 'migration_310_provenance_backfill';
    SELECT count(*) INTO genesis_count FROM concept_transition_log t
        JOIN concept_registry cr ON cr.concept_id = t.concept_id
        WHERE cr.domain = 'feature'
          AND cr.metadata->>'migrated_by' = 'migration_310_provenance_backfill'
          AND t.trigger_reason = 'genesis_seed';
    IF tagged_count <> 43 THEN
        RAISE EXCEPTION 'expected exactly 43 rows tagged by this migration, got %; re-check the Phase 151 provenance gap before assuming this migration is safe to re-apply elsewhere', tagged_count;
    END IF;
    IF tagged_count <> genesis_count THEN
        RAISE EXCEPTION 'genesis-row backfill incomplete: % rows tagged but only % genesis rows created', tagged_count, genesis_count;
    END IF;
END $$;

COMMIT;
