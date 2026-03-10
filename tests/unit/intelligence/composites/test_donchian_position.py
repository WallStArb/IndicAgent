import pandas as pd
import pytest

from src.intelligence.composites.donchian_position import plugin


def _frames(close: float, d_high: float, d_mid: float, d_low: float) -> dict:
    df = pd.DataFrame(
        {"close": [close - 1, close], "high": [close] * 2, "low": [close] * 2, "volume": [100] * 2}
    )
    return {
        "main": df,
        "features": {
            "donchian_high_20": d_high,
            "donchian_mid_20": d_mid,
            "donchian_low_20": d_low,
        },
    }


def test_price_at_top_of_channel_returns_positive():
    out = plugin.compute_full(_frames(close=5010.0, d_high=5010.0, d_mid=5000.0, d_low=4990.0))
    assert out["donchian_position_20"] == pytest.approx(1.0, abs=0.01)


def test_price_at_bottom_of_channel_returns_negative():
    out = plugin.compute_full(_frames(close=4990.0, d_high=5010.0, d_mid=5000.0, d_low=4990.0))
    assert out["donchian_position_20"] == pytest.approx(-1.0, abs=0.01)


def test_price_at_mid_returns_zero():
    out = plugin.compute_full(_frames(close=5000.0, d_high=5010.0, d_mid=5000.0, d_low=4990.0))
    assert out["donchian_position_20"] == pytest.approx(0.0, abs=0.01)


def test_missing_donchian_returns_zero():
    frames = {"main": pd.DataFrame({"close": [5000.0]}), "features": {}}
    out = plugin.compute_full(frames)
    assert out["donchian_position_20"] == 0.0
