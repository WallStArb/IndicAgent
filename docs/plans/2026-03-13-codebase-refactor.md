# Codebase Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the two highest-maintenance copy-paste patterns: API route utility duplication across three route modules, and silent exception swallows in service `_load_config()` paths.

**Architecture:** Extract shared API utilities to `src/api/utils.py`; add `logger.warning()` to silent exception fallbacks so failures are observable without changing the fallback behavior.

**Tech Stack:** Python 3.12, FastAPI, structlog, pytest

---

## Chunk 1: Extract API Route Utilities

Three route files — `features.py`, `signals.py`, `sse.py` — each define their own copies of `_get_settings()`, `_resolve_contract()`, and `_parse_jsonb()`. They differ slightly:

| Function | `features.py` | `signals.py` | `sse.py` |
|---|---|---|---|
| `_get_settings` | `@lru_cache(maxsize=1)` + deferred import | same | module global var |
| `_resolve_contract` | base→symbol lookup | same | same + regex fallback for VX-style |
| `_parse_jsonb` | returns `{}` on None/failure | returns `None` on None/failure | not present |

**Resolution:**
- `_get_settings()` → canonical `@lru_cache(maxsize=1)` pattern (per CLAUDE.md)
- `_resolve_contract()` → use `sse.py` version (most complete, handles VX → VXH6)
- `parse_jsonb(value, default)` → add `default` param so both call sites work: `features.py` passes `default={}`, `signals.py` passes `default=None`

---

### Task 1: Create `src/api/utils.py` with shared utilities

**Files:**
- Create: `src/api/utils.py`
- Create: `tests/unit/api/test_api_utils.py`

- [ ] **Step 1.1: Write failing tests for `get_settings()`**

```python
# tests/unit/api/test_api_utils.py
from unittest.mock import patch, MagicMock
from src.api.utils import get_settings, resolve_contract, parse_jsonb


def test_get_settings_returns_settings_instance():
    from src.config.settings import Settings
    result = get_settings()
    assert isinstance(result, Settings)


def test_get_settings_is_cached():
    result1 = get_settings()
    result2 = get_settings()
    assert result1 is result2
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/api/test_api_utils.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.api.utils'`

- [ ] **Step 1.3: Write failing tests for `resolve_contract()`**

```python
def test_resolve_contract_already_a_code():
    # symbol with digit → return as-is, no settings lookup
    assert resolve_contract("ESH6") == "ESH6"


def test_resolve_contract_base_to_contract(monkeypatch):
    mock_contract = MagicMock()
    mock_contract.base = "ES"
    mock_contract.symbol = "ESH6"
    mock_settings = MagicMock()
    mock_settings.contracts = [mock_contract]
    monkeypatch.setattr("src.api.utils.get_settings", lambda: mock_settings)
    assert resolve_contract("ES") == "ESH6"


def test_resolve_contract_vx_regex_fallback(monkeypatch):
    # "VX" should match "VXH6" via regex fallback
    mock_contract = MagicMock()
    mock_contract.base = "VIX"
    mock_contract.symbol = "VXH6"
    mock_settings = MagicMock()
    mock_settings.contracts = [mock_contract]
    monkeypatch.setattr("src.api.utils.get_settings", lambda: mock_settings)
    assert resolve_contract("VX") == "VXH6"


def test_resolve_contract_unknown_fallback(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.contracts = []
    monkeypatch.setattr("src.api.utils.get_settings", lambda: mock_settings)
    assert resolve_contract("UNKNOWN") == "UNKNOWN"
```

- [ ] **Step 1.4: Write failing tests for `parse_jsonb()`**

```python
def test_parse_jsonb_none_returns_default():
    assert parse_jsonb(None, default={}) == {}
    assert parse_jsonb(None, default=None) is None


def test_parse_jsonb_string_parsed():
    assert parse_jsonb('{"a": 1}', default={}) == {"a": 1}


def test_parse_jsonb_invalid_string_returns_default():
    assert parse_jsonb("not-json", default={}) == {}
    assert parse_jsonb("not-json", default=None) is None


def test_parse_jsonb_dict_passthrough():
    d = {"a": 1}
    assert parse_jsonb(d, default={}) is d
```

- [ ] **Step 1.5: Run tests to confirm they all fail**

```bash
.venv/bin/pytest tests/unit/api/test_api_utils.py -v
```

- [ ] **Step 1.6: Implement `src/api/utils.py`**

```python
"""
Shared utilities for API route modules.

Centralises: Settings access (cached), contract resolution, JSONB parsing.
"""

import json
import re
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def get_settings():
    """Return cached Settings instance. Import is deferred to avoid circular imports."""
    from ..config.settings import Settings
    return Settings()


def resolve_contract(symbol: str) -> str:
    """Map base symbol (ES) to active contract code (ESH6).

    Accepts both base symbols and full contract codes. If the symbol already
    contains a digit it is returned unchanged. Falls back to regex matching for
    cases like "VX" → "VXH6" (VIX futures use a different base prefix).
    """
    if any(ch.isdigit() for ch in symbol):
        return symbol
    settings = get_settings()
    for c in settings.contracts:
        if c.base == symbol:
            return c.symbol
    # Regex fallback: "VX" matches "VXH6" when base is "VIX"
    for c in settings.contracts:
        m = re.match(r"^([A-Z0-9]{1,4}?)[A-Z]\d+$", c.symbol)
        if m and m.group(1) == symbol:
            return c.symbol
    return symbol


def parse_jsonb(value: Any, *, default: Any = None) -> Any:
    """Parse asyncpg JSONB field to Python object.

    Returns `default` when value is None or unparseable.
    Pass default={} for tier expansion (features route).
    Pass default=None for optional JOIN data (signals route).
    """
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default
    return value  # already dict (asyncpg may parse automatically)
```

- [ ] **Step 1.7: Run tests — all should pass**

```bash
.venv/bin/pytest tests/unit/api/test_api_utils.py -v
```
Expected: all PASS

- [ ] **Step 1.8: Commit**

```bash
git add src/api/utils.py tests/unit/api/test_api_utils.py
git commit -m "feat(api): add shared API route utilities module"
```

---

### Task 2: Update `features.py` to use shared utilities

**Files:**
- Modify: `src/api/routes/features.py`

- [ ] **Step 2.1: Run existing features route tests to establish baseline**

```bash
.venv/bin/pytest tests/unit/api/test_features_route.py -v
```
Expected: all PASS (record count before changes)

- [ ] **Step 2.2: Replace duplicated functions in `features.py`**

Remove the `_get_settings`, `_resolve_contract`, and `_parse_jsonb` local definitions.
Add the import. Replace every call site.

Change the imports block (add `utils` import, remove `lru_cache` and `json` if no longer needed):

```python
# Remove:
import json
from functools import lru_cache

# Add:
from ..utils import get_settings as _get_settings, resolve_contract as _resolve_contract
from ..utils import parse_jsonb as _parse_jsonb
```

Then delete the three local function bodies. All call sites (`_resolve_contract(symbol)`, `_parse_jsonb(row[tier])`) remain identical — the wrapper name aliases ensure zero diff in call syntax.

Note: `_parse_jsonb` in `features.py` returns `{}` on failure. Update every call site to pass `default={}`:
```python
_parse_jsonb(row[tier], default={})
```

- [ ] **Step 2.3: Run tests — should still pass**

```bash
.venv/bin/pytest tests/unit/api/test_features_route.py -v
```

- [ ] **Step 2.4: Commit**

```bash
git add src/api/routes/features.py
git commit -m "refactor(api/features): use shared utils for settings/contract/jsonb"
```

---

### Task 3: Update `signals.py` to use shared utilities

**Files:**
- Modify: `src/api/routes/signals.py`

- [ ] **Step 3.1: Run existing signals route tests to establish baseline**

```bash
.venv/bin/pytest tests/unit/api/test_signals_route.py tests/unit/api_tests/test_signals_routes.py -v
```

- [ ] **Step 3.2: Replace duplicated functions in `signals.py`**

```python
# Remove:
import json
from functools import lru_cache

# Add:
from ..utils import get_settings as _get_settings, resolve_contract as _resolve_contract
from ..utils import parse_jsonb as _parse_jsonb
```

Delete the three local function bodies.

Note: `_parse_jsonb` in `signals.py` returns `None` on failure (not `{}`). Call sites:
```python
_parse_jsonb(row["bar"], default=None)
_parse_jsonb(row["i1"], default=None)
# ... etc
```

- [ ] **Step 3.3: Run tests — should still pass**

```bash
.venv/bin/pytest tests/unit/api/test_signals_route.py tests/unit/api_tests/test_signals_routes.py -v
```

- [ ] **Step 3.4: Commit**

```bash
git add src/api/routes/signals.py
git commit -m "refactor(api/signals): use shared utils for settings/contract/jsonb"
```

---

### Task 4: Update `sse.py` to use shared utilities

**Files:**
- Modify: `src/api/routes/sse.py`

- [ ] **Step 4.1: Run existing SSE tests to establish baseline**

```bash
.venv/bin/pytest tests/unit/api/test_sse_routes.py -v
```

- [ ] **Step 4.2: Replace duplicated functions in `sse.py`**

`sse.py` has its own `_get_settings()` (module global) and `_resolve_contract()` (with regex fallback — same as the canonical version we put in utils.py).

```python
# Remove the module-level global and the two local function definitions:
#   _settings: Settings | None = None
#   def _get_settings() -> Settings: ...
#   def _resolve_contract(symbol: str) -> str: ...

# Add import:
from ..utils import get_settings as _get_settings, resolve_contract as _resolve_contract
```

Call sites for `_get_settings()` and `_resolve_contract()` remain unchanged.

Note: `sse.py` also uses `_get_settings()` inside `_build_stream_list()` for `env_prefix`. No change needed there — same interface.

- [ ] **Step 4.3: Run tests — should still pass**

```bash
.venv/bin/pytest tests/unit/api/test_sse_routes.py -v
```

- [ ] **Step 4.4: Run full unit suite to confirm nothing regressed**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short
```
Expected: all PASS (1613+)

- [ ] **Step 4.5: Commit**

```bash
git add src/api/routes/sse.py
git commit -m "refactor(api/sse): use shared utils for settings/contract resolution"
```

---

## Chunk 2: Silent Exception Logging

Two services have `except Exception: <fallback>` blocks with no log output. When Settings() fails at startup for any reason, the service silently degrades — no trace in journalctl. These blocks are correctly structured (fallback behavior is intentional) but need a `logger.warning()` so failures are observable.

**Affected locations:**

| File | Line | Block | Fallback | Fix |
|---|---|---|---|---|
| `services/feature_writer_service.py` | ~217 | `Settings()` → `_env_prefix = ""` | Empty string prefix | Add `logger.warning(...)` |
| `services/feature_writer_service.py` | ~260 | `Settings()` → `_settings = None` | Default config values | Add `logger.warning(...)` |
| `services/signal_generator_service.py` | ~466 | `Settings()` → `_settings = None` | Default config values | Add `logger.warning(...)` |

The block at `signal_generator_service.py:1042` (`insert_signals` failure) re-raises after compensating — it is NOT silent and does not need changing.

The module-level function at `signal_generator_service.py:234` (tick bid/ask parse) returns a safe `{"bid": None, "ask": None}` fallback — intentional parse guard, no log needed.

---

### Task 5: Add logging to silent Settings() fallbacks

**Files:**
- Modify: `services/feature_writer_service.py`
- Modify: `services/signal_generator_service.py`

These are in service `__init__` / `_load_config` — no unit test coverage needed (the behavior doesn't change; we're only adding visibility).

- [ ] **Step 5.1: Fix `feature_writer_service.py` — env_prefix fallback (~line 214)**

Before:
```python
try:
    _s = Settings()
    self._env_prefix: str = f"{_s.env_name}:" if _s.env_name else ""
except Exception:
    self._env_prefix = ""
```

After:
```python
try:
    _s = Settings()
    self._env_prefix: str = f"{_s.env_name}:" if _s.env_name else ""
except Exception as e:
    self.logger.warning("Settings() failed — defaulting env_prefix to empty string", error=str(e))
    self._env_prefix = ""
```

- [ ] **Step 5.2: Fix `feature_writer_service.py` — `_load_config` Settings fallback (~line 258)**

Before:
```python
try:
    _settings = Settings()
except Exception:
    _settings = None
```

After:
```python
try:
    _settings = Settings()
except Exception as e:
    logger.warning("Settings() failed in _load_config — using hardcoded defaults", error=str(e))
    _settings = None
```

Note: `_load_config` is a plain method, not async, called before `self.logger` may be set — use the module-level `logger` (structlog.get_logger(__name__)) if available, otherwise use the instance logger after confirming `self.logger` is set before `_load_config` is called in `__init__`.

- [ ] **Step 5.3: Fix `signal_generator_service.py` — `_load_config` Settings fallback (~line 464)**

Before:
```python
try:
    _settings = Settings()
except Exception:
    _settings = None
```

After:
```python
try:
    _settings = Settings()
except Exception as e:
    logger.warning("Settings() failed in _load_config — using hardcoded defaults", error=str(e))
    _settings = None
```

- [ ] **Step 5.4: Run unit tests to confirm no regressions**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short
```

- [ ] **Step 5.5: Commit**

```bash
git add services/feature_writer_service.py services/signal_generator_service.py
git commit -m "fix(services): add warning logs to silent Settings() exception fallbacks"
```

---

## Chunk 3: Verification

- [ ] **Step 6.1: Full test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```
Expected: all green, count >= 1613

- [ ] **Step 6.2: Lint**

```bash
.venv/bin/ruff check . --fix
```
Expected: no new errors introduced

---

## Future Work (not in this plan)

These are the larger structural refactors identified. Tackle them in a separate milestone phase when there's appetite for higher-risk changes:

1. **`BaseAsyncService` class** — extract 40-65 lines of init boilerplate repeated across all 9 services into `src/core/base_service.py`. Template method pattern: subclasses override `_run_service_loops()`. High maintenance gain, medium risk (requires careful testing of all services).

2. **`PluginExecutor` abstraction** — `indicator_service.py` and `market_analysis_service.py` each implement identical plugin-state-swap-and-run logic (`_plugin_cache`, `_plugin_states`, per-bar lock acquire/release). Extract to `src/core/plugin_execution.py`.

3. **`ConsumerGroupWarmup` utility** — three services implement nearly identical "xrevrange → parse bars → create consumer group" startup sequences. Extract to `src/core/stream_utils.py` with an injectable bar-parser callback.

These are tracked in the project backlog (`ROADMAP.md`) for future milestone planning.
