"""Tests for WinnerSelectorService.

Behavior tests:
  1. _select_winner_for_bar() returns None when no signals provided
  2. _select_winner_for_bar() selects by majority direction when no CIS
  3. _select_winner_for_bar() returns no_signal result when all signals suppressed
  4. _select_winner_for_bar() sorts active signals by adjusted_rank
  5. process() buffers signal and returns buffered status
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.monitoring.data_quality_monitor import DataQualityMonitor
from src.observability.circuit_breaker import CircuitBreaker


def make_event(confidence=0.8, direction=1, plugin_name="trad_TrendFollowing", adjusted_rank=3.0):
    class _Event:
        symbol = "ES"
        tf = "1m"
        timeframe = "1m"
        features = {"confidence": confidence}

        def model_dump(self):
            return {
                "confidence": confidence,
                "direction": direction,
                "setup_plugin": plugin_name,
                "adjusted_rank": adjusted_rank,
                "regime_eligible": True,
                "features": {"confidence": confidence},
            }

    return _Event()


def make_stage():
    from collections import defaultdict

    from src.intelligence.stages.winner_selector import WinnerSelectorService

    stage = WinnerSelectorService.__new__(WinnerSelectorService)
    stage.stage_name = "winner_selector"
    stage._output_topic = "development.pipeline.winner"
    stage.consumer = AsyncMock()
    stage.producer = AsyncMock()
    stage.attribution_producer = AsyncMock()
    stage.circuit_breaker = CircuitBreaker()
    stage.data_quality_monitor = DataQualityMonitor("winner_selector")
    stage.events_consumed = MagicMock()
    stage.events_produced = MagicMock()
    stage.processing_errors = MagicMock()
    stage.circuit_state = MagicMock()
    stage._bar_buffer = defaultdict(list)
    return stage


@pytest.mark.asyncio
async def test_winner_selector_no_signals_returns_none():
    """Test 1: _select_winner_for_bar() returns None for empty signals."""
    stage = make_stage()

    result = await stage._select_winner_for_bar("ES", "1m", [])

    assert result is None


@pytest.mark.asyncio
async def test_winner_selector_majority_direction():
    """Test 2: _select_winner_for_bar() picks majority direction."""
    stage = make_stage()
    signals = [
        {"confidence": 0.8, "direction": 1, "setup_plugin": "trad_TrendFollowing", "adjusted_rank": 3.0, "regime_eligible": True, "features": {}},
        {"confidence": 0.7, "direction": 1, "setup_plugin": "trad_MeanReversion", "adjusted_rank": 1.0, "regime_eligible": True, "features": {}},
        {"confidence": 0.6, "direction": -1, "setup_plugin": "trad_MTFAlignment", "adjusted_rank": 4.0, "regime_eligible": True, "features": {}},
    ]

    result = await stage._select_winner_for_bar("ES", "1m", signals)

    assert result is not None
    assert result["selected_signal"] is not None
    # 2 longs vs 1 short — should pick long
    assert result["selected_signal"]["direction"] == 1


@pytest.mark.asyncio
async def test_winner_selector_all_suppressed():
    """Test 3: _select_winner_for_bar() returns no_signal when all suppressed."""
    stage = make_stage()
    signals = [
        {"confidence": 0.8, "direction": 1, "setup_plugin": "trad_TrendFollowing", "adjusted_rank": 3.0, "regime_eligible": False, "features": {}},
    ]

    result = await stage._select_winner_for_bar("ES", "1m", signals)

    assert result is not None
    assert result["selected_signal"] is None
    assert result["resolution_method"] == "no_signal"


@pytest.mark.asyncio
async def test_winner_selector_sorts_by_adjusted_rank():
    """Test 4: _select_winner_for_bar() selects lowest adjusted_rank in majority group."""
    stage = make_stage()
    signals = [
        {"confidence": 0.7, "direction": 1, "setup_plugin": "trad_MeanReversion", "adjusted_rank": 1.0, "regime_eligible": True, "features": {}},
        {"confidence": 0.8, "direction": 1, "setup_plugin": "trad_TrendFollowing", "adjusted_rank": 3.0, "regime_eligible": True, "features": {}},
    ]

    result = await stage._select_winner_for_bar("ES", "1m", signals)

    # adjusted_rank=1.0 < 3.0 → MeanReversion wins
    assert result["selected_signal"]["setup_plugin"] == "trad_MeanReversion"


@pytest.mark.asyncio
async def test_winner_selector_process_buffers_signal():
    """Test 5: process() buffers signal and returns buffered status."""
    stage = make_stage()
    event = make_event()

    result = await stage.process(event)

    assert result["status"] == "buffered"
    assert result["signal_count"] == 1
