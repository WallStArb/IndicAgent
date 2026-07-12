---
status: pending
priority: P2
filed: 2026-07-12
source: found incidentally while scoping todo 072 (crowding proxy regression) - needed to confirm
  momentum_z_slow's lookback window before deciding whether to reuse it as a public-factor proxy
---

# `feature.momentum.window_fast/mid/slow` APR keys are silently inert — prewarm list never loads them

## Finding

`FeatureFactoryConfig` (`services/feature_vector_pipeline.py:559-580`) reads
`feature.momentum.window_fast/mid/slow` via `ConfigService.get_sync()`, which only reads from an
in-memory cache populated during `_prewarm_threshold_config()`. But `_THRESHOLD_KEYS`
(`feature_vector_pipeline.py:445-447`) prewarms `feature.momentum.window_short` and
`feature.momentum.window_long` — keys that don't exist anywhere in `config_state` — instead of
the `_fast/_mid/_slow` keys the config object actually reads. `zscore_window` is correctly
prewarmed.

Net effect: every `get_sync()` call for `window_fast/mid/slow` misses cache and silently falls
through to the hardcoded Python defaults (5/20/60), regardless of what's stored in
`config_state`. This has been invisible because the seeded DB values happen to equal the code
defaults (`config_history` has zero rows for these three keys — they were seeded, never actually
applied via `ConfigService.set()`). **Changing these three APR keys today has zero effect on the
running pipeline.**

`momentum_z_slow` is also not an academic "12-1" style momentum (no month-skip/gap) — it's a
flat 60-bar log-return z-scored over a 252-bar window, same construction as `momentum_z_fast`
(5-bar) and `momentum_z_mid` (20-bar), just the longest of the three. And the same bar-count
window applies to every timeframe (1m/5m/15m/1h/1d) — 60 bars means 60 minutes on 1m but 60 days
on 1d, since `FeatureFactoryConfig` is built once and reused across all `(symbol, tf)` pairs
(`services/feature_vector_pipeline.py:906`), not scaled per-timeframe.

Separately, `volatility_rank_z` is not implemented at all — hardcoded `None` at
`feature_factory.py:3375,4421`, per an unactioned "Phase 139 enrichment pass" comment. Every row
in `feature_vectors.volatility_rank_z` is NULL. `momentum_rank_z` and `volume_rank_z` are in the
same unbuilt state (cross-sectional rank columns, not yet populated by anything).

## Not yet done

- Fix options: (a) add the correct `_fast/_mid/_slow` keys to `_THRESHOLD_KEYS`, verify the live
  `config_state` values match intent, remove the dead `_short`/`_long` prewarm entries; (b)
  separately decide whether `momentum_z_slow` should become a genuine month-skip momentum
  (academic 12-1 style) or stay as-is with a corrected doc comment — current schema docstring
  ("slow-scale return z-score") doesn't claim to be academic 12-1, so this may just need the APR
  wiring fixed, not the formula changed.
- `volatility_rank_z`/`momentum_rank_z`/`volume_rank_z`: decide whether Phase 139's cross-sectional
  rank enrichment is still planned or should be removed as dead schema (3 permanently-NULL
  columns is itself worth resolving one way or the other).
- Not fixed in this session — found while researching a different todo (072), out of scope to
  touch `feature_vector_pipeline.py`/`feature_factory.py` (live hot-path code) without dedicated
  planning and test coverage.

## References

- `services/feature_vector_pipeline.py:445-447` (`_THRESHOLD_KEYS`), `:559-580`
  (`FeatureFactoryConfig` construction), `:906` (single shared config reused across all tf)
- `src/intelligence/feature_factory.py:1733-1752` (`_momentum_z_series_full`,
  `_momentum_reversal_z_series_full`), `:2940-2943` (call sites), `:3375,4421`
  (`volatility_rank_z = None`)
- `src/intelligence/schemas.py:1248-1249,1482` (field docstrings)
- `src/config/config_service.py:99-105` (`get_sync()` cache-only read)
