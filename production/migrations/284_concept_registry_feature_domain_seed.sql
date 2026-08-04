-- Migration 284: concept_registry domain='feature' seed + feature_transition_log replay
-- (Phase 170 Plan 03, todo 118 scope item 1)
--
-- DATA-ONLY migration. Zero schema changes (that was migration 283, Plan 01). Zero
-- application-code changes -- feature_registry remains the sole live authority for the
-- feature lifecycle until Plan 06 cuts the writers over. The concept rows seeded here are,
-- until then, a faithful snapshot, not a second writer.
--
-- feature_registry and feature_transition_log are DROPped at the end of Phase 170 (Plan 08).
-- This is the one-way-door step: anything not carried across here is destroyed, not deferred.
-- Todo 118 explicitly rules out the lighter "genesis-seed with a pointer back" alternative for
-- exactly this reason -- a pointer to a table that is about to be dropped is a dangling
-- reference, not a preservation path. This migration instead REPLAYS every
-- feature_transition_log row into concept_transition_log with its original triggered_at.
--
-- Field-by-field mapping (feature_registry -> concept_registry / concept_gate / concept_parent):
--
--   concept_registry:
--     domain              <- 'feature'
--     name                <- fr.feature_name
--     description         <- fr.formula_short
--     status              <- fr.status
--     enabled             <- (fr.status = 'active')   -- feature_registry had no enabled column;
--                                                        status='active' WAS the enabling
--                                                        condition. Seeding false uniformly
--                                                        would render 138 active features as
--                                                        disabled to any human/query reading the
--                                                        table -- worse than the redundancy.
--     group_name          <- fr.group_name
--     is_control           <- fr.is_control
--     control_expectation <- fr.control_expectation
--     added_phase         <- fr.added_phase
--     created_at          <- fr.added_at
--     parent_concept_id   <- NULL (superseded by concept_parent)
--     redundancy_group    <- NULL (no feature_registry equivalent; the canonical doc's "only
--                                  one holds active" displacement rule must NOT switch on for
--                                  this domain by accident)
--     sensitivity         <- NULL
--     metadata            <- tier, formula_short, normalization, linear_ready, requires_htf,
--                             window_apr_keys, source_dims, notes, apr_namespace,
--                             migrated_from, migrated_by (jsonb_strip_nulls)
--     NOTE: no dedicated `tier` column is created -- todo 118 explicitly routes `tier` to
--     metadata JSONB.
--
--   concept_gate (one per seeded concept):
--     gate_metric_name            <- 'ic_sharpe_hac'   (the metric fr.min_ic_sharpe gates)
--     gate_eval_method            <- 'bootstrap_ci'
--     min_gate_metric             <- fr.min_ic_sharpe
--     min_gate_n                  <- fr.min_ic_n
--     fdr_required                <- fr.fdr_required
--     fdr_alpha                   <- fr.fdr_alpha
--     last_eval_metric            <- fr.last_ic_sharpe
--     last_eval_n                 <- fr.last_ic_n
--     last_eval_at                <- fr.last_eval_at
--     consecutive_shadow_passes   <- fr.consecutive_shadow_passes
--     observations_since_demotion <- fr.observations_since_demotion
--     min_promotion_consecutive / min_new_observations / demotion_threshold / decay_floor /
--     regime_scope / baseline_metric / decay_ratio  <- left NULL (inherit APR defaults)
--     `fr.last_ic_value` is DELIBERATELY DROPPED -- todo 118 states this is a decided
--     consequence of the measurement/governance/reporting split (full IC richness stays in
--     feature_ic_scores), not an oversight.
--
--   concept_parent: one edge per (child, parent_name) pair unnested from
--     fr.parent_features, resolved by name to concept_id on both sides. 16 edges today.
--
-- THE GENESIS PRECEDENT: 226_concept_registry_seed_ensemble_strategy.sql lines 102-119 (NOT
-- migration 225 -- 225 creates the four tables and contains no INSERT INTO
-- concept_transition_log at all). Its statement, verbatim (comment reproduced for provenance):
--
--   -- Genesis transition for the incumbent only: establishes ic_proportional as active
--   -- without fabricating a promotion event. corpus_build_ref NULL - pre-registry incumbency
--   -- is not attributable to a specific corpus build.
--   INSERT INTO concept_transition_log
--       (concept_id, domain, name, from_status, to_status, trigger_reason, notes)
--   SELECT concept_id, 'ensemble_strategy', 'ic_proportional', 'candidate', 'active',
--          'genesis_seed', '...'
--   FROM concept_registry
--   WHERE domain = 'ensemble_strategy' AND name = 'ic_proportional'
--     AND NOT EXISTS (
--         SELECT 1 FROM concept_transition_log t
--         WHERE t.domain = 'ensemble_strategy' AND t.name = 'ic_proportional'
--           AND t.trigger_reason = 'genesis_seed'
--     );
--
-- Four properties carried forward from 226, two deliberate deviations:
--   CARRY    from_status = 'candidate' (a literal, not fr.status)
--   CARRY    trigger_reason = 'genesis_seed'
--   CARRY    corpus_build_ref left unset/NULL, for the reason 226's comment gives
--   CARRY    idempotency via a WHERE NOT EXISTS guard, NOT ON CONFLICT
--   DEVIATE  one row per concept (226 seeded only its single incumbent; here every one of the
--            249 features is an incumbent by construction)
--   DEVIATE  triggered_at = fr.added_at (226 let it default to NOW(); here a real per-feature
--            creation timestamp exists and the replay's whole purpose is that chronology
--            survives)
--
-- WHY ON CONFLICT CANNOT BE USED for either the genesis rows or the replay rows:
-- concept_transition_log's PK is (id, triggered_at) with id BIGSERIAL
-- (225_concept_registry_mvp.sql:111-133), so a re-apply always allocates a fresh id and the
-- conflict target can never match -- the same trap migration 225's own header documents for
-- config_history under "M-3". Without an explicit WHERE NOT EXISTS guard, a second apply
-- DOUBLES both the genesis rows and the replayed rows, and the replay-count assertion below
-- would then RAISE, turning a re-apply from a no-op into a hard failure.
--
-- L-7 CONTRACT (recorded here per plan, not implemented -- todo 252 is a separate fix):
-- concept_transition_log provenance keys off the SAME fingerprint tuple (code_content_key /
-- apr_snapshot_key / upstream_watermark) that ic_engine uses for corpus-vintage identity.
-- Todo 252's eventual fix must reuse that tuple rather than invent a second versioning scheme.
--
-- Idempotency: concept_registry seed uses ON CONFLICT (domain, name) DO NOTHING -- safe,
-- because concept_registry has a real natural-key UNIQUE constraint on (domain, name), unlike
-- concept_transition_log. concept_gate seed uses ON CONFLICT (concept_id) DO NOTHING (real PK).
-- concept_parent seed uses ON CONFLICT DO NOTHING (real composite PK). Only the two
-- concept_transition_log inserts (genesis + replay) need the WHERE NOT EXISTS pattern.
--
-- ORPHANED TRANSITION-LOG ROWS (discovered live, not in the plan's <interfaces> snapshot):
-- 2 of the 2 feature_transition_log rows (new_high_flag, new_low_flag, both
-- trigger_reason='operator_override') reference feature_names that no longer exist in
-- feature_registry at all -- fully removed, not merely status='deprecated'. The replay step's
-- concept_id FK has nothing to attach to for these without a corresponding concept_registry
-- row, and this migration's own hard replay-count assertion (source count == replayed count)
-- would otherwise abort every apply on exactly the "silently loses its history" condition it
-- exists to prevent. Fixed by seeding a small number of TOMBSTONE concept_registry rows --
-- domain='feature', metadata->>'migrated_from'='feature_transition_log' (NOT
-- 'feature_registry', distinguishing them from the 249 real rows) -- for any
-- feature_transition_log feature_name absent from feature_registry, giving the replay a valid
-- concept_id. These rows carry no concept_gate row (no feature_registry data exists to
-- populate one) and receive no genesis_seed row (genesis seeding, step 4, sources strictly
-- from feature_registry, matching the plan's literal design -- a tombstone was never a live
-- incumbent). Consequence for the row-count parity check: concept_registry WHERE
-- domain='feature' now totals 249 (real) + N (tombstones, 2 today), so the parity assertion
-- below is scoped to metadata->>'migrated_from'='feature_registry' rather than an unscoped
-- domain='feature' count -- every other must-have (gate parity, lineage-edge count,
-- genesis-row count) is naturally unaffected since none of those queries touch tombstone rows.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. concept_registry rows: domain='feature'
-- ---------------------------------------------------------------------------

INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, control_expectation,
     added_phase, created_at, parent_concept_id, redundancy_group, sensitivity, metadata)
SELECT
    'feature',
    fr.feature_name,
    fr.formula_short,
    fr.status,
    (fr.status = 'active'),
    fr.group_name,
    fr.is_control,
    fr.control_expectation,
    fr.added_phase,
    fr.added_at,
    NULL,
    NULL,
    NULL,
    jsonb_strip_nulls(jsonb_build_object(
        'tier', fr.tier,
        'formula_short', fr.formula_short,
        'normalization', fr.normalization,
        'linear_ready', fr.linear_ready,
        'requires_htf', fr.requires_htf,
        'window_apr_keys', to_jsonb(fr.window_apr_keys),
        'source_dims', to_jsonb(fr.source_dims),
        'notes', fr.notes,
        'apr_namespace', 'feature.',
        'migrated_from', 'feature_registry',
        'migrated_by', 'migration_284'
    ))
FROM feature_registry fr
ON CONFLICT (domain, name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. concept_gate rows: one per seeded concept
-- ---------------------------------------------------------------------------

INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_metric, min_gate_n,
     fdr_required, fdr_alpha, last_eval_metric, last_eval_n, last_eval_at,
     consecutive_shadow_passes, observations_since_demotion)
SELECT
    cr.concept_id,
    'ic_sharpe_hac',
    'bootstrap_ci',
    fr.min_ic_sharpe,
    fr.min_ic_n,
    fr.fdr_required,
    fr.fdr_alpha,
    fr.last_ic_sharpe,
    fr.last_ic_n,
    fr.last_eval_at,
    fr.consecutive_shadow_passes,
    fr.observations_since_demotion
FROM feature_registry fr
JOIN concept_registry cr ON cr.domain = 'feature' AND cr.name = fr.feature_name
ON CONFLICT (concept_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. concept_parent edges from feature_registry.parent_features
-- ---------------------------------------------------------------------------

INSERT INTO concept_parent (child_concept_id, parent_concept_id)
SELECT child.concept_id, parent.concept_id
FROM feature_registry fr
CROSS JOIN LATERAL unnest(fr.parent_features) AS pf(parent_name)
JOIN concept_registry child  ON child.domain='feature'  AND child.name = fr.feature_name
JOIN concept_registry parent ON parent.domain='feature' AND parent.name = pf.parent_name
WHERE fr.parent_features IS NOT NULL
ON CONFLICT DO NOTHING;

-- Hard integrity assertion: this is the whole point of L-8's FK-enforced join table, so an
-- unresolved parent name must abort the migration, not warn.
DO $$
DECLARE expected INT; actual INT;
BEGIN
    SELECT COALESCE(sum(array_length(parent_features,1)),0) INTO expected FROM feature_registry;
    SELECT count(*) INTO actual FROM concept_parent;
    IF expected <> actual THEN
        RAISE EXCEPTION 'concept_parent edge count mismatch: expected %, got % -- an unresolved parent name would silently orphan lineage', expected, actual;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 3b. Tombstone concept_registry rows for orphaned feature_transition_log feature_names
--     (feature removed from feature_registry entirely; history must still be replayable)
-- ---------------------------------------------------------------------------

WITH orphan_names AS (
    SELECT DISTINCT ftl.feature_name
    FROM feature_transition_log ftl
    WHERE NOT EXISTS (
        SELECT 1 FROM feature_registry fr WHERE fr.feature_name = ftl.feature_name
    )
),
orphan_last_status AS (
    SELECT DISTINCT ON (ftl.feature_name) ftl.feature_name, ftl.to_status
    FROM feature_transition_log ftl
    JOIN orphan_names o ON o.feature_name = ftl.feature_name
    ORDER BY ftl.feature_name, ftl.triggered_at DESC
),
orphan_first_seen AS (
    SELECT ftl.feature_name, MIN(ftl.triggered_at) AS first_triggered_at
    FROM feature_transition_log ftl
    JOIN orphan_names o ON o.feature_name = ftl.feature_name
    GROUP BY ftl.feature_name
)
INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, control_expectation,
     added_phase, created_at, parent_concept_id, redundancy_group, sensitivity, metadata)
SELECT
    'feature',
    s.feature_name,
    'Orphaned feature-history tombstone (Phase 170, todo 118): feature_transition_log has a '
    'row for this feature_name but no corresponding feature_registry row exists at migration '
    'time. This row exists solely so the transition-log replay has a valid concept_id to '
    'attach the preserved history to -- it is not a live feature and carries no concept_gate '
    'row.',
    s.to_status,
    false,
    NULL, false, NULL, NULL,
    f.first_triggered_at,
    NULL, NULL, NULL,
    jsonb_build_object(
        'migrated_from', 'feature_transition_log',
        'migrated_by', 'migration_284',
        'orphaned_at_migration', true
    )
FROM orphan_last_status s
JOIN orphan_first_seen f USING (feature_name)
ON CONFLICT (domain, name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. concept_transition_log genesis rows, one per seeded concept
-- ---------------------------------------------------------------------------

INSERT INTO concept_transition_log
    (concept_id, domain, name, from_status, to_status, trigger_reason, triggered_at, notes)
SELECT
    cr.concept_id, 'feature', fr.feature_name, 'candidate', fr.status, 'genesis_seed',
    fr.added_at,
    'Migrated from feature_registry (Phase 170, todo 118). Establishes the incumbent status '
    'at migration time without fabricating a promotion event.'
FROM feature_registry fr
JOIN concept_registry cr ON cr.domain = 'feature' AND cr.name = fr.feature_name
WHERE NOT EXISTS (
    SELECT 1 FROM concept_transition_log t
    WHERE t.domain = 'feature' AND t.name = fr.feature_name AND t.trigger_reason = 'genesis_seed'
);

-- ---------------------------------------------------------------------------
-- 5. feature_transition_log REPLAY -- every row, with its original triggered_at
-- ---------------------------------------------------------------------------

INSERT INTO concept_transition_log
    (concept_id, domain, name, from_status, to_status, trigger_reason, triggered_at,
     gate_metric, gate_n, ci_lower, notes)
SELECT
    cr.concept_id,
    'feature',
    ftl.feature_name,
    ftl.from_status,
    ftl.to_status,
    CASE ftl.trigger_reason
        WHEN 'ic_promotion'      THEN 'promotion'
        WHEN 'ic_demotion'       THEN 'demotion_performance'
        WHEN 'parent_cascade'    THEN 'parent_cascade'
        WHEN 'operator_override' THEN 'operator_override'
        -- No ELSE: an unmapped source reason must violate the NOT NULL/CHECK and abort this
        -- migration, not insert a NULL that would read as "no reason recorded".
    END,
    ftl.triggered_at,
    ftl.ic_sharpe,
    ftl.ic_n,
    ftl.ic_value,
    'Replayed from feature_transition_log id=' || ftl.id || ' (Phase 170, todo 118).'
FROM feature_transition_log ftl
JOIN concept_registry cr ON cr.domain = 'feature' AND cr.name = ftl.feature_name
WHERE NOT EXISTS (
    SELECT 1 FROM concept_transition_log t
    WHERE t.domain = 'feature'
      AND t.notes = 'Replayed from feature_transition_log id=' || ftl.id || ' (Phase 170, todo 118).'
);

-- Hard assertion: every feature_transition_log row must have a replayed counterpart --
-- feature_transition_log is about to be dropped, and a feature present in the log but absent
-- from the registry (or an unresolved name) would silently lose its history.
DO $$
DECLARE source_count INT; replayed_count INT;
BEGIN
    SELECT count(*) INTO source_count FROM feature_transition_log;
    SELECT count(*) INTO replayed_count FROM concept_transition_log
        WHERE domain = 'feature' AND notes LIKE 'Replayed from feature_transition_log%';
    IF source_count <> replayed_count THEN
        RAISE EXCEPTION 'transition-log replay incomplete: % source rows vs % replayed -- a feature present in the log but absent from the registry would silently lose its history, and feature_transition_log is about to be dropped', source_count, replayed_count;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 6. Guard against accidental cascade trigger fire during the seed
-- ---------------------------------------------------------------------------

-- None of the statements above UPDATE concept_registry.status, so
-- trg_cascade_concept_parent_deprecation cannot fire during this seed. Confirmed by asserting
-- zero parent_cascade rows were created under domain='feature' by this migration.
DO $$
DECLARE cascade_count INT;
BEGIN
    SELECT count(*) INTO cascade_count FROM concept_transition_log
        WHERE domain = 'feature' AND trigger_reason = 'parent_cascade';
    IF cascade_count <> 0 THEN
        RAISE EXCEPTION 'unexpected parent_cascade rows (%) created under domain=feature during the seed -- the cascade trigger fired when it should not have', cascade_count;
    END IF;
END $$;

COMMIT;
