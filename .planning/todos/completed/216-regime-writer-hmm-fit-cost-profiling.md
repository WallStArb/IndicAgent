---
status: completed
priority: P1
filed: 2026-07-30
closed: 2026-08-02
source: user mandate mid-session ("compute needs to improve") -- step-duration audit of
  today's corpus pipeline run found this, but the process wasn't running at audit time
  so it couldn't be py-spy'd like todo 215's ic_engine finding
---

## Addendum (2026-08-02, post-`/simplify`): DRY'd the wiring, empirically verified the fingerprint classification

4 parallel review agents (reuse/simplification/efficiency/altitude) caught two real gaps in the
first pass, both fixed: (1) the 5 services each hand-wired `ProcessPoolExecutor(initializer=...,
initargs=...)` identically with no shared construction point -- a 6th future service adding a
pool would silently reintroduce the bug. Consolidated into `make_worker_pool(n_workers,
blas_threads_per_worker)` in `services/_batch_utils.py`; all 5 call sites now go through it. (2)
The OPERATIONAL-vs-COMPUTATIONAL classification of `blas_threads_per_worker` in ic_engine.py's
fingerprint system asserted "pure throughput knob" without checking whether thread count moves
actual output (BLAS reduction order is not associative under IEEE 754). Checked directly: fit
the same synthetic HMM at threads=1 vs threads=24, same `random_state`. `means_`/`transmat_`/
`covars_` differed at ~1e-10 absolute (real, not zero) but the discrete Viterbi state
assignments -- what `regime_writer` actually writes -- were byte-identical across all 50,000
observations. Classification confirmed correct, now documented as measured rather than assumed,
in both `limit_blas_threads()`'s docstring and migration 281's `config_schema.description`
(synced live via `UPDATE`, no `config_history` entry -- schema descriptions aren't versioned
data, matching migration 166's precedent). Full unit suite green throughout
(`.venv/bin/pytest tests/unit/ -q`); live `ic_engine` run (`pid 1638298`) confirmed undisturbed
after every edit.

## Resolution (2026-08-02): root cause found without live profiling, fix shipped system-wide, migration 281 applied

`regime_writer.py`'s `regime_writer.log.1` from the last full run was checked first (read-only,
safe alongside the then-live `ic_engine` pass): **zero cells hit `hmm_not_converged_retry`** (244
successful fits, 76 correctly-gated degenerate skips, 0 retries) -- this todo's original
"n_iter=200 x convergence retries" hypothesis is refuted. 244 cells actually fit 26.79M total
rows (5m alone: 55 cells, 18.2M rows, 68% of the total) -- real, substantial EM cost, not a
retry-inflation artifact.

**Root cause, found via `threadpoolctl.threadpool_info()` + an isolated benchmark (no live
process touched):** numpy/hmmlearn in this venv link against OpenBLAS with no thread cap --
every process defaults to spawning one BLAS thread per logical core (24 on this host).
`regime_writer.py` runs 12 `ProcessPoolExecutor` workers with no `initializer=`; none of
`ic_engine.py`/`ensemble_ic_engine.py`/`counterfactual_tracker.py`/`backfill_feature_factory.py`
capped it either. Measured (matching regime_writer's real shape -- 50k rows, 5D obs, K=5, single
process, zero contention from any other process): **4.65s at the default 24 threads vs 1.86s
capped to 1 -- 2.5x slower even in isolation.** Small-state HMM/rank-IC workloads operate on tiny
per-step matrices; BLAS thread coordination overhead exceeds any real parallel gain. Under actual
12-way process contention the real cost is plausibly worse than this isolated 2.5x -- this todo's
original "py-spy a live run" ask is superseded by a cleaner root-cause path that didn't require
one.

**Fix shipped, scope grew beyond regime_writer alone** (same bug, same fix, all 5 live
`ProcessPoolExecutor`-based batch services -- `equity_regime_model.py` excluded, retired/dead
per Phase 144): `services/_batch_utils.py`'s new `limit_blas_threads()` (calls
`threadpoolctl.threadpool_limits(n)`, not a context manager -- persists for the worker's whole
lifetime), wired as `initializer=`/`initargs=` on every `ProcessPoolExecutor(...)` construction
in `regime_writer.py`, `ic_engine.py`, `ensemble_ic_engine.py`, `counterfactual_tracker.py`,
`backfill_feature_factory.py`. `ic_engine.py` additionally calls it once in its own main process
(the cross-sectional pass's bootstrap parallelism is a same-process `ThreadPoolExecutor`, not a
separate pool, and shares the main process's BLAS state). New APR key
`infra.blas_threads_per_worker` (migration 281, default 1, `[rca_analysis]` provenance) governs
the cap. `ic_engine.py`'s `ICEngineConfig` dataclass gained the field as OPERATIONAL (throughput
knob, never invalidates a fingerprint) -- `test_computational_and_operational_fields_partition_
dataclass_exactly` still passes. Full unit suite green (`.venv/bin/pytest tests/unit/ -q`).
Applied live via `psql -f production/migrations/281_blas_thread_oversubscription_fix.sql` --
zero effect on the then-in-flight `ic_engine` cross-sectional pass (loads config once at
startup, same batching discipline as migration 280).

**Not yet confirmed at full production scale:** the 2.5x isolated number is real but is a lower
bound, not the actual regime_writer wall-clock delta -- that needs the next full
`regime_writer.py` run to self-confirm via its own step-timing log (todo 217's instrumentation,
once it fires for a completed step) and `logs/regime_writer.log`'s event counts. No follow-up
todo needed to track this -- it surfaces naturally the next time the corpus pipeline runs
`regime_writer` from a real invocation, and the fix is either validated or (if the isolated
benchmark doesn't generalize under 12-way contention for some unforeseen reason) visibly not,
either way readable from that run's own logs without a dedicated investigation.

# `regime_writer.py` (corpus pipeline step 2, per-symbol GaussianHMM fit) took 13,053s
# (3h37m) in today's run -- the single largest step measured so far, but not yet
# profiled to a specific root cause

## Evidence

`logs/corpus_pipeline/full_run_20260730_062200.out`: step 2/8 (`regime_writer`) ran
06:22:01 -> 09:59:34 EDT, `DONE in 13053s`. `infra.regime_writer.workers` = 12
(ProcessPoolExecutor, one `GaussianHMM` fit per (symbol, tf) cell, `n_iter` = 200,
5D observations, `hmm_random_state` = 42 -- see `[[project_hmm_improvement_decisions]]`).
Roughly comparable total cost to todo 215's `ic_engine` finding (the pipeline's other
dominant step) -- these two steps are the corpus pipeline's actual bottleneck, not the
other 6 steps (step 3 = 2291s, step 4 = ~100-170s; steps 1/6/7/8 not yet measured this
cycle).

Unlike todo 215, this was NOT caught by a live profile -- the process had already
finished by the time this audit ran, so there's no `py-spy` stack evidence yet, only
the wall-clock total. Root cause is unconfirmed: could be inherent EM-iteration cost
(`n_iter=200` x however many symbols fail to converge and trigger the documented
same-seed retry at `n_iter*2`, see todo 108), scaler/data-prep redone per cell,
or something else entirely.

There's a separate, unrelated prior investigation into this same script,
`[[project_regime_refit_wedge]]` -- that one is about a STALL/wedge bug (workers going
to 0% CPU with no progress), not steady-state throughput. Don't conflate the two; this
todo is about normal-path cost, not the wedge.

## What to do

Next time `regime_writer.py --refit` (or a plain corpus-pipeline run) has it actively
running, `py-spy dump` several worker PIDs the same way todo 215 did, to find out
whether the EM fit itself dominates, retries are frequent enough to matter, or
something else (I/O, data prep) is the real cost. Only after that evidence exists is a
fix worth designing -- don't guess at an HMM-specific optimization without a profile,
same discipline as todo 215.

## Sizing

Investigation first (cheap, non-invasive `py-spy dump` against a live run) -- sizing
for any resulting fix depends entirely on what that finds.
