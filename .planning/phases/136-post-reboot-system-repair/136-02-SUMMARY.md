---
phase: 136-post-reboot-system-repair
plan: "02"
subsystem: intelligence-pipeline
tags: [fvg-fill, tier-i7, plugin-registry, log-noise]
dependency_graph:
  requires: []
  provides: [fvg-fill-disabled-i7]
  affects: [intelligence-pipeline, shadow-auto-enroll]
tech_stack:
  added: []
  patterns: [tier-membership-comment-removal]
key_files:
  modified:
    - src/intelligence/register_plugins.py
    - tests/unit/intelligence/test_i7_registration.py
    - tests/unit/intelligence/test_plugin_registry.py
decisions:
  - "FVGFill import and registry.register_pattern() retained so plugin remains importable; only TIER_I7 membership removed"
  - "Total plugin count (134) unchanged; only TIER_I7 count drops from 36 to 35"
metrics:
  duration: "5 minutes"
  completed: "2026-06-18"
  tasks_completed: 2
  files_modified: 3
---

# Phase 136 Plan 02: FVGFill TIER_I7 Disable Summary

Removed `fvg_fill_plugin.name` from `TIER_I7` in `register_plugins.py`, eliminating 4,187 circuit-breaker events per boot that were masking real intelligence_pipeline errors. FVGFill import and pattern registration retained for future restoration.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Remove fvg_fill_plugin.name from TIER_I7 | 21c5a3b1 | src/intelligence/register_plugins.py |
| 2 | Update TIER_I7 count assertions in tests | dca95f4a | tests/unit/intelligence/test_i7_registration.py, tests/unit/intelligence/test_plugin_registry.py |

## Verification

- `fvg_fill_plugin.name not in TIER_I7` confirmed (TIER_I7 count: 35)
- Restoration comment present at line 642: `# FVGFill removed: entry-timing defect (see plugin docstring). Restore after at_limit redesign.`
- `registry.register_pattern(fvg_fill_plugin)` retained at line 410 (import stays live)
- Total registry count unchanged at 134 (FVGFill still registered as a pattern object)
- All 523 affected tests pass (0 failures)

## Deviations from Plan

None - plan executed exactly as written.

Note: worktree lacked `.venv` symlink; added `ln -s /home/bg/dev/indicagent/.venv .venv` to satisfy pre-commit hook (this is infrastructure, not a code deviation).

## Self-Check: PASSED

- src/intelligence/register_plugins.py - modified (FVGFill removed from TIER_I7)
- tests/unit/intelligence/test_i7_registration.py - modified (counts updated)
- tests/unit/intelligence/test_plugin_registry.py - modified (count updated)
- Commit 21c5a3b1 - exists
- Commit dca95f4a - exists
