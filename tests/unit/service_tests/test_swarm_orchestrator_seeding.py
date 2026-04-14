"""Tests for swarm_orchestrator_agent context cache seeding."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.swarm_orchestrator_agent import SwarmOrchestratorComputeAgent
from src.intelligence.swarm.context import SwarmContextCache


@pytest.mark.asyncio
async def test_seed_from_db_row_populates_cache():
    """seed_from_db_row populates cache with DB row data."""
    cache = SwarmContextCache()

    row = {
        "symbol": "ES",
        "tf": "5m",
        "ts": datetime(2026, 4, 12, tzinfo=UTC),
        "i1": {"atr_14": 5.0, "adx": 25.0, "rsi_14": 55.0},
        "i4": {"hmm_regime": 1, "trend_regime": "trending"},
        "i6": {"ctf_score": 0.7},
        "bar": {"close": 5400.0, "volume": 1500},
    }

    cache.seed_from_db_row(row)

    assert ("ES", "5m") in cache._cache
    event, _ = cache._cache[("ES", "5m")]
    assert event.symbol == "ES"
    assert event.tf == "5m"


@pytest.mark.asyncio
async def test_seed_from_db_row_handles_none_jsonb_columns():
    """seed_from_db_row handles None JSONB columns gracefully."""
    cache = SwarmContextCache()

    row = {
        "symbol": "NQ",
        "tf": "15m",
        "ts": datetime.now(UTC),
        "i1": None,
        "i4": None,
        "i6": None,
        "bar": None,
    }

    # Should not raise exception
    cache.seed_from_db_row(row)

    assert ("NQ", "15m") in cache._cache


@pytest.mark.asyncio
async def test_setup_seeds_context_cache_from_db():
    """SwarmOrchestratorComputeAgent seeds context cache on startup."""
    from src.config.settings import Settings
    settings = Settings()
    agent = SwarmOrchestratorComputeAgent.__new__(SwarmOrchestratorComputeAgent)
    agent._settings = settings
    agent._settings = MagicMock()
    agent._settings.database_url = "postgresql://test"
    agent._context_cache = SwarmContextCache()
    agent.logger = MagicMock()

    # Mock DB rows
    mock_rows = [
        {
            "symbol": "ES",
            "tf": "5m",
            "ts": datetime.now(UTC),
            "i1": {"atr": 5.0},
            "i4": {"regime": 1},
            "i6": {"score": 0.7},
            "bar": {"close": 5400.0},
        },
        {
            "symbol": "NQ",
            "tf": "5m",
            "ts": datetime.now(UTC),
            "i1": {"atr": 3.0},
            "i4": {"regime": 0},
            "i6": {"score": 0.5},
            "bar": {"close": 18000.0},
        },
    ]

    # Mock asyncpg pool
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.__aexit__ = AsyncMock()
    mock_pool.close = AsyncMock()

    await agent._seed_context_cache(mock_pool)

    assert len(agent._context_cache._cache) == 2
    assert ("ES", "5m") in agent._context_cache._cache
    assert ("NQ", "5m") in agent._context_cache._cache


@pytest.mark.asyncio
async def test_seed_context_cache_handles_empty_db():
    """_seed_context_cache handles empty DB gracefully."""
    from src.config.settings import Settings
    settings = Settings()
    agent = SwarmOrchestratorComputeAgent.__new__(SwarmOrchestratorComputeAgent)
    agent._settings = settings
    agent._settings = MagicMock()
    agent._settings.database_url = "postgresql://test"
    agent._context_cache = SwarmContextCache()
    agent.logger = MagicMock()

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.__aexit__ = AsyncMock()
    mock_pool.close = AsyncMock()

    await agent._seed_context_cache(mock_pool)

    assert len(agent._context_cache._cache) == 0


@pytest.mark.asyncio
async def test_seed_context_cache_handles_db_error_gracefully():
    """_seed_context_cache handles DB errors without crashing."""
    from src.config.settings import Settings
    settings = Settings()
    agent = SwarmOrchestratorComputeAgent.__new__(SwarmOrchestratorComputeAgent)
    agent._settings = settings
    agent._settings = MagicMock()
    agent._settings.database_url = "postgresql://test"
    agent._context_cache = SwarmContextCache()
    agent.logger = MagicMock()

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
    mock_pool.close = AsyncMock()

    # Should not raise exception
    await agent._seed_context_cache(mock_pool)

    # Cache should still be functional
    assert agent._context_cache is not None
