"""Tests for TODAdjusterService.

Behavior tests:
  1. process() applies tod_multiplier from tod_multipliers cache when present
  2. process() falls back to session priors when no DB multiplier cached
  3. process() clamps multiplier to [0.7, 1.3]
  4. process() stores tod_multiplier in result for downstream stages
  5. process() sets attribution_reason with regime/tf/hour
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.monitoring.data_quality_monitor import DataQualityMonitor
from src.observability.circuit_breaker import CircuitBreaker


def make_event(timestamp="2026-01-02T14:30:00+00:00", confidence=0.8, regime_type="trend"):
    """14:30 UTC = 9:30 ET (NY market open)."""
    class _Event:
        symbol = "ES"
        tf = "1m"
        timeframe = "1m"
        features = {"confidence": confidence}
        ts = datetime.fromisoformat(timestamp)

        def model_dump(self):
            return {
                "confidence": confidence,
                "regime_type_at_fire": regime_type,
                "features": {"confidence": confidence},
            }

    return _Event()


def make_stage():
    from src.intelligence.stages.tod_adjuster import TODAdjusterService

    stage = TODAdjusterService.__new__(TODAdjusterService)
    stage.stage_name = "tod_adjuster"
    stage._output_topic = "development.pipeline.tod_adjusted"
    stage.consumer = AsyncMock()
    stage.producer = AsyncMock()
    stage.attribution_producer = AsyncMock()
    stage.circuit_breaker = CircuitBreaker()
    stage.data_quality_monitor = DataQualityMonitor("tod_adjuster")
    stage.events_consumed = MagicMock()
    stage.events_produced = MagicMock()
    stage.processing_errors = MagicMock()
    stage.circuit_state = MagicMock()
    stage.tod_multipliers = {}
    stage._last_multiplier_load = 0.0
    return stage


@pytest.mark.asyncio
async def test_tod_adjuster_uses_cached_multiplier():
    """Test 1: process() applies multiplier from tod_multipliers cache."""
    stage = make_stage()
    # 9:30 ET = hour 9
    stage.tod_multipliers[("trend", "1m", 9)] = 1.15
    event = make_event(regime_type="trend")

    result = await stage.process(event)

    # 0.8 * 1.15 = 0.92
    assert result["confidence"] == pytest.approx(0.92, abs=1e-4)
    assert result["tod_multiplier"] == pytest.approx(1.15, abs=1e-4)


@pytest.mark.asyncio
async def test_tod_adjuster_falls_back_to_session_priors():
    """Test 2: process() falls back to session priors when no DB multiplier."""
    stage = make_stage()
    stage.tod_multipliers = {}  # Empty cache
    event = make_event(regime_type="trend")  # 9:30 ET = NY open

    result = await stage.process(event)

    # Should have applied some multiplier (not crash)
    assert "tod_multiplier" in result
    assert result["tod_multiplier"] >= 0.7
    assert result["tod_multiplier"] <= 1.3


@pytest.mark.asyncio
async def test_tod_adjuster_clamps_to_bounds():
    """Test 3: process() clamps multiplier to [0.7, 1.3]."""
    stage = make_stage()
    stage.tod_multipliers[("trend", "1m", 9)] = 2.0  # Way too high

    event = make_event(regime_type="trend")
    result = await stage.process(event)

    # Should be clamped to 1.3
    assert result["tod_multiplier"] <= 1.3


@pytest.mark.asyncio
async def test_tod_adjuster_stores_multiplier_in_result():
    """Test 4: process() stores tod_multiplier in result."""
    stage = make_stage()
    event = make_event()

    result = await stage.process(event)

    assert "tod_multiplier" in result


@pytest.mark.asyncio
async def test_tod_adjuster_sets_attribution_reason():
    """Test 5: process() sets attribution_reason."""
    stage = make_stage()
    event = make_event()

    result = await stage.process(event)

    assert "attribution_reason" in result
    assert result["attribution_reason"]
