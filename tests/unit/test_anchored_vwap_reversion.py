"""Unit tests for trad_AnchoredVWAPReversion structural rewrite.

Tests verify:
- Displacement-only (no return velocity) produces no signal
- Departure + return velocity + reclaim confirmation fires once
- Wick-only reclaim (close stays on departure side) rejected
- deduplicate_event prevents re-fire on same (departure_sigma, vwap) episode
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 30, close_val: float = 5000.0) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame."""
    close = np.full(n, close_val, dtype=float)
    spread = close * 0.002
    high = close + spread
    low = close - spread
    open_ = close.copy()
    volume = np.full(n, 1000.0)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def _make_frames(
    *,
    close_val: float = 5000.0,
    sigma: float = 2.0,
    velocity: float = -0.05,
    vwap: float = 5000.0,
    hmm: int = 0,
    hurst: float = 0.45,
    df_override: pd.DataFrame | None = None,
    atr: float = 10.0,
) -> dict:
    """Build a minimal frames dict for AnchoredVWAPReversionPlugin."""
    df = df_override if df_override is not None else _make_ohlcv(close_val=close_val)

    features = {
        "session_vwap_deviation_sigma": sigma,
        "session_vwap_deviation_velocity": velocity,
        "session_vwap": vwap,
        "hmm_regime": hmm,
        "hurst_exponent": hurst,
        "hurst_mr_quality": 1.0 - hurst,
        "vol_regime": 0.5,
        "atr_14": atr,
        "avwap_upper_band": vwap + 2 * atr,
        "avwap_lower_band": vwap - 2 * atr,
        "ctf_score": 0.0,
        "timeframe": "1m",
        "timestamp": "2026-01-01T10:00:00Z",
    }

    return {
        "main": df,
        "i1": features,
        "i2": {},
        "i3": {},
        "i4": features,
        "i5": {},
        "smc": features,
        "i6": features,
        "__symbol__": "ES",
        "__timeframe__": "1m",
        "symbol": "ES",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnchoredVWAPReversionStructural:
    def _plugin(self):
        from src.intelligence.trading.anchored_vwap_reversion import (
            AnchoredVWAPReversionPlugin,
        )

        return AnchoredVWAPReversionPlugin()

    def test_displacement_only_no_signal(self):
        """Continuous displacement abs(sigma) >= 1.5 with NO return velocity must not fire.

        Price is above VWAP (sigma > 0) and velocity is also positive (pushing further away).
        No reclaim, no return - must produce no_signal() for all 10 bars.
        """
        plugin = self._plugin()

        # sigma = 2.0 (departed), velocity = +0.1 (moving away from VWAP, NOT toward it)
        for _ in range(10):
            frames = _make_frames(
                close_val=5020.0,
                sigma=2.0,
                velocity=0.1,  # moving AWAY from VWAP (sigma > 0 => toward would be < 0)
                vwap=5000.0,
            )
            result = plugin.compute_full(frames)
            assert (
                result.get("signal_type") == "none"
            ), "Displacement-only (no return velocity) must not fire"

    def test_departure_plus_return_fires_once(self):
        """Departure (sigma=2.0) followed by return velocity + reclaim must fire once.

        Bars 1-5: departed (sigma grows to 2.0), no return velocity
        Bar 6: velocity toward VWAP, close crosses below VWAP (reclaim) -> fires
        """
        plugin = self._plugin()
        vwap = 5000.0

        # Bars 1-5: departed above VWAP, no return velocity
        for _ in range(5):
            frames = _make_frames(
                close_val=5020.0,
                sigma=2.0,
                velocity=0.05,  # not toward VWAP
                vwap=vwap,
            )
            result = plugin.compute_full(frames)
            assert result.get("signal_type") == "none", "Should not fire before return"

        # Bar 6: return velocity + reclaim candle (close < VWAP for sigma > 0)
        # sigma > 0 means price above VWAP; reclaim = close crosses back below VWAP
        close_arr = np.full(30, vwap - 5.0)  # close at 4995 (below VWAP = reclaim)
        df_reclaim = pd.DataFrame(
            {
                "open": close_arr,
                "high": close_arr + 5.0,
                "low": close_arr - 2.0,
                "close": close_arr,
                "volume": np.full(30, 1000.0),
            }
        )
        frames_reclaim = _make_frames(
            close_val=vwap - 5.0,
            sigma=2.0,  # still departed by sigma measure
            velocity=-0.05,  # toward VWAP (sigma > 0 => toward = velocity < 0)
            vwap=vwap,
            df_override=df_reclaim,
        )
        result = plugin.compute_full(frames_reclaim)
        assert (
            result.get("signal_type") == "vwap_reversion_short"
        ), f"Expected fire on departure+return bar; got: {result.get('signal_type')}"
        assert result.get("direction") == -1
        assert 0.0 < result.get("confidence", 0.0) <= 1.0

    def test_wick_only_no_fire(self):
        """Wick touches VWAP but close stays above -> no reclaim confirmation.

        sigma = 2.0 (above VWAP), velocity toward VWAP, but close stays above VWAP.
        Only the wick dips to VWAP level. Must return no_signal().
        """
        plugin = self._plugin()
        vwap = 5000.0

        # Depart first so departure_sigma is set
        frames_depart = _make_frames(
            close_val=5020.0,
            sigma=2.0,
            velocity=0.05,  # away from VWAP
            vwap=vwap,
        )
        plugin.compute_full(frames_depart)

        # Wick-only: high touches but close stays ABOVE VWAP (no reclaim)
        close_arr = np.full(30, 5008.0)  # close above vwap=5000
        df_wick = pd.DataFrame(
            {
                "open": close_arr,
                "high": close_arr + 10.0,
                "low": np.full(30, vwap - 2.0),  # wick dips below VWAP
                "close": close_arr,  # but close stays ABOVE
                "volume": np.full(30, 1000.0),
            }
        )
        frames_wick = _make_frames(
            close_val=5008.0,
            sigma=1.6,  # still departed
            velocity=-0.03,  # toward VWAP
            vwap=vwap,
            df_override=df_wick,
        )
        result = plugin.compute_full(frames_wick)
        assert (
            result.get("signal_type") == "none"
        ), "Wick-only reclaim (close stays above VWAP) must not fire"

    def test_deduplicate_prevents_refire(self):
        """After firing, same (departure_sigma, vwap) episode must not re-fire.

        Bar 6 fires. Bar 7 has identical departure_sigma and vwap.
        deduplicate_event must block the second fire.
        """
        plugin = self._plugin()
        vwap = 5000.0
        departure_sigma = 2.0

        # Depart first
        frames_depart = _make_frames(
            close_val=5020.0,
            sigma=departure_sigma,
            velocity=0.05,
            vwap=vwap,
        )
        plugin.compute_full(frames_depart)

        # Build reclaim bar (close below VWAP)
        close_arr = np.full(30, vwap - 5.0)
        df_reclaim = pd.DataFrame(
            {
                "open": close_arr,
                "high": close_arr + 3.0,
                "low": close_arr - 2.0,
                "close": close_arr,
                "volume": np.full(30, 1000.0),
            }
        )

        def _reclaim_frames():
            return _make_frames(
                close_val=vwap - 5.0,
                sigma=departure_sigma,
                velocity=-0.05,
                vwap=vwap,
                df_override=df_reclaim,
            )

        # First reclaim bar -> should fire
        result_1 = plugin.compute_full(_reclaim_frames())
        assert result_1.get("signal_type") == "vwap_reversion_short", "First reclaim bar must fire"

        # Second bar with identical (departure_sigma, vwap) -> deduplicate must block
        result_2 = plugin.compute_full(_reclaim_frames())
        assert (
            result_2.get("signal_type") == "none"
        ), "deduplicate_event must prevent re-fire on same episode"
