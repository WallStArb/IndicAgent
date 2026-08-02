-- Migration 281: infra.blas_threads_per_worker -- fix OpenBLAS thread oversubscription
-- across every ProcessPoolExecutor-based batch service (todo 216).
--
-- Root cause (measured, not guessed -- performance-investigation-sop.md): numpy/scipy/
-- hmmlearn in this venv link against OpenBLAS with no thread cap, so every process
-- defaults to spawning one BLAS thread per logical core (24 on this host). None of
-- regime_writer.py/ic_engine.py/ensemble_ic_engine.py/counterfactual_tracker.py/
-- backfill_feature_factory.py capped this before today -- each ProcessPoolExecutor
-- worker (regime_writer alone runs 12) could independently try to use all 24 cores'
-- worth of BLAS threads, on top of the process-level parallelism those pools already
-- provide.
--
-- Isolated benchmark (zero contention from other processes): a GaussianHMM fit
-- matching regime_writer's real shape (50k rows, 5D obs, K=5) ran 4.65s at the default
-- (24 threads) vs 1.86s capped to 1 thread -- 2.5x slower with NO oversubscription in
-- play yet. For small-state-count HMM/rank-IC workloads, the per-step matrices are
-- tiny; BLAS thread coordination overhead exceeds any real parallel gain. Under actual
-- 12-way (or 8-way) ProcessPoolExecutor contention, the real cost is plausibly worse --
-- this todo also confirmed regime_writer's 3h37m runtime is NOT explained by
-- convergence retries (zero occurred in the last full run's log), leaving inherent
-- EM/BLAS cost as the dominant remaining factor.
--
-- Determinism check (why this is OPERATIONAL, not COMPUTATIONAL, in ic_engine.py's
-- fingerprint classification): the same fit run at threads=1 vs threads=24 produced
-- means_/transmat_/covars_ differing at ~1e-10 absolute (BLAS reduction-order noise,
-- not a real algorithmic difference) but byte-identical discrete Viterbi state
-- assignments across all 50,000 observations. This field moves wall time and the 16th
-- significant digit, not the labels or IC values anything downstream reads.
--
-- infra.blas_threads_per_worker: shared across all 5 services above via
-- services/_batch_utils.py's limit_blas_threads(), passed as each ProcessPoolExecutor's
-- initializer= so every worker process is capped from the moment it starts (fork or
-- spawn). ic_engine.py additionally calls it once in its own main process, since the
-- cross-sectional pass's bootstrap parallelism is a same-process ThreadPoolExecutor
-- (alpha.ic.cross_sectional_bootstrap_threads), not a separate pool.
--
-- Default 1: true parallelism already comes from the process-level worker pool: each
-- worker running single-threaded BLAS is the correct shape when N processes already
-- saturate the box. Not an ML learning target.
--
-- Deliberately NOT restarting any live corpus-pipeline process: ic_engine (step 5/8) is
-- mid-flight as of this migration (started 2026-07-30 17:08:55 EDT) and loads this key
-- once at startup -- zero effect on that run. Takes effect on the next regime_writer/
-- ic_engine/ensemble_ic_engine/counterfactual_tracker/backfill_feature_factory
-- invocation. Same batching discipline as migration 280.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.blas_threads_per_worker',
    'int',
    '1',
    1, 24,
    '[rca_analysis] Per-ProcessPoolExecutor-worker OpenBLAS/OpenMP thread cap, applied via '
    'services/_batch_utils.py make_worker_pool()/limit_blas_threads() (threadpoolctl.'
    'threadpool_limits()) in each worker''s initializer=. Shared by regime_writer.py, '
    'ic_engine.py, ensemble_ic_engine.py, counterfactual_tracker.py, '
    'backfill_feature_factory.py. Without this, each worker process defaults to using all '
    'logical cores'' worth of BLAS threads, oversubscribing N-worker pools by ~Nx. Measured '
    '(todo 216): a representative GaussianHMM fit ran 2.5x slower at the unthreaded default '
    'than at threads=1, in complete isolation. Also empirically confirmed non-COMPUTATIONAL: '
    'threads=1 vs threads=24 on an identical fit produced byte-identical discrete state '
    'labels despite ~1e-10 floating-point noise in the raw model parameters. Default 1 is '
    'correct because process-level parallelism (infra.*.workers) already provides the real '
    'parallelism; raising this only makes sense alongside a corresponding drop in worker '
    'count, and should be re-benchmarked before changing, not guessed. Not an ML learning '
    'target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.blas_threads_per_worker', '1', 1)
ON CONFLICT (config_key) DO NOTHING;
