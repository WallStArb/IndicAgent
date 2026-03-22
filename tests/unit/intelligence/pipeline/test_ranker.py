"""Unit tests for rank_signals pure function."""
from __future__ import annotations

from src.intelligence.pipeline.ranker import rank_signals
from src.intelligence.trading.aggregator import SETUP_PRIORITY


def make_signal(confidence=0.8, plugin="trad_TrendFollowing", direction=1, regime_type="trend"):
    return {
        "confidence": confidence,
        "setup_plugin": plugin,
        "direction": direction,
        "regime_type": regime_type,
        "regime_type_at_fire": regime_type,
    }


def test_computes_adjusted_rank():
    """Known plugin + perf_weight → adjusted_rank = priority * weight."""
    plugin = "trad_TrendFollowing"
    priority = SETUP_PRIORITY[plugin]
    weight = 0.8
    sig = make_signal(plugin=plugin)
    result = rank_signals([sig], {(plugin, "1m"): weight}, "1m")
    expected_rank = round(priority * weight, 4)
    assert result[0]["adjusted_rank"] == expected_rank
    assert result[0]["perf_multiplier"] == weight


def test_unknown_plugin_gets_999():
    """Plugin not in SETUP_PRIORITY → priority=999."""
    sig = make_signal(plugin="trad_Unknown")
    result = rank_signals([sig], {}, "1m")
    assert result[0]["adjusted_rank"] == round(999 * 1.0, 4)


def test_missing_perf_weight_defaults_to_one():
    """No perf_weight entry → multiplier=1.0."""
    plugin = "trad_TrendFollowing"
    priority = SETUP_PRIORITY[plugin]
    sig = make_signal(plugin=plugin)
    result = rank_signals([sig], {}, "1m")
    assert result[0]["perf_multiplier"] == 1.0
    assert result[0]["adjusted_rank"] == round(priority * 1.0, 4)


def test_does_not_mutate_input():
    """Input signal dicts are not mutated."""
    sig = make_signal(plugin="trad_TrendFollowing")
    original_conf = sig["confidence"]
    rank_signals([sig], {}, "1m")
    assert sig["confidence"] == original_conf
    assert "adjusted_rank" not in sig
