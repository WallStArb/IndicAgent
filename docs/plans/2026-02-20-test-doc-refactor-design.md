# Test & Doc Refactor Design

**Date:** 2026-02-20
**Status:** Approved
**Scope:** Approach 2 — move misplaced files + extract shared fixture

---

## Problem

Four test files sit at `tests/unit/` root with no subdirectory:

| File | Lines | Should be in |
|------|-------|--------------|
| `test_double_top_bottom.py` | 131 | `tests/unit/intelligence/` |
| `test_head_shoulders.py` | 141 | `tests/unit/intelligence/` |
| `test_triangle_wedge.py` | 152 | `tests/unit/intelligence/` |
| `test_enhanced_monitoring.py` | 499 | `tests/unit/core/` |

Additionally, `make_ohlcv()` is copy-pasted identically into four intelligence test files:
- `test_context_plugins.py`
- `test_smart_money_plugins.py` (plus variant `make_ohlcv_from_hl`)
- `test_structure_plugins.py`
- `test_trading_setups.py`

The chart pattern tests use a variant (`_make_frames` + `_base`) that serves the same purpose.

One doc is stale: `docs/contributing/testing-standards.md` references `tests/unit/patterns/` (a directory that does not exist).

---

## Design

### Tests

**Step 1 — Move `test_enhanced_monitoring.py`**
Move to `tests/unit/core/`. No content changes.

**Step 2 — Move I5 chart pattern tests**
Move `test_double_top_bottom.py`, `test_head_shoulders.py`, `test_triangle_wedge.py` into `tests/unit/intelligence/`. Rename `_make_frames` helpers to `make_frames` for style consistency. No other content changes.

**Step 3 — Extract shared `make_ohlcv` fixture**
Create `tests/unit/intelligence/conftest.py` with a module-scoped `make_ohlcv` pytest fixture. Remove the local `make_ohlcv` copy from each file that defines one. The three chart pattern tests keep their own `make_frames` helper (different signature — takes `high`, `low`, `close` separately) so they don't need the shared fixture.

### Docs

**Step 4 — Fix `testing-standards.md`**
Replace the `tests/unit/patterns/` reference with `tests/unit/intelligence/`. Update test count to match post-refactor total.

---

## What Does Not Change

- Test logic — zero changes to assertions or test data
- Test count — all 383 tests continue to pass
- `tests/conftest.py` — global fixtures stay as-is
- All `docs/plans/` historical files — kept as archive

---

## Success Criteria

1. `pytest tests/ --ignore=tests/integration -q` reports 383 passing
2. No test file at `tests/unit/` root (except `__init__.py` and `__pycache__`)
3. `make_ohlcv` defined exactly once (in `tests/unit/intelligence/conftest.py`)
4. `testing-standards.md` references the correct directory
