-- Migration 248: alpha_strategy_scores + gate_evaluations tables and missing
-- alpha.scoring.* APR keys (Phase 148, SCORE-01/02/03)
--
-- This is the shared foundation for Phase 148 (Alpha Scoring System): the two tables
-- every downstream plan (SCORE-01/02/03) writes to do not exist yet, and the schema
-- doc (docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md) specified three
-- alpha.scoring.* APR keys that were never actually migrated in. This migration
-- removes both blockers once, cleanly, before any code is written.
--
-- Re-verified at execution time (2026-07-22): head migration is 247
-- (247_regime_groups_dual_write_symbol_hmm.sql, an unrelated concurrent
-- workstream). 248 is free. Phase 162 has reserved 249-252 for its own four
-- migrations; not touched here.
--
-- (a) alpha_strategy_scores -- SCORE-01 (AlphaScorer) writes here. text/double
-- precision types throughout (never uuid), matching the live alpha_frames.frame_id
-- text convention (RESEARCH.md Pitfall 4).
--
-- (b) gate_evaluations -- SCORE-02 (Gate 1: signal proof) and SCORE-03 (Gate 2:
-- execution proof) both write one row here per gate run. Loose jsonb evidence
-- column with no enforced sub-schema, matching the llm_calls / integrity_monitor
-- audit-log convention (RESEARCH.md Open Question 3).
--
-- (c) alpha.scoring.* APR keys -- two provenance classes:
--   - min_sharpe / max_drawdown_ratio: GATE-THRESHOLD keys encoding SHADOW-REVIEW.md
--     criteria 3/4. PRE-REGISTERED: not tunable post-hoc (same discipline as
--     alpha.validation.regime_gate_min_clusters, migration 244).
--   - min_ic_alpha_score_corr: DIAGNOSTIC-ONLY. ROADMAP.md defines ic_alpha_score_corr
--     as a monotonicity diagnostic, not a gate -- no plan thresholds against it.
--
-- ON CONFLICT DO NOTHING on all three INSERTs guards a concurrent/re-run migration
-- from overwriting an already-live value (T-148-F1). config_history changed_by
-- records the actual migration filename number for an auditable trail (T-148-F2).
--
-- Do NOT re-seed the four already-live alpha.scoring.* keys (min_strategy_n=30,
-- bootstrap_max_n=5000, bootstrap_batch=1000, bootstrap_random_state=42).

BEGIN;

CREATE TABLE IF NOT EXISTS alpha_strategy_scores (
    symbol               text,
    tf                   text,
    regime               text,
    alpha_score_decile   integer,
    sample_n             integer,
    n_clusters           integer,
    win_rate             double precision,
    sharpe_annualized    double precision,
    max_drawdown         double precision,
    ic_alpha_score_corr  double precision,
    ci_lower             double precision,
    ci_upper             double precision,
    compute_version      text,
    run_ts               timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tf, regime, alpha_score_decile, run_ts)
);

CREATE TABLE IF NOT EXISTS gate_evaluations (
    eval_id   text,
    gate_id   text NOT NULL,
    result    text NOT NULL,
    evidence  jsonb NOT NULL,
    run_ts    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gate_id, run_ts)
);

-- alpha.scoring.min_sharpe -- GATE-THRESHOLD (SHADOW-REVIEW.md criterion 3)
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.scoring.min_sharpe',
    'float',
    '0.5',
    0.0, 5.0,
    '[conventional] SHADOW-REVIEW.md criterion 3 frozen Sharpe threshold for Gate 2 '
    '(SCORE-03 execution proof). PRE-REGISTERED: not tunable post-hoc.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.scoring.min_sharpe', '0.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.scoring.min_sharpe', 1, '0.5', 'migration_248',
     'Seed SHADOW-REVIEW.md frozen Sharpe gate threshold, never previously migrated')
ON CONFLICT DO NOTHING;

-- alpha.scoring.max_drawdown_ratio -- GATE-THRESHOLD (SHADOW-REVIEW.md criterion 4)
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.scoring.max_drawdown_ratio',
    'float',
    '0.25',
    0.0, 1.0,
    '[conventional] SHADOW-REVIEW.md criterion 4 frozen max-drawdown-ratio threshold '
    'for Gate 2 (SCORE-03 execution proof). PRE-REGISTERED: not tunable post-hoc.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.scoring.max_drawdown_ratio', '0.25', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.scoring.max_drawdown_ratio', 1, '0.25', 'migration_248',
     'Seed SHADOW-REVIEW.md frozen max-drawdown-ratio gate threshold, never previously migrated')
ON CONFLICT DO NOTHING;

-- alpha.scoring.min_ic_alpha_score_corr -- DIAGNOSTIC-ONLY, not a gate threshold
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.scoring.min_ic_alpha_score_corr',
    'float',
    '0.3',
    -1.0, 1.0,
    '[conventional] SCORE-01 ic_alpha_score_corr monotonicity diagnostic reference '
    'value: correlation between alpha_score_decile rank and mean_pnl_r. '
    'DIAGNOSTIC-ONLY, not a gate threshold -- no plan thresholds against it.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.scoring.min_ic_alpha_score_corr', '0.3', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.scoring.min_ic_alpha_score_corr', 1, '0.3', 'migration_248',
     'Seed SCORE-01 ic_alpha_score_corr diagnostic reference value, never previously migrated')
ON CONFLICT DO NOTHING;

COMMIT;
