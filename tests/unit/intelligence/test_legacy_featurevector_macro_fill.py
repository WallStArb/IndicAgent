"""The legacy FeatureVector path re-fabricates 0.0 for macro columns the kernels leave NaN.

Documents current behavior end to end so it fails loudly when phase 186 plan 25 changes it.
The kernel layer emits NaN for rows before the first daily record (186 review F9/B5a); the
legacy `_build_feature_vector` wraps the macro fields in `_guard(..., 0.0)` and FeatureVector
fields are non-nullable floats, so the persisted value is 0.0 (todo 463 covers the
nullable-field policy). When 186-25 removes those guards and writes NaN as NULL, the
`*_until_186_25` tests below must be replaced by "rebuilt early-history macro columns are
NULL, not 0.0, in feature_vectors".
"""

from __future__ import annotations

import numpy as np
from structlog.testing import capture_logs

from src.intelligence import feature_factory as ff
from src.intelligence.feature_factory import FeatureFactory
from src.intelligence.features.kernels._cache_state import FeatureCache
from src.intelligence.features.kernels.macro import (
    CROSS_ASSET_SYMBOLS,
    build_cross_asset_series,
    build_symbol_beta_series,
)
from tests.unit.intelligence import test_macro_alignment as tma

_GUARDED_MACRO_FIELDS = (
    "vix_z",
    "flight_quality",
    "yield_slope_z",
    "tip_tlt_ret_z",
    "hyg_lqd_ret_z",
    "sb_corr_fast",
    "sb_corr_slow",
    "sb_corr_z",
)
_PRODUCTS = ("yield_slope_momentum_product", "vix_reversion_product")


def _early_history_case():
    """Intraday sessions 70-74 have no daily record yet (records start at session 75)."""
    bars, daily = tma._intraday(), tma._daily_bars()
    late = {s: series[tma.TARGET_SESSION :] for s, series in daily.items()}
    n_early = tma.BARS_PER_SESSION * (tma.TARGET_SESSION - tma.INTRADAY_SESSIONS.start)
    return bars, late, n_early


def _legacy_batch(bars, late):
    cross = build_cross_asset_series(*(late[s] for s in CROSS_ASSET_SYMBOLS), tma.CONFIG)
    beta = build_symbol_beta_series(
        late[tma.SYMBOL], late["SPY"], late["TLT"], tma.SYMBOL, tma.CONFIG
    )
    ff._GUARD_COUNTED_SUBSTITUTIONS.clear()
    results = FeatureFactory.compute_batch(
        bars,
        tma.SYMBOL,
        "5m",
        FeatureCache(),
        tma.CONFIG,
        cross_asset_by_date=cross,
        beta_by_date=beta,
    )
    return results


def test_kernel_layer_is_nan_and_legacy_featurevector_is_zero_until_186_25():
    bars, late, n_early = _early_history_case()
    kernel = tma._macro_outputs(late, bars)
    for name in _GUARDED_MACRO_FIELDS:
        assert np.isnan(kernel[name][:n_early]).all(), f"kernel {name} must be NaN"
    results = _legacy_batch(bars, late)
    for name in _GUARDED_MACRO_FIELDS:
        legacy = [getattr(fv, name) for _, fv in results[:n_early]]
        assert legacy == [0.0] * n_early, f"legacy FeatureVector {name} must re-fabricate 0.0"


def test_missing_macro_input_does_not_fire_the_guard_counted_tripwire_until_186_25():
    """The products of a missing cross-asset input are missing data, not a numerical anomaly:
    the substituted value stays 0.0 on the legacy path, but the counter stays silent."""
    bars, late, n_early = _early_history_case()
    with capture_logs() as logs:  # compute_batch reports and clears the counter at its end
        results = _legacy_batch(bars, late)
    for name in _PRODUCTS:
        assert [getattr(fv, name) for _, fv in results[:n_early]] == [0.0] * n_early
    fired = [e for e in logs if e["event"] == "theory_interaction_guard_substitutions"]
    assert fired == [], fired


def test_guard_counted_still_fires_when_the_inputs_are_finite_and_the_product_is_not():
    ff._GUARD_COUNTED_SUBSTITUTIONS.clear()
    assert ff._guard_counted(float("inf"), "vix_reversion_product", inputs=(1.0, 2.0)) == 0.0
    assert ff._GUARD_COUNTED_SUBSTITUTIONS == {"vix_reversion_product": 1}
    assert (
        ff._guard_counted(float("nan"), "vix_reversion_product", inputs=(float("nan"), 2.0)) == 0.0
    )
    assert ff._GUARD_COUNTED_SUBSTITUTIONS == {"vix_reversion_product": 1}
    ff._GUARD_COUNTED_SUBSTITUTIONS.clear()
