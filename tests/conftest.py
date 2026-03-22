"""
pytest configuration and fixtures for IndicAgent tests.
"""

import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so services/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock

# Set test environment
os.environ["INDICAGENT_ENV"] = "test"
os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/indicagent_test"


@pytest_asyncio.fixture
async def mock_database_connection():
    """Mock database connection for testing."""
    conn_mock = AsyncMock()
    conn_mock.fetchval = AsyncMock(return_value=1)
    conn_mock.fetch = AsyncMock(return_value=[])
    conn_mock.execute = AsyncMock(return_value="INSERT 0 1")
    conn_mock.close = AsyncMock()
    return conn_mock


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    return {
        "symbols": ["ESU5", "NQU5", "RTYU5"],
        "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
        "redis_url": "redis://localhost:6379/1",
        "database_url": "postgresql://postgres:postgres@localhost:5432/indicagent_test",
    }


@pytest.fixture
def sample_market_data():
    """Sample market data for testing."""
    return {
        "symbol": "ESU5",
        "timeframe": "1m",
        "timestamp": "2025-08-13T07:30:00Z",
        "open": 6475.0,
        "high": 6476.5,
        "low": 6474.0,
        "close": 6475.5,
        "volume": 150,
    }


@pytest.fixture
def sample_indicator_data():
    """Sample indicator data for testing."""
    return {
        "symbol": "ESU5",
        "timeframe": "1m",
        "timestamp": "2025-08-13T07:30:00Z",
        "RSI": 65.5,
        "SMA_20": 6470.2,
        "EMA_12": 6472.8,
        "MACD": 2.3,
        "MACD_SIGNAL": 1.8,
        "ATR": 8.5,
    }
