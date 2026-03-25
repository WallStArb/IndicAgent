"""
Reference implementations from first principles.

Use these to validate production code is mathematically correct.
All implementations follow original paper formulas exactly.
"""

import numpy as np
from typing import List, Dict


def rsi_reference(prices: List[float], period: int = 14) -> np.ndarray:
    """
    Reference RSI implementation from Wilder's 1978 paper.

    RSI = 100 - (100 / (1 + RS))
    RS = Average Gain / Average Loss (Wilder's smoothing)

    Args:
        prices: List of closing prices
        period: RSI period (default 14)

    Returns:
        Array of RSI values (first `period` values are NaN)
    """
    prices = np.array(prices, dtype=float)
    deltas = np.diff(prices)

    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.zeros_like(deltas)
    avg_loss = np.zeros_like(deltas)

    # Initialize with simple average
    avg_gain[period - 1] = np.mean(gains[:period])
    avg_loss[period - 1] = np.mean(losses[:period])

    # Wilder's smoothing for subsequent values
    for i in range(period, len(deltas)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i]) / period

    # Calculate RS and RSI
    # When avg_loss is 0 (perfect uptrend), RS = infinity, RSI = 100
    rs = np.divide(avg_gain, avg_loss, out=np.full_like(avg_gain, np.inf), where=avg_loss != 0)
    rsi = np.where(avg_loss == 0, 100.0, 100 - (100 / (1 + rs)))

    # First `period` values are undefined (warmup)
    result = np.full(len(prices), np.nan)
    result[period:] = rsi[period - 1:]

    return result


def macd_reference(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, np.ndarray]:
    """
    Reference MACD implementation.

    MACD Line = EMA(fast) - EMA(slow)
    Signal Line = EMA(MACD, signal_period)
    Histogram = MACD - Signal

    Args:
        prices: List of closing prices
        fast: Fast EMA period (default 12)
        slow: Slow EMA period (default 26)
        signal: Signal line EMA period (default 9)

    Returns:
        Dict with 'macd', 'signal', 'histogram' arrays
    """
    prices = np.array(prices, dtype=float)

    def ema(data: np.ndarray, period: int) -> np.ndarray:
        """Exponential Moving Average."""
        alpha = 2 / (period + 1)
        ema_values = np.zeros_like(data)
        ema_values[0] = data[0]

        for i in range(1, len(data)):
            ema_values[i] = alpha * data[i] + (1 - alpha) * ema_values[i - 1]

        return ema_values

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def atr_reference(high: List[float], low: List[float], close: List[float], period: int = 14) -> np.ndarray:
    """
    Reference ATR implementation (Wilder's smoothing).

    True Range = max(high - low, |high - close_prev|, |low - close_prev|)
    ATR = Wilder's smoothing of True Range

    Args:
        high: List of high prices
        low: List of low prices
        close: List of close prices
        period: ATR period (default 14)

    Returns:
        Array of ATR values (first `period` values are NaN)
    """
    high = np.array(high, dtype=float)
    low = np.array(low, dtype=float)
    close = np.array(close, dtype=float)

    true_range = np.zeros(len(close))
    true_range[0] = high[0] - low[0]

    for i in range(1, len(close)):
        tr1 = high[i] - low[i]
        tr2 = abs(high[i] - close[i - 1])
        tr3 = abs(low[i] - close[i - 1])
        true_range[i] = max(tr1, tr2, tr3)

    atr = np.zeros_like(true_range)
    atr[period - 1] = np.mean(true_range[:period])

    for i in range(period, len(true_range)):
        atr[i] = (atr[i - 1] * (period - 1) + true_range[i]) / period

    # First `period` values are undefined (need `period` bars for first ATR)
    result = np.full(len(close), np.nan)
    result[period:] = atr[period - 1:-1]  # Shift by 1: first ATR at index `period`

    return result


def vwap_reference(high: List[float], low: List[float], close: List[float], volume: List[float]) -> np.ndarray:
    """
    Reference VWAP implementation.

    VWAP = Cumulative(Volume * Typical Price) / Cumulative(Volume)
    Typical Price = (High + Low + Close) / 3

    Args:
        high: List of high prices
        low: List of low prices
        close: List of close prices
        volume: List of volumes

    Returns:
        Array of VWAP values
    """
    high = np.array(high, dtype=float)
    low = np.array(low, dtype=float)
    close = np.array(close, dtype=float)
    volume = np.array(volume, dtype=float)

    typical_price = (high + low + close) / 3
    tp_volume = typical_price * volume

    cumulative_tp_volume = np.cumsum(tp_volume)
    cumulative_volume = np.cumsum(volume)

    # Handle zero volume
    vwap = np.divide(
        cumulative_tp_volume,
        cumulative_volume,
        out=np.zeros_like(cumulative_tp_volume),
        where=cumulative_volume != 0,
    )

    return vwap


def volatility_reference(prices: List[float], period: int = 20) -> np.ndarray:
    """
    Reference volatility implementation (std dev of returns, annualized).

    Volatility = std(returns) * sqrt(252)

    Args:
        prices: List of closing prices
        period: Lookback period (default 20)

    Returns:
        Array of annualized volatility values (first `period` values are NaN)
    """
    prices = np.array(prices, dtype=float)
    returns = np.diff(np.log(prices))

    volatility = np.full(len(prices), np.nan)

    for i in range(period, len(prices)):
        window = returns[i - period:i]
        volatility[i] = np.std(window) * np.sqrt(252)

    return volatility
