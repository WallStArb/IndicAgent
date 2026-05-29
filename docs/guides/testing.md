# Testing Strategy Guide

**Version:** 2.8
**Last Updated:** 2026-05-28

---

## Overview

IndicAgent uses pytest for testing with three test categories: unit, integration, and e2e. Tests are organized by component and use markers for selective execution.

**Testing philosophy:**
- Unit tests are fast and isolated (no external dependencies)
- Integration tests verify component interaction
- E2E tests validate full workflows (requires full stack)

---

## Test Structure

```
tests/
├── conftest.py                 # Shared fixtures and configuration
├── fixtures/                   # Test data fixtures
│   ├── bar_events.py
│   ├── signals.py
│   └── ...
├── unit/                       # Isolated component tests
│   ├── api/
│   ├── core/
│   ├── intelligence/
│   ├── providers/
│   └── ...
├── integration/                # Component interaction tests
│   └── (organized by feature)
└── e2e/                        # Full workflow tests (when added)
```

---

## Running Tests

### All Tests

```bash
# Run all tests (unit + integration)
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=html
```

### Unit Tests Only

```bash
# Fast unit tests (no external dependencies)
pytest tests/unit -v

# Specific unit test file
pytest tests/unit/intelligence/test_plugins.py -v

# Specific test
pytest tests/unit/intelligence/test_plugins.py::test_rsi_compute -v
```

### Integration Tests

```bash
# All integration tests
pytest tests/integration -v -m integration

# Specific integration test
pytest tests/integration/test_pipeline.py -v
```

### By Marker

```bash
# Skip slow tests
pytest tests/ -v -m "not slow"

# Skip tests requiring IBKR
pytest tests/ -v -m "not requires_ibkr"

# Only DB tests
pytest tests/ -v -m requires_db
```

---

## Test Markers

| Marker | Purpose | Usage |
|--------|---------|-------|
| `unit` | Fast, isolated tests | `pytest tests/unit -m unit` |
| `integration` | Component interaction | `pytest tests/integration -m integration` |
| `slow` | Long-running tests | `pytest -m "not slow"` |
| `requires_ibkr` | Needs IBKR TWS | `pytest -m "not requires_ibkr"` |
| `requires_redis` | Needs Redis | `pytest -m "not requires_redis"` |
| `requires_db` | Needs database | `pytest tests/integration -m requires_db` |
| `performance` | Benchmarks | `pytest tests/performance -m performance` |

---

## Writing Tests

### Unit Test Pattern

```python
import pytest
from unittest.mock import AsyncMock, patch
from src.intelligence.plugins.rsi import RSIPlugin

class TestRSIPlugin:
    """Unit tests for RSI plugin."""

    @pytest.fixture
    def plugin(self):
        """Fresh plugin instance per test."""
        return RSIPlugin(period=14)

    @pytest.mark.unit
    def test_compute_next(self, plugin):
        """Test RSI calculation."""
        # Setup
        plugin.update(100.0)
        for i in range(20):
            plugin.update(100.0 + i)

        # Execute
        result = plugin.compute_next(bar_event)

        # Assert
        assert 0 <= result <= 100
        assert isinstance(result, float)

    @pytest.mark.unit
    def test_invalid_input(self, plugin):
        """Test handling of invalid input."""
        with pytest.raises(ValueError):
            plugin.compute_next(None)
```

### Integration Test Pattern

```python
import pytest
from src.core.database_manager import get_connection

@pytest.mark.integration
@pytest.mark.requires_db
async def test_signal_persistence():
    """Test signal is persisted to database."""
    async with get_connection(settings) as conn:
        # Setup
        signal = create_test_signal()

        # Execute
        await signal_writer.write(signal)

        # Verify
        result = await conn.fetchval(
            "SELECT COUNT(*) FROM signal_ledger WHERE id = $1",
            signal.id
        )
        assert result == 1
```

### Async Test Pattern

```python
import pytest_asyncio

@pytest.mark.asyncio
async def test_async_operation():
    """Test async function."""
    result = await async_function()
    assert result is not None
```

---

## Fixtures

### Built-in Fixtures (conftest.py)

| Fixture | Purpose |
|---------|---------|
| `mock_database_connection` | Mock DB connection (AsyncMock) |
| `mock_config` | Mock configuration dict |
| `sample_market_data` | Sample bar event |
| `sample_indicator_data` | Sample indicator values |

### Custom Fixtures

Create fixtures in `tests/fixtures/`:

```python
# tests/fixtures/signals.py
import pytest

@pytest.fixture
def sample_signal():
    """Sample I7 signal."""
    return {
        "symbol": "ES",
        "timeframe": "5m",
        "fired_at": datetime.now(UTC),
        "entry_type": "at_close",
        "confidence": 0.8,
    }
```

---

## Test Configuration

### pytest.ini

```ini
[tool:pytest]
minversion = 6.0
addopts =
    -ra                    # Show summary of all failures
    -q                     # Quiet output
    --strict-markers       # Error on unknown markers
    --asyncio-mode=auto    # Async test support
testpaths = tests
python_files = test_*.py
markers =
    unit: Unit tests
    integration: Integration tests
    slow: Slow-running tests
    requires_ibkr: Tests requiring IBKR TWS connection
    requires_db: Tests requiring database connection
```

---

## CI Integration

### GitHub Actions (When Added)

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      - name: Run unit tests
        run: pytest tests/unit -v
      - name: Run integration tests
        run: pytest tests/integration -v -m integration
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

---

## Pre-Commit Hook

Install pre-commit hooks:

```bash
pip install pre-commit
pre-commit install
```

`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: local
    hooks:
      - id: pytest-unit
        name: Run unit tests
        entry: pytest tests/unit -v
        language: python
        pass_filenames: false
```

---

## Performance Testing

### Benchmark Pattern

```python
import pytest
import time

@pytest.mark.performance
def test_plugin_latency():
    """Benchmark plugin execution time."""
    plugin = RSIPlugin(period=14)
    bar = create_test_bar()

    start = time.perf_counter()
    for _ in range(1000):
        plugin.compute_next(bar)
    elapsed = time.perf_counter() - start

    # Assert average latency < 1ms
    assert elapsed / 1000 < 0.001
```

---

## Test Data Management

### Factories

Use factory pattern for test data:

```python
# tests/fixtures/factories.py
class SignalFactory:
    """Factory for creating test signals."""

    @staticmethod
    def create(**kwargs):
        """Create signal with defaults and overrides."""
        defaults = {
            "symbol": "ES",
            "timeframe": "5m",
            "confidence": 0.8,
        }
        defaults.update(kwargs)
        return Signal(**defaults)
```

### Test Database

Use separate database for tests:

```bash
# Create test database
createdb indicagent_test

# Run tests with test DB
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent_test \
  pytest tests/integration -m requires_db
```

---

## Common Patterns

### Mocking External Dependencies

```python
from unittest.mock import patch

@pytest.mark.unit
def test_ibkr_provider():
    """Test IBKR provider without actual connection."""
    with patch('src.providers.ibkr.IBKR') as mock_ibkr:
        mock_ibkr.return_value.reqMktData.return_value = mock_data
        
        provider = IBKRProviderAgent()
        bars = provider.fetch_bars("ES")
        
        assert len(bars) > 0
```

### Async Mocking

```python
@pytest.mark.asyncio
async def test_async_writer():
    """Test async writer with mocked DB."""
    conn = AsyncMock()
    conn.execute.return_value = "INSERT 0 1"
    
    result = await writer.write(signal, conn)
    
    assert result is True
    conn.execute.assert_called_once()
```

---

## Troubleshooting

### Tests Failing Locally

```bash
# Check test environment
echo $INDICAGENT_ENV
echo $DATABASE_URL

# Verify test DB exists
psql -U postgres -l | grep indicagent_test

# Check for pytest cache issues
pytest --cache-clear

# Run with verbose output
pytest tests/unit/test_file.py -vv -s
```

### Import Errors

Ensure project root is on sys.path (conftest.py handles this):

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```

---

## Test Coverage Goals

| Component | Target Coverage | Status |
|-----------|-----------------|--------|
| Core utilities | 90%+ | High priority |
| Intelligence plugins | 80%+ | Medium priority |
| Services | 70%+ | Medium priority |
| API routes | 60%+ | Low priority |
| Scripts | 50%+ | Low priority |

Check coverage:
```bash
pytest tests/ --cov=src --cov-report=html --cov-report=term
```

---

## See Also

- **pytest docs:** https://docs.pytest.org/
- **pytest-asyncio:** https://pytest-asyncio.readthedocs.io/
- **conftest.py:** `tests/conftest.py`
- **Existing tests:** `tests/unit/`, `tests/integration/`
