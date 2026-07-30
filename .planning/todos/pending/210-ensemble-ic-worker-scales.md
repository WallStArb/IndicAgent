---
status: pending
priority: P2
filed: 2026-07-30
source: task reviewer finding during SDD execution of docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md
  Task 4 (services/ensemble_ic_engine.py's EnsembleICConfig mirror + audit)
---

# `_run_ensemble_ic_worker`'s per-scale loop still iterates the hardcoded flat `_SCALES`
# tuple, not `EnsembleICConfig.active_scales_for(tf)` -- wasted compute, not incorrect output

## Problem

The 2026-07-30 per-tf active-scale-set plan's own "Downstream sweep" step (Task 4, Step 7)
audited `services/ensemble_ic_engine.py`'s independent `_SCALES` constant, expecting exactly
2 usages (the definition + `_select_hold_bars_from_decay`'s `ordered_scales` line). Live grep
found a third: `services/ensemble_ic_engine.py:953`, inside `_run_ensemble_ic_worker`. For
every `(symbol, tf)` pair fetched from `forward_returns`/`ensemble_alpha`, this function
iterates `for scale in _SCALES:` unconditionally (all 4 scales, regardless of `tf`) and
attempts a full IC computation (rank-IC, walk-forward folds, HAC Sharpe) against
`returns_by_scale[scale]`.

This site was missed by both the original design spec's "Downstream sweep" section (which
only named the `_calibrate_hold_max_bars` decay walk for this file) and the implementation
plan's Task 6 text (which expected exactly 2 `_SCALES` occurrences in this file).

**Confirmed NOT a correctness bug** (Task 4's implementer traced this directly,
`services/ensemble_ic_engine.py:944-947`): `n_valid = int(valid_mask.sum()); if n_valid <
config.min_reliable_n: continue` short-circuits before any real computation for a
degenerate cell. For `tf='1h'`, `scale='slow'`/`'extended'` (0.000 measured
`forward_returns` completeness), `returns_sub` is all-NaN, `n_valid == 0`, and the loop
`continue`s immediately -- no row gets written, no wrong output. Same "silent-but-not-wrong,
wasted compute" characterization the design doc used for `ic_engine.py`'s pre-fix state --
just a smaller cost class here (array masking on an already-small per-cell N, not the
"249 features x CI computation" cost Task 3's fix eliminated).

## Fix

Gate `for scale in _SCALES:` (line ~953) to `for scale in config.active_scales_for(tf):`,
mirroring Task 3's fix in the sibling file exactly. Needs its own test (a mock-fetch test
asserting the 1h worker never attempts `slow`/`extended` computation at all, analogous to
Task 3's `test_compute_one_regime_cell_attributes_scales_correctly_for_reduced_tf`) and its
own review -- same shape and rigor as Task 3, just scoped to this one function.

## Sizing

Small, single-site, mechanical -- `EnsembleICConfig.active_scales_for(tf)` already exists
(added by Task 4 of the per-tf active-scale-set plan) and `config`/`tf` are already in scope
at this call site (confirmed by the implementer). Pure compute-waste reduction, not a
correctness fix -- lower urgency than todo 209, no drift risk since no wrong row is ever
written.

## References

- `docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md` -- the plan whose Task 4
  review surfaced this
- `services/ensemble_ic_engine.py:953` (`_run_ensemble_ic_worker`) -- the site to fix
- `services/ensemble_ic_engine.py:944-947` -- the existing `min_reliable_n` guard that
  prevents any incorrect output today
- `.planning/todos/pending/209-ops-vol-normalized-target-ab-scales.md` -- the sibling
  finding from Task 3's review (same defect class, different file)
