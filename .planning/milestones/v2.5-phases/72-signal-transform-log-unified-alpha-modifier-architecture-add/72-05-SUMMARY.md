---
phase: 72-signal-transform-log-unified-alpha-modifier-architecture-add
plan: "05"
subsystem: swarm-graduation
tags: [refactor, cli, graduation, validate-skeptic]
dependency_graph:
  requires: [72-02]
  provides: [thin-cli-wrapper-validate-skeptic]
  affects: [scripts/validate_skeptic.py]
tech_stack:
  added: []
  patterns: [thin-cli-wrapper, delegate-to-library]
key_files:
  modified:
    - scripts/validate_skeptic.py
decisions:
  - "Reuse graduation.py EVAL_WALK_FORWARD_FRACTION constant rather than adding --train-fraction CLI arg"
  - "SELECT predicted_multiplier AS multiplier aligns with graduation.py DataFrame contract (multiplier column)"
  - "json.dumps(evaluate_all(...)) replaces all per-dimension print loops for consistent output format"
metrics:
  duration_minutes: 5
  completed: "2026-04-25"
  tasks_completed: 1
  files_modified: 1
---

# Phase 72 Plan 05: CLI Refactor (validate_skeptic.py) Summary

Rewrote `scripts/validate_skeptic.py` from a 186-line script with inline compute logic into a 138-line thin CLI wrapper that delegates all graduation computation to `src.intelligence.swarm.graduation`.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite validate_skeptic.py as thin CLI wrapper | 7975446a | scripts/validate_skeptic.py |

## What Was Built

Thin CLI wrapper over `graduation.py` that:
- Imports `GATE_SPEARMAN_RHO`, `GATE_CALIBRATION_MAX_ERROR`, `GATE_CVAR_BOTTOM_DECILE`, and `evaluate_all` from `src.intelligence.swarm.graduation`
- Fetches data from `alpha_multiplier_shadow JOIN signal_ledger` with `predicted_multiplier AS multiplier` alias
- Calls `evaluate_all(df, ...)` and prints JSON result
- Exits 0 if `is_graduated`, 1 otherwise

## Deviations from Plan

None - plan executed exactly as written. The original script was 186 lines (not 530 as described in the plan — the plan referenced a planned but not-yet-existing larger version). The refactored file is 138 lines.

## Known Stubs

None.

## Threat Flags

None — this is a CLI script with no network endpoints, auth paths, or schema changes.

## Self-Check: PASSED

- [x] `scripts/validate_skeptic.py` exists and is 138 lines (<150)
- [x] Contains `from src.intelligence.swarm.graduation import`
- [x] Does NOT contain `def compute_spearman` or `def compute_calibration`
- [x] Does NOT contain `GATE_SPEARMAN_RHO = -0.15` (old negative constant)
- [x] `--help` exits 0 and shows `--agent` flag
- [x] `ruff check` exits 0
- [x] `black --check` exits 0
- [x] Commit 7975446a exists
