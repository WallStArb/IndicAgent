# 321 - No shared FeatureFactoryConfig test builder -- ~90-kwarg literal hand-typed independently in 15+ test files

**Filed:** 2026-08-15
**Source:** `/simplify` altitude review during todo 320's (Velocity Primitives Extension) cleanup
pass. Not a defect in todo 320's diff -- a pre-existing pattern that diff was forced to extend.

## What

`FeatureFactoryConfig` (`src/intelligence/feature_factory.py`) is a frozen dataclass with ~95
non-defaulted fields. Every test file that needs a `FeatureFactory.compute()`/`compute_batch()`
call defines its own local `_make_cfg`/`_make_config` function that hand-types the full
`FeatureFactoryConfig(...)` kwarg literal from scratch. No shared builder/fixture exists anywhere
in the repo (checked: no `tests/unit/intelligence/conftest.py` fixture, no
`make_feature_factory_config`-style helper).

15+ files carry an independent copy of this literal:
`tests/unit/intelligence/test_feature_factory_batch_parity.py`, `test_feature_factory_p7.py`,
`test_smc_amd_cycle.py`, `test_smc_fvg.py`, `test_smc_liquidity.py`, `test_smc_order_blocks.py`,
`test_smc_structure.py`, `test_smc_zones.py`, `test_support_resistance_primitives.py`,
`test_swing_fib_trend_structure_primitives.py`, `test_volume_profile_primitives.py`,
`tests/unit/pipeline/pipeline_helpers.py`, `tests/unit/services/test_backfill_feature_factory.py`,
`tests/unit/test_canary_predictors.py`, `tests/unit/test_feature_factory.py`.

## Why this matters

Every time a field is added to `FeatureFactoryConfig` -- which per that file's own docstring
history has happened repeatedly (Phase 151 Plans 01/03/04/05/06, now todo 320) -- the identical
4-6-line mechanical edit must be manually replayed across all 15+ files. Todo 320's diff is itself
the evidence: a multi-hundred-line block of mechanically-identical hunks, one per file, adding the
same 4 new kwargs (`rsi_velocity_window`, `ofi_velocity_window`, `cvd_velocity_window`,
`volume_velocity_window`) everywhere. This is pure toil and a growing drift surface -- a file that
forgets the mechanical edit fails loudly (missing-kwarg `TypeError`, not a silent bug), but the
toil cost keeps compounding every time `FeatureFactoryConfig` grows.

## Fix

Add a single shared builder -- `tests/unit/intelligence/conftest.py` (or
`tests/support/feature_factory_config.py`) exposing
`default_feature_factory_config(**overrides) -> FeatureFactoryConfig` with the full default kwarg
set defined exactly once. Convert each file's local `_make_cfg`/`_make_config` into a thin wrapper
around it (or delete it in favor of direct imports where no per-file overrides are needed). Future
field additions to `FeatureFactoryConfig` then touch one file instead of 15+.

Not urgent (each site fails loudly, not silently, if forgotten) -- but worth doing before the next
Phase adds more fields and the file count grows further.
