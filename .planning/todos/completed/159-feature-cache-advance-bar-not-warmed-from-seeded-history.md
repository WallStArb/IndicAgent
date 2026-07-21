# 159 — `FeatureCache.advance_bar()` state not warmed from seeded bar history at startup

**Status:** COMPLETE (2026-07-21) — `_get_cache()` now warms `above_wk_vwap` from
`self._bar_history` on cache creation (`services/feature_vector_pipeline.py`), 3 new regression
tests in `tests/unit/services/test_feature_vector_pipeline_cache_warmup.py`, all directly-relevant
test suites pass, ruff/black clean.

**Deliberate deviation from this todo's own "fix direction":** the suggested approach was to
replay `cache.advance_bar()` (bundled: `update_wk_vwap()` + `hmm_duration += 1.0`) for every
seeded historical bar. Implemented instead by calling `update_wk_vwap()` directly, NOT the
bundled `advance_bar()` — replaying `hmm_duration`'s unconditional increment across up to 199
buffered bars would set it to a plausibly-large, equally-fabricated value (a false claim of long
regime persistence) rather than a real bars-since-last-regime-change count, which isn't
recoverable without re-running HMM classification retroactively over the buffered window.
`hmm_duration` stays cold (0.0) on purpose, preserving the already-documented,
self-correcting-at-next-regime-change behavior this todo itself rated lower severity. Verified via
`refresh_regime()`'s reset logic (`feature_cache.py:121-123`): the reset only fires on a label
*change* relative to the cache's own prior label, so a fabricated large `hmm_duration` would not
self-correct any faster than a cold 0.0 does today — warming it would add a new silent-wrong-answer
risk without fixing the one this todo describes.

**Found:** 2026-07-20, via Codex peer review of the todo 158 fix (`cache.advance_bar()` added
to `services/feature_vector_pipeline.py`'s `_process_bar_compute`).

## What's wrong

Todo 158 fixed `above_wk_vwap`/`hmm_duration` being permanently frozen at their dataclass
defaults on the live path by adding `cache.advance_bar(...)` after `FeatureFactory.compute()`.
That call only fires going forward, per live bar, from whenever the pipeline starts computing.

`_seed_bar_history_from_db()` (`services/feature_vector_pipeline.py:686`, via
`BarHistorySeeder.seed()`) populates `self._bar_history` with up to 200 real historical bars
per (symbol, tf) at every pipeline startup — but never touches `FeatureCache`. `_get_cache()`
(`services/feature_vector_pipeline.py:168`) lazily creates a brand-new, fully-cold `FeatureCache()`
on first live bar. So after every restart (deploy, crash, contract roll), `above_wk_vwap` and
`hmm_duration` start from their defaults again instead of reflecting the already-available
seeded history — even though `_bar_history` has the data to compute them correctly.

**Contrast with regime fields:** `hmm_regime_prob`/`hurst`/`garch_ratio`/etc. self-heal within
`regime_cache_refresh_bars` (default 30) live bars after restart, because `refresh_regime()` is
called with the *full* current history window (`bars_dicts`, which includes the seeded bars) and
recomputes from scratch each time. `advance_bar()`'s fields don't self-heal the same way — they
accumulate incrementally, bar by bar, and only see bars that arrive after the cache object
itself was created.

## Impact

- `above_wk_vwap`: after every restart, the weekly VWAP accumulator (`_wk_tp_vol_sum`/
  `_wk_vol_sum`) starts at zero instead of reflecting the true week-to-date volume-weighted
  price. Every live bar until the next ISO week boundary (up to ~7 days) computes
  `above_wk_vwap` against an artificially truncated "week" that only includes bars since
  restart — silently wrong, not just stale, per CLAUDE.md's "silent wrong answers are worse
  than loud crashes."
- `hmm_duration`: resets to 0 at restart instead of the true bars-since-last-regime-change
  count. Self-corrects at the next actual regime change (which resets it anyway), so the error
  window is bounded by regime persistence, not a full week — lower severity than `above_wk_vwap`.

## Fix direction

Mirror `compute_batch()`'s own warm-up loop (`feature_factory.py:3748-3766`, which calls
`cache.advance_bar()` for every bar in the warm-up region before real computation begins).
Candidate approach: when `_get_cache()` creates a new `FeatureCache` for a (symbol, tf) that has
seeded history in `self._bar_history`, walk that history (excluding the bar about to be
processed via the normal `compute()` + `advance_bar()` path, to avoid double-counting) and call
`cache.advance_bar()` for each historical bar in chronological order before the first live
vector computes.

## References

- `services/feature_vector_pipeline.py:168` (`_get_cache` — lazy, cold `FeatureCache()`)
- `services/feature_vector_pipeline.py:686` (`_seed_bar_history_from_db` — populates
  `_bar_history` only, never touches cache)
- `services/feature_vector_pipeline.py:946` (todo 158's fix — the per-bar `advance_bar()` call
  this gap sits behind)
- `src/intelligence/feature_factory.py:3748-3766` (`compute_batch()`'s warm-up loop — the
  pattern to mirror)
- `src/intelligence/feature_cache.py:142-182` (`update_wk_vwap()`/`advance_bar()`)
