# Test & Doc Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move four misplaced test files to their correct directories, eliminate the `make_ohlcv` copy-paste, and fix the stale directory reference in testing-standards.md.

**Architecture:** Pure structural refactor — zero logic changes. All 383 tests must pass after every task. Extract `make_ohlcv` / `make_ohlcv_from_hl` into a shared `helpers.py` module (not a pytest fixture) to avoid changing test function signatures.

**Tech Stack:** Python, pytest, git mv

---

## Task 1: Move test_enhanced_monitoring.py → tests/unit/core/

**Files:**
- Move: `tests/unit/test_enhanced_monitoring.py` → `tests/unit/core/test_enhanced_monitoring.py`

**Step 1: Move the file**

```bash
git mv tests/unit/test_enhanced_monitoring.py tests/unit/core/test_enhanced_monitoring.py
```

**Step 2: Verify tests still pass**

```bash
.venv/bin/python3 -m pytest tests/unit/core/test_enhanced_monitoring.py -q
```

Expected: all tests in that file pass (should be ~35 or so).

**Step 3: Run full suite to confirm nothing broke**

```bash
.venv/bin/python3 -m pytest tests/ --ignore=tests/integration -q
```

Expected: 383 passed.

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: move test_enhanced_monitoring to tests/unit/core/"
```

---

## Task 2: Move I5 chart pattern tests → tests/unit/intelligence/

The three pattern test files were created at the wrong level. They belong with the other intelligence tests.

**Files:**
- Move: `tests/unit/test_double_top_bottom.py` → `tests/unit/intelligence/test_double_top_bottom.py`
- Move: `tests/unit/test_head_shoulders.py` → `tests/unit/intelligence/test_head_shoulders.py`
- Move: `tests/unit/test_triangle_wedge.py` → `tests/unit/intelligence/test_triangle_wedge.py`

**Step 1: Move the files**

```bash
git mv tests/unit/test_double_top_bottom.py tests/unit/intelligence/test_double_top_bottom.py
git mv tests/unit/test_head_shoulders.py tests/unit/intelligence/test_head_shoulders.py
git mv tests/unit/test_triangle_wedge.py tests/unit/intelligence/test_triangle_wedge.py
```

**Step 2: Run the moved tests**

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_double_top_bottom.py \
  tests/unit/intelligence/test_head_shoulders.py \
  tests/unit/intelligence/test_triangle_wedge.py -q
```

Expected: 35 passed.

**Step 3: Verify no stragglers at root**

```bash
ls tests/unit/*.py
```

Expected: only `__init__.py` (no test files remaining at root).

**Step 4: Run full suite**

```bash
.venv/bin/python3 -m pytest tests/ --ignore=tests/integration -q
```

Expected: 383 passed.

**Step 5: Commit**

```bash
git add -A
git commit -m "refactor: move I5 chart pattern tests to tests/unit/intelligence/"
```

---

## Task 3: Extract shared helpers into tests/unit/intelligence/helpers.py

`make_ohlcv` is defined identically in four files. `make_ohlcv_from_hl` exists in one. Extract both into a shared module.

**Files:**
- Create: `tests/unit/intelligence/helpers.py`
- Modify: `tests/unit/intelligence/test_context_plugins.py` (remove local copy, add import)
- Modify: `tests/unit/intelligence/test_smart_money_plugins.py` (remove both local copies, add import)
- Modify: `tests/unit/intelligence/test_structure_plugins.py` (remove local copy, add import)
- Modify: `tests/unit/intelligence/test_trading_setups.py` (remove local copy, add import)

**Step 1: Create helpers.py**

```python
# tests/unit/intelligence/helpers.py
"""Shared test helpers for intelligence plugin tests."""
from __future__ import annotations

import numpy as np
import pandas as pd


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
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def make_ohlcv_from_hl(
    high: np.ndarray, low: np.ndarray, volume: np.ndarray | None = None
) -> pd.DataFrame:
    """Build OHLCV from explicit high/low arrays (close = midpoint)."""
    close = (high + low) / 2
    open_ = close + np.random.default_rng(0).normal(0, 0.001, len(close)) * close
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    if volume is None:
        volume = np.full(len(close), 1000.0)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})
```

**Step 2: Update test_context_plugins.py**

Remove lines 7–18 (the `make_ohlcv` function definition).
Add this import at the top, after the `import pandas as pd` line:

```python
from tests.unit.intelligence.helpers import make_ohlcv
```

**Step 3: Update test_smart_money_plugins.py**

Remove lines 7–35 (the `make_ohlcv` and `make_ohlcv_from_hl` definitions).
Add this import at the top, after the `import pandas as pd` line:

```python
from tests.unit.intelligence.helpers import make_ohlcv, make_ohlcv_from_hl
```

**Step 4: Update test_structure_plugins.py**

Remove lines 7–18 (the `make_ohlcv` function definition).
Add this import after `import pandas as pd`:

```python
from tests.unit.intelligence.helpers import make_ohlcv
```

**Step 5: Update test_trading_setups.py**

Remove lines 7–18 (the `make_ohlcv` function definition).
Add this import after `import pandas as pd`:

```python
from tests.unit.intelligence.helpers import make_ohlcv
```

**Step 6: Run all affected tests**

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/ -q
```

Expected: all intelligence tests pass.

**Step 7: Run full suite**

```bash
.venv/bin/python3 -m pytest tests/ --ignore=tests/integration -q
```

Expected: 383 passed.

**Step 8: Commit**

```bash
git add tests/unit/intelligence/helpers.py \
  tests/unit/intelligence/test_context_plugins.py \
  tests/unit/intelligence/test_smart_money_plugins.py \
  tests/unit/intelligence/test_structure_plugins.py \
  tests/unit/intelligence/test_trading_setups.py
git commit -m "refactor: extract make_ohlcv into tests/unit/intelligence/helpers.py"
```

---

## Task 4: Fix testing-standards.md and commit design doc

**Files:**
- Modify: `docs/contributing/testing-standards.md`
- Stage: `docs/plans/2026-02-20-test-doc-refactor-design.md`
- Stage: `docs/plans/2026-02-20-test-doc-refactor.md`

**Step 1: Fix the wrong directory reference in testing-standards.md**

Find the block:

```
tests/
├── unit/           # Fast, isolated — no Redis, no DB, no network
│   ├── indicators/ # I1 indicator plugin tests
│   ├── patterns/   # I5 pattern plugin tests
│   └── ...
```

Replace with:

```
tests/
├── unit/           # Fast, isolated — no Redis, no DB, no network
│   ├── core/       # Core infrastructure tests (circuit breaker, state manager, metrics)
│   ├── indicators/ # I1 indicator plugin tests
│   ├── intelligence/ # I1–I8 plugin tests (context, patterns, structure, etc.)
│   └── ...
```

**Step 2: Update test count in testing-standards.md**

Find the line:

```
**Current:** 383 unit tests passing, 0 ruff errors.
```

Verify this is still accurate after all tasks (it should be — no tests are added or removed). If pytest reports a different number, update accordingly.

**Step 3: Run full suite one final time**

```bash
.venv/bin/python3 -m pytest tests/ --ignore=tests/integration -q
```

Expected: 383 passed, 0 errors.

**Step 4: Commit everything**

```bash
git add docs/contributing/testing-standards.md \
  docs/plans/2026-02-20-test-doc-refactor-design.md \
  docs/plans/2026-02-20-test-doc-refactor.md
git commit -m "docs: fix testing-standards.md directory reference + add refactor plan docs"
```

---

## Verification Checklist

- [ ] `tests/unit/*.py` contains only `__init__.py` (no test files at root)
- [ ] `tests/unit/core/test_enhanced_monitoring.py` exists
- [ ] `tests/unit/intelligence/test_double_top_bottom.py` exists
- [ ] `tests/unit/intelligence/test_head_shoulders.py` exists
- [ ] `tests/unit/intelligence/test_triangle_wedge.py` exists
- [ ] `tests/unit/intelligence/helpers.py` exists
- [ ] `make_ohlcv` appears exactly once across all files in `tests/unit/intelligence/`
- [ ] Full suite: 383 passed
