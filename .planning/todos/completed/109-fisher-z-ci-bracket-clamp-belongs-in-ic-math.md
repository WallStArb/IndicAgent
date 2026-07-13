---
**Created:** 2026-07-13
**Completed:** 2026-07-13
**Area:** statistics
**Type:** correctness (silent-wrong-answer prevention)
**Priority:** P2
**Effort:** S
**Benefit:** Closes the CI-bracket boundary guard gap at the two live persistence call sites
(`ensemble_ic_engine.py`, `ops_oos_holdout_eval.py`) that had no protection against a future
`_fisher_z_ci` regression producing a non-bracketing CI
**Risk:** low — pure-function relocation, generalized from scalar to vectorized, all existing
call sites keep the same signature
---

## Resolution (2026-07-13)

Fixed exactly as proposed: moved `_clamp_ci_to_ic` from `ops_ensemble_ablation.py` into
`src/intelligence/statistics/ic_math.py`, generalized from a scalar-only implementation to a
vectorized one (`np.nanmax` over the violation arrays so a single bad element in a multi-feature
batch still raises), and **folded the clamp directly into `_fisher_z_ci`** rather than exposing it
as a separate helper callers must remember to invoke — this was deliberately stronger than the
todo's own proposal, since a separate-helper design is exactly the shape that let the two
unguarded call sites go unnoticed in the first place.

- `ic_math.py`: `_CI_BOUNDARY_TOL = 1e-6` constant + vectorized `_clamp_ci_to_ic()` + `_fisher_z_ci`
  now clamps its own output before returning.
- `services/ensemble_ic_engine.py` and `scripts/ops/corpus/ops_oos_holdout_eval.py`: no code
  change needed — both call `_fisher_z_ci` directly and now get the guard automatically.
- `ops_ensemble_ablation.py`: removed its now-redundant local `_clamp_ci_to_ic`/`_CI_BOUNDARY_TOL`
  and the explicit second clamp call in `compute_arm_ic` (its own `_fisher_z_ci` call already
  returns a clamped bracket).
- Tests: added `test_ci_bracket_always_encompasses_ic_at_boundary` (IC=±1.0 boundary) and ported
  the two scalar clamp tests from `test_ensemble_ablation.py` into `test_fisher_z_ci.py`, plus a
  new vectorized-raise test, against `ic_math.py`'s function directly. Removed the now-dead
  `_clamp_ci_to_ic` import/tests from `test_ensemble_ablation.py`.
- Verified: 79/79 tests pass across `test_ensemble_ablation.py`, `test_fisher_z_ci.py`,
  `test_ensemble_ic_math.py`, `test_bootstrap_ic.py`; full `tests/unit/` suite green; ruff/black
  clean on all changed files.

# 109 — `_fisher_z_ci` CI-bracket boundary clamp should live in `ic_math.py`, not be reimplemented
per-caller

Filed 2026-07-13 from the `/simplify` altitude review of todo 084 (`ops_ensemble_ablation.py`).
See git history for the original filing text (finding, why-it-matters, and proposed-fix sections
unchanged by this resolution).
