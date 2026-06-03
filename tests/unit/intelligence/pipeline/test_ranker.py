"""Unit tests for rank_signals pure function.

Phase 112 2-C: SETUP_PRIORITY removed. adjusted_rank = perf_multiplier.
D-16: sample_size < 100 → warm-up penalty (0.5).
"""

from __future__ import annotations

import pytest

from src.intelligence.pipeline.ranker import WARMUP_PENALTY_MULTIPLIER, rank_signals


def make_signal(confidence=0.8, plugin="trad_TrendFollowing", direction=1, regime_type="trend"):
    return {
        "confidence": confidence,
        "setup_plugin": plugin,
        "direction": direction,
        "regime_type": regime_type,
        "regime_type_at_fire": regime_type,
    }


@pytest.mark.asyncio
async def test_computes_adjusted_rank_from_perf_weight():
    """adjusted_rank = perf_multiplier (no SETUP_PRIORITY factor, 2-C)."""
    plugin = "trad_TrendFollowing"
    weight = 0.8
    sig = make_signal(plugin=plugin)
    # Pass sample_size=100 via tuple to get above warm-up threshold
    result = await rank_signals([sig], {(plugin, "1m", "*"): (weight, 100)}, "1m")
    assert result[0]["adjusted_rank"] == round(weight, 4)
    assert result[0]["perf_multiplier"] == weight
    assert result[0]["sample_size"] == 100


@pytest.mark.asyncio
async def test_unknown_plugin_gets_warmup_penalty():
    """Plugin absent from perf_weights → warm-up penalty 0.5 (D-16)."""
    sig = make_signal(plugin="trad_Unknown")
    result = await rank_signals([sig], {}, "1m")
    assert result[0]["adjusted_rank"] == WARMUP_PENALTY_MULTIPLIER
    assert result[0]["sample_size"] == 0


@pytest.mark.asyncio
async def test_missing_perf_weight_defaults_to_warmup():
    """No perf_weight entry → warm-up penalty (not neutral 1.0) per D-16."""
    plugin = "trad_TrendFollowing"
    sig = make_signal(plugin=plugin)
    result = await rank_signals([sig], {}, "1m")
    assert result[0]["perf_multiplier"] == WARMUP_PENALTY_MULTIPLIER
    assert result[0]["adjusted_rank"] == WARMUP_PENALTY_MULTIPLIER
    assert result[0]["sample_size"] == 0


@pytest.mark.asyncio
async def test_sample_size_below_100_gets_warmup_penalty():
    """sample_size < 100 → perf_multiplier = 0.5 (D-16 warm-up penalty)."""
    plugin = "trad_TrendFollowing"
    sig = make_signal(plugin=plugin)
    # Provide a "good" perf_multiplier but with sample_size=50 (below threshold)
    result = await rank_signals([sig], {(plugin, "1m", "*"): (1.2, 50)}, "1m")
    assert result[0]["adjusted_rank"] == WARMUP_PENALTY_MULTIPLIER
    assert result[0]["perf_multiplier"] == WARMUP_PENALTY_MULTIPLIER
    assert result[0]["sample_size"] == 50


@pytest.mark.asyncio
async def test_does_not_mutate_input():
    """Input signal dicts are not mutated."""
    sig = make_signal(plugin="trad_TrendFollowing")
    original_conf = sig["confidence"]
    await rank_signals([sig], {}, "1m")
    assert sig["confidence"] == original_conf
    assert "adjusted_rank" not in sig


# -- Symbol-keyed lookup tests --


@pytest.mark.asyncio
async def test_symbol_specific_weight_used():
    """When symbol='ES', the (plugin, tf, 'ES') weight is used."""
    plugin = "trad_TrendFollowing"
    weight = 0.6
    sig = make_signal(plugin=plugin)
    result = await rank_signals([sig], {(plugin, "1m", "ES"): (weight, 100)}, "1m", symbol="ES")
    assert result[0]["perf_multiplier"] == weight
    assert result[0]["adjusted_rank"] == round(weight, 4)


@pytest.mark.asyncio
async def test_symbol_falls_back_to_global_star():
    """When no symbol-specific weight, falls back to (plugin, tf, '*')."""
    plugin = "trad_TrendFollowing"
    weight = 0.8
    sig = make_signal(plugin=plugin)
    result = await rank_signals([sig], {(plugin, "1m", "*"): (weight, 100)}, "1m", symbol="ES")
    assert result[0]["perf_multiplier"] == weight
    assert result[0]["adjusted_rank"] == round(weight, 4)


@pytest.mark.asyncio
async def test_symbol_no_weight_defaults_to_warmup():
    """When neither symbol-specific nor global weight exists, applies warm-up penalty."""
    plugin = "trad_TrendFollowing"
    sig = make_signal(plugin=plugin)
    result = await rank_signals([sig], {}, "1m", symbol="ES")
    assert result[0]["perf_multiplier"] == WARMUP_PENALTY_MULTIPLIER
    assert result[0]["adjusted_rank"] == WARMUP_PENALTY_MULTIPLIER


@pytest.mark.asyncio
async def test_backward_compat_plain_float_weight():
    """Plain float weight (no sample_size) treated as validated (sample_size=30)."""
    plugin = "trad_TrendFollowing"
    weight = 1.2
    sig = make_signal(plugin=plugin)
    result = await rank_signals([sig], {(plugin, "1m", "*"): weight}, "1m")
    assert result[0]["perf_multiplier"] == weight
    assert result[0]["adjusted_rank"] == round(weight, 4)
