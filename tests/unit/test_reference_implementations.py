"""Tests for reference implementations from first principles."""

import numpy as np

from src.validation.reference_implementations import (
    atr_reference,
    macd_reference,
    rsi_reference,
    volatility_reference,
    vwap_reference,
)


def test_rsi_reference_simple_case():
    """Test RSI with known values."""
    prices = [44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42,
              45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
    result = rsi_reference(prices, period=14)

    # First 14 values should be NaN (warmup)
    assert np.isnan(result[:14]).all()

    # RSI should be bounded [0, 100]
    assert np.nanmax(result) <= 100
    assert np.nanmin(result) >= 0

    # Last value should be non-NaN and in valid range
    assert not np.isnan(result[-1])
    assert 0 <= result[-1] <= 100

def test_rsi_reference_uptrend():
    """Test RSI in strong uptrend."""
    prices = [100 + i for i in range(20)]  # Perfect uptrend
    result = rsi_reference(prices, period=14)

    # RSI should be high (>70) in strong uptrend
    assert result[-1] > 70

def test_rsi_reference_downtrend():
    """Test RSI in strong downtrend."""
    prices = [100 - i for i in range(20)]  # Perfect downtrend
    result = rsi_reference(prices, period=14)

    # RSI should be low (<30) in strong downtrend
    assert result[-1] < 30

def test_macd_reference():
    """Test MACD calculation."""
    prices = [100 + i + np.sin(i / 2) for i in range(50)]
    result = macd_reference(prices)

    assert "macd" in result
    assert "signal" in result
    assert "histogram" in result
    assert len(result["macd"]) == len(prices)
    assert len(result["signal"]) == len(prices)
    assert len(result["histogram"]) == len(prices)

    # Histogram = MACD - Signal
    np.testing.assert_array_almost_equal(
        result["histogram"],
        result["macd"] - result["signal"],
        decimal=10
    )

def test_atr_reference():
    """Test ATR calculation."""
    high = [102 + i for i in range(20)]
    low = [100 + i for i in range(20)]
    close = [101 + i for i in range(20)]
    result = atr_reference(high, low, close, period=14)

    # First 14 values should be NaN
    assert np.isnan(result[:14]).all()

    # ATR should be positive
    assert np.nanmin(result) >= 0
    assert not np.isnan(result[-1])

def test_vwap_reference():
    """Test VWAP calculation."""
    high = [102 + i for i in range(20)]
    low = [100 + i for i in range(20)]
    close = [101 + i for i in range(20)]
    volume = [1000 + i * 100 for i in range(20)]
    result = vwap_reference(high, low, close, volume)

    # VWAP should be positive and within reasonable bounds
    assert np.all(result > 0)
    assert np.all(result >= np.min(low) - 1)  # Allow small margin
    assert np.all(result <= np.max(high) + 1)
    # VWAP should be monotonically increasing in uptrend (with volume)
    assert result[-1] > result[0]

def test_volatility_reference():
    """Test volatility calculation."""
    prices = [100 + i + np.random.randn() * 2 for i in range(50)]
    result = volatility_reference(prices, period=20)

    # First 20 values should be NaN
    assert np.isnan(result[:20]).all()

    # Volatility should be positive
    assert np.nanmin(result) >= 0
    assert not np.isnan(result[-1])
