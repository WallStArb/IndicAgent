---
status: pending
priority: P2
filed: 2026-07-13
source: /simplify altitude review of todo 084 (ops_ensemble_ablation.py)
---

# `_fisher_z_ci` CI-bracket boundary clamp should live in `ic_math.py`, not be reimplemented per-caller

## Finding

`ops_ensemble_ablation.py`'s `compute_arm_ic` hardens against a real numerical
edge case in `_fisher_z_ci` (`src/intelligence/statistics/ic_math.py`): near
`IC = +-1.0`, the tanh/arctanh round-trip can produce a CI bound that falls a
few `1e-11` on the wrong side of the point estimate (observed magnitude ~8e-11).
The ablation script added `_clamp_ci_to_ic()` — a tolerance-gated helper that
clamps genuine float64 noise silently but raises loudly if the violation is
larger than noise (a real bug in `_fisher_z_ci`, not a numerical artifact).

This guard is specific to `_fisher_z_ci`'s own implementation, not to
ablation. **Two other live production call sites of `_fisher_z_ci` have no
such guard and write the unguarded, possibly-inconsistent CI straight into
persisted tables:**

- `services/ensemble_ic_engine.py:786-788` — writes `ic_ci_lower`/`ic_ci_upper`
  directly into `alpha_ensemble_ic`, no bracket check.
- `scripts/ops/corpus/ops_oos_holdout_eval.py:213` — same pattern.

Confirmed via direct read of both files (not just grep) during the /simplify
review — neither has any bracket-consistency check.

## Why this matters

Both of those tables' CI columns feed into gates and reports elsewhere in the
system (`alpha_ensemble_ic` in particular is read by the ensemble weight
comparison and decay-walk machinery). A future regression in `_fisher_z_ci`
(sign error, off-by-one in `n`) that produces a materially wrong, non-bracketing
CI would currently pass through silently at both sites — exactly the "silent
wrong answer" class of bug this project's principles treat as worse than a
loud crash. The ablation script's own review cycle caught and fixed this for
itself; the same defect is still live in the two call sites that actually
persist data.

## Proposed fix

Move the bracket-consistency check into `ic_math.py` itself — either folded
into `_fisher_z_ci` before it returns (raise on a violation larger than a
tight numerical-noise tolerance, clamp silently within it), or as a small
shared helper (e.g. `clamp_ci_to_point_estimate(ci_lower, ci_upper, ic, tol)`)
that all three callers (`ensemble_ic_engine.py`, `ops_oos_holdout_eval.py`,
`ops_ensemble_ablation.py`) apply uniformly. `ops_ensemble_ablation.py`'s
`_clamp_ci_to_ic` (module-local, `_CI_BOUNDARY_TOL = 1e-6`) is a working
reference implementation — the tolerance value and raise/clamp logic can be
lifted directly.

## Not yet done

Nothing built. This is a real finding, not yet actioned — deliberately not
fixed as part of todo 084's own diff, since it requires touching shared
production code (`ic_math.py`) plus two already-shipped services outside that
diff's scope, which needs its own review rather than riding along on an
unrelated ops-script cleanup pass.

## References

- `scripts/ops/alpha/ops_ensemble_ablation.py` — `_clamp_ci_to_ic` (reference
  implementation), `_CI_BOUNDARY_TOL` (the tolerance value and its provenance
  comment)
- `src/intelligence/statistics/ic_math.py` — `_fisher_z_ci`, the function this
  guard belongs next to
- `services/ensemble_ic_engine.py:786-788`, `scripts/ops/corpus/ops_oos_holdout_eval.py:213`
  — the two unguarded call sites
