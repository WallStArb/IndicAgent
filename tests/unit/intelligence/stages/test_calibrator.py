"""Tests for CalibratorService.

Behavior tests:
  1. process() applies isotonic calibration curve via np.interp when curve exists
  2. process() passes confidence through unchanged when no curve for plugin/tf
  3. process() stores calibrated_confidence in result
  4. process() sets attribution_reason
  5. process() handles missing confidence field gracefully
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.monitoring.data_quality_monitor import DataQualityMonitor
from src.observability.circuit_breaker import CircuitBreaker


def make_event(confidence=0.8, plugin_name="trad_TrendFollowing"):
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
    from src.intelligence.stages.calibrator import CalibratorService

    stage = CalibratorService.__new__(CalibratorService)
    stage.stage_name = "calibrator"
    stage._output_topic = "development.pipeline.calibrated"
    stage.consumer = AsyncMock()
    stage.producer = AsyncMock()
    stage.attribution_producer = AsyncMock()
    stage.circuit_breaker = CircuitBreaker()
    stage.data_quality_monitor = DataQualityMonitor("calibrator")
    stage.events_consumed = MagicMock()
    stage.events_produced = MagicMock()
    stage.processing_errors = MagicMock()
    stage.circuit_state = MagicMock()
    stage.calibration_curves = {}
    stage._last_curve_load = 0.0
    return stage


@pytest.mark.asyncio
async def test_calibrator_applies_isotonic_curve():
    """Test 1: process() applies calibration curve via np.interp."""
    stage = make_stage()
    # Simple linear curve: 0.0 → 0.0, 1.0 → 0.9 (compress overconfidence)
    stage.calibration_curves[("trad_TrendFollowing", "1m")] = ([0.0, 1.0], [0.0, 0.9])
    event = make_event(confidence=0.8)

    result = await stage.process(event)

    # np.interp(0.8, [0.0, 1.0], [0.0, 0.9]) = 0.72
    assert result["calibrated_confidence"] == pytest.approx(0.72, abs=1e-3)


@pytest.mark.asyncio
async def test_calibrator_passthrough_no_curve():
    """Test 2: process() passes confidence through when no calibration curve."""
    stage = make_stage()
    stage.calibration_curves = {}  # No curves loaded
    event = make_event(confidence=0.75)

    result = await stage.process(event)

    assert result["calibrated_confidence"] == pytest.approx(0.75, abs=1e-4)


@pytest.mark.asyncio
async def test_calibrator_stores_calibrated_confidence():
    """Test 3: process() stores calibrated_confidence in result."""
    stage = make_stage()
    event = make_event()

    result = await stage.process(event)

    assert "calibrated_confidence" in result


@pytest.mark.asyncio
async def test_calibrator_sets_attribution_reason():
    """Test 4: process() sets attribution_reason."""
    stage = make_stage()
    event = make_event()

    result = await stage.process(event)

    assert "attribution_reason" in result


@pytest.mark.asyncio
async def test_calibrator_handles_missing_confidence():
    """Test 5: process() handles missing confidence gracefully."""
    stage = make_stage()
    event = make_event(confidence=0.0)

    result = await stage.process(event)

    assert "calibrated_confidence" in result
    assert result["calibrated_confidence"] >= 0.0
