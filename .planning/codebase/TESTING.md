# Testing Patterns

**Analysis Date:** 2026-02-22

## Test Framework

**Runner:**
- pytest 6.0+ with asyncio support
- Config: `pytest.ini` with custom markers
- Async support: `pytest-asyncio` with `asyncio_mode = auto`

**Assertion Library:**
- pytest built-in assertions (`assert` statements)
- `pytest.approx()` for floating-point comparisons: `assert result == pytest.approx(5102.0, abs=1.0)`

**Run Commands:**
```bash
pytest tests                           # Run all tests
pytest tests -v                        # Verbose output
pytest tests -k test_name              # Run specific test by name pattern
pytest tests --asyncio-mode=auto       # Run async tests (auto-enabled in config)
pytest --collect-only                  # List all tests without running
pytest tests --tb=short                # Abbreviated traceback on failure
```

**Coverage:**
```bash
pytest --cov=src tests                 # Generate coverage report
pytest --cov=src --cov-report=html     # HTML coverage report
```

## Test File Organization

**Location:**
- Unit tests: `tests/unit/` with subdirectories mirroring `src/` structure
- Service tests: `tests/unit/service_tests/` for services at project root
- Integration tests: `tests/integration/` (separate from unit tests)
- Daemon tests: `tests/unit/daemons/`
- Plugin/Intelligence tests: `tests/unit/intelligence/`
- Provider tests: `tests/unit/providers/`

**Naming:**
- `test_*.py` prefix mandatory (configured in `pytest.ini`)
- Test classes: `Test*` prefix (e.g., `TestAssetClass`, `TestInstrument`, `TestMomentumBreakout`)
- Test functions: `test_*` prefix (e.g., `test_futures_instrument`, `test_long_breakout_all_gates_pass`)
- Helper functions: `_make_*` or `_base_*` (e.g., `_make_service()`, `_base_features()`)

**Directory Structure:**
```
tests/
├── conftest.py                          # Shared fixtures and configuration
├── unit/
│   ├── config/
│   │   └── test_settings.py
│   ├── core/
│   │   ├── test_models.py
│   │   ├── test_stream_keys_signals.py
│   │   └── test_stream_keys_aggregated.py
│   ├── service_tests/
│   │   ├── test_indicator_service.py
│   │   ├── test_market_analysis_service.py
│   │   ├── test_signal_tracker_service.py
│   │   └── test_ai_narrative_service.py
│   ├── daemons/
│   │   ├── test_daemon_tick_accumulator.py
│   │   └── test_daemon_provisional_bar.py
│   ├── intelligence/
│   │   ├── test_momentum_breakout.py
│   │   ├── helpers.py
│   │   └── test_*.py (one per setup plugin)
│   └── providers/
│       └── test_*.py
└── integration/
    └── (integration tests here)
```

## Test Structure

**Suite Organization:**
Test files use a mix of class-based and function-based tests. Classes group related test cases; functions are used for simple, single-concern tests.

Class-based tests:
```python
class TestMomentumBreakout:
    def test_long_breakout_all_gates_pass(self):
        """Docstring describes test case clearly."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        # Setup
        close = np.full(50, 5010.0)
        close[-1] = 5015.0
        df = make_ohlcv(close, volume)
        features = _base_features(roc=0.5, swing_high=5010.0)

        # Execute
        plugin = MomentumBreakoutPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        # Assert
        assert result.get("signal_type") == "momentum_breakout_long"
        assert result.get("direction") == 1
```

Function-based tests:
```python
def test_build_i1_message_includes_ohlcv_and_features():
    """Combined message must contain OHLCV fields AND I1 feature outputs."""
    from services.indicator_service import build_i1_message

    bar = {"open": 5300.0, "high": 5305.0, "low": 5299.0, "close": 5303.0, "volume": 1000}
    features = {"rsi_14": 58.3, "macd": 2.1, "atr_14": 4.5}
    ts = datetime(2026, 2, 20, 10, 0, 0)

    msg = build_i1_message(bar, features, ts, symbol="ES", timeframe="1m")

    assert msg["open"] == "5300.0"
    assert msg["rsi_14"] == "58.3"
```

**Patterns:**
- **Arrange-Act-Assert (AAA):** Setup data, call function, verify results
- **Test one concept:** Each test verifies a single behavior or condition
- **Clear naming:** Test name describes what it tests and expected outcome
- **Docstrings:** Every test has a one-line docstring explaining its purpose

## Mocking

**Framework:** `unittest.mock` (standard library)

**Patterns:**
Import mocking:
```python
from unittest.mock import AsyncMock, MagicMock, patch
```

Mock service initialization with patch context managers:
```python
def _make_service():
    """Instantiate AINarrativeService with all external deps mocked."""
    with (
        patch("services.ai_narrative_service.start_metrics_server"),
        patch("services.ai_narrative_service.counter", return_value=MagicMock()),
        patch("services.ai_narrative_service.Settings") as mock_settings,
    ):
        mock_settings.return_value.env_name = ""
        from services.ai_narrative_service import AINarrativeService
        return AINarrativeService()
```

Async mocking:
```python
@pytest.mark.asyncio
async def test_process_message_skips_zero_direction():
    """direction=0 → no Ollama call, message acked anyway."""
    svc = _make_service()
    svc.redis_client = AsyncMock()

    with patch("services.ai_narrative_service.call_ollama_async") as mock_ollama:
        await svc._process_single_message(...)
        mock_ollama.assert_not_called()
    svc.redis_client.xack.assert_called_once()
```

Mocking with return values:
```python
with patch(
    "services.ai_narrative_service.call_ollama_async",
    return_value="fake_narrative",
) as mock_ollama:
    # Test code that uses mocked function
```

**What to Mock:**
- External I/O: Redis, databases, HTTP calls
- File system operations when not testing them directly
- System time: `datetime.now()`, `time.time()`
- External services: LLMs, market data providers
- Metrics/observability: counters, gauges, logging (unless specifically testing)

**What NOT to Mock:**
- Business logic under test
- Data models and Pydantic schemas
- Configuration objects (use real or fake instances)
- Plugin compute logic (test with real data)
- Stream consumers/producers (test with Redis mocks for behavior)

## Fixtures and Factories

**Test Data:**
Helper modules provide factory functions for test data:
- `tests/unit/intelligence/helpers.py`: `make_ohlcv()` creates DataFrame with OHLCV columns
- Inline helpers: `_base_features()` creates minimal feature dict for a test case

Example from `test_momentum_breakout.py`:
```python
def _base_features(roc=0.5, swing_high=5010.0, swing_low=4990.0, trend_regime=0.0):
    """Minimal features for a passing triple-gate setup."""
    return {
        "roc_14": roc,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "trend_regime": trend_regime,
        "atr_14": 8.0,
    }
```

**Pytest Fixtures (conftest.py):**
Shared fixtures available to all tests via `tests/conftest.py`:

```python
@pytest_asyncio.fixture
async def mock_redis():
    """Mock Redis client for testing."""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=b"PONG")
    redis_mock.xadd = AsyncMock(return_value=b"1234567890-0")
    redis_mock.aclose = AsyncMock()
    return redis_mock

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
def mock_config():
    """Mock configuration for testing."""
    return {
        "symbols": ["ESU5", "NQU5", "RTYU5"],
        "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
    }
```

**Location:**
- Fixtures shared across test suite: `tests/conftest.py`
- Fixtures specific to a test module: inline at top of test file
- Helper functions: separate modules like `tests/unit/intelligence/helpers.py`

## Coverage

**Requirements:** Not enforced by default; coverage measurement available via pytest-cov

**View Coverage:**
```bash
pytest --cov=src --cov-report=term-missing tests
pytest --cov=src --cov-report=html tests      # Creates htmlcov/index.html
```

**Current Status:** Project has 476+ passing unit tests across all tiers (I1-I8); specific coverage targets not enforced

## Test Types

**Unit Tests:**
- Scope: Single function, class method, or small module
- Approach: Isolated with mocked dependencies
- Location: `tests/unit/`
- Examples: `test_models.py` (Pydantic models), `test_indicator_service.py` (message building functions)
- Setup: Direct instantiation or factory helpers like `_make_service()`

**Integration Tests:**
- Scope: Multiple components working together (e.g., service consuming Redis stream, writing to database)
- Approach: Use test database/Redis when possible; external mocks for outside services
- Location: `tests/integration/` (separate from unit)
- Currently minimal; most tests are unit-focused

**E2E Tests:**
- Not in codebase — covered by manual testing and demo scenarios

**Plugin Tests:**
- Scope: Full plugin compute logic (I1-I8 plugins)
- Approach: Real data fixtures, verify output shape and validation
- Location: `tests/unit/intelligence/test_*.py` (one file per setup plugin)
- Pattern: Arrange OHLCV + features, call `plugin.compute_full()`, assert output

## Common Patterns

**Async Testing:**
Mark test with `@pytest.mark.asyncio` decorator and use `async def`:
```python
@pytest.mark.asyncio
async def test_process_message_skips_zero_direction():
    svc = _make_service()
    svc.redis_client = AsyncMock()

    await svc._process_single_message(...)

    svc.redis_client.xack.assert_called_once()
```

Running in event loop (for non-async test code calling async functions):
```python
def test_evaluate_signals_against_bar_no_db_returns_empty():
    svc = SignalTrackerService()
    svc.db_manager = None

    transitions = asyncio.get_event_loop().run_until_complete(
        svc._evaluate_signals_against_bar("ES", "1m", {"high": 5305.0})
    )
    assert transitions == []
```

**Error Testing:**
Test error conditions explicitly:
```python
def test_no_signal_roc_too_weak(self):
    """ROC below threshold → no signal even if volume and structure qualify."""
    plugin = MomentumBreakoutPlugin()
    result = plugin.compute_full({"main": df, "features": _base_features(roc=0.1)})

    assert result.get("signal_type", "none") == "none"
```

**Approximate Assertions:**
Use `pytest.approx()` for floating-point comparisons:
```python
assert result["entry_price"] == pytest.approx(5015.0, abs=1.0)
assert result["stop_loss"] == pytest.approx(5002.0, abs=2.0)
```

**Test Markers:**
Pytest markers for test categorization (defined in `pytest.ini`):
```python
@pytest.mark.unit              # Unit tests
@pytest.mark.integration       # Integration tests
@pytest.mark.slow              # Slow-running tests
@pytest.mark.requires_ibkr     # Requires IBKR TWS connection
@pytest.mark.requires_redis    # Requires Redis connection
@pytest.mark.requires_db       # Requires database connection
```

Example:
```python
@pytest.mark.requires_redis
def test_redis_connection():
    # Test that requires Redis
    pass
```

---

*Testing analysis: 2026-02-22*
