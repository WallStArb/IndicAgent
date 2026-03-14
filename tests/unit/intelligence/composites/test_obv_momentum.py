import pandas as pd

from src.intelligence.composites.obv_momentum import plugin


def _frames(closes: list[float], volumes: list[float]) -> dict:
    df = pd.DataFrame(
        {
            "close": closes,
            "volume": volumes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
        }
    )
    return {"main": df, "features": {}}


def test_rising_obv_returns_positive():
    # Rising price + high volume = rising OBV
    out = plugin.compute_full(
        _frames(
            closes=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0],
            volumes=[1000] * 11,
        )
    )
    assert out["obv_slope_sign"] == 1


def test_falling_obv_returns_negative():
    # Falling price + high volume = falling OBV
    out = plugin.compute_full(
        _frames(
            closes=[110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0, 101.0, 100.0],
            volumes=[1000] * 11,
        )
    )
    assert out["obv_slope_sign"] == -1


def test_insufficient_bars_returns_zero():
    out = plugin.compute_full(_frames(closes=[100.0, 101.0], volumes=[100, 100]))
    assert out["obv_slope_sign"] == 0
