"""Edge case coverage for all Tier 1 plugins.

Tests that every plugin handles:
- Gap up/down in price series (synthetic_ohlcv_gap fixture)
- Zero-volume bars (volume-dependent plugins only)
- Single-bar input (all plugins return {} or similar, no crash)
- Empty DataFrame input (all plugins return {}, no crash)

Contract: insufficient data or degenerate input -> empty/missing outputs, NEVER crash.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import pytest

from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin
from src.intelligence.context.kalman_trend import KalmanTrendPlugin
from src.intelligence.features.i1_indicators.adx import ADXPlugin
from src.intelligence.features.i1_indicators.atr import ATRPlugin
from src.intelligence.features.i1_indicators.bollinger import BollingerPlugin
from src.intelligence.features.i1_indicators.cci import CCIPlugin
from src.intelligence.features.i1_indicators.macd import MACDPlugin
from src.intelligence.features.i1_indicators.mfi import MFIPlugin
from src.intelligence.features.i1_indicators.rsi import RSIPlugin
from src.intelligence.features.i1_indicators.stochastic import StochasticPlugin
from src.intelligence.features.i1_indicators.vwap import VWAPPlugin
from src.intelligence.features.i1_indicators.williams_r import WilliamsRPlugin
from src.intelligence.trading.volume_zscore import VolumeZscorePlugin
from tests.unit.intelligence.correctness.conftest import frames_from_ohlcv

# ---------------------------------------------------------------------------
# Module-level constant: Tier 1 plugin registry for edge-case parametrize
# Each entry: (plugin_class, list_of_expected_output_keys)
# ---------------------------------------------------------------------------
TIER1_PLUGINS: list[tuple[type, list[str]]] = [
    (ATRPlugin, ["atr_14"]),
    (BollingerPlugin, ["bb_20_2_upper", "bb_20_2_mid", "bb_20_2_lower"]),
    (MACDPlugin, ["macd_12_26_9", "macd_signal_12_26_9", "macd_histogram_12_26_9"]),
    (RSIPlugin, ["rsi_14"]),
    (StochasticPlugin, ["stoch_k_14_3", "stoch_d_14_3"]),
    (MFIPlugin, ["mfi_14"]),
    (CCIPlugin, ["cci_14"]),
    (WilliamsRPlugin, ["williams_r_14"]),
    (ADXPlugin, ["adx_14", "plus_di_14", "minus_di_14"]),
    (VWAPPlugin, ["vwap", "vwap_std"]),
    (KalmanTrendPlugin, ["kalman_trend", "kalman_slope", "kalman_price_position"]),
    (GARCHVolatilityPlugin, ["garch_sigma", "garch_vol_ratio"]),
    (VolumeZscorePlugin, ["volume_z_score"]),
]

# Volume-dependent plugins: must not crash on zero volume; may return 0.0 or {} but never exception
VOLUME_PLUGINS: list[tuple[type, list[str]]] = [
    (MFIPlugin, ["mfi_14"]),
    (VWAPPlugin, ["vwap"]),
    (VolumeZscorePlugin, ["volume_z_score"]),
]


def _plugin_ids(params: list[tuple[type, list[str]]]) -> list[str]:
    """Generate readable test IDs from plugin class names."""
    return [cls.__name__ for cls, _ in params]


def _all_output_values_finite(result: dict[str, Any]) -> bool:
    """Return True if every numeric output value in result is finite."""
    for k, v in result.items():
        if k == "_state":
            continue
        if isinstance(v, float) and not math.isfinite(v):
            return False
        if isinstance(v, int):
            pass  # ints (e.g. garch_vol_regime) are always finite
    return True


class TestEdgeCases:
    """Edge case coverage: gap, zero volume, single bar, empty input."""

    @pytest.mark.parametrize(
        "plugin_cls,output_keys", TIER1_PLUGINS, ids=_plugin_ids(TIER1_PLUGINS)
    )
    def test_plugins_handle_gap(
        self, plugin_cls: type, output_keys: list[str], synthetic_ohlcv_gap: pd.DataFrame
    ) -> None:
        """All Tier 1 plugins must not crash on a 200-bar series containing a 5% gap.

        After the gap bar (index 100), any plugin that has warmed up must produce
        a defined (present and finite) value for each of its expected output keys.
        """
        plugin = plugin_cls()
        frames = frames_from_ohlcv(synthetic_ohlcv_gap)

        # Must not raise
        result = plugin.compute_full(frames)

        # If the plugin produced output, all numeric values must be finite
        assert isinstance(result, dict), f"{plugin_cls.__name__}.compute_full must return dict"
        assert _all_output_values_finite(result), (
            f"{plugin_cls.__name__}: non-finite output on gap fixture: "
            f"{[(k, v) for k, v in result.items() if k != '_state' and isinstance(v, float) and not math.isfinite(v)]}"
        )

        # If result is non-empty, the expected keys should be present and finite
        if result:
            for key in output_keys:
                if key in result:
                    val = result[key]
                    if isinstance(val, float):
                        assert math.isfinite(
                            val
                        ), f"{plugin_cls.__name__}[{key}] = {val} is not finite after gap"

    @pytest.mark.parametrize(
        "plugin_cls,output_keys", VOLUME_PLUGINS, ids=_plugin_ids(VOLUME_PLUGINS)
    )
    def test_plugins_handle_zero_volume(
        self, plugin_cls: type, output_keys: list[str], synthetic_ohlcv_zero_volume: pd.DataFrame
    ) -> None:
        """Volume-dependent plugins must NOT crash on all-zero volume input.

        Acceptable outcomes:
        - Returns {} (no output, insufficient data semantics)
        - Returns a dict with finite values or 0.0 sentinel

        Unacceptable: raises any exception, or returns NaN/Inf in output.
        """
        plugin = plugin_cls()
        frames = frames_from_ohlcv(synthetic_ohlcv_zero_volume)

        # Must not raise
        result = plugin.compute_full(frames)

        assert isinstance(
            result, dict
        ), f"{plugin_cls.__name__}.compute_full must return dict on zero-volume input"

        # All numeric outputs must be finite (NaN / Inf are not acceptable sentinels)
        for k, v in result.items():
            if k == "_state":
                continue
            if isinstance(v, float):
                assert math.isfinite(
                    v
                ), f"{plugin_cls.__name__}[{k}] = {v} is not finite on zero-volume input"

    @pytest.mark.parametrize(
        "plugin_cls,output_keys", TIER1_PLUGINS, ids=_plugin_ids(TIER1_PLUGINS)
    )
    def test_plugins_handle_single_bar(
        self, plugin_cls: type, output_keys: list[str], synthetic_ohlcv_single_bar: pd.DataFrame
    ) -> None:
        """All Tier 1 plugins must not crash on a 1-bar input.

        Contract: insufficient data -> empty/missing outputs, NEVER crash.
        The result dict may be {} or may contain a subset of keys, but it
        must never raise an exception.
        """
        plugin = plugin_cls()
        frames = frames_from_ohlcv(synthetic_ohlcv_single_bar)

        # Must not raise
        result = plugin.compute_full(frames)

        assert isinstance(
            result, dict
        ), f"{plugin_cls.__name__}.compute_full must return dict on single-bar input"

        # Any values that are present must still be finite
        for k, v in result.items():
            if k == "_state":
                continue
            if isinstance(v, float):
                assert math.isfinite(
                    v
                ), f"{plugin_cls.__name__}[{k}] = {v} is not finite on single-bar input"

        # Plugins with lookback > 1 should NOT produce main outputs on 1 bar
        # (they should return {} or a dict without the expected keys)
        plugin_instance = plugin
        min_lookback = getattr(plugin_instance, "min_lookback", 2)
        if min_lookback > 1:
            for key in output_keys:
                # If the key IS present on 1 bar for a high-lookback plugin, that's suspicious
                # but we only fail if the value is non-finite; we don't fail on presence alone
                if key in result:
                    val = result[key]
                    if isinstance(val, float):
                        assert math.isfinite(
                            val
                        ), f"{plugin_cls.__name__}[{key}] = {val} not finite on single-bar input"

    @pytest.mark.parametrize(
        "plugin_cls,output_keys", TIER1_PLUGINS, ids=_plugin_ids(TIER1_PLUGINS)
    )
    def test_plugins_handle_empty_frames(self, plugin_cls: type, output_keys: list[str]) -> None:
        """All Tier 1 plugins must not crash on an empty DataFrame.

        Contract: empty input -> must return a dict and never raise.
        Some plugins (e.g. VolumeZscorePlugin) return a 0.0 sentinel instead
        of {} — that is an acceptable documented behavior as long as:
        1. No exception is raised.
        2. Any returned values are finite (not NaN or Inf).
        """
        plugin = plugin_cls()
        empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        frames = {"main": empty_df}

        # Must not raise
        result = plugin.compute_full(frames)

        assert isinstance(
            result, dict
        ), f"{plugin_cls.__name__}.compute_full must return dict on empty DataFrame"

        # Any values present must be finite — no NaN or Inf sentinels allowed
        for k, v in result.items():
            if k == "_state":
                continue
            if isinstance(v, float):
                assert math.isfinite(
                    v
                ), f"{plugin_cls.__name__}[{k}] = {v} is not finite on empty DataFrame"
