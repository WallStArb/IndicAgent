---
status: pending
priority: P2
filed: 2026-09-19
source: user statement 2026-09-19 that a 1000-2000 symbol universe is not reachable at the current
  compute cost; measured from the live ic_engine corpus run's log plus Fable 5.1's research pass
  (docs/research/2026-09-19-ic-engine-bootstrap-ci-optimization-research.md)
---

# ic_engine full recompute costs about 2.4 worker-hours per symbol -- a 1000-2000 symbol universe means 10-20 day recomputes; measure per-symbol threading before anything else

## What

The current corpus run (`services/ic_engine.py --workers 10`, PID 359172, started 2026-09-17) had
processed about 207 of the 233 `compute_eligible` symbols after 2 days 2 hours. Derived from
`logs/ic_engine.log*` `ic_engine.clustering` events (symbol count seen, not a benchmark; some
symbols counted are still in progress; box was also shared with other work, load average ~20):

- about 2.4 worker-hours per symbol, or 4-5 CPU-hours at the ~190% CPU each worker shows
- per-symbol work is linear in symbol count: 1000 symbols is about 10 days per full recompute on
  this box, 2000 is about 20 days
- the cross-sectional stage is bounded by rows and scratch disk, not just time. The first run's
  per-symbol and pooled passes finished (233 symbols x 4 tfs, 2026-09-20 07:00 UTC), then the run
  died at 09:19 UTC on the first 15m cross-sectional cell: pre-flight estimate 21,523,866 rows vs
  `alpha.ic.max_cell_rows=15000000` (`n_estimated = regime_timestamps x symbols`, an upper bound by
  design). 1d and 1h cells (9 each) had completed. 5m cells will be about 3x larger. Disk-backed
  scratch needs 2.2 x rows x features x 4 bytes, so a 21.5M-row cell is about 55 GB; the same cell
  at 1000-2000 symbols would be 5-9x that per cell, which exceeds this box's 562 GB free disk for 5m.
  `max_cell_rows` is excluded from the cell fingerprint, so raising it does not invalidate
  completed cells; cross-sectional cells resume via per-cell fingerprints.

Adding symbols is not the expensive part (existing symbols' results do not change when new ones
join, apart from pooled/cross-sectional stages). The cost that blocks iteration is every
recompute after a feature, config, or methodology change.

## Levers, in the order to pull them

1. **Per-symbol threading (measure first).** `per_symbol_bootstrap_threads` defaults to 1 on the
   per-symbol `ProcessPoolExecutor` path. The `cross_sectional_bootstrap_threads` comment at
   `services/ic_engine.py:583-598` records a 2-6x wall-time reduction from threading because
   scipy `rankdata` releases the GIL. Not measured on the per-symbol path. Run only after the
   current corpus run finishes, since a benchmark now competes with it for CPU.
2. **Numba `nogil=True` kernel plus threads.** Fable measured a byte-identical 1.26-1.54x for a
   fused Numba kernel without `nogil` (`scripts/analysis/ic_engine_bootstrap_ci_numba_benchmark.py`,
   same contention caveat). `nogil=True` plus `ThreadPoolExecutor`, and `prange`, were not tested.
   Extend that script to test them before deciding.
3. **Staged bootstrap.** Cheap point IC for every cell; 2000-resample bootstrap only where it can
   change a decision. Selecting cells on the same statistic later tested distorts BH-FDR, so the
   selection rule must be pre-registered and the FDR family defined over all cells. Todo 227's
   early stopping already does a within-cell version of this.
4. **Incremental recompute.** Key each cell's result to a feature-definition and config hash so a
   change to one feature invalidates only that feature's cells. Largest structural win, most
   engineering.
5. **Cluster.** The standing long-term direction (`project_long_term_securities_universe_scaling`).
   Optimize first; a cluster running an unoptimized job only costs more.

## Not in scope

HAC-for-rank-IC replacement of the bootstrap. Fable's verdict stands: the only candidate
(Pohle/Wermuth/Weiss, arXiv:2512.14609) is R-only, unvalidated on this corpus, and its own
simulations show no coverage advantage over block bootstrap. Revisit only as a dedicated
statistical validation against `ops_ic_null_calibration.py` on the 5m cells behind todo 099.

## Gate

Lever 1 needs the live run to finish. Scope any universe expansion by measured recompute cost, not
a target symbol count. Phase 174's D-10 result already made single-name equity expansion the
weaker lever (cross-asset ETFs first), so this cost bound mostly caps how far a later single-name
expansion can go, not the near-term plan.
