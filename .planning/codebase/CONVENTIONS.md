# Coding Conventions

**Analysis Date:** 2026-03-11

## Python Code Organization

**Import Order:**
1. `from __future__ import annotations` (first line, PEP 563 forward references)
2. Standard library imports (os, sys, datetime, asyncio, etc.)
3. Third-party imports (pandas, redis, pydantic, structlog, etc.)
4. Relative imports from project (src.*, services.*, production.*, etc.)

Use `isort` via ruff (`[tool.ruff.lint.isort]` in pyproject.toml) with `known-first-party = ["src", "production", "services"]`.

**Module Structure:**
- Docstrings: All modules begin with `"""..."""` describing purpose, key classes, and latest status
- Type hints: Use `from __future__ import annotations` for all forward references; avoid `Optional[T]` in favor of `T | None`
- Private functions: Prefix with `_` (e.g., `_make_service()`, `_min_bars_for_tf()`)
- No E402 (module-level import not at top) allowed except in `/services/`, `/production/`, `/scripts/`, `/tests/integration/` (marked as per-file-ignore in ruff config)

## File Naming

**Python:**
- Services: `{name}_service.py` (e.g., `indicator_service.py`, `signal_generator_service.py`)
- Plugins: `{name}.py` (e.g., `cci.py`, `rsi.py`)
- Tests: `test_{component}.py` (e.g., `test_stream_utils.py`, `test_hma.py`)
- Core utilities: `{functionality}.py` (e.g., `stream_keys.py`, `service_utils.py`, `database_manager.py`)
- Modules with private helpers: `_{name}.py` (e.g., `_publishing.py`, `_consuming.py`, `_monitoring.py`)

**TypeScript/TSX:**
- Components: kebab-case (e.g., `indicator-grid.tsx`, `signal-card.tsx`)
- Utilities: kebab-case (e.g., `format.ts`, `types.ts`)
- Hooks: `use-{name}.ts` (e.g., `use-market-stream.ts`)

## Naming Conventions

**Functions & Methods:**
- `snake_case` (PEP 8) for all functions and methods (e.g., `insert_signals()`, `record_activation()`). 
- Verb-first for actions: `compute_full()`, `publish_ohlcv_bar()`.
- Getter-like: `get_active_contracts()`, `min_bars_for_tf()`.
- Boolean predicates: `is_*()` or `has_*()` (e.g., `is_num()`, `has_context()`).
- Internal: `_private_method()` with leading underscore.

**Classes:**
- `PascalCase` for all classes (e.g., `CCIPlugin`, `IndicatorService`, `TradeFrame`).
- **Persistence Pattern:** All database I/O MUST use `src/persistence/repository/` classes. All asynchronous persistence consumers MUST use the `DataWriterAgent` pattern defined in `src/persistence/writer/`.


**Variables:**
- `snake_case` for all variables, parameters, module names
- Abbreviations allowed when standard: `df` (DataFrame), `tf` (timeframe), `ts` (timestamp), `msg` (message), `svc` (service)
- Multi-symbol tuples: `(plugin_name, symbol, timeframe)` — always in this order in state keys
- Dictionary keys: `snake_case` consistently (e.g., `bar_history`, `_df_cache`, `feature_ts`)
- Redis stream keys: constructed via `src/core/stream_keys.py` functions, NEVER hardcoded

**Classes:**
- `PascalCase` for all classes (e.g., `CCIPlugin`, `IndicatorService`, `TradeFrame`)
- Dataclasses: use `@dataclass` decorator with `default_factory=dict` or `field()` for mutable defaults
- Protocol classes: define with `class SomethingPlugin(Protocol):` in `src/intelligence/plugins.py`

**Constants:**
- `UPPERCASE_SNAKE_CASE` for module-level constants (e.g., `PLUGIN_METRICS_SAMPLE_RATE`, `TF_SECONDS`)
- Dictionary mappings: `_UPPER_CASE` with leading underscore (e.g., `_MIN_BARS_FOR_TF`, `_TF_MINUTES`)

**Abbreviations (standard):**
- `I1`, `I2`, `I3`, `I4`, `I5`, `I6`, `I7`, `I8` — intelligence tiers (not `i1` lowercase)
- `SMC` — Smart Money Concepts
- `OHLCV` — Open/High/Low/Close/Volume
- `MTF` — multi-timeframe
- `BOS` — break of structure
- `CHoCH` — change of character
- `FVG` — fair value gap
- `OB` — order block
- `MAE` / `MFE` — max adverse / favorable excursion
- `TTL` — time-to-live

## Type Annotations

**Python:**
- Always annotate function signatures: `def foo(bar: str, baz: int = 10) -> dict[str, Any]:`
- Use `|` union syntax (not `Union`): `str | None` not `Optional[str]`
- Generic containers: `dict[str, Any]`, `list[str]`, `tuple[str, str, int]`
- Pydantic models: `BaseModel` with `model_config = ConfigDict(extra="forbid")` or `extra="allow"` as appropriate
- Protocol definitions in `src/intelligence/plugins.py`: `class IndicatorPlugin(Protocol):`

**TypeScript:**
- Always use strict mode: `"strict": true` in `tsconfig.json`
- Interface names: `PascalCase` (e.g., `IndicatorData`, `SignalCardProps`)
- Export types with `type` keyword: `export type IndicatorData = { ... }`
- Null checks: guard with `?? undefined` and `!= null` (handles both null and undefined)

## Code Style

**Formatting:**
- Line length: 100 characters (Black + ruff)
- Black configuration: `target-version = ["py313"]`, `line-length = 100`
- Run before commit: `.venv/bin/black .` then `.venv/bin/ruff check . --fix`
- No manual formatting — always use tools

**String Formatting:**
- f-strings: preferred for all interpolation (e.g., `f"{symbol}:{timeframe}"`)
- Multi-line strings: use `"""..."""` docstrings, not concatenation

**Whitespace:**
- No trailing whitespace
- One blank line between functions/methods in a class
- Two blank lines between top-level definitions
- Blank lines within long functions to separate logical blocks

## Dataclass Patterns

**Standard Plugin Definition:**
```python
@dataclass
class CCIPlugin:
    name: str = "CCI"
    outputs: set[str] = frozenset({"cci_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    periods: list[int] = None
    _state: dict = field(default_factory=dict)
```

**Key Rules:**
- Use `frozenset` for `outputs` and `capability_tags` (immutable, hashable)
- Use `tuple[InputSpec, ...]` for `inputs` (immutable)
- Use `field(default_factory=dict)` for `_state` (mutable, per-instance)
- `None` defaults only for optionals that are set in `__post_init__`

## Signal Ledger Status Values

**Raw String Literals** (no enum — kept as strings across all services):
- `"pending"` — signal fired, awaiting activation
- `"active"` — zone activated, trade in progress
- `"regime_suppressed"` — signal suppressed by regime gate

Consolidated in `src/intelligence/trading/signal_ledger.py`.

## Error Handling

**Try-Except Pattern:**
```python
try:
    # operation
except SpecificError as e:
    logger.warning("Operation failed", error=str(e), context=value)
    # fallback or continue
except Exception as e:
    logger.error("Unexpected error", error=str(e), exc_info=True)
    raise
```

**Guidelines:**
- Catch specific exceptions, never bare `except:`
- Log at `warning` level for expected failures (e.g., parsing, timeout)
- Log at `error` level for unexpected exceptions with `exc_info=True`
- Always include `error=str(e)` in log context for structured logging
- Include context fields: `symbol=symbol, timeframe=timeframe, plugin=name`
- Consumer group setup: catch `redis.ResponseError` specifically for BUSYGROUP detection

**Example (from stream_utils.py):**
```python
try:
    await client.xgroup_create(stream, group, "$", mkstream=True)
    return True
except redis.ResponseError as e:
    if "BUSYGROUP" in str(e):
        await client.xgroup_setid(stream, group, "$")
        return False
    raise
```

## Logging

**Framework:** `structlog` with stdlib logging (configured in `src/core/service_utils.py`)

**Initialization:**
```python
from src.core.service_utils import setup_service_logging

setup_service_logging(
    log_file="logs/my_service.log",
    level="INFO",
    backup_count=5
)
self.logger = structlog.get_logger("MyService")
```

**Context Fields (always included):**
- `timestamp` — ISO 8601 (automatic via TimeStamper)
- `service` — service name
- `symbol` — trading symbol (e.g., "ESH6", "VX")
- `timeframe` — bar period (e.g., "1m", "5m", "1h")
- `level` — log level (automatic)

**Usage Patterns:**
```python
self.logger.info("Message", symbol=symbol, timeframe=timeframe, key=value)
self.logger.warning("Degradation", error=str(e), plugin=name)
self.logger.error("Failure", error=str(e), trace=traceback.format_exc())
```

**Log Levels:**
- `info`: state changes, startup/shutdown, periodic summaries
- `warning`: recoverable failures, degradation, resource constraints
- `error`: unrecoverable failures, crashes, data loss risk
- `debug`: detailed plugin execution, buffer state, intermediate computations (disabled by default)

## Comments

**When to Comment:**
- Complex algorithms: explain approach before code
- Non-obvious decisions: "Why are we doing this?"
- Workarounds: "FIXME: explain temporary solution"
- Formula references: cite academic papers or sources
- State machine transitions: document all states and triggers

**JSDoc/Docstring Pattern:**
```python
def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Compute full indicator set from price history.

    Args:
        frames: Dict with 'main' key containing OHLCV DataFrame.

    Returns:
        Dict of indicator outputs keyed by name (e.g. 'cci_14').
        Empty dict if insufficient bars.
    """
```

**Avoid:**
- Comment every line (bad: noise, maintenance burden)
- Comment obvious code (bad: "x = 5  # set x to 5")
- Stale comments (outdated comments are worse than no comments)

## Redis Stream Keys

**Construction:** NEVER hardcode stream names. Use functions from `src/core/stream_keys.py`:
```python
from src.core.stream_keys import market as sk_market, indicators as sk_indicators

stream_name = sk_market(env_prefix, symbol, timeframe)  # "market:ESH6:1m"
stream_name = sk_indicators(env_prefix, symbol, timeframe)  # "indicators:ESH6:1m"
```

**Key Patterns:**
- `market:SYMBOL:TF` — raw OHLCV bars
- `indicators:SYMBOL:TF` — I1 technical indicators
- `intelligence:SYMBOL:TF` — full IntelligenceEvent (I1–I8)
- `signals:SYMBOL:TF:aggregated` — final I7 signal selection
- `narratives:SYMBOL:TF` — I8 LLM narrative
- `llm_calls:stream` — audit log of all LLM calls
- `llm_outcomes:stream` — signal exits with outcome/PnL
- `ticks:SYMBOL:live` — live tick updates (not bars)
- `price:SYMBOL:latest` — hash key for latest bid/ask

## Plugin Protocol

**All plugins must implement:**
```python
@dataclass
class MyPlugin:
    name: str = "MyPlugin"
    outputs: frozenset[str]  # immutable frozenset
    min_lookback: int
    supports_incremental: bool
    capability_tags: frozenset[str]
    inputs: tuple[InputSpec, ...]  # immutable tuple
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full computation from history."""

    def compute_next(self, windows: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Incremental computation from last bar."""
```

**State Management:**
- `_state` is swapped onto plugin at start of bar, written back after
- GARCH/HMM plugins fully reassign `_state` dict — always write back
- Incremental (`compute_next()`) relies on `_state` being present from prior `compute_full()`

## Package Management

**Python:**
- `requirements.txt` — production dependencies
- `.venv` — virtual environment (committed)
- Lockfile: `uv.lock` (UV package manager)
- Command: `.venv/bin/pip install -r requirements.txt` or `uv pip install`

**TypeScript:**
- `package.json` — dependencies and build scripts
- `node_modules` — NOT committed (gitignore)
- Lockfile: `package-lock.json` (npm)
- Command: `npm install` (cached from lock file)

## Async/Await Patterns

**Service Event Loop:**
```python
async def start(self) -> None:
    try:
        await self._connect_redis()
        asyncio.create_task(self._process_market_data())
        asyncio.create_task(self._health_monitor_loop())
    except Exception as e:
        self.logger.error("Failed to start", error=str(e))
        raise

async def stop(self) -> None:
    self.running = False
    await asyncio.sleep(0.1)  # let tasks finish
    await self.redis_client.close()
```

**Consumer Groups (xreadgroup):**
```python
all_streams = {name: ">" for name in self._stream_map}
messages = await self.redis_client.xreadgroup(
    group, consumer, all_streams, count=10, block=1000
)
for stream_bytes, msgs in messages:
    stream_name = stream_bytes.decode() if isinstance(stream_bytes, bytes) else stream_bytes
    # process msgs
```

**Signal Handler:**
```python
def _signal_handler(self, signum: int, frame: Any) -> None:
    self.logger.info("Received shutdown signal", signal=signum)
    self.running = False

signal.signal(signal.SIGINT, self._signal_handler)
signal.signal(signal.SIGTERM, self._signal_handler)
```

---

*Convention analysis: 2026-03-11*
