-- Migration 298: alpha.ic.bootstrap_early_stop.{enabled,check_interval,tol,
-- min_resamples,stable_checks} (todo 227, adaptive bootstrap resample count)
--
-- Todo 215 (completed 2026-07-30) confirmed _blocked_bootstrap_ci's cost is
-- dominated by scipy.stats.rankdata's O(n log n) sort, and landed threading
-- as the throughput fix (~1.3x, now core-contention-capped -- 8 ic_engine
-- workers x 2 threads near the 24-logical-core ceiling). Todo 227 identified
-- the remaining lever: alpha.ic.bootstrap_resamples=2000 is fixed regardless
-- of how quickly the CI's Monte Carlo standard error actually stabilizes.
--
-- Design decision (todo 227 step 1, resolved 2026-08-05 by grepping every
-- downstream consumer of ic_ci_lower/ic_ci_upper): bit-identical
-- reproducibility across different resample counts is NOT load-bearing for
-- this CI. Every consumer reads it as a threshold/sign gate --
-- ensemble_trainer.py's significance clause (ic_ci_lower > 0 or the
-- sign-symmetric variant), alpha_publisher.py's direction-aware gate
-- (ci_lower > cost_hurdle / ci_upper < -cost_hurdle), counterfactual_
-- tracker.py's exit condition (ic_ci_lower < 0) -- never an exact value
-- compared run-to-run. Contrast with HMM_RANDOM_STATE, which IS load-bearing
-- (changing it invalidates downstream regime labels used as literal
-- categorical feature values). A documented numeric tolerance is therefore
-- an acceptable replacement invariant for this specific CI.
--
-- Seeded with enabled=false: landing this code must not itself change any
-- existing ic_ci_lower/ic_ci_upper value or any gate decision derived from
-- it -- same "off by default, flipping on is a separate deploy decision"
-- pattern as alpha.hmm.walk_forward.enabled (migration 269) and todo 108's
-- multi-seed HMM restarts. Flipping this on is a genuine behavior change
-- (approximate CI bounds, fewer resamples on cells that converge early) and
-- needs its own corpus re-run to confirm no gate gets flipped by the
-- approximation, not something this migration's seed value forces.
--
-- check_interval/min_resamples/stable_checks/tol are [initial_estimate], not
-- benchmarked against real feature_vectors data -- chosen conservatively
-- (require 200 resamples minimum, 2 consecutive stable checkpoints, a tol an
-- order of magnitude tighter than the ~0.02-0.05 typical IC magnitude in
-- this corpus) so an initial live trial errs toward "barely saves compute"
-- rather than "silently returns a noisy CI." Tune once real convergence data
-- exists (same category of open calibration-backlog item as todo 226's
-- n_iter=200 headroom check -- see docs/reference cleanup pass
-- 2026-07-27 APR calibration-backlog inventory).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ic.bootstrap_early_stop.enabled',
    'bool',
    'false',
    NULL, NULL,
    '[initial_estimate] Gate for adaptive early-stop on _blocked_bootstrap_ci''s '
    'resample loop (services/ic_engine.py, todo 227). false (seeded default) is '
    'byte-identical to the pre-todo-227 fixed-bootstrap_resamples behavior. '
    'Flipping true is a genuine behavior change (approximate ci_lower/ci_upper, '
    'fewer resamples on cells that converge early) -- a separate, later, '
    'explicit deployment decision requiring its own corpus re-run, not forced '
    'by this migration. Bit-identical reproducibility confirmed NOT load-bearing '
    'for this CI (every downstream consumer reads it as a threshold/sign gate, '
    'never an exact run-to-run value) -- see this migration''s header. Not an '
    'ML learning target.'
),
(
    'alpha.ic.bootstrap_early_stop.check_interval',
    'int',
    '200',
    10, 2000,
    '[initial_estimate] Recompute and check the running ci_lower/ci_upper '
    'estimate every this-many additional resamples once early-stop is enabled. '
    'Smaller = checks more often (more overhead, stops closer to the true '
    'convergence point); larger = fewer checks (less overhead, may overshoot '
    'by up to this many wasted resamples). Not benchmarked -- see this '
    'migration''s header. Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_early_stop.tol',
    'float',
    '0.002',
    0.0, 1.0,
    '[initial_estimate] Max absolute change in ci_lower/ci_upper (elementwise '
    'across a feature block) between consecutive checkpoints to count as '
    '"stable." An order of magnitude tighter than this corpus''s typical '
    '~0.02-0.05 IC magnitude, chosen conservatively pending real convergence '
    'data (todo 227). Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_early_stop.min_resamples',
    'int',
    '200',
    10, 2000,
    '[initial_estimate] Never stop early before at least this many resamples '
    'have been computed, regardless of how quickly the estimate appears to '
    'stabilize -- guards against a lucky-noise false stop on very few draws. '
    'Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_early_stop.stable_checks',
    'int',
    '2',
    1, 10,
    '[initial_estimate] Require this many CONSECUTIVE checkpoints within tol '
    'before actually stopping -- guards against stopping on a single-checkpoint '
    'fluke. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic.bootstrap_early_stop.enabled', 'false', 1),
    ('alpha.ic.bootstrap_early_stop.check_interval', '200', 1),
    ('alpha.ic.bootstrap_early_stop.tol', '0.002', 1),
    ('alpha.ic.bootstrap_early_stop.min_resamples', '200', 1),
    ('alpha.ic.bootstrap_early_stop.stable_checks', '2', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ic.bootstrap_early_stop.enabled', 1, 'false', 'migration_298',
     'Seed adaptive bootstrap early-stop OFF -- landing the code must not itself '
     'change any existing CI value, todo 227 [initial_estimate]'),
    (NOW(), 'alpha.ic.bootstrap_early_stop.check_interval', 1, '200', 'migration_298',
     'Seed checkpoint interval, todo 227 [initial_estimate]'),
    (NOW(), 'alpha.ic.bootstrap_early_stop.tol', 1, '0.002', 'migration_298',
     'Seed stability tolerance, todo 227 [initial_estimate]'),
    (NOW(), 'alpha.ic.bootstrap_early_stop.min_resamples', 1, '200', 'migration_298',
     'Seed minimum resamples before allowing early-stop, todo 227 [initial_estimate]'),
    (NOW(), 'alpha.ic.bootstrap_early_stop.stable_checks', 1, '2', 'migration_298',
     'Seed required consecutive stable checkpoints, todo 227 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
