# 004 — FeatureFactory compute() / compute_batch() Unification

**Priority: Medium — bug factory; every fix and feature add requires two edits**
**Gate: No dependency; can be done any time after Phase 141**
**Source:** `docs/plans/2026-06-26-renaissance-optimization-roadmap.md` (ARCH-002)

---

## Problem

`FeatureFactory` has two compute paths with ~95% duplicated logic:
- `compute()` — streaming path, returns single FeatureVector for last bar
- `compute_batch()` — backfill path, returns all FeatureVectors for the window

Both paths: build numpy arrays from bars, compute ATR/momentum/etc., apply guard fallbacks.
The only difference is `_zscore_last()` vs `_*_series_full()` for the final value extraction.

Every bug fix and every new feature requires editing both paths. This has already caused
divergence — the batch path had silent-constant bugs (CTF, VP/SR, HMM in Phase 140.5-P1)
that the streaming path did not, because they were maintained separately.

---

## Fix

Unify into a single `_compute_all(bars, ...)` that runs all series functions once, then
extract at the required index:

```python
class FeatureFactory:
    @staticmethod
    def compute(bars, symbol, tf, cache, config) -> FeatureVector:
        """Streaming: return FeatureVector for last bar."""
        all_vectors = FeatureFactory._compute_all(bars, symbol, tf, cache, config)
        return all_vectors[-1] if all_vectors else _cold_start_vector(cache, tf)

    @staticmethod
    def compute_batch(bars, symbol, tf, cache, config) -> list[tuple[datetime, FeatureVector]]:
        """Batch: return all (bar_ts, FeatureVector) pairs."""
        return FeatureFactory._compute_all(bars, symbol, tf, cache, config, return_all=True)

    @staticmethod
    def _compute_all(bars, symbol, tf, cache, config, return_all=False):
        """Single shared implementation. All series computed once."""
        ...
```

The `_*_series_full()` functions already compute the full array cheaply — extracting
`[-1]` for streaming is O(1). No performance regression in streaming mode.

---

## Scope

- `src/intelligence/feature_factory.py` — unify into `_compute_all()` private method
- `services/backfill_feature_factory.py` — no change needed (calls compute_batch)
- All tests continue to pass — externally identical behavior

This also eliminates the risk of future streaming/batch divergence on new features.
