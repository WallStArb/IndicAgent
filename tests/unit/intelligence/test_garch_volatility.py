"""Tests for GARCH(1,1) volatility forecast plugin."""

import math

import numpy as np
import pandas as pd

from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, vol_scale: float = 1.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 5000.0 + np.cumsum(rng.standard_normal(n) * vol_scale)
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    return pd.DataFrame(
        {
            "open": close - rng.uniform(0, 0.5, n),
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(100, 1000, n).astype(float),
        }
    )


class TestGARCHVolatility:
    def test_outputs_expected_keys(self):
        plugin = GARCHVolatilityPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "garch_sigma" in result
        assert "garch_vol_ratio" in result
        assert "garch_vol_regime" in result
        assert "garch_shock" in result

    def test_sigma_is_positive(self):
        plugin = GARCHVolatilityPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert result["garch_sigma"] > 0

    def test_vol_regime_is_valid(self):
        """Regime should be 0, 1, 2, or 3."""
        plugin = GARCHVolatilityPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert result["garch_vol_regime"] in (0, 1, 2, 3)

    def test_high_vol_data_higher_sigma(self):
        """High-volatility data should produce larger sigma."""
        plugin_low = GARCHVolatilityPlugin()
        plugin_high = GARCHVolatilityPlugin()
        result_low = plugin_low.compute_full({"main": _make_ohlcv(n=200, vol_scale=0.5)})
        result_high = plugin_high.compute_full({"main": _make_ohlcv(n=200, seed=99, vol_scale=5.0)})
        assert result_high["garch_sigma"] > result_low["garch_sigma"]

    def test_shock_non_negative(self):
        plugin = GARCHVolatilityPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert result["garch_shock"] >= 0

    def test_short_data_returns_empty(self):
        plugin = GARCHVolatilityPlugin()
        result = plugin.compute_full({"main": _make_ohlcv(n=5)})
        assert result == {}

    def test_vol_ratio_is_finite(self):
        """Vol ratio should be finite."""
        plugin = GARCHVolatilityPlugin()
        result = plugin.compute_full({"main": _make_ohlcv(n=100)})
        assert math.isfinite(result["garch_vol_ratio"])

    def test_alpha_beta_sum_below_one(self):
        """Default parameters should satisfy alpha + beta < 1 (stationarity)."""
        plugin = GARCHVolatilityPlugin()
        assert plugin.alpha + plugin.beta < 1.0


def test_garch_reads_apr_config() -> None:
    """GARCHVolatilityPlugin must read omega/alpha/beta from _config_service when injected."""
    from unittest.mock import MagicMock

    plugin = GARCHVolatilityPlugin()

    mock_cfg = MagicMock()
    mock_cfg.get_sync.side_effect = lambda key, default=None: {
        "feature.garch.omega": 0.00002,  # doubled from default
        "feature.garch.alpha": 0.20,  # doubled from default
        "feature.garch.beta": 0.75,  # different from default
    }.get(key, default)

    plugin._config_service = mock_cfg

    df = _make_ohlcv(100)
    result = plugin.compute_full({"main": df})

    assert result, "Should return results with APR config injected"
    mock_cfg.get_sync.assert_any_call("feature.garch.omega", 0.00001)
    mock_cfg.get_sync.assert_any_call("feature.garch.alpha", 0.10)
    mock_cfg.get_sync.assert_any_call("feature.garch.beta", 0.85)
