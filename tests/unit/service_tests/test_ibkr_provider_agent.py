"""Unit tests for IBKRProviderAgent — TDD tests for Plan 54-03.

Tests structural contract (BaseProviderAgent inheritance) and concrete
method implementations (agent name, metrics port, provider name, adapter type).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Test 12: IBKRProviderAgent inherits from BaseProviderAgent
# ---------------------------------------------------------------------------


def test_inherits_base_provider_agent():
    """IBKRProviderAgent must be a subclass of BaseProviderAgent."""
    from services.ibkr_provider_agent import IBKRProviderAgent
    from src.providers.base_provider_agent import BaseProviderAgent

    assert issubclass(IBKRProviderAgent, BaseProviderAgent)


# ---------------------------------------------------------------------------
# Test 13: _create_adapter returns IBKRAdapter
# ---------------------------------------------------------------------------


def test_create_adapter_returns_ibkr_adapter():
    """_create_adapter() must return an IBKRAdapter instance."""
    import asyncio
    from unittest.mock import MagicMock

    from services.ibkr_provider_agent import IBKRProviderAgent
    from src.providers.ibkr_adapter import IBKRAdapter

    agent = IBKRProviderAgent.__new__(IBKRProviderAgent)
    agent._settings = MagicMock()
    agent._settings.ib_host = "192.168.1.157"
    agent._settings.ib_port = 7497
    agent._settings.ib_client_id = 35

    adapter = agent._create_adapter()
    assert isinstance(adapter, IBKRAdapter)


# ---------------------------------------------------------------------------
# Test 14: _agent_name returns correct string
# ---------------------------------------------------------------------------


def test_agent_name():
    """_agent_name() must return 'ibkr_provider_agent'."""
    from services.ibkr_provider_agent import IBKRProviderAgent

    agent = IBKRProviderAgent.__new__(IBKRProviderAgent)
    assert agent._agent_name() == "ibkr_provider_agent"


# ---------------------------------------------------------------------------
# Test 15: _agent_metrics_port returns 9129
# ---------------------------------------------------------------------------


def test_metrics_port():
    """_agent_metrics_port() must return 9129."""
    from services.ibkr_provider_agent import IBKRProviderAgent

    agent = IBKRProviderAgent.__new__(IBKRProviderAgent)
    assert agent._agent_metrics_port() == 9129


# ---------------------------------------------------------------------------
# Test 16: _provider_name_str returns "ibkr"
# ---------------------------------------------------------------------------


def test_provider_name():
    """_provider_name_str() must return 'ibkr'."""
    from services.ibkr_provider_agent import IBKRProviderAgent

    agent = IBKRProviderAgent.__new__(IBKRProviderAgent)
    assert agent._provider_name_str() == "ibkr"
