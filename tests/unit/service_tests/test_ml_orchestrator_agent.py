"""Unit tests for MLOrchestratorComputeAgent. Uses __new__ pattern."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_agent():
    from services.ml_orchestrator_agent import MLOrchestratorComputeAgent
    agent = MLOrchestratorComputeAgent.__new__(MLOrchestratorComputeAgent)
    agent._pool = MagicMock()
    agent._producer = MagicMock()
    agent._producer.publish = AsyncMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "test"
    agent._settings.DATA_QUALITY_MIN_SCORE = 0.85
    agent.logger = MagicMock()
    return agent


@pytest.mark.asyncio
async def test_orchestrator_skips_discovery_on_low_quality_score():
    """When data_quality_score < threshold, DiscoveryNode must not run."""
    from services.ml_orchestrator_agent import MLOrchestrationState

    agent = _make_agent()
    discovery_ran = []

    async def mock_data_quality_node(state):
        return {**state, "data_quality_score": 0.60}  # below 0.85

    async def mock_discovery_node(state):
        discovery_ran.append(True)
        return state

    agent._data_quality_node = mock_data_quality_node
    agent._discovery_node = mock_discovery_node

    initial_state: MLOrchestrationState = {
        "data_quality_score": None,
        "last_discovery_run_id": None,
        "model_status": "none",
        "last_error": None,
    }

    final_state = await agent._run_graph(initial_state)
    assert final_state["data_quality_score"] == 0.60
    assert len(discovery_ran) == 0  # discovery was skipped


@pytest.mark.asyncio
async def test_orchestrator_runs_discovery_when_quality_high():
    """When data_quality_score >= threshold, DiscoveryNode must run."""
    agent = _make_agent()
    discovery_ran = []

    async def mock_data_quality_node(state):
        return {**state, "data_quality_score": 0.92}

    async def mock_discovery_node(state):
        discovery_ran.append(True)
        return {**state, "last_discovery_run_id": "run-123"}

    agent._data_quality_node = mock_data_quality_node
    agent._discovery_node = mock_discovery_node

    initial_state = {
        "data_quality_score": None,
        "last_discovery_run_id": None,
        "model_status": "none",
        "last_error": None,
    }

    final_state = await agent._run_graph(initial_state)
    assert final_state["data_quality_score"] == 0.92
    assert len(discovery_ran) == 1
    assert final_state["last_discovery_run_id"] == "run-123"


@pytest.mark.asyncio
async def test_training_node_is_noop():
    """TrainingNode must log 'awaiting Phase 67' and return state unchanged."""
    from services.ml_orchestrator_agent import MLOrchestratorComputeAgent

    agent = MLOrchestratorComputeAgent.__new__(MLOrchestratorComputeAgent)
    agent.logger = MagicMock()

    state = {"data_quality_score": 0.9, "last_discovery_run_id": "r1", "model_status": "none", "last_error": None}
    result = await agent._training_node(state)

    assert result == state  # state unchanged
    agent.logger.info.assert_called()
    logged_msg = str(agent.logger.info.call_args)
    assert "Phase 67" in logged_msg or "awaiting" in logged_msg.lower()


@pytest.mark.asyncio
async def test_monitor_node_is_noop():
    """MonitorNode must log 'awaiting Phase 67' and return state unchanged."""
    from services.ml_orchestrator_agent import MLOrchestratorComputeAgent

    agent = MLOrchestratorComputeAgent.__new__(MLOrchestratorComputeAgent)
    agent.logger = MagicMock()

    state = {"data_quality_score": 0.9, "last_discovery_run_id": "r1", "model_status": "none", "last_error": None}
    result = await agent._monitor_node(state)

    assert result == state
    agent.logger.info.assert_called()
    logged_msg = str(agent.logger.info.call_args)
    assert "Phase 67" in logged_msg or "awaiting" in logged_msg.lower()
