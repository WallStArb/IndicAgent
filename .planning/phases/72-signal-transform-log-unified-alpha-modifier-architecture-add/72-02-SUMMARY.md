---
phase: 72-signal-transform-log-unified-alpha-modifier-architecture-add
plan: "02"
subsystem: intelligence.swarm
tags: [graduation, validation, pure-functions, tdd]
dependency_graph:
  requires: []
  provides: [src.intelligence.swarm.graduation]
  affects:
    - scripts/validate_skeptic.py (Plan 05 — thin CLI wrapper over this module)
    - services/graduation_compute_agent.py (Plan 09 — imports evaluate_all)
tech_stack:
  added: [scipy.stats.spearmanr, scipy.stats.norm]
  patterns: [pure-function module, Fisher z-transform MDE, temporal walk-forward split]
key_files:
  created:
    - src/intelligence/swarm/graduation.py
    - src/intelligence/swarm/__init__.py
    - tests/unit/test_graduation.py
  modified: []
decisions:
  - "_nan_to_none() inner helper in evaluate_all avoids repeated inline ternary for NaN→None conversion"
  - "compute_segment_power uses Fisher z-transform approximation for MDE — consistent with scipy conventions"
  - "EVAL_WALK_FORWARD_FRACTION used as default arg in compute_walk_forward signature for DRY"
  - "black reformatted compute_walk_forward sort chain to single line — preserved as-is (lint authority)"
metrics:
  duration: "~15 minutes"
  completed: "2026-04-25"
  tasks_completed: 2
  files_created: 3
---

# Phase 72 Plan 02: graduation.py Validation Module Summary

Pure-function graduation validation module with Spearman correlation, calibration decile analysis, CVaR, power analysis, walk-forward split, and value-add Sharpe comparison — single source of truth for both GraduationComputeAgent and validate_skeptic.py CLI.

## What Was Built

`src/intelligence/swarm/graduation.py` — DB-ignorant Renaissance validation module with:

- **10 locked gate/eval constants** with positive multiplier semantics (`GATE_SPEARMAN_RHO = 0.15`, sign-flipped from `validate_skeptic.py`'s `failure_probability` semantics)
- **6 compute functions**: `compute_spearman`, `compute_calibration`, `compute_expected_shortfall`, `compute_segment_power`, `compute_walk_forward`, `compute_value_add`
- **`evaluate_all()` orchestrator** returning all 15 keys of the `GraduationResult` Kafka payload schema with UTC ISO-8601 timestamps ending in `Z`
- **`src/intelligence/swarm/__init__.py`** exposing `graduation` as a submodule

`tests/unit/test_graduation.py` — 11 deterministic unit tests (seeded RNG, no DB, no asyncio):
- Gate constant sign assertion (`GATE_SPEARMAN_RHO == 0.15`)
- Spearman pass/fail/insufficient-N coverage
- CVaR bottom decile gate pass
- Segment power MDE finite/inf boundaries
- Walk-forward 70/30 temporal split
- Value-add Sharpe delta positive
- `evaluate_all` payload schema (all 15 keys, Z-suffix timestamps, 90-day expiry)
- `is_graduated=False` on single gate failure

## TDD Gate Compliance

- **RED commit** `72dfe4da`: `test(72-02)` — 11 tests failing with `ModuleNotFoundError` (graduation.py absent)
- **GREEN commit** `cce2fc89`: `feat(72-02)` — graduation.py implemented; all 11 tests pass

## Deviations from Plan

None — plan executed exactly as written. The `_nan_to_none()` inner helper was added within `evaluate_all` to avoid three repeated inline ternaries (ruff E501 long-line fix); this is cosmetic refactoring with no behavioral change.

## Known Stubs

None. All functions return computed values; no placeholder data.

## Threat Flags

None. This is a pure-function, DB-ignorant, network-ignorant validation module. No new network endpoints, auth paths, or file access patterns introduced.

## Self-Check: PASSED

- graduation.py: FOUND
- __init__.py: FOUND
- test_graduation.py: FOUND
- Commit cce2fc89 (feat): FOUND
- Commit 72dfe4da (test): FOUND
