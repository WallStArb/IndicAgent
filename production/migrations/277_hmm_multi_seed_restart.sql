-- Migration 277: alpha.hmm.n_restarts APR key — todo 108
--
-- Adds the APR key backing regime_writer.py's multi-seed HMM restart mechanism
-- (fit alpha.hmm.n_restarts different seeds, derived deterministically as
-- hmm_random_state + i, keep whichever converged model has the highest
-- log-likelihood). Default 1 makes the new code path byte-identical to the
-- prior single-seed-fit + same-seed-retry-on-non-convergence behavior — this
-- migration ships the mechanism only; the empirical before/after validation
-- (log-likelihood + label-agreement delta on real symbols) and any
-- corpus-wide rollout decision remain open, see todo 108.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.hmm.n_restarts',
    'int',
    '1',
    1, 20,
    '[initial_estimate] Number of GaussianHMM fits attempted in regime_writer.py, '
    'one per seed derived deterministically as alpha.hmm.random_state + i for '
    'i in range(n_restarts) — the converged fit with the highest log-likelihood is '
    'kept. GaussianHMM''s EM objective is non-convex, so a single seed can land in a '
    'worse local optimum than a different seed would find. Changing this away from 1 '
    'changes which local optimum regime_writer.py lands on and therefore invalidates '
    'all downstream regime labels in feature_vectors — same caution class as '
    'alpha.hmm.random_state. Not an ML learning target. Default 1 reproduces the prior '
    'single-seed-fit behavior exactly (one seed, one same-seed convergence retry).'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.hmm.n_restarts', '1', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.hmm.n_restarts', 1, '1', 'migration_277',
    'Initial estimate: default 1, byte-identical to prior single-seed HMM fit [initial_estimate]'
)
ON CONFLICT DO NOTHING;

COMMIT;
