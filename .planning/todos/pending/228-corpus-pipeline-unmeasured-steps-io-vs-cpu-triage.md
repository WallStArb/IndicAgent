---
status: pending
priority: P2
filed: 2026-08-02
source: throughput brainstorm following todos 215/216 -- both closed fixes targeted
  CPU-bound compute (rankdata, BLAS threading) on the two steps that happened to get
  profiled; the other 6 steps have never been checked for whether they're even
  CPU-bound
---

# 4 of the corpus pipeline's 8 steps have zero timing data and have never been
# checked for I/O- vs CPU-boundedness -- don't extend compute/threading fixes to them
# without checking first

## Problem

Todos 215 (`ic_engine`, step 5) and 216 (`regime_writer`, step 2) both found and fixed
real CPU-bound bottlenecks (`rankdata` sort cost, OpenBLAS thread oversubscription).
That's real signal for those two steps specifically -- but steps 1 (`feature_factory`),
6 (`ic_shrinkage`), 7 (`ensemble_trainer`), and 8 (`alpha_publisher`) have no timing
data at all (only steps 2/3/4/5 have been measured across various partial runs, per
todo 217's own filing). Applying CPU-bound intuition (more threads, cap BLAS) to a step
that's actually bottlenecked on TimescaleDB writes would do nothing -- or actively hurt,
if it adds process/thread contention around an already-saturated I/O path.

## What to do

**Blocked on todo 217** (structured step timing) landing and one full pipeline run
producing real per-step durations for all 8 steps. Once that data exists:

1. Identify which of steps 1/6/7/8 are actually significant (comparable magnitude to
   steps 2/5, not the ~100-170s step 4 already measured as cheap).
2. For each significant one, follow `docs/foundation/performance-investigation-sop.md`
   before touching code: check `pg_stat_activity.wait_event`, `iostat -x 1` during a
   live run, and chunk count/compression status on whatever hypertable it writes to.
   Never assume CPU-bound from the todo 215/216 precedent -- measure fresh per step.
3. Only after that classifies a step as CPU-bound does a thread/library-level fix
   (matching todos 215/216's playbook) become the right next move. An I/O-bound step
   needs batch-size/COPY-vs-INSERT tuning instead -- different fix family entirely.

## Sizing

Investigation only, no code changes implied yet -- sizing for any resulting fix depends
entirely on what step turns out to dominate and whether it's I/O- or CPU-bound.
