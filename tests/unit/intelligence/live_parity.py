"""The streaming replay of FeatureFactory for the tests that still read `compute()` (live path).

The replay runs the per-bar order of the live pipeline: from bar 1, update_session_vp and
update_session_levels, then compute(), then advance_bar(). It does not refresh the regime cache.
Fixtures pass UTC-aware timestamps and float prices. The batch path it was once compared with
(`FeatureFactory.compute_batch`) was deleted in R2 item 2; the corpus-rerun path is read through
`production_series`. This module goes with the streaming path (R2 item 5).

live_last() calls compute() once, on the last bar, instead of on every bar: linear in bar count
rather than quadratic. That equals the per-bar loop only if compute() leaves no state behind.
live_last() checks the cache is byte-identical across its call on every fixture that uses it."""

from __future__ import annotations

import math
import pickle

from src.intelligence.feature_factory import FeatureFactory
from src.intelligence.features.feature_factory_config import FeatureFactoryConfig
from src.intelligence.features.feature_vector import FeatureVector
from src.intelligence.features.kernels._cache_state import FeatureCache

_PARITY_TOL = 1e-6


def _apply_mutators(cache: FeatureCache, bar: dict, cfg: FeatureFactoryConfig) -> None:
    """The per-bar mutators compute_batch() runs before compute()."""
    cache.update_session_vp(bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"], cfg)
    cache.update_session_levels(bar["ts"], bar["open"], bar["high"], bar["low"], bar["close"], cfg)


def _advance(cache: FeatureCache, bar: dict) -> None:
    cache.advance_bar(bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"])


def live_per_bar(bars: list[dict], cfg: FeatureFactoryConfig) -> list[FeatureVector]:
    """compute() on every bar over the growing history, one vector per bar from bar 1."""
    cache = FeatureCache()
    out = []
    for i in range(1, len(bars)):
        _apply_mutators(cache, bars[i], cfg)
        out.append(FeatureFactory.compute(bars[: i + 1], "SPY", "5m", cache, cfg))
        _advance(cache, bars[i])
    return out


def live_last(bars: list[dict], cfg: FeatureFactoryConfig) -> FeatureVector:
    """The last vector of live_per_bar(), with compute() called only on the last bar."""
    assert len(bars) >= 2, "the replay starts at bar 1"
    cache = FeatureCache()
    for i in range(1, len(bars) - 1):
        _apply_mutators(cache, bars[i], cfg)
        _advance(cache, bars[i])
    _apply_mutators(cache, bars[-1], cfg)
    before = pickle.dumps(cache)
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)
    assert pickle.dumps(cache) == before, "compute() wrote the cache; live_last() is not live"
    return fv


def _same(b: float | None, s: float | None) -> bool:
    if b is None or s is None:
        return b is s
    if math.isnan(b) or math.isnan(s):
        return math.isnan(b) and math.isnan(s)
    return abs(b - s) < _PARITY_TOL
