"""Unit tests for trad_PatternCompletion structural rewrite (Phase 124-04).

Covers:
- Structural trigger: neckline break fires; confidence-only (no neckline break) does NOT fire
- Instance consumption: same (pattern, direction, anchor) fires at most once
- Triangle breakout: apex-bound breach fires once
- Pattern field persistence in signal dict
- Confidence formula properties (convergence, direction purity)
- Class attribute checks
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.archive.trading_i7.pattern_completion import PatternCompletionPlugin
from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

# Reference prices for structural tests
_NECKLINE_DB = 4900.0  # double_bottom neckline (close must exceed this)
_NECKLINE_DT = 5100.0  # double_top neckline (close must fall below this)
_NECKLINE_HS = 4950.0  # HS neckline


def _base_i5_features(
    dt_db_confidence: float = 0.0,
    dt_db_pattern: int = 0,
    dt_db_neckline: float | None = None,
    hs_confidence: float = 0.0,
    hs_pattern: int = 0,
    hs_neckline: float | None = None,
    tri_confidence: float = 0.0,
    tri_breakout_bias: int = 0,
    tri_apex_bars: int = 0,
    atr: float = 10.0,
) -> dict:
    """Minimal i1/i5 feature dict for PatternCompletion."""
    d: dict = {
        "atr_14": atr,
        "dt_db_confidence": dt_db_confidence,
        "dt_db_pattern": dt_db_pattern,
        "hs_confidence": hs_confidence,
        "hs_pattern": hs_pattern,
        "tri_confidence": tri_confidence,
        "tri_breakout_bias": tri_breakout_bias,
        "tri_apex_bars": tri_apex_bars,
    }
    if dt_db_neckline is not None:
        d["dt_db_neckline"] = dt_db_neckline
    if hs_neckline is not None:
        d["hs_neckline"] = hs_neckline
    return d


def _make_frames(features: dict, close_arr: np.ndarray | None = None) -> dict:
    """Build minimal frames dict for compute_full.

    Default close array rises from 5000 to 5050 (n=50).
    Override with close_arr for structural tests that need specific close values.
    """
    if close_arr is None:
        close_arr = np.linspace(5000.0, 5050.0, 50)
    df = make_ohlcv(close_arr)
    return {
        "main": df,
        "symbol": "",
        "__symbol__": "TEST",
        "__timeframe__": "1m",
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features,
    }


# ---------------------------------------------------------------------------
# Structural rewrite tests (Phase 124-04 mandated)
# ---------------------------------------------------------------------------


class TestConfidenceOnlyNoSignal:
    def test_confidence_only_no_fire_dt(self):
        """DT: confidence=0.80 > threshold, but close is ABOVE neckline — no structural completion."""
        # neckline_DT=5100; close ends at 5150 (above neckline) -> NOT below neckline -> no fire
        close_arr = np.linspace(5100.0, 5150.0, 50)
        features = _base_i5_features(
            dt_db_confidence=0.80,
            dt_db_pattern=1,  # double_top (bearish: close must break BELOW neckline)
            dt_db_neckline=_NECKLINE_DT,  # 5100 — close=5150 is ABOVE, no structural completion
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features, close_arr))
        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_confidence_only_no_fire_db(self):
        """DB: confidence=0.80 > threshold, but close is BELOW neckline — no structural completion."""
        # close starts at 5000, neckline at 5100 -> to NOT break above, use close < neckline
        close_arr = np.linspace(4800.0, 4850.0, 50)  # close[-1]=4850, below neckline 4900
        features = _base_i5_features(
            dt_db_confidence=0.80,
            dt_db_pattern=2,  # double_bottom (bullish: close must break ABOVE neckline)
            dt_db_neckline=_NECKLINE_DB,  # 4900 — close=4850 does NOT break above
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features, close_arr))
        assert result.get("signal_type", "none") == "none"

    def test_no_neckline_feature_no_fire(self):
        """If dt_db_neckline is absent from features, no structural completion can be detected."""
        features = _base_i5_features(
            dt_db_confidence=0.90,
            dt_db_pattern=2,  # double_bottom
            # dt_db_neckline intentionally omitted
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("signal_type", "none") == "none"


class TestNecklineBreakFiresOnce:
    def test_db_neckline_break_fires(self):
        """DB: close breaks above neckline — signal fires (direction=1)."""
        # close ends at 5050, neckline at 4900 -> close > neckline -> structural completion
        features = _base_i5_features(
            dt_db_confidence=0.75,
            dt_db_pattern=2,  # double_bottom
            dt_db_neckline=_NECKLINE_DB,  # 4900
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("direction") == 1
        assert result.get("signal_type", "").startswith("pattern_double_bottom")

    def test_dt_neckline_break_fires(self):
        """DT: close breaks below neckline — signal fires (direction=-1)."""
        # Use close array that ends BELOW neckline_dt=5100
        close_arr = np.linspace(5150.0, 5050.0, 50)  # falls to 5050 < 5100
        features = _base_i5_features(
            dt_db_confidence=0.75,
            dt_db_pattern=1,  # double_top
            dt_db_neckline=_NECKLINE_DT,  # 5100
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features, close_arr))
        assert result.get("direction") == -1
        assert result.get("signal_type", "").startswith("pattern_double_top")

    def test_hs_top_neckline_break_fires(self):
        """HS top: close breaks below neckline — signal fires (direction=-1)."""
        close_arr = np.linspace(5100.0, 4900.0, 50)  # falls to 4900 < 4950
        features = _base_i5_features(
            hs_confidence=0.78,
            hs_pattern=1,  # hs_top (bearish)
            hs_neckline=_NECKLINE_HS,  # 4950
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features, close_arr))
        assert result.get("direction") == -1
        assert "hs_top" in result.get("signal_type", "")

    def test_hs_bottom_neckline_break_fires(self):
        """Inverse HS: close breaks above neckline — signal fires (direction=1)."""
        close_arr = np.linspace(4800.0, 5100.0, 50)  # rises to 5100 > 4950
        features = _base_i5_features(
            hs_confidence=0.78,
            hs_pattern=2,  # hs_bottom (bullish)
            hs_neckline=_NECKLINE_HS,  # 4950
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features, close_arr))
        assert result.get("direction") == 1


class TestInstanceConsumption:
    def test_same_instance_no_refire(self):
        """Once a pattern instance fires, subsequent calls with same structural anchor return no_signal."""
        features = _base_i5_features(
            dt_db_confidence=0.75,
            dt_db_pattern=2,
            dt_db_neckline=_NECKLINE_DB,
        )
        plugin = PatternCompletionPlugin()
        frames = _make_frames(features)

        first = plugin.compute_full(frames)
        assert first.get("direction") == 1, "First call should fire"

        second = plugin.compute_full(frames)
        assert (
            second.get("signal_type", "none") == "none"
        ), "Second call with same instance must be suppressed"

    def test_different_anchor_fires_again(self):
        """A different structural anchor (new neckline level) produces a fresh signal."""
        features_a = _base_i5_features(
            dt_db_confidence=0.75,
            dt_db_pattern=2,
            dt_db_neckline=4900.0,
        )
        features_b = _base_i5_features(
            dt_db_confidence=0.75,
            dt_db_pattern=2,
            dt_db_neckline=4800.0,  # different neckline = different instance
        )
        plugin = PatternCompletionPlugin()

        first = plugin.compute_full(_make_frames(features_a))
        assert first.get("direction") == 1

        second = plugin.compute_full(_make_frames(features_b))
        assert second.get("direction") == 1, "Different structural anchor should fire"


class TestTriangleBreakout:
    def test_triangle_bullish_apex_breach_fires(self):
        """Triangle bullish breakout: close breaches consolidation high — fires (direction=1)."""
        # Build frames where recent bars consolidate then close[-1] breaks out above
        # consolidation high. apex_bars=5 -> lookback=5 bars for consolidation.
        n = 50
        close_arr = np.ones(n) * 5000.0
        # Last 5 bars consolidate at 5000 (high=5010, low=4990 via make_ohlcv spread)
        # Final bar breaks out above
        close_arr[-1] = 5200.0  # well above any consolidation high

        features = _base_i5_features(
            tri_confidence=0.75,
            tri_breakout_bias=1,  # bullish
            tri_apex_bars=5,
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features, close_arr))
        assert result.get("direction") == 1
        assert "triangle" in result.get("signal_type", "")

    def test_triangle_bearish_apex_breach_fires(self):
        """Triangle bearish breakout: close breaches consolidation low — fires (direction=-1)."""
        n = 50
        close_arr = np.ones(n) * 5000.0
        close_arr[-1] = 4800.0  # well below any consolidation low

        features = _base_i5_features(
            tri_confidence=0.75,
            tri_breakout_bias=-1,  # bearish
            tri_apex_bars=5,
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features, close_arr))
        assert result.get("direction") == -1

    def test_triangle_no_breach_no_fire(self):
        """Triangle: breakout_bias set but close stays within consolidation — no fire."""
        # Consolidation high ~5010 (from make_ohlcv spread on 5000 bars)
        # Final close=5005 does NOT breach consolidation high
        n = 50
        close_arr = np.ones(n) * 5000.0
        # Do not set close[-1] to breach the range — leave at 5000

        features = _base_i5_features(
            tri_confidence=0.75,
            tri_breakout_bias=1,  # bullish but not breaking out
            tri_apex_bars=5,
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features, close_arr))
        assert result.get("signal_type", "none") == "none"

    def test_triangle_instance_consumed(self):
        """Triangle fires once; re-submitting same apex fires no_signal on second call."""
        n = 50
        close_arr = np.ones(n) * 5000.0
        close_arr[-1] = 5200.0

        features = _base_i5_features(
            tri_confidence=0.75,
            tri_breakout_bias=1,
            tri_apex_bars=5,
        )
        plugin = PatternCompletionPlugin()
        frames = _make_frames(features, close_arr)

        first = plugin.compute_full(frames)
        assert first.get("direction") == 1

        second = plugin.compute_full(frames)
        assert second.get("signal_type", "none") == "none"


# ---------------------------------------------------------------------------
# Confidence threshold context filter
# ---------------------------------------------------------------------------


class TestConfidenceContextFilter:
    def test_confidence_below_threshold_suppresses_even_after_neckline_break(self):
        """Structural completion occurred (neckline broken) but confidence < 0.70: no signal."""
        features = _base_i5_features(
            dt_db_confidence=0.60,  # below 0.70 threshold
            dt_db_pattern=2,
            dt_db_neckline=_NECKLINE_DB,
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("signal_type", "none") == "none"

    def test_confidence_exactly_at_threshold_suppressed(self):
        """Strict > gate: confidence == 0.70 does NOT pass (must exceed, not equal)."""
        features = _base_i5_features(
            dt_db_confidence=0.70,
            dt_db_pattern=2,
            dt_db_neckline=_NECKLINE_DB,
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("signal_type", "none") == "none"

    def test_confidence_above_threshold_with_neckline_break_fires(self):
        """Confidence > 0.70 AND structural completion: signal fires."""
        features = _base_i5_features(
            dt_db_confidence=0.75,
            dt_db_pattern=2,
            dt_db_neckline=_NECKLINE_DB,
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("direction") == 1


# ---------------------------------------------------------------------------
# Pattern field persistence (data flow fix)
# ---------------------------------------------------------------------------


class TestPatternFieldPersistence:
    def test_pattern_fields_in_signal_dict(self):
        """Valid structural completion: signal dict contains pattern_name, pattern_raw_confidence, pattern_count."""
        features = _base_i5_features(
            dt_db_confidence=0.80,
            dt_db_pattern=2,
            dt_db_neckline=_NECKLINE_DB,
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))

        assert result.get("direction") != 0, "Expected a valid signal"
        assert isinstance(result["pattern_name"], str)
        assert len(result["pattern_name"]) > 0
        assert isinstance(result["pattern_raw_confidence"], float)
        assert isinstance(result["pattern_count"], int)
        assert result["pattern_count"] >= 1

    def test_pattern_name_matches_best_candidate(self):
        """dt_db_pattern=2 (double_bottom) -> pattern_name == 'double_bottom'."""
        features = _base_i5_features(
            dt_db_confidence=0.85,
            dt_db_pattern=2,
            dt_db_neckline=_NECKLINE_DB,
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("pattern_name") == "double_bottom"

    def test_pattern_raw_confidence_matches_best_candidate(self):
        """pattern_raw_confidence should equal the I5 confidence value (rounded to 4dp)."""
        features = _base_i5_features(
            dt_db_confidence=0.85,
            dt_db_pattern=2,
            dt_db_neckline=_NECKLINE_DB,
        )
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("pattern_raw_confidence") == pytest.approx(0.85, abs=1e-4)


# ---------------------------------------------------------------------------
# Confidence formula properties
# ---------------------------------------------------------------------------


class TestConfidenceFormula:
    def test_convergence_score_increases_with_candidates(self):
        """3 structurally-completing candidates -> higher confidence than 1 candidate."""
        # All bullish (direction=1): DB + HS bottom + triangle bullish
        close_arr = np.linspace(5000.0, 5050.0, 50)  # ends at 5050

        single_features = _base_i5_features(
            dt_db_confidence=0.80,
            dt_db_pattern=2,
            dt_db_neckline=_NECKLINE_DB,  # 4900 < 5050 -> structural completion
        )
        multi_features = _base_i5_features(
            dt_db_confidence=0.80,
            dt_db_pattern=2,
            dt_db_neckline=_NECKLINE_DB,
            hs_confidence=0.75,
            hs_pattern=2,  # hs_bottom (bullish: close=5050 > neckline_hs=4950)
            hs_neckline=_NECKLINE_HS,  # 4950 < 5050 -> structural completion
            tri_confidence=0.72,
            tri_breakout_bias=1,  # bullish; set apex_bars so breakout is detected
            tri_apex_bars=5,
        )
        # For triangle, close[-1]=5050 needs to exceed consolidation high.
        # With close_arr all at ~5050, consolidation bars[-6:-1] ~5050 -> no breach.
        # Use a breakout close for triangle.
        breakout_close = np.ones(50) * 5000.0
        breakout_close[-1] = 5200.0

        single_result = PatternCompletionPlugin().compute_full(
            _make_frames(single_features, close_arr)
        )
        multi_result = PatternCompletionPlugin().compute_full(
            _make_frames(multi_features, breakout_close)
        )

        assert single_result.get("direction") != 0, "Single candidate should fire"
        assert multi_result.get("direction") != 0, "Multi-candidate should fire"

        single_conf = single_result.get("confidence", 0.0)
        multi_conf = multi_result.get("confidence", 0.0)
        assert (
            multi_conf >= single_conf
        ), f"Multi-candidate ({multi_conf:.4f}) should be >= single-candidate ({single_conf:.4f})"

    def test_direction_purity_penalizes_disagreement(self):
        """Best candidate from agreeing pair vs disagreeing pair: agreeing has higher confidence."""
        # Agreeing: DT(bearish) + HS top(bearish) -> both -1
        # Disagreeing: DT(bearish, higher conf) + HS bottom(bullish, lower conf) -> split
        close_arr_down = np.linspace(5200.0, 5050.0, 50)  # falls to 5050 < neckline_dt=5100

        agree_features = _base_i5_features(
            dt_db_confidence=0.80,
            dt_db_pattern=1,  # double_top (bearish)
            dt_db_neckline=_NECKLINE_DT,  # 5100; close=5050 < 5100 -> completion
            hs_confidence=0.75,
            hs_pattern=1,  # hs_top (bearish)
            hs_neckline=5110.0,  # 5110; close=5050 < 5110 -> completion
        )
        disagree_features = _base_i5_features(
            dt_db_confidence=0.80,
            dt_db_pattern=1,  # double_top (bearish, direction=-1)
            dt_db_neckline=_NECKLINE_DT,
            hs_confidence=0.75,
            hs_pattern=2,  # hs_bottom (bullish, direction=1 — disagrees)
            hs_neckline=5000.0,  # 5000; close=5050 > 5000 -> structural completion for hs_bottom
        )

        agree_result = PatternCompletionPlugin().compute_full(
            _make_frames(agree_features, close_arr_down)
        )
        disagree_result = PatternCompletionPlugin().compute_full(
            _make_frames(disagree_features, close_arr_down)
        )

        assert agree_result.get("direction") != 0, "Agreeing candidates should produce signal"
        assert disagree_result.get("direction") != 0, "Disagreeing candidates should produce signal"

        agree_conf = agree_result.get("confidence", 0.0)
        disagree_conf = disagree_result.get("confidence", 0.0)
        assert (
            agree_conf > disagree_conf
        ), f"Agreeing ({agree_conf:.4f}) should beat disagreeing ({disagree_conf:.4f})"


# ---------------------------------------------------------------------------
# Class attribute checks
# ---------------------------------------------------------------------------


class TestClassAttributes:
    def test_regime_type_is_trend(self):
        assert PatternCompletionPlugin.regime_type == "trend"

    def test_shadow_only_flag(self):
        assert PatternCompletionPlugin.shadow_only is True

    def test_confidence_threshold_is_0_70(self):
        assert PatternCompletionPlugin.confidence_threshold == pytest.approx(0.70)

    def test_instances_registry_empty_on_init(self):
        """Each plugin instance starts with an empty _instances dict."""
        plugin = PatternCompletionPlugin()
        assert isinstance(plugin._instances, dict)
        assert len(plugin._instances) == 0
