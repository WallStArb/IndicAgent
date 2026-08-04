-- Migration 283: concept_registry/concept_gate schema gaps vs feature_registry (Phase 170
-- Plan 01, todo 118 items L-5/L-8/L-9/L-10)
--
-- feature_registry is DROPped at the end of Phase 170 once domain='feature' rows are folded
-- into concept_registry (Plan 03). Anything not ported here is destroyed, not deferred --
-- these are one-way-door gaps, closed structurally BEFORE any feature row is seeded. This
-- migration seeds ZERO domain='feature' rows and changes ZERO application code; that is
-- Plan 03's job. Existing domain='ensemble_strategy' rows (5 in concept_registry, 5 in
-- concept_gate) are untouched.
--
-- L-8 (lineage): feature_registry.parent_features is a bare TEXT[] of feature names -- no FK,
-- no referential integrity, and (today) always exactly 2 entries per non-NULL row, i.e.
-- multi-parent lineage that a single parent_concept_id FK column could never express. Fixed
-- via a proper child/parent join table (concept_parent) with FK constraints on BOTH sides and
-- a self-edge CHECK. concept_registry.parent_concept_id (single-parent) is NOT dropped here --
-- domain='ensemble_strategy' may still reference it and dropping it is out of scope for this
-- phase; the feature domain uses concept_parent exclusively going forward.
--
-- L-8 cycle guard: the cascade trigger added below (L-9) is deliberately recursive (an inner
-- UPDATE re-fires the same trigger per touched child), and recursion over a graph is only safe
-- if that graph has no cycles. fn_concept_parent_cycle_guard() enforces that as a real
-- constraint on both the INSERT and UPDATE paths of concept_parent, not merely an assumption.
--
--   KNOWN CONCURRENCY LIMIT (recorded here and in the guard's own comment; also called out in
--   tests/integration/test_concept_parent_lineage.py's module docstring): the recursive check
--   in fn_concept_parent_cycle_guard() reads only COMMITTED edges. Two concurrent transactions
--   that each insert one leg of a two-edge cycle (A->B in one, B->A in the other) can therefore
--   both pass and both commit, because neither sees the other's uncommitted row. Closing that
--   would require SERIALIZABLE isolation or a table-level advisory lock on every edge write.
--   Neither is warranted in this phase: concept_parent's ONLY writer is migration 284, which
--   inserts all 16 edges inside a single transaction, and no runtime service writes lineage
--   edges. CONTRACT for any future writer: any component that writes concept_parent outside a
--   single-transaction seed MUST take pg_advisory_xact_lock() on a fixed key covering the table
--   first, or the cycle guard is best-effort for that writer.
--
-- L-9 (cascade): feature_registry's fn_cascade_parent_deprecation() (AFTER UPDATE OF status,
-- tier='1_interaction'-scoped) is generalized here to fn_cascade_concept_parent_deprecation(),
-- scoped by the concept_parent join table instead of a tier filter, so cascade works across
-- every domain automatically. Two real bugs in the live function -- and in todo 118's proposed
-- near-literal translation of it -- are fixed in this replacement, NOT carried forward:
--   BUG-1 (ordering): the live function runs the audit INSERT AFTER the UPDATE. Todo 118's
--     proposed version additionally filters the INSERT on `WHERE cr.status != 'deprecated'` --
--     by the time that INSERT runs, every cascaded child IS already 'deprecated', so it selects
--     ZERO rows and the cascade is silently unaudited. Fixed by logging FIRST, updating SECOND.
--   BUG-2 (fabricated from_status): both versions hard-code 'active' as from_status. A
--     shadow_only or candidate child cascaded to deprecated gets an audit row claiming a
--     transition that never happened, corrupting the exact audit trail concept_transition_log
--     exists to keep trustworthy. Fixed by selecting the child's real current status.
-- concept_transition_log.trigger_reason already permits 'parent_cascade' (migration 225) -- no
-- CHECK change needed for L-9.
--
-- L-10 (identity): concept_registry gains is_control/control_expectation (feature_registry's
-- control-canary columns, today used by 5 rows) plus group_name (feature_registry's peer-group
-- label). group_name is deliberately UNCONSTRAINED TEXT here, not an 11-value CHECK like
-- feature_registry.group_name -- the vocabulary is domain-specific and concept_registry is
-- cross-domain; the controlled-vocabulary system (vocabulary_drift.py, Phase 161) polices its
-- values, not a table CHECK.
--   PLANNER NOTE (verbatim per 170-01-PLAN.md): group_name is NOT named in todo 118's "folds
--   into metadata JSONB" list, but it is not decorative either -- it is read with real SQL-level
--   filtering by ops_ic_shrinkage.py (leave-one-out peer-group shrinkage, a live corpus-pipeline
--   step), ops_ensemble_ablation.py (SELECT DISTINCT group_name, family labels), and
--   ops_broadcast_feature_audit.py. It gets a dedicated column by the same rule todo 118 applies
--   to is_control ("both scripts do real WHERE filtering today; moving to JSONB predicates would
--   be a pure regression for no benefit"). `tier` DOES follow todo 118 and goes to metadata
--   JSONB in Plan 03 -- no tier column is added here.
--
-- L-5 (recovery counters): concept_gate gains consecutive_shadow_passes / observations_since_
-- demotion, matching feature_registry's Phase 143 LIFECYCLE-01 columns (migration 209) exactly
-- in type (INTEGER / BIGINT, both NOT NULL DEFAULT 0).
--
-- APR: no new keys minted. The feature domain reuses the EXISTING
-- alpha.decay.recovery_min_observations (2000) and alpha.decay.recovery_min_passes (2) keys
-- rather than adding alpha.concept_registry.feature_* siblings -- those two keys already ARE
-- the feature-recovery floors ic_engine reads today; a second pair would be two sources of
-- truth for one threshold.
--
-- All statements idempotent (CREATE TABLE/INDEX IF NOT EXISTS, ADD COLUMN IF NOT EXISTS) except
-- the two ADD CONSTRAINT statements, which are guarded with a DO block checking pg_constraint
-- first (ADD CONSTRAINT has no IF NOT EXISTS form). Safe to re-run.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. L-8: concept_parent lineage join table
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS concept_parent (
    child_concept_id  UUID NOT NULL REFERENCES concept_registry(concept_id),
    parent_concept_id UUID NOT NULL REFERENCES concept_registry(concept_id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (child_concept_id, parent_concept_id),
    CONSTRAINT concept_parent_no_self_check CHECK (child_concept_id <> parent_concept_id)
);

CREATE INDEX IF NOT EXISTS concept_parent_parent_idx ON concept_parent (parent_concept_id);

COMMENT ON TABLE concept_parent IS
    'Multi-parent lineage join table (L-8), superseding feature_registry.parent_features'' bare '
    'TEXT[] of feature names with real FK-enforced referential integrity on both '
    'child_concept_id and parent_concept_id. concept_registry.parent_concept_id (single-parent '
    'FK column) is NOT dropped -- domain=''ensemble_strategy'' may still reference it; the '
    'feature domain uses this table exclusively. Deliberately carries NO ordinality column: no '
    'consumer of lineage depends on parent order (Plan 07 traces the single reader end to end '
    'and proves it with an invariance test). If a future consumer ever needs order, the fix is '
    'an explicit ordinality column seeded from unnest(...) WITH ORDINALITY, not an implicit '
    'reliance on insertion order.';

-- ---------------------------------------------------------------------------
-- 2. L-8: cycle guard on concept_parent (BEFORE INSERT OR UPDATE)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_concept_parent_cycle_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        WITH RECURSIVE descendants(id) AS (
            SELECT NEW.child_concept_id
            UNION
            SELECT cp.child_concept_id
            FROM concept_parent cp JOIN descendants d ON cp.parent_concept_id = d.id
        )
        SELECT 1 FROM descendants WHERE id = NEW.parent_concept_id
    ) THEN
        RAISE EXCEPTION 'concept_parent cycle rejected: parent % is already a descendant of child %',
            NEW.parent_concept_id, NEW.child_concept_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_concept_parent_cycle_guard() IS
    'Rejects any concept_parent INSERT or UPDATE that would make NEW.parent_concept_id a '
    'descendant of NEW.child_concept_id (a cycle). Exists because '
    'fn_cascade_concept_parent_deprecation'' is deliberately recursive across this same table, '
    'and that recursion is only safe if the lineage DAG has no cycles -- this guard makes '
    'acyclicity an enforced invariant, not an assumption. '
    'KNOWN CONCURRENCY LIMIT: the recursive check above reads only COMMITTED edges. Two '
    'concurrent transactions that each insert one leg of a two-edge cycle (A->B in one, B->A in '
    'the other) can therefore both pass and both commit -- neither sees the other''s '
    'uncommitted row. Closing that would require SERIALIZABLE isolation or a table-level '
    'advisory lock on every edge write. Neither is warranted in this phase: concept_parent''s '
    'ONLY writer is migration 284, which inserts all edges inside a single transaction, and no '
    'runtime service writes lineage edges. CONTRACT: any future component that writes '
    'concept_parent outside a single-transaction seed MUST take pg_advisory_xact_lock() on a '
    'fixed key covering this table first, or this guard is best-effort for that writer.';

DROP TRIGGER IF EXISTS trg_concept_parent_cycle_guard ON concept_parent;

CREATE TRIGGER trg_concept_parent_cycle_guard
    BEFORE INSERT OR UPDATE ON concept_parent
    FOR EACH ROW
    EXECUTE FUNCTION fn_concept_parent_cycle_guard();

-- ---------------------------------------------------------------------------
-- 3. L-10: identity/group columns on concept_registry
-- ---------------------------------------------------------------------------

ALTER TABLE concept_registry
    ADD COLUMN IF NOT EXISTS is_control BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS control_expectation TEXT,
    ADD COLUMN IF NOT EXISTS group_name TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'concept_registry_control_expectation_check'
    ) THEN
        ALTER TABLE concept_registry ADD CONSTRAINT concept_registry_control_expectation_check
            CHECK (control_expectation IS NULL OR control_expectation IN ('negative_control', 'positive_control'));
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS concept_registry_group_name_idx ON concept_registry (group_name);
CREATE INDEX IF NOT EXISTS concept_registry_domain_status_idx ON concept_registry (domain, status);

COMMENT ON COLUMN concept_registry.is_control IS
    'L-10: ported from feature_registry.is_control (5 rows true today). Marks a concept as a '
    'control canary (positive or negative) rather than a real candidate signal.';

COMMENT ON COLUMN concept_registry.control_expectation IS
    'L-10: ported from feature_registry.control_expectation. Live values today: '
    'negative_control, positive_control. CHECK-free in feature_registry; constrained here to '
    'those two known values via concept_registry_control_expectation_check.';

COMMENT ON COLUMN concept_registry.group_name IS
    'L-10: ported from feature_registry.group_name. Deliberately UNCONSTRAINED TEXT (no CHECK '
    'like feature_registry''s 11-value list) -- the vocabulary is domain-specific and '
    'concept_registry is cross-domain; the controlled-vocabulary system (vocabulary_drift.py, '
    'Phase 161) polices its values, not a table CHECK. NOT decorative: read with real SQL-level '
    'filtering by ops_ic_shrinkage.py (leave-one-out peer-group shrinkage), '
    'ops_ensemble_ablation.py (SELECT DISTINCT group_name), and ops_broadcast_feature_audit.py -- '
    'given a dedicated column for the same reason is_control is (both scripts do real WHERE '
    'filtering today; JSONB predicates would be a pure regression for no benefit).';

-- ---------------------------------------------------------------------------
-- 4. L-9: cascade-deprecation trigger on concept_registry.status
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_cascade_concept_parent_deprecation()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'deprecated' AND OLD.status <> 'deprecated' THEN
        -- BUG-1 fix (vs. feature_registry original and todo 118's literal translation): log
        -- the audit row BEFORE the UPDATE runs. Logging after would find every cascaded child
        -- already 'deprecated', so a WHERE cr.status <> 'deprecated' filter at that point
        -- selects zero rows and the cascade goes silently unaudited.
        INSERT INTO concept_transition_log
            (concept_id, domain, name, from_status, to_status, trigger_reason, triggered_at, notes)
        SELECT cr.concept_id, cr.domain, cr.name, cr.status, 'deprecated', 'parent_cascade', NOW(),
               'Cascaded from parent concept ' || NEW.name || ' (domain ' || NEW.domain || ')'
        FROM concept_registry cr
        JOIN concept_parent cp ON cp.child_concept_id = cr.concept_id
        WHERE cp.parent_concept_id = NEW.concept_id AND cr.status <> 'deprecated';

        -- BUG-2 fix: from_status above is the child's REAL current status (cr.status), never
        -- the hard-coded 'active' both prior versions used.
        UPDATE concept_registry
        SET status = 'deprecated', enabled = false
        WHERE status <> 'deprecated'
          AND concept_id IN (SELECT child_concept_id FROM concept_parent
                             WHERE parent_concept_id = NEW.concept_id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_cascade_concept_parent_deprecation() IS
    'L-9: generalizes feature_registry.fn_cascade_parent_deprecation() from a '
    'tier=''1_interaction''-filtered, parent_features-array-scanning original to a '
    'concept_parent-join-scoped trigger that fires across every domain automatically. Two '
    'deliberate generalizations over the original: (a) no tier filter -- scoping comes from the '
    'join table alone; (b) the inner UPDATE re-fires this same trigger per touched child, so '
    'multi-level chains (grandparent -> parent -> child) cascade with no extra code -- safe '
    'only because fn_concept_parent_cycle_guard() guarantees the graph has no cycles. Fixes two '
    'real bugs present in both the feature_registry original and todo 118''s proposed literal '
    'translation: BUG-1 (audit INSERT must run BEFORE the UPDATE, or it silently selects zero '
    'rows) and BUG-2 (from_status must be the child''s real current status, never a hard-coded '
    'literal).';

DROP TRIGGER IF EXISTS trg_cascade_concept_parent_deprecation ON concept_registry;

CREATE TRIGGER trg_cascade_concept_parent_deprecation
    AFTER UPDATE OF status ON concept_registry
    FOR EACH ROW
    EXECUTE FUNCTION fn_cascade_concept_parent_deprecation();

-- ---------------------------------------------------------------------------
-- 5. L-5: shadow-recovery counters on concept_gate
-- ---------------------------------------------------------------------------

ALTER TABLE concept_gate
    ADD COLUMN IF NOT EXISTS consecutive_shadow_passes INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS observations_since_demotion BIGINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN concept_gate.consecutive_shadow_passes IS
    'L-5: ported from feature_registry.consecutive_shadow_passes (migration 209, Phase 143 '
    'LIFECYCLE-01). Compared against the EXISTING alpha.decay.recovery_min_passes APR key (no '
    'new key minted) for shadow_only -> active promotion eligibility.';

COMMENT ON COLUMN concept_gate.observations_since_demotion IS
    'L-5: ported from feature_registry.observations_since_demotion (migration 209, Phase 143 '
    'LIFECYCLE-01). Compared against the EXISTING alpha.decay.recovery_min_observations APR key '
    '(no new key minted) for shadow_only -> active promotion eligibility.';

COMMIT;
