-- Migration 311: retire feature_registry and feature_transition_log (todo 118 scope
-- item 4, Phase 170 Plan 08)
--
-- The 2026-08-04 explicit user override of this project's usual rename-not-drop
-- default for retirements applies here: literal DROP TABLE, not a frozen/archived
-- table left behind.
--
-- Numbered 311, not 285 (170-08-PLAN.md's original number) -- 285 was claimed by an
-- unrelated migration (285_feature_ic_scores_history_archive.sql) in the time between
-- this plan being written and executed; 310 was this same session's
-- concept_registry_feature_provenance_backfill.sql.
--
-- PRECONDITIONS ASSERTED BEFORE THIS MIGRATION WAS WRITTEN (not re-derived here --
-- recorded for the audit trail):
--   1. scripts/ops/alpha/ops_concept_feature_migration_verify.py printed VERDICT: PASS
--      (11/11 checks) after migration 310 backfilled provenance metadata for 43
--      features Phase 151 seeded directly into concept_registry, bypassing migration
--      284's batch seed.
--   2. The plan's ORIGINAL evidence bar -- a live, post-Plan-06 ic_engine lifecycle-hook
--      run emitting a registry_dual_write_verified integrity_monitor fact -- was found
--      to be structurally unreachable under the current OOS-pin discipline: every
--      in-sample ic_engine run's training_window_end clamps to alpha.validation.oos_start
--      (pinned 2025-12-24), and that exact window already has decay_cells_flagged/
--      guard_fail_fraction integrity_monitor facts from 2026-07-22, three weeks before
--      Plan 06's dual-write code shipped -- so _run_lifecycle_hook's own idempotency
--      guard (Step 0) short-circuits before ever reaching the dual-write comparison
--      block, on every possible re-run, regardless of run count or data quality.
--      Advancing oos_start to manufacture a fresh window is explicitly flagged
--      elsewhere (docs/plans/OOS-EVAL-PROTOCOL.md) as "a bigger call affecting every
--      future gate, not bundled into this one" -- not appropriate to do casually just
--      to unblock this retirement.
--   3. Explicit user direction (2026-08-10): feature_registry is governance/bookkeeping
--      metadata, not something gating live capital or trading decisions -- the static
--      parity check plus this authorization is sufficient evidence for this retirement,
--      given (2) above makes the original dynamic evidence bar unreachable by
--      construction, not merely inconvenient to clear.
--
-- This DOES relax 170-08-PLAN.md's original "positive artifact, not absence of
-- failure" evidence standard (T-170-24 in that plan's threat model). Recorded plainly
-- rather than silently: the authorizing evidence for THIS retirement is the static
-- parity script's PASS plus explicit human sign-off, not a live dual-write comparison
-- fact. The three RAISE EXCEPTION guards below still apply the same replay/row-count/
-- status-parity checks 170-08-PLAN.md specified, inside the same transaction as the
-- DROP, so an actual data shortfall still refuses the drop mechanically -- only the
-- "was a live comparison run" requirement was relaxed, not the "do the two registries
-- actually agree" requirement.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. PRE-DROP GUARD -- re-assert parity one final time inside the same transaction
--    as the DROP, so a shortfall makes the drop impossible, not merely inadvisable.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    v_transition_log_count INT;
    v_replayed_count INT;
    v_registry_count INT;
    v_concept_count INT;
BEGIN
    SELECT count(*) INTO v_transition_log_count FROM feature_transition_log;
    SELECT count(*) INTO v_replayed_count FROM concept_transition_log
        WHERE domain = 'feature' AND notes LIKE 'Replayed from feature_transition_log%';
    IF v_transition_log_count <> v_replayed_count THEN
        RAISE EXCEPTION 'refusing to drop: transition-log replay incomplete (% source rows, % replayed)',
            v_transition_log_count, v_replayed_count;
    END IF;

    SELECT count(*) INTO v_registry_count FROM feature_registry;
    -- Scoped to metadata->>'migrated_from'='feature_registry' -- concept_registry also
    -- carries 2 migration-284 orphan tombstones (migrated_from='feature_transition_log')
    -- for feature_transition_log rows with no corresponding feature_registry entry;
    -- those never had a feature_registry counterpart and must not be counted here.
    -- Migration 310 backfilled this tag onto all 292 real rows (43 of them, Phase 151's
    -- direct-seed features, previously carried no migrated_from tag at all) -- if this
    -- guard ever fires because a future feature was added to concept_registry without
    -- the tag, that is migration 310's provenance-backfill gap recurring, not a bug in
    -- this guard.
    SELECT count(*) INTO v_concept_count FROM concept_registry
        WHERE domain = 'feature' AND metadata->>'migrated_from' = 'feature_registry';
    IF v_registry_count <> v_concept_count THEN
        RAISE EXCEPTION 'refusing to drop: registry row-count parity broken (feature_registry=%, concept_registry=%)',
            v_registry_count, v_concept_count;
    END IF;

    IF EXISTS (
        SELECT 1 FROM feature_registry fr
        JOIN concept_registry cr ON cr.domain = 'feature' AND cr.name = fr.feature_name
        WHERE cr.status IS DISTINCT FROM fr.status
    ) THEN
        RAISE EXCEPTION 'refusing to drop: status parity broken between feature_registry and concept_registry';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. DROP the tables. No IF EXISTS, no CASCADE -- a missing table or an
--    unexpected dependent object should fail loudly, since guard (1) above
--    already proves the expected state.
-- ---------------------------------------------------------------------------

DROP TABLE feature_transition_log;
DROP TABLE feature_registry;

-- ---------------------------------------------------------------------------
-- 3. DROP the orphaned trigger function. The trigger itself
--    (trg_cascade_parent_deprecation) drops with its table above; the function
--    does not. Its generalized replacement, fn_cascade_concept_parent_deprecation
--    (migration 283), is unaffected.
-- ---------------------------------------------------------------------------

DROP FUNCTION IF EXISTS fn_cascade_parent_deprecation();

-- ---------------------------------------------------------------------------
-- 4. APR key disposition. grep -rn "alpha.feature_registry" src/ services/
--    scripts/ tests/ (excluding the pinned integration baseline fixture, a
--    historical snapshot never edited) found zero live consumers -- the sole
--    reader, FeatureRegistryService.get_ic_sharpe_gate, was deleted as dead
--    code in the commit landing this retirement's Task 1. DELETE, not rename.
-- ---------------------------------------------------------------------------

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), cs.config_key, cs.version, cs.config_value, 'migration_311',
    'Removed: sole consumer (FeatureRegistryService.get_ic_sharpe_gate) deleted as dead '
    'code, feature_registry retired (Phase 170, todo 118 scope item 4).'
FROM config_state cs
WHERE cs.config_key LIKE 'alpha.feature_registry.%'
  AND NOT EXISTS (
      SELECT 1 FROM config_history ch
      WHERE ch.config_key = cs.config_key AND ch.changed_by = 'migration_311'
  );

DELETE FROM config_state WHERE config_key LIKE 'alpha.feature_registry.%';
DELETE FROM config_schema WHERE config_key LIKE 'alpha.feature_registry.%';

COMMIT;
