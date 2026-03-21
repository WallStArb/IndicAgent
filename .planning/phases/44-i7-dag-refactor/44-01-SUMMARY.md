---
phase: 44-i7-dag-refactor
plan: 01
subsystem: intelligence
tags: [python, i7, plugin-utils, utilities, tdd]

# Dependency graph
requires:
  - phase: 43-performance-stability-emergency
    provides: stable service baseline before DAG refactor
provides:
  - "src/intelligence/trading/plugin_utils.py — no_signal, extract_ohlcv, default_compute_next, signal_type_for_direction"
  - "src/intelligence/trading/atr_utils.py — get_atr null-guard wrapper (no recomputation)"
  - "src/intelligence/trading/confidence_utils.py — compose_confidence, CONF_FLOOR=0.10, CONF_CEIL=0.95"
  - "src/intelligence/utils/ package — backward-compatible upgrade from utils.py module"
  - "src/intelligence/utils/common.py — is_num, crossover_detect, threshold_cross, track_bars_ago (tier-agnostic)"
affects: [44-02, 44-03, 44-04, all subsequent I7 plugin refactors]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level function utilities (not BasePlugin class) per D-01/D-02"
    - "Single null-guard accessor for I1 ATR — no recomputation in I7"
    - "System-wide confidence clamp via compose_confidence() — no inline min/max in plugins"
    - "Python package upgrade pattern: utils.py → utils/__init__.py with core.py + common.py"

key-files:
  created:
    - src/intelligence/trading/plugin_utils.py
    - src/intelligence/trading/atr_utils.py
    - src/intelligence/trading/confidence_utils.py
    - src/intelligence/utils/__init__.py
    - src/intelligence/utils/core.py
    - src/intelligence/utils/common.py
    - tests/unit/intelligence/test_plugin_utils.py
    - tests/unit/intelligence/test_atr_utils.py
    - tests/unit/intelligence/test_confidence_utils.py
    - tests/unit/intelligence/test_utils_common.py
  modified: []

key-decisions:
  - "utils.py promoted to utils/ package via __init__.py re-exports — all 20+ existing relative imports work unchanged"
  - "utils/common.py uses isinstance-based is_num (not math.isfinite) — identical to composites/common.py per spec"
  - "utils/core.py is verbatim copy of original utils.py — no behavior changes, just location"
  - "compose_confidence clamps to [0.10, 0.95] and rounds to 4 decimal places — system-wide contract enforced at single point"

patterns-established:
  - "D-01/D-02: I7 shared logic lives as module-level functions, not base class inheritance"
  - "D-05/D-07: ATR is consumed from I1, never recomputed — get_atr() is the only accessor"
  - "D-12/D-13: All I7 confidence values pass through compose_confidence() before signal emission"
  - "D-23/D-25: composites/common.py utilities accessible from utils/common.py without breaking I2 imports"

requirements-completed: [DAG-01, DAG-03, DAG-04]

# Metrics
duration: 6min
completed: 2026-03-20
---

# Phase 44 Plan 01: I7 Utility Foundation Summary

**4 new Python modules establishing shared I7 utility foundation: plugin_utils (no_signal/extract_ohlcv/signal_type helpers), atr_utils (ATR null-guard), confidence_utils ([0.10,0.95] system clamp), utils/common.py (tier-agnostic composites); 58 tests all green**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-03-21T01:49:45Z
- **Completed:** 2026-03-21T01:55:46Z
- **Tasks:** 2 of 2
- **Files modified:** 10 created

## Accomplishments

- Created `plugin_utils.py` with 4 functions (no_signal, extract_ohlcv, default_compute_next, signal_type_for_direction) that eliminate copy-paste boilerplate across I7 plugins
- Created `atr_utils.py` with `get_atr()` null-guard that enforces D-07 (no ATR recomputation in I7 — consume I1's atr_14 only)
- Created `confidence_utils.py` with `compose_confidence()` enforcing system-wide [0.10, 0.95] clamp at a single point
- Promoted `composites/common.py` to `utils/common.py` as tier-agnostic module; upgraded `utils.py` to a package with 100% backward-compatible re-exports
- 58 tests across 4 test files, all passing; no regressions in 1569 existing tests

## Task Commits

1. **Task 1: Create plugin_utils, atr_utils, confidence_utils with tests (TDD)** — `54f59eb` (feat)
2. **Task 2: Promote composites/common.py to utils/common.py** — `48a169a` (feat)

## Files Created/Modified

- `src/intelligence/trading/plugin_utils.py` — no_signal, extract_ohlcv, default_compute_next, signal_type_for_direction
- `src/intelligence/trading/atr_utils.py` — get_atr null-guard wrapper (positive-float or None)
- `src/intelligence/trading/confidence_utils.py` — CONF_FLOOR/CONF_CEIL constants + compose_confidence()
- `src/intelligence/utils/__init__.py` — re-exports all legacy utils.py symbols for backward compat
- `src/intelligence/utils/core.py` — verbatim copy of original utils.py content
- `src/intelligence/utils/common.py` — verbatim promotion of composites/common.py with module docstring
- `tests/unit/intelligence/test_plugin_utils.py` — 16 tests (no_signal: 5, extract_ohlcv: 7, default_compute_next: 1, signal_type: 3)
- `tests/unit/intelligence/test_atr_utils.py` — 9 tests covering all null/zero/negative/invalid cases
- `tests/unit/intelligence/test_confidence_utils.py` — 11 tests covering floor/ceil/rounding/boundary
- `tests/unit/intelligence/test_utils_common.py` — 21 tests covering all 4 utility functions + import path

## Decisions Made

- `utils.py` upgraded to `utils/` package using `__init__.py` with re-exports from `core.py` — preserves all 20+ existing relative imports (`from ..utils import X`) without any changes to callers
- `utils/common.py` uses isinstance-based `is_num` (identical to composites/common.py) not the stricter `math.isfinite` version in `utils.py` — this is intentional per plan spec to preserve I2 composite semantics
- `compose_confidence` uses 4-decimal rounding for consistent ML feature representation

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created utils/ package with backward-compatible re-exports**

- **Found during:** Task 2 (utils/common.py creation)
- **Issue:** Creating `src/intelligence/utils/` package directory shadows the existing `src/intelligence/utils.py` module. The existing `test_utils.py` and 4 production files import `find_peaks`, `find_troughs`, `clamp`, `is_num` from `src.intelligence.utils` — these imports would fail with ImportError against an empty `__init__.py`
- **Fix:** Created `utils/core.py` as verbatim copy of original `utils.py`; populated `utils/__init__.py` with explicit re-exports of all public symbols from `core.py`. All 20+ existing relative imports and absolute imports continue to resolve
- **Files modified:** `src/intelligence/utils/__init__.py`, `src/intelligence/utils/core.py`
- **Verification:** `from src.intelligence.utils import find_peaks, find_troughs, is_num, clamp` succeeds; `test_utils.py` passes; all 1569 prior tests still pass
- **Committed in:** `48a169a` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking import issue)
**Impact on plan:** Required for correctness. No scope creep — the deviation was a direct consequence of the planned directory creation.

## Issues Encountered

- Pre-commit hook (`check_plugin_file_naming`) blocked `_core.py` (leading underscore not in allowed pattern). Renamed to `core.py` before commit. Only cosmetic; no behavior change.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 02 can now import from `src.intelligence.trading.plugin_utils`, `atr_utils`, `confidence_utils`, and `src.intelligence.utils.common` for all I7 plugin refactors
- `composites/common.py` is unchanged in this plan — import migration to `utils/common.py` happens in Plan 02 per spec (D-25)
- Zero new dependencies introduced

---
*Phase: 44-i7-dag-refactor*
*Completed: 2026-03-20*
