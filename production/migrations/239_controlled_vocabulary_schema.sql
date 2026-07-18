-- Migration 239: Controlled Vocabulary - three-table schema (phase 161, plan 161-01)
--
-- NUMBERING NOTE: plan 161-01 originally specified migration numbers 237/238 for this
-- schema+seed pair. Both were already taken by the time this plan executed (Phase 146 shipped
-- two migrations at those numbers - a taxonomy-cleanup migration and a measurement-contract
-- migration for the instrument tag calibrator - on 2026-07-17). This migration and its seed
-- companion (240) use the next free integers per the plan's own fallback instruction ("if
-- taken, use the next free integer and note it in the SUMMARY").
--
-- Builds the storage foundation from docs/research/concept-controlled-vocabulary.md: a
-- single migration-governed source of truth for symbolic taxonomies (the "APR for symbolic
-- codes"), replacing hardcoded label sets scattered across consumers. Three tables:
--   controlled_vocabulary    - flat (namespace, code) -> label/description/sort_order registry
--   vocabulary_group         - named (namespace, group_name) groupings within a namespace
--   vocabulary_group_member  - join table: which codes belong to which group
--
-- Scope per CONTEXT.md D-01/D-03/D-04/D-04b (six live namespaces only, revised from five):
-- regime_hmm, regime_cross_sectional_equity, regime_cross_sectional_rates, timeframe,
-- asset_class, tier. Archived-SLA namespaces (signal_outcome, entry_type, signal_status,
-- session_type) are explicitly deferred, not seeded here or in the companion migration.
--
-- D-02 (closed decision, not reopened by this migration): the existing symbol-to-taxonomy
-- tag-assignment system (migrations 227/228) stays permanently separate from this registry.
-- Its definition rows are authoritative/flat vocabulary definitions (same epistemic kind as
-- controlled_vocabulary); its assignment rows are confidence-weighted, falsifiable-hypothesis
-- entity assignments - a fundamentally different kind of row. Forcing both through one table
-- would make the schema lie about what kind of row it is. No shared table, no FK, no ENUM type
-- bridges the two systems.
--
-- All statements idempotent: CREATE TABLE IF NOT EXISTS. Safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS controlled_vocabulary (
    namespace     TEXT        NOT NULL,
    code          TEXT        NOT NULL,
    label         TEXT        NOT NULL,
    description   TEXT,
    sort_order    INT         NOT NULL DEFAULT 0,
    is_deprecated BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (namespace, code)
);

COMMENT ON TABLE controlled_vocabulary IS
    'Authoritative flat vocabulary registry: one row per (namespace, code) symbolic taxonomy '
    'entry (e.g. regime_hmm/trending_up, timeframe/5m). Rows here are definitional - a code '
    'either exists in a namespace or it does not, with no confidence/weight/evidence attached. '
    'This is explicitly distinct from the symbol-to-tag assignment system (migration 227), '
    'whose rows are confidence-weighted, falsifiable-hypothesis entity assignments with '
    'provenance and evidence columns - a different epistemic kind of row entirely, not merely '
    'a different schema. Do not add weight/confidence/evidence columns here; that need belongs '
    'in a membership table like the existing tag-assignment table, not in this definitional '
    'registry.';

CREATE TABLE IF NOT EXISTS vocabulary_group (
    namespace   TEXT        NOT NULL,
    group_name  TEXT        NOT NULL,
    label       TEXT        NOT NULL,
    description TEXT,
    sort_order  INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (namespace, group_name)
);

COMMENT ON TABLE vocabulary_group IS
    'Named grouping within a controlled_vocabulary namespace (e.g. regime_hmm/trending, '
    'regime_cross_sectional_equity/low_vol). Groups are independent and may overlap - a code '
    'can belong to more than one group in the same namespace (e.g. regime_hmm/trending_up '
    'belongs to both trending and bullish_bias). This is why the shape is a join table '
    '(vocabulary_group_member) rather than a single parent_code column on controlled_vocabulary.';

CREATE TABLE IF NOT EXISTS vocabulary_group_member (
    namespace  TEXT NOT NULL,
    group_name TEXT NOT NULL,
    code       TEXT NOT NULL,
    PRIMARY KEY (namespace, group_name, code),
    FOREIGN KEY (namespace, code) REFERENCES controlled_vocabulary(namespace, code),
    FOREIGN KEY (namespace, group_name) REFERENCES vocabulary_group(namespace, group_name)
);

COMMENT ON TABLE vocabulary_group_member IS
    'Join table: which controlled_vocabulary codes belong to which vocabulary_group, within '
    'the same namespace. Composite FKs to both parent tables enforce referential integrity - '
    'a membership row can never reference a code or group that does not exist.';

COMMIT;
