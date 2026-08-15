# 320 - Velocity Primitives Extension: rsi/ofi/cvd/volume 2nd-derivative fields -- implemented and closed same session

**Filed:** 2026-08-15
**Source:** User asked whether the corpus tracks "acceleration" (2nd-derivative) primitives, and
whether there was data worth adding. Investigation found the Phase 151 Plan 01 Task 2 velocity
construction (`_vol_velocity_z_series_full` -- first-difference-then-re-z-score of an
already-computed z-score series) had only been applied to 4 fields
(`momentum_z_velocity_fast/mid/slow`, `vwap_dev_sigma_velocity`) plus `vol_velocity_z` (atr_z).
Six comparable source fields never got the same treatment: `rsi_fast/mid/slow`, `ofi_z`,
`cvd_slope_z`, `volume_z`. User confirmed "implement now" over drafting a discovery-track idea doc
first.

## What shipped

6 new `feature_vectors` columns (`real`, migration 316), reusing the existing generic helper
byte-identically (no new compute mechanism):

- `rsi_velocity_fast` / `rsi_velocity_mid` / `rsi_velocity_slow` -- zscore(diff(rsi_fast/mid/slow)),
  one shared APR window (`feature.rsi_velocity.window`, seeded 14), matching
  `feature.momentum_velocity.window`'s own one-key-for-3-gradients precedent.
- `ofi_z_velocity` -- zscore(diff(ofi_z)), `feature.ofi_velocity.window`.
- `cvd_slope_z_velocity` -- zscore(diff(cvd_slope_z)), `feature.cvd_velocity.window`.
- `volume_z_velocity` -- zscore(diff(volume_z)), `feature.volume_velocity.window`. Closes a real
  naming/quality gap: the only prior volume-rate proxy was `vol_acceleration`, a crude 1-bar
  `V_t/V_{t-1}` ratio, not a proper z-scored velocity like every other `_velocity` field.

`FeatureVector` (`src/intelligence/schemas.py`) grew 292 -> 298 fields. Full wiring: `_PrecomputedSeries`
dataclass + `_precompute_series()` (batch), `_build_feature_vector()` signature + construction,
`compute()` streaming path, `compute_batch()` backfill loop, `_cold_start_vector()` fallback,
`FEATURE_VECTOR_DOMAIN` registry (all tagged `"quant"`), `FeatureFactoryConfig` (4 new APR-backed
window fields), both production config-loading call sites (`feature_vector_pipeline.py`'s
`_THRESHOLD_KEYS` prewarm registry AND `backfill_feature_factory.py`), `feature_vector_persistence.py`
(new `_VELOCITY_EXTENSION_FIELD_NAMES` slice, 301 -> 307 INSERT columns), migration 316
(6 columns + 4 APR keys + `concept_registry`/`concept_gate` rows seeded directly -- `feature_registry`
no longer exists, migration 311 dropped it).

**Scoped out, not shipped:** `adx_velocity`. ADX has no precomputed full-history array in
`_precompute_series` -- it's sourced from `cache.adx`, a stateful incremental indicator external to
the vectorized batch path. Reusing `_vol_velocity_z_series_full` on it needs a new
`_adx_series_full()` vectorized implementation first (ADX depends on the already-vectorized ATR
series under the hood, so this is plausible, just a separate task -- not a clean application of the
existing pattern like the 6 fields that shipped).

## Verification

Full `tests/unit/` suite green after fixing every hardcoded field/column-count assertion this
touched (a real, recurring failure class in this codebase -- `FEATURE_VECTOR_DOMAIN` completeness
count, `_record_to_insert_params`/`feature_vector_to_insert_params` tuple-length assertions in 3
separate test files, the `test_every_key_read_building_feature_factory_config_is_prewarmed` gate
in `test_feature_vector_pipeline_threshold_keys.py` which caught a genuinely missing
`_THRESHOLD_KEYS` entry -- without it the 4 new APR keys would have silently cache-missed and
ignored `config_state` edits forever). 15 test files' `FeatureFactoryConfig(...)` direct-construction
call sites updated with the 4 new non-defaulted config fields, matching this codebase's own
"non-defaulted, every construction site wired in the same plan" precedent for velocity-window APR
fields.

## Status: not yet run against the corpus

Migration 316 applied (queued briefly behind an unrelated pre-existing `compress_chunk` background
job holding a lock on `feature_vectors` -- not killed, per the compression-policy-deadlock
precedent in the disk-full-incident history). The 6 new columns are 100% NULL on all existing rows
until the next `backfill_feature_factory.py --refresh` or live pipeline pass recomputes them --
same "not yet run" status as every other Phase 151 field until the corpus pipeline's next full
pass. `ensemble_trainer.py`'s `_assert_concept_registry_alignment` gate (crash-loud schema-parity
check between `concept_registry(domain='feature')` JOIN `concept_gate` and
`dataclasses.fields(FeatureVector)`) will pass on the next run since migration 316 seeded matching
`concept_registry`/`concept_gate` rows for all 6 new fields.

Not evaluated for predictive value -- these are Stage-0 atomic primitives (tier `'0_atomic'`),
same falsification bar as any other candidate: cheap to compute, unproven until an IC/Sharpe pass
runs and clears the gate. Given the discovery track's 4/4-dead track record on prior candidates,
don't assume acceleration terms are useful without measurement.
