---
status: pending
priority: P3
found_during: phase-151-code-review
found_date: 2026-08-05
---

# _guard_counted's observable-tripwire guarantee only holds on the batch path (151-REVIEW.md WR-04)

## What

`_guard_counted()` (`src/intelligence/feature_factory.py`) is designed to make a non-finite
substitution "OBSERVABLE rather than a silent collapse" for the 10 Theory-Motivated
Interaction compounds (Phase 151 Plan 06). That guarantee only holds for the batch path:
`_report_guard_counted_substitutions()` (the function that logs and resets the counter) is
called exactly once, from `compute_batch()`. The live daemon (`FeatureVectorPipeline`) only
ever calls `compute()`, which increments the same module-level `_GUARD_COUNTED_SUBSTITUTIONS`
dict but never reports it -- a live-path substitution silently accumulates in a counter no
operator ever sees.

## Impact

Low likelihood (the design doc argues a float64 product of two z-scores essentially cannot
overflow) but if it ever fires live, there is currently no way to know without attaching a
debugger to a running process. Live IBKR ingestion is currently intentionally stopped, so
this has no live-data blast radius today -- same operational context as todos 261/264.

## Fix options

1. Call `_report_guard_counted_substitutions()` periodically from `FeatureVectorPipeline`
   (e.g. alongside its existing periodic regime-cache refresh).
2. Emit the OTel counter this project already has infrastructure for
   (`src/observability/metrics.py`) directly from `_guard_counted()` on both paths, rather
   than relying on a batch-only log-and-reset call -- probably the better fix, since it
   doesn't require touching `FeatureVectorPipeline`'s internals at all.

## References

- `.planning/phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-REVIEW.md` WR-04 -- full finding detail
- `src/intelligence/feature_factory.py` -- `_guard_counted`/`_report_guard_counted_substitutions`/`_GUARD_COUNTED_SUBSTITUTIONS`
