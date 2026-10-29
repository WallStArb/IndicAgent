-- Migration 537: contribution accounting schema (phase 187 plan 14 Task 2, design 13, 10.2.3).
--
-- research_run gains the kind `subset_refit` (a leave-one-family-out or Shapley subset refit is a
-- counted attempt, design 7.1: same run_group and mode as its book, its own recipe and series) and
-- five typed headline columns of the contribution block, NULL at insert and set once at the
-- terminal update (the guard function is replaced to refuse them at insert; the existing
-- terminal-once rule already freezes them after).
--
-- APR keys (alpha.research.contribution.*): exact Shapley runs while the book has at most
-- shapley_exact_max_families families (12 = [conventional]: 2^12 = 4,096 subset refits is the most a
-- ridge closed form refits in minutes); beyond it seeded permutation sampling draws shapley_samples
-- orders (2000 = [initial_estimate]: standard error about 2% of a typical marginal at 6 or more
-- families). shapley_seed fixes the sampler: changing it changes every sampled Shapley output and
-- its recorded value is part of the contribution block. cluster_corr (0.7 = [initial_estimate]) is
-- the |correlation| above which two members of a corpus or generated family share an in-fold
-- cluster; clusters are accounting groups only and never decide admission or weights. None is an
-- ML learning target. Idempotent.

BEGIN;

ALTER TABLE research_run DROP CONSTRAINT research_run_kind_check;
ALTER TABLE research_run ADD CONSTRAINT research_run_kind_check
    CHECK (kind = ANY (ARRAY['evidence', 'book_test', 'pod_book', 'legacy_verdict', 'subset_refit']));

ALTER TABLE research_run
    ADD COLUMN IF NOT EXISTS n_families         integer,
    ADD COLUMN IF NOT EXISTS effective_breadth  double precision,
    ADD COLUMN IF NOT EXISTS top_group_share    double precision,
    ADD COLUMN IF NOT EXISTS lofo_max_t_drop    double precision,
    ADD COLUMN IF NOT EXISTS sign_stability_min double precision;

CREATE OR REPLACE FUNCTION fn_research_run_guard()
RETURNS TRIGGER AS $$

BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'started' THEN
            RAISE EXCEPTION 'research_run is append-only: a row must be inserted as started, got %',
                NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.evidence IS NOT NULL OR NEW.finished_at IS NOT NULL
           OR NEW.snapshot_hash IS NOT NULL
           OR NEW.decision_t IS NOT NULL OR NEW.decision_p IS NOT NULL
           OR NEW.gross_sharpe IS NOT NULL OR NEW.mean_session_pnl IS NOT NULL
           OR NEW.turnover_per_session IS NOT NULL OR NEW.n_sessions IS NOT NULL
           OR NEW.span_start IS NOT NULL OR NEW.span_end IS NOT NULL
           OR NEW.n_families IS NOT NULL OR NEW.effective_breadth IS NOT NULL
           OR NEW.top_group_share IS NOT NULL OR NEW.lofo_max_t_drop IS NOT NULL
           OR NEW.sign_stability_min IS NOT NULL THEN
            RAISE EXCEPTION 'research_run is append-only: a started row carries no evidence, '
                'finished_at, snapshot_hash or headline numbers'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    -- UPDATE
    IF OLD.status <> 'started' THEN
        RAISE EXCEPTION 'research_run is append-only: run % is already terminal (%)',
            OLD.run_id, OLD.status
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status NOT IN ('completed', 'guard_failed', 'refused', 'failed') THEN
        RAISE EXCEPTION 'research_run is append-only: a started row may only move to a '
            'terminal status, got %', NEW.status
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.finished_at IS NULL THEN
        RAISE EXCEPTION 'research_run is append-only: a terminal row needs finished_at'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.run_group IS DISTINCT FROM OLD.run_group
       OR NEW.concept_id IS DISTINCT FROM OLD.concept_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.mode IS DISTINCT FROM OLD.mode
       OR NEW.spec_path IS DISTINCT FROM OLD.spec_path
       OR NEW.spec_hash IS DISTINCT FROM OLD.spec_hash
       OR NEW.spec_blob IS DISTINCT FROM OLD.spec_blob
       OR NEW.code_commit IS DISTINCT FROM OLD.code_commit
       OR NEW.vintage IS DISTINCT FROM OLD.vintage
       OR NEW.budget_m IS DISTINCT FROM OLD.budget_m
       OR NEW.screen_alpha IS DISTINCT FROM OLD.screen_alpha
       OR NEW.started_at IS DISTINCT FROM OLD.started_at
       OR NEW.recipe_hash IS DISTINCT FROM OLD.recipe_hash
       OR NEW.informed_by IS DISTINCT FROM OLD.informed_by THEN
        RAISE EXCEPTION 'research_run is append-only: only status, snapshot_hash, evidence, '
            'finished_at and the headline numbers change, once'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.snapshot_hash IS NOT NULL
       AND NEW.snapshot_hash IS DISTINCT FROM OLD.snapshot_hash THEN
        RAISE EXCEPTION 'research_run is append-only: snapshot_hash may go from NULL to a '
            'value, never change'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    ('alpha.research.contribution.shapley_exact_max_families', 'int', '12', 2, 20,
     '[conventional] Contribution accounting: Shapley over families is exact (every subset refit) while the book has at most this many families; above it, seeded permutation sampling. 12 = 4,096 subsets. Not an ML learning target.'),
    ('alpha.research.contribution.shapley_samples', 'int', '2000', 100, 100000,
     '[initial_estimate] Contribution accounting: permutation draws for sampled Shapley above shapley_exact_max_families. Each draw refits up to K subsets (cached). Not an ML learning target.'),
    ('alpha.research.contribution.shapley_seed', 'int', '20261029', 0, 2147483647,
     '[initial_estimate] Contribution accounting: seed of the sampled Shapley permutations. Changing it changes every sampled Shapley output and invalidates comparisons with recorded contribution blocks. Not an ML learning target.'),
    ('alpha.research.contribution.cluster_corr', 'float', '0.7', 0.1, 0.99,
     '[initial_estimate] Contribution accounting: absolute in-fold correlation above which two members of a corpus or generated family share an accounting cluster (complete linkage, training fold only). Accounting groups never decide admission or weights. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('alpha.research.contribution.shapley_exact_max_families', '12', 1),
    ('alpha.research.contribution.shapley_samples', '2000', 1),
    ('alpha.research.contribution.shapley_seed', '20261029', 1),
    ('alpha.research.contribution.cluster_corr', '0.7', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_537',
       'seed: contribution accounting (plan 187-14)'
FROM config_state s
WHERE s.config_key LIKE 'alpha.research.contribution.%'
  AND NOT EXISTS (SELECT 1 FROM config_history h WHERE h.config_key = s.config_key);

COMMIT;
