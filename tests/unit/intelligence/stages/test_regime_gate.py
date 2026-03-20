"""Tests for RegimeGateService.

Behavior tests:
  1. process() passes through signal when no regime_data present
  2. process() suppresses when hmm_regime_prob < 0.55
  3. process() suppresses when hmm_regime_duration < 3
  4. process() suppresses when hmm_regime not in allowed list for plugin regime_type
  5. process() sets regime_eligible=True when all gate checks pass
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.monitoring.data_quality_monitor import DataQualityMonitor
from src.observability.circuit_breaker import CircuitBreaker


def make_event(regime_data=None, regime_type="any", confidence=0.8):
    class _Event:
        symbol = "ES"
        tf = "1m"
        timeframe = "1m"
        features = {"confidence": confidence, "regime_data": regime_data}

        def model_dump(self):
            return {
                "confidence": confidence,
                "regime_type": regime_type,
                "features": {"confidence": confidence, "regime_data": regime_data},
            }

    return _Event()


def make_stage():
    from src.intelligence.stages.regime_gate import RegimeGateService

    stage = RegimeGateService.__new__(RegimeGateService)
    stage.stage_name = "regime_gate"
    stage._output_topic = "development.pipeline.regime_gated"
    stage.consumer = AsyncMock()
    stage.producer = AsyncMock()
    stage.attribution_producer = AsyncMock()
    stage.circuit_breaker = CircuitBreaker()
    stage.data_quality_monitor = DataQualityMonitor("regime_gate")
    stage.events_consumed = MagicMock()
    stage.events_produced = MagicMock()
    stage.processing_errors = MagicMock()
    stage.circuit_state = MagicMock()
    return stage


@pytest.mark.asyncio
async def test_regime_gate_passthrough_no_regime_data():
    """Test 1: process() passes through when no regime_data present."""
    stage = make_stage()
    event = make_event(regime_data=None)

    result = await stage.process(event)

    assert result["regime_eligible"] is True


@pytest.mark.asyncio
async def test_regime_gate_suppresses_low_prob():
    """Test 2: process() suppresses when hmm_regime_prob < 0.55."""
    stage = make_stage()
    event = make_event(regime_data={"hmm_regime": 1, "hmm_regime_prob": 0.4, "hmm_regime_duration": 5})

    result = await stage.process(event)

    assert result["regime_eligible"] is False
    assert result["suppression_reason"] == "regime_prob"


@pytest.mark.asyncio
async def test_regime_gate_suppresses_short_duration():
    """Test 3: process() suppresses when hmm_regime_duration < 3."""
    stage = make_stage()
    event = make_event(regime_data={"hmm_regime": 1, "hmm_regime_prob": 0.8, "hmm_regime_duration": 1})

    result = await stage.process(event)

    assert result["regime_eligible"] is False
    assert result["suppression_reason"] == "regime_duration"


@pytest.mark.asyncio
async def test_regime_gate_suppresses_wrong_type():
    """Test 4: process() suppresses when regime type not in allowed list."""
    stage = make_stage()
    # trend plugin in ranging (hmm_regime=0) regime
    event = make_event(
        regime_data={"hmm_regime": 0, "hmm_regime_prob": 0.8, "hmm_regime_duration": 5},
        regime_type="trend",
    )

    result = await stage.process(event)

    assert result["regime_eligible"] is False
    assert result["suppression_reason"] == "regime_type"


@pytest.mark.asyncio
async def test_regime_gate_eligible_when_all_checks_pass():
    """Test 5: process() sets regime_eligible=True when all checks pass."""
    stage = make_stage()
    # trend plugin in trending (hmm_regime=1) regime
    event = make_event(
        regime_data={"hmm_regime": 1, "hmm_regime_prob": 0.75, "hmm_regime_duration": 5},
        regime_type="trend",
    )

    result = await stage.process(event)

    assert result["regime_eligible"] is True
    assert result["suppression_reason"] is None
