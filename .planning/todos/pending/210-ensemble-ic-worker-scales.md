---
status: pending
priority: P1
filed: 2026-07-30
source: task reviewer finding during SDD execution of docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md
  Task 4 (services/ensemble_ic_engine.py's EnsembleICConfig mirror + audit); premise
  corrected by the plan's final whole-branch review same day -- see Correction below
---

# `_run_ensemble_ic_worker`'s per-scale loop still iterates the hardcoded flat `_SCALES`
# tuple, not `EnsembleICConfig.active_scales_for(tf)` -- a real measurement-integrity risk,
# NOT wasted-compute-only as originally filed (see Correction, 2026-07-30)

## Correction (2026-07-30) -- original "not a correctness bug" ruling was wrong

Task 4's original investigation (below, kept for record) concluded this was compute-waste
only because `min_reliable_n` would short-circuit on all-NaN `returns_sub` for 1h's
excluded scales. **That premise is false.** The plan's final whole-branch review queried
live `forward_returns` for `tf='1h'`, `return_type='executable_open_to_open'`
(n=2,177,197):

| | value |
|---|---|
| `complete_slow` true | 0.0000 |
| `return_slow` NOT NULL | 0.9992 |
| `complete_extended` true | 0.0000 |
| `return_extended` NOT NULL | 0.9978 |

`forward_return_writer._build_forward_return_sql` populates `return_{scale}` whenever
`open_entry > 0 AND open_{scale} > 0` -- the same-ET-session completeness gate only sets
`complete_{scale}=false`, it never NULLs the return value itself. `ic_engine.py` correctly
gates on completeness (`valid_mask = scale_complete & np.isfinite(returns_scale)`) --
that's WHY 1h slow/extended yields nothing there. But `_run_ensemble_ic_worker`'s own gate
(`ensemble_ic_engine.py:944-947`) is `valid_mask = np.isfinite(alpha_sub) &
np.isfinite(returns_sub)` -- **no `complete_` term at all**. With ~99.9% of `return_slow`/
`return_extended` finite for 1h, `n_valid` clears `min_reliable_n=100` easily. Once
`ensemble_alpha` is repopulated (currently empty, 0 rows -- this is why nothing has gone
wrong YET), this loop will compute and write real `alpha_ensemble_ic` rows at 1h
lookahead 20/60 from returns that span the overnight session gap -- exactly the
non-executable, gap-contaminated return class Invariant 1 (`docs/foundation/
v3-north-star.md`) exists to exclude.

**Bumped P2 -> P1**: this is a latent measurement-integrity divergence, not a wasted-CPU
nice-to-have -- fix before `ensemble_alpha` next gets repopulated, not opportunistically.

## Problem (original 2026-07-30 filing, premise now corrected above)

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

Per the Correction above, gating the loop alone is necessary but arguably not sufficient --
worth also asking whether `_WORKER_FETCH_SQL`/`_POOLED_WORKER_FETCH_SQL`'s fetch should
join in `complete_{scale}` and mask on it directly (matching `ic_engine.py`'s own
discipline), rather than relying solely on the outer loop never reaching an excluded
scale. Decide at fix time whether the loop-gate alone closes the gap or whether the
finite-only `valid_mask` also needs the `complete_` term for defense in depth.

## Sizing

Small, single-site, mechanical -- `EnsembleICConfig.active_scales_for(tf)` already exists
(added by Task 4 of the per-tf active-scale-set plan) and `config`/`tf` are already in scope
at this call site (confirmed by the implementer). **Re-sized 2026-07-30 (see Correction):
this is a measurement-integrity fix, not compute-waste cleanup** -- prioritize accordingly,
ahead of todo 209 (which really is compute-waste-only, a standalone diagnostic script).

## References

- `docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md` -- the plan whose Task 4
  review surfaced this
- `services/ensemble_ic_engine.py:953` (`_run_ensemble_ic_worker`) -- the site to fix
- `services/ensemble_ic_engine.py:944-947` -- the existing `min_reliable_n` guard that
  prevents any incorrect output today
- `.planning/todos/pending/209-ops-vol-normalized-target-ab-scales.md` -- the sibling
  finding from Task 3's review (same defect class, different file)
