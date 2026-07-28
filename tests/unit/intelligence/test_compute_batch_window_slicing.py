"""Regression guard: compute_batch()'s per-bar bounded-window features must stay
pinned to known-correct values.

Root cause this guards (perf pass, 2026-07-27, found via cProfile on SPY/5m's full
20-year history): compute_batch() already builds opens/highs/lows/closes/volumes as
numpy arrays once at the top of the function, but the per-bar loop used to rebuild 5
more numpy arrays from scratch via Python list comprehension over the raw bar dicts
-- on every single bar -- to get the same bounded window (MIN_WINDOW, feeding
cci/aroon/vol_ratio/cmf/range_position). Fixed by slicing the pre-built arrays
instead (w_opens = opens[window_start:i+1], etc.) -- same source data, same
indices, verified bit-identical against the pre-fix implementation across 700
synthetic bars / all 181 FeatureVector fields before landing.

This test pins exact golden values for the fields that depend on that window, so
a future change to this loop that reintroduces a slicing/indexing bug (off-by-one,
wrong array, stale window bound) fails loud instead of silently drifting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory
from tests.unit.services.test_backfill_feature_factory import _make_config


def _make_golden_bars(n: int = 150, seed: int = 7) -> list[dict]:
    rng = np.random.default_rng(seed)
    base = 50.0
    closes = base + np.cumsum(rng.normal(0, 0.3, n))
    bars = []
    ts0 = datetime(2021, 3, 1, 14, 30, tzinfo=UTC)
    for i in range(n):
        c = closes[i]
        o = c + rng.normal(0, 0.08)
        h = max(o, c) + abs(rng.normal(0, 0.1))
        lo = min(o, c) - abs(rng.normal(0, 0.1))
        v = abs(rng.normal(500_000, 100_000))
        bars.append(
            {
                "ts": ts0 + timedelta(minutes=5 * i),
                "open": float(o),
                "high": float(h),
                "low": float(lo),
                "close": float(c),
                "volume": float(v),
            }
        )
    return bars


# {row_index: {field: expected_value}}, captured from the verified-correct
# post-fix implementation (equivalence-checked against the pre-fix implementation
# across a separate 700-bar/181-field sweep, see commit message for the perf pass).
_GOLDEN: dict[int, dict[str, float]] = {
    0: {
        "cci_fast": 88.42981465277278,
        "cci_mid": 123.12464078191253,
        "cci_slow": 55.021154654117474,
        "aroon_fast": 0.8571428571428571,
        "aroon_slow": 0.52,
        "vol_ratio": 0.7756453487547087,
        "cmf": 0.03174057992542234,
        "range_position": 0.85006210727827,
        "bar_close_pos": 0.8260711743693807,
    },
    1: {
        "cci_fast": 55.497877491393915,
        "cci_mid": 97.90664806665188,
        "cci_slow": 53.83119780984339,
        "aroon_fast": 0.7142857142857143,
        "aroon_slow": 0.52,
        "vol_ratio": 0.8295621360199589,
        "cmf": -0.04504437773143851,
        "range_position": 0.7717616334287065,
        "bar_close_pos": 0.20747995701485947,
    },
    10: {
        "cci_fast": -36.09030484648288,
        "cci_mid": -32.260033880315085,
        "cci_slow": 37.368565418910904,
        "aroon_fast": -0.5000000000000001,
        "aroon_slow": 0.52,
        "vol_ratio": 1.2611255443251344,
        "cmf": -0.0039165367426294544,
        "range_position": 0.3368893591614053,
        "bar_close_pos": 0.6178717910896293,
    },
    89: {
        "cci_fast": 40.005865308642974,
        "cci_mid": 0.24454979483049233,
        "cci_slow": -56.50562425908791,
        "aroon_fast": -0.6428571428571429,
        "aroon_slow": -0.8,
        "vol_ratio": 1.0426654499551624,
        "cmf": 0.08717229489397522,
        "range_position": 0.5070106833926332,
        "bar_close_pos": 0.2772759753244578,
    },
}


@pytest.fixture(scope="module")
def golden_results():
    bars = _make_golden_bars()
    config = _make_config()
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(
        bars,
        "GOLD",
        "5m",
        cache,
        config,
        warm_up_bars=60,
        cross_asset_by_date={},
        ctf_by_ts=None,
        ctf_ts_list=None,
    )
    assert len(results) == 90, "synthetic fixture changed -- regenerate golden values"
    return results


@pytest.mark.parametrize("row_index", sorted(_GOLDEN.keys()))
def test_window_dependent_fields_match_golden_values(golden_results, row_index: int) -> None:
    _ts, fv = golden_results[row_index]
    expected = _GOLDEN[row_index]
    for field_name, expected_value in expected.items():
        actual_value = getattr(fv, field_name)
        assert actual_value == expected_value, (
            f"row {row_index} field={field_name}: expected {expected_value!r}, "
            f"got {actual_value!r} -- compute_batch()'s bounded-window slicing "
            f"(w_opens/w_highs/w_lows/w_closes/w_volumes) may have regressed"
        )


def test_window_slicing_matches_dict_reconstruction_at_arbitrary_offsets() -> None:
    """Direct proof of the equivalence property the fix relies on: slicing the
    pre-built arrays must equal what the old list-comprehension-from-dicts
    reconstruction would have produced, at several window boundaries."""
    bars = _make_golden_bars(n=100, seed=13)
    opens = np.array([b["open"] for b in bars], dtype=float)
    highs = np.array([b["high"] for b in bars], dtype=float)

    for i, window_start in [(5, 0), (50, 10), (99, 60)]:
        sliced_opens = opens[window_start : i + 1]
        sliced_highs = highs[window_start : i + 1]

        reconstructed_bars = bars[window_start : i + 1]
        reconstructed_opens = np.array([b["open"] for b in reconstructed_bars], dtype=float)
        reconstructed_highs = np.array([b["high"] for b in reconstructed_bars], dtype=float)

        assert np.array_equal(sliced_opens, reconstructed_opens)
        assert np.array_equal(sliced_highs, reconstructed_highs)
