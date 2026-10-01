---
status: completed
priority: P3
filed: 2026-09-30
source: plan 186-15 review (altitude); acceptance criterion for 186-25
---

# Kernels import their pure helpers from the legacy feature_cache

## What

`kernels/calendar.py`, `price.py`, `smc.py`, `vp_sr.py`, `macro.py` and `cross_tf.py` import from
`src/intelligence/feature_cache.py` (`FeatureCache`, `_HMM_K`, `_hmm_forward_step`,
`_zscore_from_deque`, the session value-area helpers). The registry layer depends on the module
the retirement of the cache-driven loop deletes, in the wrong direction: the new code should be
the base and the legacy cache should import from it.

## Options

1. Leave until `feature_cache.py` is deleted; the imports then break and get fixed.
2. Move the pure helpers (`_hmm_forward_step`, `_HMM_K`, the session helpers) into the kernels
   package (or a sibling module) in 186-25, and have `FeatureCache` import from kernels while it
   still exists.

## Recommendation

Option 2, added to 186-25's acceptance criteria (done in its PLAN.md: no `feature_cache` import
under `src/intelligence/features/kernels/`, checked by grep, and the AMD/session replay moves with
the helpers). The move is mechanical and bit-identical; the `_HMM_*` tables are also the APR
question in todo 472.

## Steps

1. Move the helpers; re-export nothing from `feature_cache`.
2. Point `FeatureCache` and the kernels at the new home.
3. Add the grep check to the class-naming style of tooling (a test that fails on the import).


## Closed 2026-10-01 (phase 186 plan 25)

Option 2, landed in commit 2770851da (the kernels-package move of FeatureCache and its pure
helpers): the session value-area and profile helpers, `_hmm_forward_step`, `_HMM_K` and
`_zscore_from_deque` live under `src/intelligence/features/kernels/`, `FeatureCache` (now
`kernels/_cache_state.py`) imports them from there, and no kernel module imports the legacy
cache (grep clean; outputs bit-identical against the golden fixture).
