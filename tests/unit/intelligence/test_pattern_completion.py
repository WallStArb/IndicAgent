"""Unit tests for trad_PatternCompletion (Phase 118-02).

Covers:
- threshold gate at 0.70 (rejects below, accepts above)
- pattern fields persisted into signal dict (data flow fix)
- convergence_score increases with more candidates
- direction_purity penalizes disagreement
- regime_type, shadow_only, requires_i6_confluence class attributes
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.trading.pattern_completion import PatternCompletionPlugin
from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _base_i5_features(
    dt_db_confidence: float = 0.0,
    dt_db_pattern: int = 0,
    hs_confidence: float = 0.0,
    hs_pattern: int = 0,
    tri_confidence: float = 0.0,
    tri_breakout_bias: int = 0,
    atr: float = 10.0,
) -> dict:
    """Minimal i1/i5 feature dict for PatternCompletion."""
    return {
        "atr_14": atr,
        "dt_db_confidence": dt_db_confidence,
        "dt_db_pattern": dt_db_pattern,
        "hs_confidence": hs_confidence,
        "hs_pattern": hs_pattern,
        "tri_confidence": tri_confidence,
        "tri_breakout_bias": tri_breakout_bias,
    }


def _make_frames(features: dict, n: int = 50) -> dict:
    """Build a minimal frames dict suitable for compute_full."""
    close = np.linspace(5000.0, 5050.0, n)
    df = make_ohlcv(close)
    return {
        "main": df,
        "symbol": "",
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features,
    }


# ---------------------------------------------------------------------------
# Threshold gate
# ---------------------------------------------------------------------------


class TestThresholdGate:
    def test_threshold_gate_rejects_below_0_70(self):
        """best_confidence = 0.60 < 0.70 threshold: no signal returned."""
        features = _base_i5_features(dt_db_confidence=0.60, dt_db_pattern=2)
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_threshold_gate_accepts_above_0_70(self):
        """best_confidence = 0.75 > 0.70 threshold: signal returned."""
        features = _base_i5_features(dt_db_confidence=0.75, dt_db_pattern=2)
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        # A valid signal has direction != 0
        assert result.get("direction") == 1  # double_bottom is bullish

    def test_threshold_gate_exactly_at_0_70_is_rejected(self):
        """Confidence exactly == 0.70 does NOT exceed the strict > gate."""
        features = _base_i5_features(dt_db_confidence=0.70, dt_db_pattern=2)
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("signal_type", "none") == "none"


# ---------------------------------------------------------------------------
# Pattern field persistence (data flow fix)
# ---------------------------------------------------------------------------


class TestPatternFieldPersistence:
    def test_pattern_fields_in_signal_dict(self):
        """Valid candidate: signal dict contains pattern_name, pattern_raw_confidence, pattern_count."""
        features = _base_i5_features(dt_db_confidence=0.80, dt_db_pattern=2)
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))

        # Must be a valid signal
        assert result.get("direction") != 0, "Expected a valid signal"

        # Structured fields present with correct types
        assert isinstance(result["pattern_name"], str)
        assert len(result["pattern_name"]) > 0
        assert isinstance(result["pattern_raw_confidence"], float)
        assert isinstance(result["pattern_count"], int)
        assert result["pattern_count"] >= 1

    def test_pattern_name_matches_best_candidate(self):
        """dt_db_pattern=2 (double_bottom) -> pattern_name == 'double_bottom'."""
        features = _base_i5_features(dt_db_confidence=0.85, dt_db_pattern=2)
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("pattern_name") == "double_bottom"

    def test_pattern_raw_confidence_matches_best_candidate(self):
        """pattern_raw_confidence should equal the I5 confidence value (rounded to 4dp)."""
        features = _base_i5_features(dt_db_confidence=0.85, dt_db_pattern=2)
        plugin = PatternCompletionPlugin()
        result = plugin.compute_full(_make_frames(features))
        assert result.get("pattern_raw_confidence") == pytest.approx(0.85, abs=1e-4)


# ---------------------------------------------------------------------------
# Confidence formula properties
# ---------------------------------------------------------------------------


class TestConfidenceFormula:
    def test_convergence_score_increases_with_candidates(self):
        """3 candidates at same best_confidence -> higher confidence than 1 candidate."""
        single_features = _base_i5_features(dt_db_confidence=0.80, dt_db_pattern=2)
        multi_features = _base_i5_features(
            dt_db_confidence=0.80,
            dt_db_pattern=2,  # bullish
            hs_confidence=0.75,
            hs_pattern=2,  # hs_bottom (bullish)
            tri_confidence=0.72,
            tri_breakout_bias=1,  # bullish
        )

        # Fresh instances: deduplicate_event fires once per zone per plugin instance
        single_result = PatternCompletionPlugin().compute_full(_make_frames(single_features))
        multi_result = PatternCompletionPlugin().compute_full(_make_frames(multi_features))

        assert single_result.get("direction") != 0, "Expected valid signal for single candidate"
        assert multi_result.get("direction") != 0, "Expected valid signal for multi candidate"

        single_conf = single_result.get("confidence", 0.0)
        multi_conf = multi_result.get("confidence", 0.0)
        assert (
            multi_conf > single_conf
        ), f"Multi-candidate ({multi_conf:.4f}) should beat single-candidate ({single_conf:.4f})"

    def test_direction_purity_penalizes_disagreement(self):
        """Two candidates of opposite direction -> lower confidence than two agreeing."""
        agree_features = _base_i5_features(
            dt_db_confidence=0.80,
            dt_db_pattern=2,  # bullish (direction=1)
            hs_confidence=0.75,
            hs_pattern=2,  # bullish (direction=1)
        )
        disagree_features = _base_i5_features(
            dt_db_confidence=0.80,
            dt_db_pattern=1,  # double_top (bearish, direction=-1) — highest confidence
            hs_confidence=0.75,
            hs_pattern=2,  # hs_bottom (bullish, direction=1) — disagrees
        )

        plugin = PatternCompletionPlugin()
        agree_result = plugin.compute_full(_make_frames(agree_features))
        disagree_result = plugin.compute_full(_make_frames(disagree_features))

        assert agree_result.get("direction") != 0, "Expected valid signal for agreeing candidates"
        assert (
            disagree_result.get("direction") != 0
        ), "Expected valid signal for disagreeing candidates"

        agree_conf = agree_result.get("confidence", 0.0)
        disagree_conf = disagree_result.get("confidence", 0.0)
        assert (
            agree_conf > disagree_conf
        ), f"Agreeing ({agree_conf:.4f}) should beat disagreeing ({disagree_conf:.4f})"


# ---------------------------------------------------------------------------
# Class attribute checks (eligibility gate + governance flags)
# ---------------------------------------------------------------------------


class TestClassAttributes:
    def test_regime_type_is_trend(self):
        """regime_type = 'trend': the aggregator regime filter applies this as an eligibility gate.

        This is NOT a confidence modifier — confidence stays intrinsic. The comment in the
        source code documents this distinction explicitly to prevent future confusion.
        """
        assert PatternCompletionPlugin.regime_type == "trend"

    def test_shadow_only_flag(self):
        """shadow_only = True: plugin runs in shadow mode until promoted by evidence gate."""
        assert PatternCompletionPlugin.shadow_only is True

    def test_requires_i6_confluence_flag(self):
        """requires_i6_confluence = True: I6 confluence check required before promotion."""
        assert PatternCompletionPlugin.requires_i6_confluence is True

    def test_confidence_threshold_is_0_70(self):
        """confidence_threshold raised to 0.70 from the pre-Phase-118 value of 0.50."""
        assert PatternCompletionPlugin.confidence_threshold == pytest.approx(0.70)
