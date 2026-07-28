---
status: pending
priority: P2
filed: 2026-07-27
source: T5's 1d independent replication, deferred the 15m follow-on due to memory contention
---

## What

`scripts/analysis/t5_nonlinear_combiner_replication_1d.py` (2026-07-27) partially replicated
T5's non-linear-combiner finding at equity/1d: the tree combiner clears its own bootstrap CI in
the cross-sectional-neutral rigor pass (`point_ic`=0.0164, `ci_lower`=0.0081), but the magnitude
collapsed ~16x from the original equity/1h finding (0.258 -> 0.0164) -- confirmed SMALL, not
confirmed LARGE. Full writeup: `docs/research/data-edge-source-thesis.md`'s T5 section (v1.4).

The 15m replication is the directly actionable one -- it's the timeframe Phase 167's live
`CrossSectionalSpreadTracker` construction actually trades on (`ctf_momentum` ranked at 15m).
Deliberately deferred at write time: 15m equity is ~8.1M feature_vectors/forward_returns rows
vs. 1d's ~330K, and the concurrent todo 183 `ic_engine` corpus recompute was holding ~9GB RSS
against only ~12GB available on this machine -- loading the full 15m corpus into one in-memory
pandas DataFrame (the pattern both the 1h and 1d T5 scripts use) risked OOM/heavy swapping.

Separately, the 1d replication surfaced an unrelated, load-bearing finding worth its own
investigation before or alongside this: `ctf_momentum` shows NEGATIVE mean IC at 1d
(`point_ic`=-0.0244, cross-sectional-neutral `ci_lower`=-0.0174, does not clear zero) -- the
opposite of its validated positive behavior at 15m (Phase 167's live Gate 1/Gate 2 both
PASSED using this exact feature at this tf). Unexplained timeframe instability
(short-horizon-momentum/long-horizon-reversal is one plausible, unconfirmed explanation).

## Next step

**Todo 183's recompute completed 2026-07-27T21:55 UTC** (the ~9GB it was holding is freed;
host has ~20GB free as of this writing — re-verify via `free -h` before running, but the
deferral reason is gone). Rerun the same pipeline at `_TF="15m"` with an
appropriately recalibrated embargo (this project's `alpha.ic.bootstrap_block_size.15m`=26,
vs. 1d's/1h's 10) and row floor. Reuse `t5_nonlinear_combiner_replication_1d.py`'s structure
(imports `_train_and_predict_oos`/`_per_symbol_ic_ci` from the original 1h script, overrides
its module-globals explicitly -- see that script's own comments on why the override is
necessary, a real Python gotcha this session caught before it silently ran the wrong embargo).

If the 15m result shows a magnitude closer to the 1h finding than the 1d one, that would be
meaningful evidence the effect is tf-dependent in a specific, not-yet-understood way rather than
simply an artifact that shrinks with lower-frequency data in general.
