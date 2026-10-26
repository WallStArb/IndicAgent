"""Live-versus-batch parity for FeatureFactory: one replay and one assertion for every primitive
test that checks a forgotten compute_batch() wiring update.

The replay follows compute_batch()'s per-bar order: from bar 1, update_session_vp,
update_overnight_range and update_session_levels, then compute(), then advance_bar(). It does
not refresh the regime cache, so the regime fields (and the products built on them) are outside
what these helpers can compare. Fixtures pass UTC-aware timestamps and float prices, which
compute_batch() would otherwise normalise first.

live_last() calls compute() once, on the last bar, instead of on every bar: linear in bar count
rather than quadratic. That equals the per-bar loop only if compute() leaves no state behind.
live_last() checks the cache is byte-identical across its call on every fixture that uses it;
test_per_bar_compute_equals_the_single_call_replay covers state kept anywhere else.
"""

from __future__ import annotations

import math
import pickle

from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
from src.intelligence.features.kernels._cache_state import FeatureCache
from src.intelligence.schemas import FeatureVector

_PARITY_TOL = 1e-6


def _apply_mutators(cache: FeatureCache, bar: dict, cfg: FeatureFactoryConfig) -> None:
    """The per-bar mutators compute_batch() runs before compute()."""
    cache.update_session_vp(bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"], cfg)
    cache.update_overnight_range(bar["ts"], bar["high"], bar["low"], cfg)
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


def batch_last(bars: list[dict], cfg: FeatureFactoryConfig) -> FeatureVector:
    """The final FeatureVector compute_batch() produces over `bars`."""
    return FeatureFactory.compute_batch(bars, "SPY", "5m", FeatureCache(), cfg)[-1][1]


def _same(b: float | None, s: float | None) -> bool:
    if b is None or s is None:
        return b is s
    if math.isnan(b) or math.isnan(s):
        return math.isnan(b) and math.isnan(s)
    return abs(b - s) < _PARITY_TOL


def assert_live_batch_parity(
    fields: tuple[str, ...], fv_batch: FeatureVector, fv_live: FeatureVector
) -> None:
    """Every field agrees to 1e-6 (None with None, NaN with NaN). A derivation stuck on its
    fallback would agree trivially, so at least one field must carry a nonzero, finite value on
    the batch side; pass each field group in its own call so one group cannot vouch for
    another."""
    assert any(
        isinstance(v := getattr(fv_batch, f), float | int) and v != 0 and math.isfinite(v)
        for f in fields
    ), f"parity check is vacuous: {fields} carry no nonzero value on the batch side"
    differ = [
        f"{f}: batch={getattr(fv_batch, f)} live={getattr(fv_live, f)}"
        for f in fields
        if not _same(getattr(fv_batch, f), getattr(fv_live, f))
    ]
    assert not differ, "live and batch differ:\n" + "\n".join(differ)
