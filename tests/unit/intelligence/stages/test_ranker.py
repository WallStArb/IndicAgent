"""Tests for RankerService.

Behavior tests:
  1. process() computes adjusted_rank = priority * perf_multiplier
  2. process() uses priority from SETUP_PRIORITY dict
  3. process() uses perf_multiplier from perf_weights cache when present
  4. process() defaults perf_multiplier to 1.0 when no weight cached
  5. process() stores adjusted_rank in result
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.monitoring.data_quality_monitor import DataQualityMonitor
from src.observability.circuit_breaker import CircuitBreaker


def make_event(plugin_name="trad_TrendFollowing", confidence=0.8):
    class _Event:
        symbol = "ES"
        tf = "1m"
        timeframe = "1m"
        features = {"confidence": confidence}

        def model_dump(self):
            return {
                "confidence": confidence,
                "setup_plugin": plugin_name,
                "features": {"confidence": confidence},
            }

    return _Event()


def make_stage():
    from src.intelligence.stages.ranker import RankerService

    stage = RankerService.__new__(RankerService)
    stage.stage_name = "ranker"
    stage._output_topic = "development.pipeline.ranked"
    stage.consumer = AsyncMock()
    stage.producer = AsyncMock()
    stage.attribution_producer = AsyncMock()
    stage.circuit_breaker = CircuitBreaker()
    stage.data_quality_monitor = DataQualityMonitor("ranker")
    stage.events_consumed = MagicMock()
    stage.events_produced = MagicMock()
    stage.processing_errors = MagicMock()
    stage.circuit_state = MagicMock()
    stage.perf_weights = {}
    stage._last_weight_load = 0.0
    return stage


@pytest.mark.asyncio
async def test_ranker_computes_adjusted_rank():
    """Test 1: process() computes adjusted_rank = priority * perf_multiplier."""
    stage = make_stage()
    # trad_TrendFollowing has priority=3
    stage.perf_weights[("trad_TrendFollowing", "1m")] = 0.8
    event = make_event(plugin_name="trad_TrendFollowing")

    result = await stage.process(event)

    # 3 * 0.8 = 2.4
    assert result["adjusted_rank"] == pytest.approx(2.4, abs=1e-4)


@pytest.mark.asyncio
async def test_ranker_uses_setup_priority():
    """Test 2: process() uses priority from SETUP_PRIORITY dict."""
    from src.intelligence.stages.ranker import SETUP_PRIORITY

    stage = make_stage()
    event = make_event(plugin_name="trad_MeanReversion")

    result = await stage.process(event)

    expected_priority = SETUP_PRIORITY.get("trad_MeanReversion", 999)
    expected_rank = expected_priority * 1.0  # default perf_multiplier
    assert result["adjusted_rank"] == pytest.approx(expected_rank, abs=1e-4)


@pytest.mark.asyncio
async def test_ranker_uses_cached_perf_multiplier():
    """Test 3: process() uses perf_multiplier from perf_weights when present."""
    stage = make_stage()
    stage.perf_weights[("trad_SqueezeExpansion", "1m")] = 0.5
    event = make_event(plugin_name="trad_SqueezeExpansion")

    result = await stage.process(event)

    assert result["perf_multiplier"] == pytest.approx(0.5, abs=1e-4)


@pytest.mark.asyncio
async def test_ranker_defaults_perf_multiplier_to_one():
    """Test 4: process() defaults perf_multiplier to 1.0 when no weight cached."""
    stage = make_stage()
    stage.perf_weights = {}
    event = make_event(plugin_name="trad_TrendFollowing")

    result = await stage.process(event)

    assert result["perf_multiplier"] == pytest.approx(1.0, abs=1e-4)


@pytest.mark.asyncio
async def test_ranker_stores_adjusted_rank():
    """Test 5: process() stores adjusted_rank in result."""
    stage = make_stage()
    event = make_event()

    result = await stage.process(event)

    assert "adjusted_rank" in result
    assert result["adjusted_rank"] >= 0.0
