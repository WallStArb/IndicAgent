"""The legacy FeatureVector path re-fabricates 0.0 for macro columns the kernels leave NaN.

Phase 186 plan 25 removed the legacy path from the rebuild: rows reach feature_vectors_v2
through `feature_vector_v2_row_values`, which maps a missing macro value (the kernels' NaN
before the first daily record, 186 review F9/B5a) to NULL, never 0.0 and never the text NaN.
The legacy `FeatureFactory._build_feature_vector` still serves the live pipeline until the
186-27 swap and keeps its `_guard(..., 0.0)` re-fabrication (todo 463 owns the nullable-field
policy there); the tests below pin that quarantine: the quarantined path's behavior is
unchanged, and the rebuild never runs through it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from structlog.testing import capture_logs

from src.intelligence import feature_factory as ff
from src.intelligence.feature_factory import FeatureFactory
from src.intelligence.features.feature_vector_persistence import (
    feature_vector_v2_row_values,
    feature_vectors_v2_numeric_columns,
)
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


def test_kernel_layer_is_nan_and_the_quarantined_legacy_vector_is_zero():
    bars, late, n_early = _early_history_case()
    kernel = tma._macro_outputs(late, bars)
    for name in _GUARDED_MACRO_FIELDS:
        assert np.isnan(kernel[name][:n_early]).all(), f"kernel {name} must be NaN"
    results = _legacy_batch(bars, late)
    for name in _GUARDED_MACRO_FIELDS:
        legacy = [getattr(fv, name) for _, fv in results[:n_early]]
        assert legacy == [0.0] * n_early, f"quarantined legacy FeatureVector {name} stays 0.0"


def test_missing_macro_input_does_not_fire_the_guard_counted_tripwire():
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


def test_the_rebuild_row_builder_writes_the_early_nan_as_null_not_zero():
    """The v2 row builder maps the kernels' NaN to None (NULL after COPY); the guarded 0.0 of
    the quarantined legacy path never reaches it because the rebuild never calls it."""
    numeric_names = feature_vectors_v2_numeric_columns()
    numeric = [1.0] * len(numeric_names)
    for name in ("vix_z", "tip_tlt_ret_z", "hyg_lqd_ret_z", "equity_beta_z"):
        numeric[numeric_names.index(name)] = np.float32("nan")
    row = feature_vector_v2_row_values(
        "QQQ", "5m", tma._row_ts(tma.TARGET_SESSION, 14, 0), None, None, numeric
    )
    values = row[5:]
    for name in ("vix_z", "tip_tlt_ret_z", "hyg_lqd_ret_z", "equity_beta_z"):
        assert values[numeric_names.index(name)] is None, name

    import services.backfill_feature_factory as bff

    rebuild_source = Path(bff.__file__).read_text()
    forbidden = ("FeatureFactory.compute", "build_feature_vector_row", "validate_feature_vector")
    for needle in forbidden:
        assert needle not in rebuild_source, needle
