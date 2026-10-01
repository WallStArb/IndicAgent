"""
pytest configuration and fixtures for IndicAgent tests.
"""

import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so services/ is importable
_project_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _project_root)
# Also add services/ so that `import _path_bootstrap` works when test files
# import from services.* as a package (service scripts use services/ as sys.path[0])
_services_dir = str(Path(__file__).resolve().parent.parent / "services")
if _services_dir not in sys.path:
    sys.path.insert(0, _services_dir)

from unittest.mock import AsyncMock  # noqa: E402

import pytest  # noqa: E402

# Disable OTel startup validation in tests (no collector running)
os.environ.setdefault("OTEL_VALIDATION_DISABLED", "1")
import pytest_asyncio  # noqa: E402

# Set test environment
os.environ["INDICAGENT_ENV"] = "test"
os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/indicagent_test"


@pytest.fixture(scope="session", autouse=True)
def _contain_tempfile(tmp_path_factory):
    """Route every bare `tempfile` call into pytest's own temp root.

    Helpers that call `tempfile.mkdtemp()` without cleanup left about 10,000 directories in /tmp;
    pytest keeps only its last three runs' roots. TMPDIR covers worker subprocesses.
    """
    import tempfile

    root = str(tmp_path_factory.mktemp("tempfile"))
    old_tempdir, old_env = tempfile.tempdir, os.environ.get("TMPDIR")
    tempfile.tempdir = root
    os.environ["TMPDIR"] = root
    yield
    tempfile.tempdir = old_tempdir
    if old_env is None:
        os.environ.pop("TMPDIR", None)
    else:
        os.environ["TMPDIR"] = old_env


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
