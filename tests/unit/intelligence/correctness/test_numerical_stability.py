"""Numerical stability tests for Tier 1 plugins over 10,000 bars.

Each test drives a plugin through a full 10K-bar deterministic synthetic
OHLCV series and asserts that every output remains finite throughout.

These tests are marked @pytest.mark.slow because each run involves 10,000
incremental plugin updates. They are the stability gate for Phase 093.

CI POLICY: Slow tests RUN in CI. They are NOT skipped. The only opt-out
is local fast iteration via `-m "not slow"`, which is forbidden in CI.
See .planning/phases/093-mathematical-correctness-audit/093-CI-GATE.md.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin
from src.intelligence.context.kalman_trend import KalmanTrendPlugin
from src.intelligence.features.i1_indicators.atr import ATRPlugin
from src.intelligence.features.i1_indicators.bollinger import BollingerPlugin
from tests.unit.intelligence.correctness.conftest import frames_from_ohlcv

# ---------------------------------------------------------------------------
# Module-level 10K-bar fixture
# ---------------------------------------------------------------------------


def _make_index(n: int, seed_date: str = "2024-01-02") -> pd.DatetimeIndex:
    """Return a UTC DatetimeIndex of *n* 1-minute bars starting at seed_date."""
    return pd.date_range(start=seed_date, periods=n, freq="1min", tz="UTC")


def _clamp_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Enforce OHLC validity: high >= max(open,close), low <= min(open,close)."""
    df = df.copy()
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"] = df[["low", "open", "close"]].min(axis=1)
    return df


@pytest.fixture(scope="module")
def long_run_ohlcv() -> pd.DataFrame:
    """10,000-bar deterministic trending OHLCV (seed=99, 1-minute UTC bars).

    Scope=module to avoid recreating 10K rows across 4 test methods.
    The series has gentle upward drift with noise and realistic spread.
    """
    n = 10_000
    rng = np.random.default_rng(99)
    base = 100.0
    # Gentle upward drift (0.02% per bar) + moderate noise
    returns = rng.normal(0.0002, 0.003, n)
    close = base * np.exp(np.cumsum(returns))
    spread = close * 0.0015
    noise = rng.normal(0, 0.001, n)
    open_ = close + noise * close
    high = close + spread * (1 + rng.uniform(0, 1, n))
    low = close - spread * (1 + rng.uniform(0, 1, n))
    volume = rng.uniform(5000, 15000, n)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=_make_index(n),
    )
    return _clamp_ohlcv(df)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestNumericalStability:
    """Numerical stability: all outputs finite over 10,000 bars."""

    def test_atr_stable_over_10k_bars(self, long_run_ohlcv: pd.DataFrame) -> None:
        """ATR(14) must produce finite positive values at every bar after warm-up.

        Strategy: compute_full on first 100 bars to warm up, then compute_next
        bar-by-bar for the remaining 9,900 bars. Assert every atr_14 is finite
        and positive.
        """
        plugin = ATRPlugin()
        n = len(long_run_ohlcv)
        warmup = 100

        frames = frames_from_ohlcv(long_run_ohlcv.iloc[:warmup])
        result = plugin.compute_full(frames)
        assert "atr_14" in result, "ATR: compute_full failed to produce atr_14 on warmup window"
        state = result.get("_state", {})

        failures: list[tuple[int, float]] = []
        for i in range(warmup, n):
            row_frames = frames_from_ohlcv(long_run_ohlcv.iloc[: i + 1])
            result = plugin.compute_next(row_frames, state=state)
            state = result.get("_state", state)
            val = result.get("atr_14")
            if val is None:
                continue
            if not math.isfinite(val) or val <= 0.0:
                failures.append((i, val))

        assert not failures, (
            f"ATR: {len(failures)} non-finite or non-positive values over 10K bars: "
            f"first 5 = {failures[:5]}"
        )

    def test_kalman_stable_over_10k_bars(self, long_run_ohlcv: pd.DataFrame) -> None:
        """Kalman filter must produce finite outputs and positive P_est at every bar.

        Strategy: compute_full on first 100 bars (>= min_lookback=30), then
        compute_next bar-by-bar for all remaining bars. Assert:
        - kalman_trend, kalman_slope, kalman_price_position are all finite
        - kalman_uncertainty (P_est) stays positive (filter stability invariant)
        - kalman_gain stays in (0, 1) (bounded Kalman gain)
        """
        plugin = KalmanTrendPlugin()
        n = len(long_run_ohlcv)
        warmup = 100

        frames = frames_from_ohlcv(long_run_ohlcv.iloc[:warmup])
        result = plugin.compute_full(frames)
        assert "kalman_trend" in result, "Kalman: compute_full failed on warmup window"
        state = result.get("_state", {})

        output_keys = [
            "kalman_trend",
            "kalman_slope",
            "kalman_price_position",
            "kalman_uncertainty",
            "kalman_upper",
            "kalman_lower",
            "kalman_gain",
        ]
        non_finite: list[tuple[int, str, float]] = []
        negative_p: list[tuple[int, float]] = []
        bad_gain: list[tuple[int, float]] = []

        for i in range(warmup, n):
            row_frames = frames_from_ohlcv(long_run_ohlcv.iloc[: i + 1])
            result = plugin.compute_next(row_frames, state=state)
            state = result.get("_state", state)

            for key in output_keys:
                val = result.get(key)
                if val is None:
                    continue
                if not math.isfinite(float(val)):
                    non_finite.append((i, key, float(val)))

            p_est = result.get("kalman_uncertainty")
            if p_est is not None and float(p_est) <= 0.0:
                negative_p.append((i, float(p_est)))

            gain = result.get("kalman_gain")
            if gain is not None and not (0.0 < float(gain) < 1.0):
                bad_gain.append((i, float(gain)))

        assert (
            not non_finite
        ), f"Kalman: {len(non_finite)} non-finite outputs: first 5 = {non_finite[:5]}"
        assert (
            not negative_p
        ), f"Kalman: P_est went non-positive at {len(negative_p)} bars: first 5 = {negative_p[:5]}"
        assert (
            not bad_gain
        ), f"Kalman: gain out of (0,1) at {len(bad_gain)} bars: first 5 = {bad_gain[:5]}"

    def test_garch_stable_over_10k_bars(self, long_run_ohlcv: pd.DataFrame) -> None:
        """GARCH(1,1) must keep garch_sigma in (1e-12, 1e6) and finite at every bar.

        Strategy: compute_full on first 100 bars, then compute_next bar-by-bar.
        Assert garch_sigma is finite and in the physically plausible range
        (1e-12, 1e6) — catches both underflow and overflow.
        """
        plugin = GARCHVolatilityPlugin()
        n = len(long_run_ohlcv)
        warmup = 100

        frames = frames_from_ohlcv(long_run_ohlcv.iloc[:warmup])
        result = plugin.compute_full(frames)
        assert "garch_sigma" in result, "GARCH: compute_full failed on warmup window"
        state = result.get("_state", {})

        sigma_lo = 1e-12
        sigma_hi = 1e6
        failures: list[tuple[int, float]] = []

        for i in range(warmup, n):
            row_frames = frames_from_ohlcv(long_run_ohlcv.iloc[: i + 1])
            result = plugin.compute_next(row_frames, state=state)
            state = result.get("_state", state)
            sigma = result.get("garch_sigma")
            if sigma is None:
                continue
            s = float(sigma)
            if not math.isfinite(s) or s < sigma_lo or s > sigma_hi:
                failures.append((i, s))

        assert not failures, (
            f"GARCH: {len(failures)} sigma values outside ({sigma_lo}, {sigma_hi}): "
            f"first 5 = {failures[:5]}"
        )

    def test_bollinger_stable_over_10k_bars(self, long_run_ohlcv: pd.DataFrame) -> None:
        """Bollinger Bands must satisfy upper >= mid >= lower at every bar.

        Strategy: compute_full on first 100 bars, then compute_next bar-by-bar.
        Assert the three-band relationship holds and all values are finite.
        """
        plugin = BollingerPlugin()
        n = len(long_run_ohlcv)
        warmup = 100

        frames = frames_from_ohlcv(long_run_ohlcv.iloc[:warmup])
        result = plugin.compute_full(frames)
        assert "bb_20_2_upper" in result, "Bollinger: compute_full failed on warmup window"
        state = result.get("_state", {})

        non_finite: list[tuple[int, str, float]] = []
        band_violations: list[tuple[int, float, float, float]] = []

        for i in range(warmup, n):
            row_frames = frames_from_ohlcv(long_run_ohlcv.iloc[: i + 1])
            result = plugin.compute_next(row_frames, state=state)
            state = result.get("_state", state)

            upper = result.get("bb_20_2_upper")
            mid = result.get("bb_20_2_mid")
            lower = result.get("bb_20_2_lower")

            if upper is None or mid is None or lower is None:
                continue

            for name, val in [("upper", upper), ("mid", mid), ("lower", lower)]:
                if not math.isfinite(float(val)):
                    non_finite.append((i, name, float(val)))

            if not (float(upper) >= float(mid) >= float(lower)):
                band_violations.append((i, float(upper), float(mid), float(lower)))

        assert (
            not non_finite
        ), f"Bollinger: {len(non_finite)} non-finite band values: first 5 = {non_finite[:5]}"
        assert not band_violations, (
            f"Bollinger: {len(band_violations)} band order violations (upper>=mid>=lower broken): "
            f"first 5 = {band_violations[:5]}"
        )
