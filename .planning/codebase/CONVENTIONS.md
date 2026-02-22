# Coding Conventions

**Analysis Date:** 2026-02-22

## Naming Patterns

**Files:**
- Python modules: `snake_case` (e.g., `indicator_service.py`, `plugin_state_manager.py`)
- Test files: `test_*.py` prefix (e.g., `test_models.py`, `test_signal_tracker_service.py`)
- Plugin classes: descriptive name + `Plugin` suffix (e.g., `MomentumBreakoutPlugin`)
- Classes: `PascalCase` (e.g., `IndicatorCalculations`, `RedisStreamsManager`, `CircuitBreakerConfig`)

**Functions:**
- Standard functions: `snake_case` (e.g., `build_i1_message`, `parse_indicators_message`)
- Async functions: `async def` with `snake_case` names (e.g., `async def fetch_historical_bars()`)
- Private functions: leading underscore (e.g., `_create_consumer_groups`, `_run_analysis_pipeline`)
- Factory/builder functions: `get_*` prefix (e.g., `get_backend_manager()`, `get_active_contracts()`)
- Helper functions in tests: `_make_*` or `_base_*` prefix (e.g., `_make_service()`, `_base_features()`)

**Variables:**
- Snake case for all variables: `tick_accum`, `circuit_breaker_state`, `consumer_groups`
- Constants: UPPER_SNAKE_CASE (e.g., `I1_PLUGINS`, `_OHLCV_FIELDS`, `TIER_I1`)
- Type unions use pipe syntax: `str | None`, `int | float`, `dict[str, Any]`
- Private instance vars: leading underscore (e.g., `self._is_running`, `self._message_cache`)

**Types:**
- Pydantic models: `PascalCase` (e.g., `CircuitBreakerConfig`, `StreamsConfig`, `Instrument`)
- Enums: `PascalCase` class names with UPPER_SNAKE_CASE members (e.g., `class CircuitState(Enum):` with `CLOSED = 0`)
- Protocol classes: `PascalCase` (e.g., `IndicatorPlugin`, `DataProvider`)
- Type hints use `|` for unions (Python 3.10+), not `Union[]`

## Code Style

**Formatting:**
- Black with 100 character line length (`line-length = 100` in `pyproject.toml`)
- Target Python 3.13 (`target-version = ["py313"]`)
- Ruff linter enabled for E, F, W, I (isort), UP (pyupgrade), B (bugbear) rules

**Linting:**
- Ruff configuration in `pyproject.toml`: `[tool.ruff]` and `[tool.ruff.lint]`
- Per-file exceptions for E402 (module import order) allowed in:
  - `services/*.py` - top-level imports after sys.path manipulation
  - `production/**/*.py` - daemon initialization
  - `scripts/*.py` - script setup
  - `tests/integration/*.py` - test infrastructure
- B008 ignored for Pydantic `Depends()` in function defaults (FastAPI pattern)
- No type checking required (`disallow_untyped_defs = false` in mypy config)

**Import Organization:**
1. Future imports: `from __future__ import annotations` (when needed for type forward refs)
2. Standard library: `import os`, `from pathlib import Path`, etc.
3. Third-party: `import asyncpg`, `import pandas as pd`, `import redis.asyncio as redis`, `import structlog`, etc.
4. Local project imports: `from src.config.settings import ...`, `from src.core.models import ...`
5. Conditional/late imports: Inside functions when needed (e.g., for circular dependency avoidance)

**Path Aliases:**
- `src` - main source directory (type: package)
- `services` - daemon/service implementations at project root
- `production` - production-specific code (daemons, scripts)
- Imports use absolute paths from project root via `sys.path.insert(0, str(project_root))`

## Error Handling

**Patterns:**
- Broad `except Exception as e:` used at service/daemon level for graceful degradation
- Specific exceptions for validation: `ValueError`, `TypeError` caught individually
- Logging on errors via structlog: `logger.error("message", error=str(e))`
- Async cleanup via `try/finally` or `AsyncContextManager` for resource management
- Circuit breaker pattern for plugin failures: `CircuitBreakerState` enum (CLOSED, OPEN, HALF_OPEN)
- No silent failures - errors always logged with context
- Example from `database_manager.py`:
  ```python
  try:
      await conn.executemany(statement, params)
      await tr.commit()
  except Exception:
      await tr.rollback()
      raise
  ```

**Exception Recovery:**
- Health checks return `bool` (True/False) instead of raising: `async def health_check() -> bool`
- Optional operations (no-op if missing): check and return empty data, don't raise
- Graceful shutdown: signal handlers and `shutdown_requested` flags for clean termination

## Logging

**Framework:** structlog (structured logging)

**Logger Creation:**
```python
import structlog
logger = structlog.get_logger(__name__)
```

**Patterns:**
- Service startup: `logger.info("✅ Service started successfully", key=value)`
- Warnings: `logger.warning("message")` for non-critical issues
- Errors: `logger.error("message", error=str(e))` with exception string
- Context binding: `logger.bind(consumer_group=cg, consumer_name=cn)` for per-instance loggers
- Metric events: `logger.info("metric_event", counter=123, gauge=45.6)`
- No print statements in production code - all logging via structlog

## Comments

**When to Comment:**
- Complex business logic: explain *why* decision made, not *what* code does
- Algorithm-heavy sections: one-line comment for each non-obvious step
- Thresholds/magic numbers: always explain threshold reasoning
- Trade-offs: note if implementation chose one approach over another
- Integration points: explain how this module connects to others

**JSDoc/TSDoc:**
- All public functions have docstrings with Args, Returns, Raises sections
- Class docstrings describe purpose and key behaviors
- Long docstrings use multi-line format:
  ```python
  def execute_batch(self, statement: str, params: list[list[Any]]) -> None:
      """Execute a batched statement within a single transaction.

      Args:
          statement: SQL statement with positional parameters
          params: Sequence of parameter tuples/lists
      """
  ```
- Dataclass fields documented inline via Field() descriptions
- Module docstrings: Version, Last Updated, Status at top of file (example in `settings.py`)

## Function Design

**Size:** Most functions 20-50 lines; longer functions broken into focused helpers

**Parameters:**
- Type hints required on all parameters
- Default values use Pydantic Field() or simple literals
- Dictionary unpacking for config: `**config` pattern used in services
- No positional-only enforcement (`/` syntax) — flexibility preferred

**Return Values:**
- Type hints required: `-> bool`, `-> dict[str, Any]`, `-> None`
- Async functions use `async def` with proper return types
- Union returns use `|` syntax: `-> str | None`
- Multiple returns wrapped in tuple: `-> tuple[dict[str, Any], dict[str, Any]]`
- No implicit returns (always explicit `return` or `None`)

**Async Patterns:**
- `async def` for all I/O operations (Redis, database, network calls)
- Context managers: `async with self.get_connection() as conn:`
- Task creation: `asyncio.create_task(coro)` for background work
- Gathering: `await asyncio.gather(*tasks, return_exceptions=True)`
- Cancellation handled: `except asyncio.CancelledError:` blocks

## Module Design

**Exports:**
- No wildcard exports (`from module import *` not used)
- Public API exported explicitly or via `__all__` list
- Private modules prefixed with underscore: `_consuming.py`, `_publishing.py`

**Barrel Files:**
- Mixin modules expose multiple capabilities in parent class
- Example: `RedisStreamsManager` inherits from `ResilienceMixin`, `PublishingMixin`, `ConsumingMixin`
- Factory functions return configured instances: `get_backend_manager()`, `redis_streams_manager()`

**Module Organization:**
- Each module has a single responsibility
- Stream-related: `stream_keys.py` (constants), `stream_models_core.py` (types), mixins in `_*.py`
- Calculation modules: `calculations.py` (main), `calc_modules/_*.py` (by category)
- Services: standalone at `services/*.py` with full dependencies imported

---

*Convention analysis: 2026-02-22*
