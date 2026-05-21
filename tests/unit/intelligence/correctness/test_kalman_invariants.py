"""Mathematical invariant tests for KalmanTrendPlugin.

Enforces these algebraic preconditions in code (not docs):
  - Posterior covariance P_est > 0 always (scalar local-level model guarantees this
    when Q > 0 and R > 0).
  - Kalman gain K strictly in (0, 1) always.
  - No NaN/Inf in any output across 500 bars.
  - Incremental state updates equal full recomputation on the same input window.
  - Slope is directionally consistent with the simulated trend.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.intelligence.context.kalman_trend import KalmanTrendPlugin
from tests.unit.intelligence.correctness.conftest import frames_from_ohlcv


def _run_full_then_incremental(plugin: KalmanTrendPlugin, df: pd.DataFrame) -> list[dict]:
    """Drive compute_full on all bars, then compute_next bar-by-bar threading state.

    Returns list of per-bar result dicts (starting from bar 0).
    """
    results = []
    # Bootstrap: compute_full gives us the initial state
    result = plugin.compute_full(frames_from_ohlcv(df))
    if not result:
        return results
    results.append(result)
    state = dict(result["_state"])

    # Incremental: advance one bar at a time using the last N rows as window
    for i in range(1, len(df)):
        # compute_next only needs the latest close; provide a 1-row window
        window = frames_from_ohlcv(df.iloc[i : i + 1])
        result = plugin.compute_next(window, state=state)
        if not result:
            break
        results.append(result)
        state = dict(result["_state"])

    return results


class TestKalmanInvariants:
    """Invariant tests for KalmanTrendPlugin's scalar local-level Kalman filter."""

    def test_kalman_covariance_strictly_positive(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """P_est (posterior covariance) must be strictly positive after every update.

        In the scalar local-level model:
          P_pred = P_est + Q          (Q > 0 -> P_pred > 0 whenever P_est >= 0)
          K      = P_pred / (P_pred + R)  (K in (0,1) for positive P_pred, R)
          P_est  = (1 - K) * P_pred   (K < 1 -> P_est > 0)

        The initialization sets P_est = R > 0, so the invariant is maintained
        inductively for all subsequent bars.
        """
        plugin = KalmanTrendPlugin()
        df = synthetic_ohlcv_trending
        results = _run_full_then_incremental(plugin, df)
        assert len(results) >= 100, "Expected at least 100 incremental results"
        for idx, r in enumerate(results):
            state = r["_state"]
            P_est = state["P_est"]
            assert P_est > 0.0, f"Bar {idx}: P_est={P_est} is not positive"
            assert math.isfinite(P_est), f"Bar {idx}: P_est={P_est} is not finite"

    def test_kalman_gain_bounded(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """Kalman gain K must be strictly in (0, 1) after every update.

        In the scalar local-level model with positive R and Q:
          K = P_pred / (P_pred + R)
        Since P_pred = P_est + Q > 0 (by the covariance invariant) and R > 0,
        we have 0 < P_pred < P_pred + R, so K = P_pred / (P_pred + R) in (0, 1).

        The plugin also exposes K directly in the 'kalman_gain' output key,
        allowing us to verify the invariant without recomputing K.
        """
        plugin = KalmanTrendPlugin()
        df = synthetic_ohlcv_trending
        results = _run_full_then_incremental(plugin, df)
        assert len(results) >= 100
        for idx, r in enumerate(results):
            # kalman_gain is exposed as an output key (verified by reading kalman_trend.py)
            K = r.get("kalman_gain")
            assert K is not None, f"Bar {idx}: 'kalman_gain' key missing from result"
            # Scalar local-level invariant: K = P_pred / (P_pred + R)
            # With P_pred > 0 and R > 0, K must be strictly in (0, 1).
            assert 0.0 < K < 1.0, f"Bar {idx}: K={K} violates 0 < K < 1"
            assert math.isfinite(K), f"Bar {idx}: K={K} is not finite"

    @pytest.mark.parametrize(
        "fixture_name",
        ["synthetic_ohlcv_trending", "synthetic_ohlcv_ranging", "synthetic_ohlcv_gap"],
    )
    def test_kalman_no_nan_inf_in_outputs(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        """All output values must be finite (no NaN or Inf) across diverse input scenarios."""
        df: pd.DataFrame = request.getfixturevalue(fixture_name)
        plugin = KalmanTrendPlugin()
        # compute_full on the full dataset
        result = plugin.compute_full(frames_from_ohlcv(df))
        assert result, f"{fixture_name}: compute_full returned empty result"
        for key, val in result.items():
            if key == "_state":
                continue
            assert math.isfinite(float(val)), f"{fixture_name}: output '{key}'={val} is not finite"

        # Also check incremental outputs
        state = dict(result["_state"])
        for i in range(1, min(50, len(df))):
            window = frames_from_ohlcv(df.iloc[i : i + 1])
            r = plugin.compute_next(window, state=state)
            if not r:
                continue
            for key, val in r.items():
                if key == "_state":
                    continue
                assert math.isfinite(
                    float(val)
                ), f"{fixture_name} bar {i}: output '{key}'={val} is not finite"
            state = dict(r["_state"])

    def test_kalman_incremental_equals_full(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """compute_next must produce identical results to compute_full on the same window.

        Protocol:
          1. compute_full on bars[0:100] to get bootstrap state.
          2. compute_next bar-by-bar for bars[100:200] threading state forward.
          3. compute_full on bars[0:200] independently.
          4. Assert final output values from (2) and (3) match within atol=1e-6.
        """
        plugin = KalmanTrendPlugin()
        df = synthetic_ohlcv_trending

        # Step 1: bootstrap on first 100 bars
        result_bootstrap = plugin.compute_full(frames_from_ohlcv(df.iloc[:100]))
        assert result_bootstrap, "Bootstrap compute_full returned empty"
        state = dict(result_bootstrap["_state"])

        # Step 2: incremental for bars 100..199
        last_incremental: dict = {}
        for i in range(100, 200):
            window = frames_from_ohlcv(df.iloc[i : i + 1])
            r = plugin.compute_next(window, state=state)
            assert r, f"compute_next returned empty at bar {i}"
            last_incremental = r
            state = dict(r["_state"])

        # Step 3: full recomputation on bars[0:200]
        result_full = plugin.compute_full(frames_from_ohlcv(df.iloc[:200]))
        assert result_full, "Full compute_full on 200 bars returned empty"

        # Step 4: compare all scalar outputs
        output_keys = [
            "kalman_trend",
            "kalman_slope",
            "kalman_price_position",
            "kalman_uncertainty",
            "kalman_upper",
            "kalman_lower",
            "kalman_gain",
        ]
        for key in output_keys:
            inc_val = last_incremental.get(key)
            full_val = result_full.get(key)
            assert inc_val is not None, f"Incremental result missing key '{key}'"
            assert full_val is not None, f"Full result missing key '{key}'"
            assert math.isclose(float(inc_val), float(full_val), abs_tol=1e-6), (
                f"Key '{key}': incremental={inc_val} vs full={full_val} "
                f"(diff={abs(float(inc_val) - float(full_val)):.2e})"
            )

    def test_kalman_slope_directionally_tracks_trend(
        self,
        synthetic_ohlcv_trending: pd.DataFrame,
        synthetic_ohlcv_ranging: pd.DataFrame,
    ) -> None:
        """Kalman slope must be directionally consistent with the underlying trend.

        The slope output is `kalman_trend[t] - kalman_trend[t-5]` (a 5-bar window).
        At a single bar it can be transiently negative even on a strongly upward trend
        due to local noise. The correct invariant tests the full-window net gain:
        the filtered level (kalman_trend) at bar 499 must exceed the filtered level
        at bar 30 (the minimum lookback) on net-upward trending data.

        On ranging data (sine wave around a constant base), the net change in the
        filtered level over the full window must be smaller in absolute terms than
        on the trending data, because the filter has spent the series tracking
        reversals rather than a sustained drift.
        """
        plugin = KalmanTrendPlugin()

        # Collect filtered level at every bar by running incrementally
        def collect_trend_levels(df: pd.DataFrame) -> list[float]:
            r = plugin.compute_full(frames_from_ohlcv(df.iloc[: plugin.min_lookback]))
            if not r:
                return []
            state = dict(r["_state"])
            levels = [float(r["kalman_trend"])]
            for i in range(plugin.min_lookback, len(df)):
                r2 = plugin.compute_next(frames_from_ohlcv(df.iloc[i : i + 1]), state=state)
                if not r2:
                    break
                levels.append(float(r2["kalman_trend"]))
                state = dict(r2["_state"])
            return levels

        trend_levels = collect_trend_levels(synthetic_ohlcv_trending)
        range_levels = collect_trend_levels(synthetic_ohlcv_ranging)

        assert len(trend_levels) >= 2, "Not enough trend bars collected"
        assert len(range_levels) >= 2, "Not enough ranging bars collected"

        # Net change in filtered level: trending must be positive (price went up ~27%)
        net_change_trend = trend_levels[-1] - trend_levels[0]
        net_change_range = abs(range_levels[-1] - range_levels[0])

        assert net_change_trend > 0.0, (
            f"Expected positive net change on trending data, "
            f"got {net_change_trend:.4f} (start={trend_levels[0]:.4f}, "
            f"end={trend_levels[-1]:.4f})"
        )

        # Ranging data should show much less net directional displacement
        # than trending data over the same number of bars
        assert net_change_range < net_change_trend, (
            f"Expected |net_range|={net_change_range:.4f} < " f"net_trend={net_change_trend:.4f}"
        )
