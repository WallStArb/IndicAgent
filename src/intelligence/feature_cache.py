"""FeatureCache — mutable state container for slow-changing features.

Holds regime-level, session-level, cross-asset, and CTF state that
compute() reads per bar. Updated by the caller (IntelligencePipeline or
backfill job), never mutated inside FeatureFactory.compute().

Cross-asset proxy instruments (D-08, confirmed at planning time):
- vix_z: SPY trailing realized volatility z-score (VXX/VIXY absent from the
  58-ETF universe; SPY realized-vol is the available proxy).
- flight_quality: TLT/SPY relative-return divergence (positive = risk-off).
- yield_slope_z: z-score of TLT/SHY return ratio (2Y-10Y curve proxy).
All three are populated via update_cross_asset() and read by compute().
Phase 138 IC will judge these proxies.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig


@dataclass
class FeatureCache:
    """Mutable state container for FeatureFactory.compute().

    Regime-level fields are refreshed every regime_cache_refresh_bars bars
    via refresh_regime(). CTF fields are updated when an HTF bar arrives.
    Cross-asset fields are updated via update_cross_asset(). Session-level
    fields are reset at session open by the caller.
    """

    # Regime-level (refreshed every N bars via refresh_regime())
    hmm_regime_prob: float = 0.0
    hmm_entropy: float = 0.0
    hurst: float = 0.5
    shannon: float = 1.0
    garch_ratio: float = 1.0
    hma_slope_z: float = 0.0
    adx: float = 0.0
    bars_since_regime_refresh: int = 0

    # Cross-asset cached from cross-asset ETF bars (updated via update_cross_asset())
    vix_z: float = 0.0  # SPY realized-vol proxy (VXX/VIXY absent from universe)
    flight_quality: float = 0.0  # TLT/SPY divergence
    yield_slope_z: float = 0.0  # TLT/SHY ratio z-score

    # CTF from HTF cached state (populated when HTF bar arrives)
    ctf_momentum: float = 0.0
    ctf_vwap_align: float = 0.0
    ctf_regime_align: float = 0.0

    # HMM duration and weekly VWAP (updated by caller per bar)
    hmm_duration: float = 0.0  # bars in current HMM discrete regime state
    above_wk_vwap: float = 0.0  # 1.0 if close > weekly VWAP, else 0.0

    # Session-level VP (reset at session open by caller)
    poc_dist_atr: float = 0.0
    va_position: float = 0.5
    sr_support_dist: float = 0.0
    sr_resist_dist: float = 0.0

    # Internal rolling histories for cross-asset z-scores (not part of FeatureVector)
    _spy_realized_vol_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)
    _yield_ratio_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)

    # Internal rolling history for regime features (HMA, ADX z-score)
    _hma_slope_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)
    _adx_raw_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)

    # Internal state for hmm_duration tracking
    _hmm_regime_label: int = field(default=-1, repr=False)

    # Internal accumulators for weekly VWAP
    _wk_tp_vol_sum: float = field(default=0.0, repr=False)
    _wk_vol_sum: float = field(default=0.0, repr=False)
    _wk_year_week: tuple = field(default=(-1, -1), repr=False)  # (iso_year, iso_week)

    def refresh_regime(self, bars: list[dict], config: FeatureFactoryConfig) -> None:
        """Recompute regime-level features from bars and update cache.

        Called by the pipeline every config.regime_cache_refresh_bars bars.
        Extracts forward-only cores (no backward smoother, D-07).

        Parameters
        ----------
        bars:
            Full bar history available to the pipeline (list of OHLCV dicts).
        config:
            Frozen config with all tunable parameters from APR.
        """
        if len(bars) < config.min_bars_warmup:
            self.bars_since_regime_refresh = 0
            return

        closes = np.array([b["close"] for b in bars], dtype=float)
        highs = np.array([b["high"] for b in bars], dtype=float)
        lows = np.array([b["low"] for b in bars], dtype=float)

        # --- Hurst exponent (R/S analysis, forward-only) ---
        window = min(config.hurst_window, len(closes))
        self.hurst = _hurst_rs(closes[-window:])

        # --- Shannon entropy of log-return distribution ---
        self.shannon = _shannon_entropy(closes)

        # --- GARCH(1,1) sigma / realized vol ratio ---
        self.garch_ratio = _garch_ratio(closes, config.garch_window)

        # --- HMM forward pass (2D, log-return + realized-vol) ---
        hmm_prob, hmm_entropy, hmm_label = _hmm_forward_2d(closes)
        self.hmm_regime_prob = hmm_prob
        self.hmm_entropy = hmm_entropy
        if self._hmm_regime_label != -1 and hmm_label != self._hmm_regime_label:
            self.hmm_duration = 0.0
        self._hmm_regime_label = hmm_label

        # --- HMA slope z-score ---
        hma_val = _hma(closes, config.hma_period)
        hma_prev = _hma(closes[:-1], config.hma_period)
        if math.isfinite(hma_val) and math.isfinite(hma_prev):
            slope = hma_val - hma_prev
            self._hma_slope_history.append(slope)
        self.hma_slope_z = _zscore_from_deque(
            self._hma_slope_history,
            config.momentum_zscore_window,
        )

        # --- ADX (raw value, 0-100) ---
        adx_val = _adx(highs, lows, closes, config.adx_period)
        self.adx = adx_val

        self.bars_since_regime_refresh = 0

    def update_wk_vwap(
        self,
        bar_ts: datetime,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """Update weekly VWAP state and set above_wk_vwap from current bar.

        Resets accumulators at ISO week boundary. Called by the pipeline or backfill
        once per bar, after FeatureFactory.compute().
        """
        iso = bar_ts.isocalendar()
        year_week = (iso.year, iso.week)
        if year_week != self._wk_year_week:
            self._wk_tp_vol_sum = 0.0
            self._wk_vol_sum = 0.0
            self._wk_year_week = year_week
        typical = (high + low + close) / 3.0
        self._wk_tp_vol_sum += typical * volume
        self._wk_vol_sum += volume
        wk_vwap = self._wk_tp_vol_sum / self._wk_vol_sum if self._wk_vol_sum > 1e-10 else close
        self.above_wk_vwap = float(close > wk_vwap)

    def advance_bar(
        self,
        bar_ts: datetime,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """Update all per-bar mutable state after FeatureFactory.compute().

        Called once per bar by the pipeline and backfill. Encapsulates:
        - Weekly VWAP accumulation and above_wk_vwap flag
        - HMM duration counter increment
        """
        self.update_wk_vwap(bar_ts, high, low, close, volume)
        self.hmm_duration += 1.0

    def update_cross_asset(
        self,
        spy_bars: list[dict],
        tlt_bars: list[dict],
        shy_bars: list[dict],
        config: FeatureFactoryConfig,
    ) -> None:
        """Populate cross-asset proxy fields from available ETF OHLCV bars.

        Called when cross-asset HTF bars arrive. All three features are computed
        from OHLCV only — no tick data, no live frames injection.

        Parameters
        ----------
        spy_bars: SPY bar history (for vix_z proxy via realized volatility)
        tlt_bars: TLT bar history (for flight_quality and yield_slope_z)
        shy_bars: SHY bar history (for yield_slope_z)
        config: Frozen FeatureFactoryConfig with zscore windows
        """
        window = config.vix_zscore_window

        # vix_z: SPY trailing realized volatility z-score (proxy for VIX)
        if len(spy_bars) >= 2:
            spy_closes = np.array([b["close"] for b in spy_bars], dtype=float)
            spy_returns = np.diff(np.log(np.maximum(spy_closes, 1e-10)))
            rv_window = min(config.cross_asset_rv_window, len(spy_returns))
            realized_vol = float(np.std(spy_returns[-rv_window:]))
            self._spy_realized_vol_history.append(realized_vol)
            self.vix_z = _zscore_from_deque(self._spy_realized_vol_history, window)

        # flight_quality: TLT/SPY relative-return divergence (positive = risk-off)
        if len(tlt_bars) >= 2 and len(spy_bars) >= 2:
            n = min(len(tlt_bars), len(spy_bars))
            tlt_closes = np.array([b["close"] for b in tlt_bars[-n:]], dtype=float)
            spy_closes_n = np.array([b["close"] for b in spy_bars[-n:]], dtype=float)
            tlt_ret = float(tlt_closes[-1] / tlt_closes[0] - 1.0) if tlt_closes[0] > 0 else 0.0
            spy_ret = (
                float(spy_closes_n[-1] / spy_closes_n[0] - 1.0) if spy_closes_n[0] > 0 else 0.0
            )
            self.flight_quality = tlt_ret - spy_ret

        # yield_slope_z: TLT/SHY return ratio z-score (2Y-10Y proxy)
        yzw = config.yield_curve_zscore_window
        if len(tlt_bars) >= 2 and len(shy_bars) >= 2:
            n = min(len(tlt_bars), len(shy_bars))
            tlt_closes = np.array([b["close"] for b in tlt_bars[-n:]], dtype=float)
            shy_closes = np.array([b["close"] for b in shy_bars[-n:]], dtype=float)
            tlt_rets = np.diff(np.log(np.maximum(tlt_closes, 1e-10)))
            shy_rets = np.diff(np.log(np.maximum(shy_closes, 1e-10)))
            min_len = min(len(tlt_rets), len(shy_rets))
            if min_len > 0:
                ratio = float(tlt_rets[-1]) - float(shy_rets[-1])
                self._yield_ratio_history.append(ratio)
            self.yield_slope_z = _zscore_from_deque(self._yield_ratio_history, yzw)


# ---------------------------------------------------------------------------
# Pure computation helpers (used by refresh_regime)
# ---------------------------------------------------------------------------


def _hurst_rs(close: np.ndarray, min_window: int = 16) -> float:
    """Rescaled range (R/S) estimate of the Hurst exponent.

    Extracted from src/intelligence/context/hurst_exponent.py.
    Returns 0.5 (random walk neutral) on insufficient data or constant series.
    """
    n = len(close)
    if n < min_window:
        return 0.5
    log_returns = np.diff(np.log(np.maximum(close, 1e-10)))
    if len(log_returns) < min_window:
        return 0.5
    mean_r = np.mean(log_returns)
    deviations = np.cumsum(log_returns - mean_r)
    r = float(np.max(deviations) - np.min(deviations))
    s = float(np.std(log_returns, ddof=1))
    if s <= 0 or r <= 0:
        return 0.5
    rs = r / s
    if rs <= 0:
        return 0.5
    return float(min(1.0, max(0.0, np.log(rs) / np.log(n))))


def _shannon_entropy(close: np.ndarray, n_bins: int = 10) -> float:
    """Normalised Shannon entropy of log-return distribution.

    Extracted from src/intelligence/context/shannon_entropy.py.
    Returns 1.0 on insufficient data.
    """
    log_returns = np.diff(np.log(np.maximum(close, 1e-10)))
    if len(log_returns) < 10:
        return 1.0
    valid_returns = log_returns[np.isfinite(log_returns)]
    if len(valid_returns) < 10:
        return 1.0
    counts, _ = np.histogram(valid_returns, bins=n_bins)
    probs = counts / counts.sum()
    probs = probs[probs > 0]
    if len(probs) == 0:
        return 1.0
    raw_entropy = float(-np.sum(probs * np.log2(probs)))
    max_entropy = float(np.log2(n_bins))
    return raw_entropy / max_entropy if max_entropy > 0 else 1.0


def _garch_ratio(close: np.ndarray, window: int) -> float:
    """GARCH(1,1) sigma / realized_vol ratio.

    Simplified extraction from src/intelligence/context/garch_volatility.py.
    Uses default GARCH parameters (omega=0.00001, alpha=0.10, beta=0.85).
    Returns 1.0 on cold start.
    """
    n = min(window, len(close))
    if n < 10:
        return 1.0
    close_w = close[-n:]
    log_returns = np.log(np.maximum(close_w[1:], 1e-10) / np.maximum(close_w[:-1], 1e-10))
    log_returns = np.where(np.isfinite(log_returns), log_returns, 0.0)
    omega, alpha, beta = 0.00001, 0.10, 0.85
    init_w = min(20, len(log_returns))
    sigma2 = float(np.var(log_returns[:init_w]))
    if sigma2 == 0.0:
        denom = 1 - alpha - beta
        sigma2 = omega / denom if denom > 1e-10 else omega
    realized_buf: deque = deque(maxlen=20)
    for r in log_returns:
        sigma2 = omega + alpha * r**2 + beta * sigma2
        realized_buf.append(float(r))
    garch_sigma = math.sqrt(max(sigma2, 0.0))
    realized_vol = float(np.std(list(realized_buf))) if len(realized_buf) >= 2 else garch_sigma
    return garch_sigma / realized_vol if realized_vol > 1e-10 else 1.0


# HMM default parameters (forward-only, 2D)
_HMM_A = np.array(
    [
        [0.95, 0.025, 0.025],
        [0.03, 0.94, 0.03],
        [0.03, 0.03, 0.94],
    ]
)
_HMM_MEANS_2D = np.array(
    [
        [0.0, 0.005],  # Ranging
        [0.001, 0.008],  # Trending up
        [-0.001, 0.012],  # Trending down
    ]
)
_HMM_VARS_2D = np.array(
    [
        [0.0001, 0.001],
        [0.0002, 0.002],
        [0.0003, 0.003],
    ]
)
_HMM_K = 3


def _hmm_forward_2d(close: np.ndarray, vol_window: int = 20) -> tuple[float, float, int]:
    """Forward HMM pass (2D: log_return + realized_vol). No backward smoother.

    Returns (dominant_state_prob, shannon_entropy_of_state_probs, dominant_state_label).
    dominant_state_label is the argmax of the final alpha vector (integer 0..K-1).
    Extracted from src/intelligence/features/smc_context/hmm_regime.py _forward_step.
    """
    if len(close) < vol_window + 1:
        # Cold start: uniform prior
        probs = np.full(_HMM_K, 1.0 / _HMM_K)
        return float(np.max(probs)), _hmm_entropy(probs), 0

    log_returns = np.log(np.maximum(close[1:], 1e-10) / np.maximum(close[:-1], 1e-10))
    log_returns = np.where(np.isfinite(log_returns), log_returns, 0.0)

    alpha = np.full(_HMM_K, 1.0 / _HMM_K)
    ret_buf: deque = deque(maxlen=vol_window)

    for ret in log_returns:
        ret_buf.append(float(ret))
        realized_vol = float(np.std(list(ret_buf))) if len(ret_buf) >= 2 else 0.005
        obs = np.array([ret, realized_vol])
        _hmm_forward_step(obs, alpha)

    dominant_prob = float(np.max(alpha))
    entropy = _hmm_entropy(alpha)
    dominant_label = int(np.argmax(alpha))
    return dominant_prob, entropy, dominant_label


def _hmm_forward_step(obs: np.ndarray, alpha: np.ndarray) -> None:
    """In-place forward algorithm step. No backward smoother (D-07).

    Parameters
    ----------
    obs: 2D observation vector [log_return, realized_vol]
    alpha: K-dim state probability vector (mutated in place)
    """
    means = _HMM_MEANS_2D
    variances = _HMM_VARS_2D
    D = len(obs)
    diff = obs - means  # (K, D)
    log_emit = -0.5 * np.sum(diff * diff / variances, axis=1)
    log_emit -= 0.5 * np.sum(np.log(variances), axis=1)
    log_emit -= 0.5 * D * math.log(2 * math.pi)

    log_alpha = np.log(np.maximum(alpha, 1e-300))
    log_alpha_new = np.zeros(_HMM_K)
    for k in range(_HMM_K):
        log_trans = log_alpha + np.log(np.maximum(_HMM_A[:, k], 1e-300))
        max_lt = float(np.max(log_trans))
        log_alpha_new[k] = max_lt + math.log(float(np.sum(np.exp(log_trans - max_lt))))
    log_alpha_new += log_emit
    # Normalize to get probabilities
    max_val = float(np.max(log_alpha_new))
    unnorm = np.exp(log_alpha_new - max_val)
    total = float(np.sum(unnorm))
    if total > 1e-300:
        alpha[:] = unnorm / total
    else:
        alpha[:] = 1.0 / _HMM_K


def _hmm_entropy(probs: np.ndarray) -> float:
    """Shannon entropy of HMM state probability vector."""
    safe = np.maximum(probs, 1e-300)
    return float(-np.sum(safe * np.log(safe)))


def _wma(series: np.ndarray, k: int) -> float:
    """Weighted Moving Average over last k values. Returns NaN if insufficient."""
    if len(series) < k:
        return float("nan")
    tail = series[-k:]
    weights = np.arange(1, k + 1, dtype=float)
    return float(np.dot(weights, tail) / weights.sum())


def _hma(close: np.ndarray, period: int) -> float:
    """Hull Moving Average (current value). Returns NaN on insufficient data."""
    if len(close) < period:
        return float("nan")
    half = period // 2
    sqrt_n = int(round(math.sqrt(period)))
    # Build diff buffer for last sqrt_n bars
    buf: deque = deque(maxlen=sqrt_n)
    start = len(close) - sqrt_n
    if start < period - 1:
        return float("nan")
    for i in range(start, len(close)):
        sub = close[: i + 1]
        wh = _wma(sub, half)
        wf = _wma(sub, period)
        if math.isfinite(wh) and math.isfinite(wf):
            buf.append(2.0 * wh - wf)
    if len(buf) < sqrt_n:
        return float("nan")
    return _wma(np.array(list(buf)), sqrt_n)


def _adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
    """Compute ADX using Wilder's smoothing. Returns 0.0 on insufficient data.

    Simplified extraction from src/intelligence/features/i1_indicators/adx.py.
    """
    n = len(close)
    if n < period * 2 + 1:
        return 0.0
    # True Range
    prev_close = close[:-1]
    curr_high = high[1:]
    curr_low = low[1:]
    tr = np.maximum(
        curr_high - curr_low,
        np.maximum(np.abs(curr_high - prev_close), np.abs(curr_low - prev_close)),
    )
    # Directional movement
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    # Wilder's smoothing
    alpha = 1.0 / period
    sm_tr = float(np.sum(tr[:period]))
    sm_plus = float(np.sum(plus_dm[:period]))
    sm_minus = float(np.sum(minus_dm[:period]))
    dx_vals: list[float] = []
    for i in range(period, len(tr)):
        sm_tr = sm_tr - sm_tr / period + float(tr[i])
        sm_plus = sm_plus - sm_plus / period + float(plus_dm[i])
        sm_minus = sm_minus - sm_minus / period + float(minus_dm[i])
        if sm_tr < 1e-10:
            continue
        plus_di = 100.0 * sm_plus / sm_tr
        minus_di = 100.0 * sm_minus / sm_tr
        di_sum = plus_di + minus_di
        if di_sum < 1e-10:
            dx_vals.append(0.0)
        else:
            dx_vals.append(100.0 * abs(plus_di - minus_di) / di_sum)
    if len(dx_vals) < period:
        return 0.0
    adx_val = float(np.mean(dx_vals[-period:]))
    return min(100.0, max(0.0, adx_val))


def _zscore_from_deque(history: deque, window: int) -> float:
    """Compute z-score of most-recent value in deque against rolling window.

    Returns 0.0 if insufficient data or near-zero std.
    """
    if len(history) < window:
        return 0.0
    arr = np.array(list(history)[-window:])
    std = float(arr.std())
    if std < 1e-8:
        return 0.0
    return float((float(history[-1]) - float(arr.mean())) / std)
