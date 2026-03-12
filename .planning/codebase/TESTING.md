# Testing Patterns

**Analysis Date:** 2026-03-11

## Test Framework & Configuration

**Test Runner:**
- Framework: pytest 6.0+
- Config file: `pytest.ini` at project root
- Python version: 3.13

**Run Commands:**
```bash
.venv/bin/pytest tests/unit/ -v              # Run all unit tests with verbose output
.venv/bin/pytest tests/unit/ -k "test_foo"   # Run tests matching pattern
.venv/bin/pytest tests/unit/ -m unit         # Run tests with @pytest.mark.unit
.venv/bin/pytest --co -q                     # List all collected tests (don't run)
```

**Watch Mode:**
```bash
.venv/bin/pytest tests/unit/ --tb=short -v --maxfail=3  # Stop after 3 failures, short traceback
```

**Coverage:**
```bash
.venv/bin/pytest tests/unit/ --cov=src --cov-report=html  # Generate HTML coverage report
```

**Pytest Configuration (pytest.ini):**
```ini
[tool:pytest]
minversion = 6.0
addopts = -ra -q --strict-markers --strict-config --disable-warnings --asyncio-mode=auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    unit: Unit tests
    integration: Integration tests
    performance: Performance/benchmark tests
    slow: Slow-running tests
    requires_ibkr: Tests requiring IBKR TWS connection
    requires_redis: Tests requiring Redis connection
    requires_db: Tests requiring database connection
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
```

**Assertion Library:**
- pytest assertions (built-in `assert` statements)
- Floating-point comparisons: `pytest.approx(expected, rel=1e-6)`
- Context matching: `pytest.raises(ExceptionType, match="pattern")`

## Test File Organization

**Location:**
- Unit tests: `tests/unit/{domain}/test_{component}.py`
- Integration tests: `tests/integration/test_{scenario}.py`
- Service tests: `tests/unit/service_tests/test_{service}.py`
- Intelligence tests: `tests/unit/intelligence/test_{plugin}.py`
- Core tests: `tests/unit/core/test_{module}.py`

**File Naming:**
- Always `test_{component}.py` (prefix, not suffix)
- One test file per component (e.g., `test_cci.py` for CCI plugin)
- Grouped by domain: `tests/unit/{domain}/test_*.py`

**Example Structure:**
```
tests/
├── unit/
│   ├── intelligence/
│   │   ├── test_hma.py
│   │   ├── test_cci.py
│   │   ├── test_trading_setups.py
│   │   └── helpers.py
│   ├── service_tests/
│   │   ├── test_indicator_service_buffer.py
│   │   ├── test_signal_generator_service.py
│   │   └── test_signal_lifecycle_service.py
│   ├── core/
│   │   ├── test_stream_utils.py
│   │   ├── test_stream_keys.py
│   │   └── test_retry_utils.py
│   ├── config/
│   │   └── test_settings.py
│   └── api/
│       └── test_health_endpoints.py
└── integration/
    ├── test_simple_pipeline.py
    └── test_comprehensive_timeframe_aggregation.py
```

## Test Structure

**Markers (always apply one):**
```python
@pytest.mark.unit          # Unit tests (no external services)
@pytest.mark.integration   # Integration tests (needs Redis, DB, IBKR)
@pytest.mark.asyncio       # Async test (auto-detected, optional explicit)
@pytest.mark.slow          # Slow test (skip with -m "not slow")
```

**Class-Based Tests:**
```python
class TestCacheNotInvalidatedWhenBufferHasRoom:
    """Cache must remain intact when buffer has room (len < _bar_history_max)."""

    def test_cache_retained_on_first_bar(self):
        """First bar appended — buffer well under max."""
        svc = _make_service()
        key = "ES:1m"
        sentinel = pd.DataFrame([{"close": 99.0}])
        svc._df_cache[key] = sentinel

        history = svc.bar_history[key]
        history["2026-01-01T10:00:00"] = {"timestamp": "...", "close": 100.0}

        # Simulate cache invalidation logic
        cache_invalidated = False
        while len(history) > svc._bar_history_max:
            history.popitem(last=False)
            cache_invalidated = True

        if cache_invalidated:
            svc._df_cache[key] = None

        assert svc._df_cache[key] is sentinel, "Cache must not be invalidated"
```

**Function-Based Tests (simple cases):**
```python
@pytest.mark.unit
def test_min_bars_for_tf_returns_120_for_1m():
    """1m timeframe requires 120 bars minimum for warmup."""
    assert min_bars_for_tf("1m") == 120

@pytest.mark.unit
def test_min_bars_for_tf_returns_26_for_5m():
    """5m+ timeframes require 26 bars (EMA-26 + Stochastic-14)."""
    assert min_bars_for_tf("5m") == 26
```

## Fixture Patterns

**Pytest Fixtures:**
```python
@pytest.fixture
def client(self):
    """Test client fixture for FastAPI testing."""
    from fastapi.testclient import TestClient
    from src.api.main import app
    return TestClient(app)

def test_health_endpoint_success(self, client):
    """Use fixture as parameter."""
    response = client.get("/health")
    assert response.status_code == 200
```

**Test Data Helpers (not fixtures):**
```python
def make_ohlcv(close: np.ndarray, volume: np.ndarray | None = None) -> pd.DataFrame:
    """Build OHLCV DataFrame from close array with synthetic high/low/open."""
    n = len(close)
    spread = np.abs(close) * 0.002
    high = close + spread
    low = close - spread
    open_ = close + np.random.default_rng(0).normal(0, 0.001, n) * close
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    if volume is None:
        volume = np.full(n, 1000.0)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume
    })

# Usage in test:
def test_hma_20_flat_series_equals_price():
    c = 5000.0
    closes = np.full(50, c)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    assert result.get("hma_20") == pytest.approx(c, rel=1e-6)
```

**Service Test Factory Pattern (using `__new__`):**
```python
def _make_service():
    """Create a minimal IndicatorService instance for buffer tests.

    Uses __new__ to bypass __init__ — avoids full service initialization
    and allows manual setting of required attributes.
    """
    from services.indicator_service import IndicatorService

    svc = IndicatorService.__new__(IndicatorService)
    svc.bar_history = defaultdict(OrderedDict)
    svc._bar_history_max = 5
    svc._df_cache = {}
    return svc
```

**Why `__new__` Pattern:**
- Avoids expensive initialization (Redis connection, config loading)
- Avoids mocking entire `__init__` signature
- Any attribute set in `__init__` must be manually set in test
- Load-bearing: if new attribute added to `__init__`, tests silently fail unless updated

**Example with Mocking:**
```python
def _make_service():
    with patch("services.indicator_service.start_metrics_server"), \
         patch("services.indicator_service.counter", return_value=MagicMock(inc=MagicMock())), \
         patch("services.indicator_service.gauge", return_value=MagicMock(set=MagicMock())), \
         patch("services.indicator_service.get_active_contracts", return_value=["ESH6"]), \
         patch("services.indicator_service.Settings"):
        from services.indicator_service import IndicatorService
        svc = IndicatorService.__new__(IndicatorService)
        svc.config = {
            "service": {"symbols": ["ESH6"], "timeframes": ["1m"], "min_history_bars": 120}
        }
        return svc
```

## Mocking

**Framework:** `unittest.mock` (stdlib)

**AsyncMock Pattern:**
```python
from unittest.mock import AsyncMock, MagicMock

async def test_retry_succeeds_on_first_attempt():
    coro = AsyncMock(return_value=42)
    result = await retry_with_backoff(coro, "arg1", max_attempts=3)

    assert result == 42
    coro.assert_called_once_with("arg1")
    assert coro.call_count == 1
```

**Side Effects (sequential return values):**
```python
async def test_retries_on_exception_and_succeeds():
    coro = AsyncMock(side_effect=[ValueError("fail"), ValueError("fail"), 99])
    result = await retry_with_backoff(coro, max_attempts=3, base_delay=0.0)

    assert result == 99
    assert coro.call_count == 3
```

**Exception Raising:**
```python
async def test_raises_after_max_attempts():
    exc = RuntimeError("always fails")
    coro = AsyncMock(side_effect=exc)

    with pytest.raises(RuntimeError, match="always fails"):
        await retry_with_backoff(coro, max_attempts=3, base_delay=0.0)

    assert coro.call_count == 3
```

**Patching (module imports):**
```python
with patch("services.indicator_service.start_metrics_server"), \
     patch("services.indicator_service.Settings"):
    from services.indicator_service import IndicatorService
    svc = IndicatorService.__new__(IndicatorService)
```

**Critical Gotcha: isinstance() with MagicMock:**
```python
# WRONG — MagicMock is truthy, float(MagicMock()) == 1.0
if result:
    value = float(result)

# RIGHT — explicit isinstance check
if isinstance(result, (int, float)):
    value = float(result)
```

**What to Mock:**
- External services: Redis, PostgreSQL, HTTP APIs
- Large dependencies: IBKR TWS, Ollama
- Heavy computations: only if they're not under test

**What NOT to Mock:**
- Core business logic under test (defeats the purpose)
- Simple library functions (bool conversions, string operations)
- Database queries themselves (use integration tests if DB testing needed)
- The module you're testing (patch *other* modules it imports)

## Test Types

### Unit Tests
**Scope:** Single function/class in isolation
**Characteristics:**
- Fast (< 100ms)
- No external services
- Use factories/helpers for test data
- Test both happy path and error cases
- Located in `tests/unit/`

**Example:**
```python
@pytest.mark.unit
def test_exponential_backoff_with_jitter_delay_increases_exponentially():
    d0 = exponential_backoff_with_jitter(0, base_delay=1.0, jitter_factor=0.0)
    d1 = exponential_backoff_with_jitter(1, base_delay=1.0, jitter_factor=0.0)
    d2 = exponential_backoff_with_jitter(2, base_delay=1.0, jitter_factor=0.0)

    assert d0 == pytest.approx(1.0)
    assert d1 == pytest.approx(2.0)
    assert d2 == pytest.approx(4.0)
```

### Integration Tests
**Scope:** Multiple components working together (e.g., service consuming Redis stream → writing to DB)
**Characteristics:**
- Slower (1-30s depending on I/O)
- Requires live Redis, PostgreSQL, optionally IBKR
- Tests real data flow, not mocked interactions
- Mark with `@pytest.mark.integration`
- Located in `tests/integration/`

**Example:**
```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_to_database_flow(self):
    redis_client = redis.Redis(host="localhost", port=6379, db=0)
    await redis_client.ping()

    db_manager = DatabaseManager("postgresql://...")
    await db_manager.initialize()

    # Publish to Redis, verify in DB
    stream_id = await streams_manager.publish_ohlcv_bar(symbol, tf, test_data)
    assert stream_id is not None

    await redis_client.close()
    await db_manager.close()
```

### E2E Tests
**Status:** Not currently implemented. Would test full pipeline end-to-end.
**Planned scope:** Market bar → I1 → I3–I8 → signal ledger → dashboard

## Async Testing

**Pattern:**
```python
@pytest.mark.asyncio
async def test_consumer_group_creation():
    """Test async function directly with @pytest.mark.asyncio."""
    mock_client = AsyncMock()
    mock_client.xgroup_create = AsyncMock(return_value=True)

    result = await ensure_consumer_group_with_reset(mock_client, "stream", "group")

    assert result is True
```

**Using asyncio.run() in sync test:**
```python
def test_retry_with_backoff_sync():
    """Wrap async call with asyncio.run() for sync test function."""
    coro = AsyncMock(return_value=42)
    result = asyncio.run(retry_with_backoff(coro, max_attempts=3))
    assert result == 42
```

## Error Testing

**Pattern — pytest.raises:**
```python
def test_parse_intelligence_event_returns_none_on_malformed_json():
    """Malformed JSON is caught, None returned, no crash."""
    result = _parse_intelligence_event({b"event": b"not-valid-json{{{"})
    assert result is None

def test_non_busygroup_error_is_reraised():
    """Non-BUSYGROUP ResponseError propagates immediately."""
    mock_client = AsyncMock()
    mock_client.xgroup_create = AsyncMock(
        side_effect=redis.ResponseError("WRONGTYPE Operation...")
    )

    with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
        await ensure_consumer_group_with_reset(mock_client, "stream", "group")
```

**Exception Matching:**
```python
with pytest.raises(ValueError, match="must be positive"):
    validate_price(-100)

with pytest.raises(ExceptionType):  # Match any exception of this type
    some_function()
```

## Plugin Testing

**Test Contracts (required):**
1. Output field names are in `plugin.outputs` frozenset
2. `plugin.min_lookback` is enforced before computing
3. Returns `{}` or zeros when fewer than `min_lookback` bars
4. On flat (constant) series, returns stable value
5. Returns correct float type, not string or None
6. Formula correctness verified against known-good inputs

**Example (HMA Plugin):**
```python
def test_hma_20_in_outputs():
    """hma_20 must be in plugin.outputs frozenset."""
    plugin = HMAPlugin()
    assert "hma_20" in plugin.outputs

def test_min_lookback_is_20():
    """plugin.min_lookback must equal 20."""
    plugin = HMAPlugin()
    assert plugin.min_lookback == 20

def test_returns_empty_or_zero_when_fewer_than_20_bars():
    """Fewer than 20 bars → returns {} or {'hma_20': 0.0}."""
    plugin = HMAPlugin()
    closes = np.full(15, 5000.0)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    assert result == {} or result.get("hma_20", 0.0) == pytest.approx(0.0)

def test_hma_20_flat_series_equals_price():
    """WMA of a constant → constant. HMA(constant) = constant."""
    plugin = HMAPlugin()
    c = 5000.0
    closes = np.full(50, c)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    assert result.get("hma_20") == pytest.approx(c, rel=1e-6)

def test_hma_20_trending_series_closer_to_current_price():
    """HMA is low-lag MA — closer to current price than SMA20."""
    plugin = HMAPlugin()
    closes = np.linspace(4800.0, 5200.0, 50)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    hma = result.get("hma_20")
    if hma is not None:
        current_price = closes[-1]
        sma_20 = float(np.mean(closes[-20:]))
        hma_distance = abs(current_price - hma)
        sma_distance = abs(current_price - sma_20)
        assert hma_distance <= sma_distance * 1.5
```

## Floating-Point Comparisons

**Pattern:**
```python
assert result == pytest.approx(expected_value)
assert result == pytest.approx(expected_value, rel=1e-6)  # 0.0001% tolerance
assert result == pytest.approx(expected_value, abs=0.01)  # ±0.01 absolute
```

**When to Use:**
- Always for float comparisons (never `==` for floats)
- Default relative tolerance: 1e-6 (0.0001%)
- For prices: use `rel=1e-4` (0.01% tolerance typical)
- For percentages: use `abs=0.01` (±1% absolute)

## Coverage

**Requirements:** None enforced in CI (no coverage gate)

**View Coverage (if tracking):**
```bash
.venv/bin/pytest tests/unit/ --cov=src --cov-report=term-missing
.venv/bin/pytest tests/unit/ --cov=src --cov-report=html
# Open htmlcov/index.html in browser
```

**Current Status:**
- 1503 passing tests (as of 2026-03-11)
- Unit tests in `tests/unit/` (115 test files)
- Integration tests in `tests/integration/` (3 test files)
- No coverage threshold enforced

## Common Patterns

### Testing Stream Message Parsing
```python
def test_parse_indicators_message_extracts_symbol_and_timeframe():
    """Indicators message parsing extracts symbol, timeframe, OHLCV."""
    fields = {
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-03-11T10:00:00",
        b"open": b"5100.25",
        b"high": b"5105.50",
        b"low": b"5098.75",
        b"close": b"5103.00",
        b"volume": b"12345",
        b"rsi_14": b"58.3",
    }

    bar, features = parse_indicators_message(fields)

    assert bar["symbol"] == "ESH6"
    assert bar["timeframe"] == "5m"
    assert features["rsi_14"] == pytest.approx(58.3)
```

### Testing Redis Mocking
```python
@pytest.mark.asyncio
async def test_xreadgroup_consumes_messages():
    """xreadgroup returns (stream_name, messages) tuples."""
    mock_client = AsyncMock()
    mock_client.xreadgroup = AsyncMock(
        return_value=[
            (b"indicators:ES:1m", [(b"1-0", {b"close": b"5100.0"})])
        ]
    )

    messages = await mock_client.xreadgroup(
        "group", "consumer", {"indicators:ES:1m": ">"}, count=1
    )

    assert len(messages) == 1
    stream_name, msgs = messages[0]
    assert stream_name == b"indicators:ES:1m"
```

### Testing Typed Event Deserialization
```python
def test_parse_intelligence_event_returns_typed_event():
    """Valid IntelligenceEvent JSON → IntelligenceEvent instance."""
    from src.intelligence.schemas import IntelligenceEvent, OHLCVBar

    event = IntelligenceEvent(
        ts=datetime(2026, 2, 18, 10, 0, 0, tzinfo=UTC),
        symbol="ESH6",
        tf="5m",
        bar=OHLCVBar(o=5100.25, h=5105.50, l=5098.75, c=5103.00, v=12345),
        # ... other fields
    )

    fields = {b"event": event.model_dump_json().encode()}
    result = _parse_intelligence_event(fields)

    assert isinstance(result, IntelligenceEvent)
    assert result.symbol == "ESH6"
    assert result.bar.o == pytest.approx(5100.25)
```

## Test Markers

**Available Markers (pytest.ini):**
```python
@pytest.mark.unit              # Unit test (fast, no external services)
@pytest.mark.integration       # Integration test (needs Redis, DB, etc.)
@pytest.mark.performance       # Performance/benchmark test
@pytest.mark.slow              # Slow test (skip with -m "not slow")
@pytest.mark.requires_ibkr     # Requires IBKR TWS connection
@pytest.mark.requires_redis    # Requires Redis running
@pytest.mark.requires_db       # Requires PostgreSQL running
```

**Running Marked Tests:**
```bash
.venv/bin/pytest -m unit                      # Only unit tests
.venv/bin/pytest -m "not slow"                # Skip slow tests
.venv/bin/pytest -m "integration and requires_redis"  # Integration + Redis
```

---

*Testing analysis: 2026-03-11*
