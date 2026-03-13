"""HurstExponentPlugin — I4 context plugin for market persistence classification.

The Hurst exponent H characterises the long-range memory of a time series:
  H > 0.5  — persistent / trending market (returns tend to continue direction)
  H = 0.5  — random walk (no memory, pure Brownian motion)
  H < 0.5  — anti-persistent / mean-reverting market (returns tend to reverse)

This plugin outputs three fields:
  hurst_exponent       — H in [0, 1], rounded to 4 decimal places
  hurst_trend_quality  — quality score for trend-following setups (high when H > 0.65)
  hurst_mr_quality     — quality score for mean-reversion setups (high when H < 0.35)

Wired into _build_all_ranked() (plan 29-05) to gate setup classes by market regime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


def _hurst_rs(close: np.ndarray, min_window: int = 16) -> float:
    """Rescaled range (R/S) estimate of the Hurst exponent.

    Uses the full series as a single window (classical Mandelbrot approach).
    Returns 0.5 (random walk neutral) when the series is too short, constant,
    or the R/S statistic cannot be computed.

    Parameters
    ----------
    close:
        Array of closing prices.  Must have length >= min_window.
    min_window:
        Minimum number of bars required.  Returns 0.5 if not met.
    """
    n = len(close)
    if n < min_window:
        return 0.5

    log_returns = np.diff(np.log(close))
    if len(log_returns) < min_window:
        return 0.5

    mean_r = np.mean(log_returns)
    deviations = np.cumsum(log_returns - mean_r)
    r = np.max(deviations) - np.min(deviations)
    s = np.std(log_returns, ddof=1)

    if s == 0 or r == 0:
        return 0.5

    rs = r / s
    if rs <= 0:
        return 0.5

    return float(min(1.0, max(0.0, np.log(rs) / np.log(n))))


def _hurst_trend_quality(h: float) -> float:
    """Map Hurst exponent to a trend-following quality score in [0, 1].

    Scoring rationale:
      H >= 0.65  — clearly trending market; trend setups highly reliable → 1.0
      H <= 0.45  — mean-reverting or flat; trend setups unreliable → 0.3
      0.45 < H < 0.65 — linear interpolation between 0.3 and 1.0
    """
    if h >= 0.65:
        return 1.0
    if h <= 0.45:
        return 0.3
    return 0.3 + 0.7 * ((h - 0.45) / 0.20)


def _hurst_mr_quality(h: float) -> float:
    """Map Hurst exponent to a mean-reversion quality score in [0, 1].

    Scoring rationale:
      H <= 0.35  — clearly anti-persistent; MR setups highly reliable → 1.0
      H >= 0.55  — trending or flat; MR setups unreliable → 0.3
      0.35 < H < 0.55 — linear interpolation between 1.0 and 0.3
    """
    if h <= 0.35:
        return 1.0
    if h >= 0.55:
        return 0.3
    return 0.3 + 0.7 * ((0.55 - h) / 0.20)


@dataclass
class HurstExponentPlugin:
    """I4 context plugin: rolling Hurst exponent + regime quality scores.

    Uses a classical R/S analysis on the last ``min_lookback`` close prices to
    estimate H, then maps it to trend and mean-reversion quality scores.

    Outputs
    -------
    hurst_exponent      : float in [0, 1]
    hurst_trend_quality : float in [0, 1] — high when market is trending
    hurst_mr_quality    : float in [0, 1] — high when market is mean-reverting
    """

    name: str = "ctx_HurstExponent"
    outputs: frozenset[str] = frozenset(
        {"hurst_exponent", "hurst_trend_quality", "hurst_mr_quality"}
    )
    min_lookback: int = 64
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"context", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=256),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        # Use last min_lookback bars for a consistent, rolling estimate
        close = df["close"].to_numpy(dtype=float)[-self.min_lookback :]

        h = _hurst_rs(close)

        return {
            "hurst_exponent": round(h, 4),
            "hurst_trend_quality": round(_hurst_trend_quality(h), 4),
            "hurst_mr_quality": round(_hurst_mr_quality(h), 4),
        }


plugin = HurstExponentPlugin()
