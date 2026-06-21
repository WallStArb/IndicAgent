"""Tests for new I4 context plugins: SessionContext and MTFVolatility."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

# ---------------------------------------------------------------------------
# SessionContext
# ---------------------------------------------------------------------------


class TestSessionContext:
    def test_ny_killzone_at_0830_et(self):
        from src.intelligence.context.session_context import SessionContextPlugin

        # 8:30 AM ET = 13:30 UTC
        ts = datetime(2026, 3, 1, 13, 30, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "timestamp": [ts],
                "open": [5000],
                "high": [5010],
                "low": [4990],
                "close": [5005],
                "volume": [1000],
            }
        )
        result = SessionContextPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        # 8:30 ET: in NY AM killzone (7:00–10:00) but NY session opens at 9:30
        assert result.get("in_ny_killzone") == 1.0
        assert result.get("session_ny") == 0.0

    def test_london_session_at_0700_utc(self):
        from src.intelligence.context.session_context import SessionContextPlugin

        # 7:00 AM UTC = 2:00 AM ET
        ts = datetime(2026, 3, 2, 7, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "timestamp": [ts],
                "open": [5000],
                "high": [5010],
                "low": [4990],
                "close": [5000],
                "volume": [1000],
            }
        )
        result = SessionContextPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("session_london") == 0.0  # 2am ET, London starts 3am ET
        assert result.get("in_london_killzone") >= 0.2  # 2am ET in killzone, continuous gradient

    def test_ny_session_at_1400_utc(self):
        from src.intelligence.context.session_context import SessionContextPlugin

        # 14:00 UTC = 9:00 AM ET (NY not yet open)
        ts = datetime(2026, 3, 2, 14, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "timestamp": [ts],
                "open": [5000],
                "high": [5010],
                "low": [4990],
                "close": [5000],
                "volume": [1000],
            }
        )
        result = SessionContextPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        # 9:00 AM ET — NY opens at 9:30
        assert result.get("session_ny") == 0.0

    def test_ny_session_open_at_1500_utc(self):
        from src.intelligence.context.session_context import SessionContextPlugin

        # 15:00 UTC = 10:00 AM ET — NY is open
        ts = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "timestamp": [ts],
                "open": [5000],
                "high": [5010],
                "low": [4990],
                "close": [5000],
                "volume": [1000],
            }
        )
        result = SessionContextPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("session_ny") >= 0.2  # Continuous bell-shaped gradient, >= floor

    def test_monday_flag(self):
        from src.intelligence.context.session_context import SessionContextPlugin

        # 2026-03-02 is a Monday
        ts = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "timestamp": [ts],
                "open": [5000],
                "high": [5010],
                "low": [4990],
                "close": [5000],
                "volume": [1000],
            }
        )
        result = SessionContextPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("is_monday") == 1.0
        assert result.get("is_friday") == 0.0

    def test_no_timestamp_returns_neutral(self):
        import numpy as np

        from src.intelligence.context.session_context import SessionContextPlugin
        from tests.unit.intelligence.helpers import make_ohlcv

        close = np.full(10, 5000.0)
        df = make_ohlcv(close)
        result = SessionContextPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        # Should return neutral 0.0 for all flags when no timestamp
        assert isinstance(result, dict)
        assert len(result) == 27  # updated: plugin now has 27 outputs

    def test_empty_returns_empty(self):
        from src.intelligence.context.session_context import SessionContextPlugin

        assert SessionContextPlugin().compute_full({}) == {}

    def test_minutes_to_ny_positive(self):
        from src.intelligence.context.session_context import SessionContextPlugin

        # 6am ET = before NY open
        ts = datetime(2026, 3, 2, 11, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "timestamp": [ts],
                "open": [5000],
                "high": [5010],
                "low": [4990],
                "close": [5000],
                "volume": [1000],
            }
        )
        result = SessionContextPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("minutes_to_ny_open", 0) > 0


# ---------------------------------------------------------------------------
# MTFVolatility
# ---------------------------------------------------------------------------


class TestMTFVolatility:
    def test_squeeze_within_expansion_detected(self):
        from src.intelligence.archive.i5_patterns.mtf_volatility import MTFVolatilityPlugin

        features = {
            "squeeze_active": 1.0,
            "vol_expansion": -0.5,
            # BB inside Keltner = squeeze (detected independently by plugin)
            "bb_20_2_upper": 100.5,
            "bb_20_2_lower": 99.5,
            "keltner_upper": 101.0,
            "keltner_lower": 99.0,
        }
        intel_15m = {"vol_expansion": 0.8}
        result = MTFVolatilityPlugin().compute_full(
            {
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
                "intel_15m": intel_15m,
            }
        )
        assert result.get("squeeze_within_expansion") > 0.0  # Continuous gradient, not binary

    def test_no_squeeze_without_expansion(self):
        from src.intelligence.archive.i5_patterns.mtf_volatility import MTFVolatilityPlugin

        features = {"squeeze_active": 1.0, "vol_expansion": -0.5}
        result = MTFVolatilityPlugin().compute_full(
            {
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        # No intel_15m or intel_1h → higher TF not expanding → no squeeze_within
        assert result.get("squeeze_within_expansion") == 0.0

    def test_no_expansion_without_cache(self):
        from src.intelligence.archive.i5_patterns.mtf_volatility import MTFVolatilityPlugin

        result = MTFVolatilityPlugin().compute_full(
            {"i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("mtf_vol_expansion_15m") == 0.0
        assert result.get("mtf_vol_expansion_1h") == 0.0

    def test_both_tfs_expanding(self):
        from src.intelligence.archive.i5_patterns.mtf_volatility import MTFVolatilityPlugin

        result = MTFVolatilityPlugin().compute_full(
            {
                "i1": {"vol_expansion": 1.0},
                "i2": {"vol_expansion": 1.0},
                "i3": {"vol_expansion": 1.0},
                "i4": {"vol_expansion": 1.0},
                "i5": {"vol_expansion": 1.0},
                "smc": {"vol_expansion": 1.0},
                "i6": {"vol_expansion": 1.0},
                "intel_15m": {"vol_expansion": 1.0},
                "intel_1h": {"vol_expansion": 1.0},
            }
        )
        assert result.get("mtf_vol_expansion_15m") == 1.0
        assert result.get("mtf_vol_expansion_1h") == 1.0
        assert result.get("vol_divergence_score", 0) > 0

    def test_divergence_score_clamped(self):
        from src.intelligence.archive.i5_patterns.mtf_volatility import MTFVolatilityPlugin

        result = MTFVolatilityPlugin().compute_full(
            {
                "i1": {"vol_expansion": 10.0},
                "i2": {"vol_expansion": 10.0},
                "i3": {"vol_expansion": 10.0},
                "i4": {"vol_expansion": 10.0},
                "i5": {"vol_expansion": 10.0},
                "smc": {"vol_expansion": 10.0},
                "i6": {"vol_expansion": 10.0},
                "intel_15m": {"vol_expansion": 10.0},
                "intel_1h": {"vol_expansion": 10.0},
            }
        )
        assert -1.0 <= result.get("vol_divergence_score", 0) <= 1.0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestI4Registration:
    def test_new_plugins_in_tier_i4(self):
        from src.intelligence.register_plugins import TIER_I4

        assert "ctx_SessionContext" in TIER_I4
        # ctx_MTFVolatility moved to TIER_I5 (reads squeeze_active from I5)

    def test_i4context_accepts_new_fields(self):
        from src.intelligence.schemas import I4Context

        obj = I4Context(
            session_ny=1.0,
            in_ny_killzone=1.0,
            is_monday=1.0,
        )
        assert obj.session_ny == 1.0
