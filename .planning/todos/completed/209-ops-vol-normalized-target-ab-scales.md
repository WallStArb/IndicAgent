---
status: completed
priority: P2
filed: 2026-07-30
completed: 2026-07-30
source: task reviewer finding during SDD execution of docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md
  Task 3 (services/ic_engine.py's 12 _SCALES call-site substitution)
---

**CLOSED 2026-07-30** — migrated to a new `_load_active_scales` helper (reads
`alpha.ic.active_scales.{tf}` from `config_state` directly, matching this script's existing
`_load_config_int`/`_load_config_float` pattern, then `canonicalize_active_scales`). Threaded a
new `scales`/`scales_by_tf` parameter through `_fetch_pooled_arrays`/`_evaluate_stratum`/`main()`,
replacing all 5 `_SCALES` call sites. 3 new unit tests
(`tests/unit/scripts/test_ops_vol_normalized_target_ab.py`). Full suite green.

# `ops_vol_normalized_target_ab.py` (Component F) still reads the flat, uniform-across-tfs
# `_SCALES` tuple directly -- now silently drifts from what `ic_engine.py` actually computes

## Problem

The 2026-07-30 per-tf active-scale-set design (`docs/superpowers/plans/2026-07-30-per-tf-
active-scale-set.md`, `docs/superpowers/specs/2026-07-30-per-tf-active-scale-set-design.md`)
replaced `ic_engine.py`'s hardcoded global `_SCALES = ("fast","mid","slow","extended")`
with a per-tf `active_scales_for(tf)` resolver, sourced from a new APR key
`alpha.ic.active_scales.{tf}` (`ACTIVE_SCALES_FALLBACKS_BY_TF` in `services/_batch_utils.py`).
Live default for `1h`: `("fast", "mid")` only -- `ic_engine.py` no longer attempts (or
writes rows for) 1h's `slow`/`extended` tiers, which had 0.000 measured completeness under
the same-ET-session gate.

`scripts/ops/alpha/ops_vol_normalized_target_ab.py` (lines 85, 192-193, 204, 224, 332 as of
this writing) imports and uses its OWN independent flat `_SCALES` tuple, in the identical
build-matrix/consume-by-positional-index pattern that was just fixed inside `ic_engine.py`
for exactly this reason. This script was not in scope for the per-tf active-scale-set plan
(that plan deliberately scoped to `ic_engine.py`/`ensemble_ic_engine.py` only) -- found as a
review finding during Task 3's implementation, not fixed there.

**Concrete drift risk:** this script (Component F, Phase 143.1's vol-normalized-target A/B
comparison) will still fetch/compare all 4 scales for 1h even though `ic_engine.py` no
longer computes/writes rows for two of them -- either silently reading stale/absent rows
for those cells, or (if it queries `feature_ic_scores` directly) getting nothing back for
`1h`'s `slow`/`extended` and needing to handle that gracefully, which it was never designed
to do since the assumption "every tf has 4 real scales" was baked in at authoring time.

## Fix

Migrate `ops_vol_normalized_target_ab.py`'s scale iteration to
`ICEngineConfig.active_scales_for(tf)` (or the equivalent shared resolver), matching the
pattern `ic_engine.py`'s own 12 call sites now use. Scoped, mechanical -- same shape as
Task 3 of the per-tf active-scale-set plan, just applied to one more file.

## Sizing

Small, single-file, mechanical -- same pattern already proven in `ic_engine.py`. Worth a
grep sweep (`grep -rln "_SCALES\b" scripts/ src/` -- not just this one file) before starting,
in case other analysis/ops scripts have the same independent copy-paste of the flat tuple.

## References

- `docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md` -- the plan whose Task 3
  review surfaced this
- `services/ic_engine.py`'s `active_scales_for(tf)` method -- the resolver to migrate to
- `services/_batch_utils.py`'s `ACTIVE_SCALES_FALLBACKS_BY_TF` -- live per-tf default,
  `1h` = `("fast","mid")`
