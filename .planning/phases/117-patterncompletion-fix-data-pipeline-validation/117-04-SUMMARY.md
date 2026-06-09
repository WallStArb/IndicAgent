---
phase: 117-patterncompletion-fix-data-pipeline-validation
plan: "04"
subsystem: intelligence-plugin-enforcement
tags: [architecture-enforcement, i7-plugins, pre-commit, testing]
dependency_graph:
  requires: ["117-02", "117-03"]
  provides: ["VAL-04", "VAL-05"]
  affects: ["src/intelligence/plugins/base.py", "src/intelligence/trading/", "tools/pre-commit.hook"]
tech_stack:
  added: []
  patterns: ["ClassVar enforcement", "startup validation", "parametrized pytest sweep", "pre-commit gate"]
key_files:
  created:
    - tests/unit/intelligence/test_i6_confluence_enforcement.py
  modified:
    - src/intelligence/plugins/base.py
    - src/intelligence/trading/*.py (36 files)
    - tools/pre-commit.hook
decisions:
  - "requires_i6_confluence uses plain bool field (not ClassVar) in dataclass implementations, matching existing regime_type pattern"
  - "True for 11 plugins that read ctf_* sub-scores by variable name; False with TODO for 25 others"
  - "No factor-count enforcement - declaration presence only (per Council review)"
metrics:
  duration_minutes: 30
  completed_date: "2026-06-09"
  tasks_completed: 4
  tasks_total: 4
  files_modified: 40
---

# Phase 117 Plan 04: I6 Confluence Enforcement Summary

Three-layer enforcement that every TIER_I7 plugin declares I6 confluence intent via `requires_i6_confluence: bool`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | ArchitectureViolation + requires_i6_confluence ClassVar | 6dfec17a | src/intelligence/plugins/base.py |
| 2 | Backfill requires_i6_confluence on all 36 TIER_I7 plugins | 4a836e3d | src/intelligence/trading/*.py (36 files) |
| 3 | TIER_I7 pytest sweep | 73eb7146 | tests/unit/intelligence/test_i6_confluence_enforcement.py |
| 4 | Pre-commit check 9 + label renumber | efb19d27 | tools/pre-commit.hook |

## What Was Built

**Task 1 - base.py enforcement:**
- `ArchitectureViolation(Exception)` added before `InputSpec` dataclass with docstring clarifying startup-time only, never per-bar
- `requires_i6_confluence: ClassVar[bool]` added to `PatternPlugin` Protocol after `fast_path`
- `validate_tier()` raises `ArchitectureViolation` for any I7 plugin missing the declaration
- No factor-count enforcement (per Council: cargo-cult, easily gamed)

**Task 2 - Backfill:**
- 11 plugins set `requires_i6_confluence = True`: those that read ctf_* sub-scores by variable name (ctf_score, ctf_structure_alignment, ctf_fvg_alignment, etc.)
  - trend_following, mtf_alignment, fvg_fill, choch_reversal, cvd_divergence, divergence_stack, gap_analysis_setup, liquidity_hunt, liquidity_sweep_reclaim, ofi_continuation, supply_demand_setup
- 25 plugins set `requires_i6_confluence = False` with `# TODO(phase-118): integrate I6 confluence`
  - These spread `frames.get("i6")` but never read ctf_* variables, or don't touch i6 at all
- Zero compute logic changes; purely additive class attribute

**Task 3 - Pytest sweep:**
- `test_requires_i6_confluence_declared` parametrized over TIER_I7 (36 params) - asserts hasattr + isinstance(bool)
- `test_validate_tier_raises_no_architecture_violation` - end-to-end startup gate test
- `test_false_values_have_todo_rationale` - confirms True count >= 1 (regression guard)
- 38/38 tests pass

**Task 4 - Pre-commit check 9:**
- `check_i6_confluence_declaration()` modeled exactly on `check_regime_type_declaration()`
- Extended exclusion list: adds `plugin_utils|atr_utils|state_utils|confidence_utils|microstructure_utils|volume_profile_utils|exhaustion_utils|signal_schema|position_sizer|aggregator|lifecycle_transitions`
- Greps `requires_i6_confluence\s*[:=]` on files containing `^class.*Plugin`
- All 8 existing `[N/8]` echo labels renumbered to `[N/9]`
- Wired into run-all block: `check_i6_confluence_declaration || FAILURES=$((FAILURES + 1))`
- Header `Checks:` list updated with item 9

## Verification

All five overall checks pass:
- `.venv/bin/pytest tests/unit/intelligence/test_i6_confluence_enforcement.py -q` — 38 passed
- `.venv/bin/ruff check src/intelligence/plugins/base.py src/intelligence/trading/ tests/unit/intelligence/test_i6_confluence_enforcement.py` — All checks passed
- `bash -n tools/pre-commit.hook` — exits 0
- `grep -c '\[[0-9]/8\]' tools/pre-commit.hook` — 0 (all renumbered)
- `register_all_plugins(); validate_tier(TIER_I7, "I7")` — no ArchitectureViolation

## Deviations from Plan

**[Rule 3 - Pattern] Used plain bool field matching codebase convention**
- Found during: Task 2
- Issue: Plan said "ClassVar[bool]" for implementations, but all 36 existing plugins use plain dataclass fields (`regime_type: str = "trend"`), not ClassVar annotations
- Fix: Added `requires_i6_confluence: bool = True/False` as plain field, matching regime_type convention. The Protocol correctly declares ClassVar; implementations use plain fields. `hasattr()` in validate_tier works for both
- Files modified: All 36 trading plugin files (already captured in Task 2 scope)

## Self-Check: PASSED

Files verified to exist:
- src/intelligence/plugins/base.py - contains ArchitectureViolation, requires_i6_confluence, raise ArchitectureViolation
- tests/unit/intelligence/test_i6_confluence_enforcement.py - 38 tests, all passing
- tools/pre-commit.hook - check_i6_confluence_declaration() defined and wired

Commits verified:
- 6dfec17a (Task 1), 4a836e3d (Task 2), 73eb7146 (Task 3), efb19d27 (Task 4)
