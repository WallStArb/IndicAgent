-- Migration 357: concept_evaluation, the append-only lifecycle evidence ledger (todo 402)
--
-- Design: docs/plans/2026-09-24-feature-lifecycle-evidence-ledger-design.md (D1/D2).
--
-- One row per (concept, training window, evidence). The feature_lifecycle node
-- (services/feature_lifecycle.py) writes a row for every feature it evaluates against a
-- window's persisted feature_ic_scores. Re-evaluating identical evidence is a no-op
-- (ON CONFLICT DO NOTHING on the primary key); new evidence for a window adds a row and
-- every earlier row is kept. Lifecycle status is derived from this table, taking the
-- latest row per window, so one window counts once however many times it is recomputed.
--
-- This replaces concept_gate's run counters (consecutive_active_fails,
-- consecutive_shadow_passes, observations_since_demotion) as the source of truth for
-- domain='feature'. Those columns stay in place, unread by the feature lifecycle, until a
-- later migration drops them; domain='ensemble_strategy' does not use them.
--
-- evidence_key: sha256 over the evaluated status, the window's guard verdict and the
-- canonical sorted cell rows the verdict read, so a status change or a changed input
-- produces a new row rather than colliding with an old one.
-- guard_status: the window-level regime-shift guard verdict. 'hold_high' windows are
-- recorded but excluded from derivation (a held window is not evidence either way).
--
-- Plain table, not a hypertable: about 300 rows per evaluated window.

BEGIN;

CREATE TABLE IF NOT EXISTS concept_evaluation (
    concept_id       uuid        NOT NULL REFERENCES concept_registry (concept_id),
    domain           text        NOT NULL,
    window_end       timestamptz NOT NULL,
    evidence_key     text        NOT NULL,
    evaluated_status text        NOT NULL,
    passed           boolean     NOT NULL,
    statistic        double precision,
    n_cells          integer     NOT NULL,
    n_observations   bigint      NOT NULL,
    guard_status     text        NOT NULL,
    detail           jsonb,
    evaluated_at     timestamptz NOT NULL DEFAULT now(),
    run_ref          text,
    PRIMARY KEY (concept_id, window_end, evidence_key),
    CONSTRAINT concept_evaluation_domain_check
        CHECK (domain = ANY (ARRAY['feature', 'ensemble_strategy', 'construction'])),
    CONSTRAINT concept_evaluation_evaluated_status_check
        CHECK (evaluated_status = ANY (ARRAY['candidate', 'shadow_only', 'active', 'deprecated'])),
    CONSTRAINT concept_evaluation_guard_status_check
        CHECK (guard_status = ANY (ARRAY['ok', 'hold_high', 'alert_low', 'insufficient_cells']))
);

CREATE INDEX IF NOT EXISTS concept_evaluation_domain_window_idx
    ON concept_evaluation (domain, window_end);

COMMENT ON TABLE concept_evaluation IS
    'Append-only lifecycle evidence ledger (todo 402, migration 357). Status is derived '
    'from the latest row per (concept, window_end); see services/feature_lifecycle.py.';

COMMIT;
