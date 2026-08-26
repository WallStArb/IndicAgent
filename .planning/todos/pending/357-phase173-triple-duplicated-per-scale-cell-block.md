---
priority: P2
status: pending
source: /simplify pass on Phase 173's diff, 2026-08-26 (4 parallel reuse/simplification/
  efficiency/altitude review agents; reuse and simplification agents independently found the
  same issue)
---

# `_compute_one_broadcast_cell` is a third near-identical copy of an existing ~140-line
# per-scale block (subsample → rank → IC/CI/walk-forward → rolling metrics → row emission)

## What

`services/ic_engine.py`'s new `_compute_one_broadcast_cell` (Phase 173, ~lines 3273-3658)
duplicates the per-scale loop body already present twice: `_compute_one_cross_sectional_cell`
(~3095-3269) and `_compute_one_regime_cell` (~2378-2428). All three call `_subsample_and_rank`
with the identical kwarg shape, build `wf_pass_full`/`passes_wf_full` from `fold_ics_list`
identically, call `_compute_ic_rolling_metrics` identically, and emit the same ~28-key row dict
— differing only in mask variable name (`cluster_input_mask`/`non_degenerate_mask`/broadcast
equivalent), array length (`n_features` vs `n_broadcast`), and feature-name lookup.

This duplication existed twice before Phase 173 (pre-existing tech debt); Phase 173 added a
third copy following the file's own established pattern rather than introducing a new problem.

## Why not fixed inline during /simplify

Extracting a shared helper (e.g. `_expand_scale_metrics(...)`) that all three cell functions
call would touch `_compute_one_cross_sectional_cell` and `_compute_one_regime_cell` — both
already-shipped, live-tested, production functions on the significance-gate hot path, one of
which (`_compute_one_cross_sectional_cell`) has the documented 2026-07-08 OOM history. A
behavior-preserving extraction across three cell functions needs the same live-corpus
verification discipline Phase 173's own Plan 04 used (smoke run + peak-RSS check), not a
mechanical same-session cleanup. Deferred to a dedicated session with that budget.

## Recommendation

Factor the shared per-scale block into one helper taking the mask/count/feature-name-lookup as
parameters; all three cell functions call it. Real DRY payoff (a future rolling-metrics fix or
new decomposition column currently needs 3 edit sites, silently divergeable) but not urgent —
none of the three copies is currently buggy.
