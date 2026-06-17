---
phase: 131-signal-generation-integrity
plan: "01"
subsystem: database
tags: [replay, asset_class, diagnostic, signal-generation, run_historical_pipeline]

# Dependency graph
requires:
  - phase: 130-script-rewriting
    provides: run_historical_pipeline.py as the replay entry point
provides:
  - "Empirical confirmation that asset_class=None universally in replay_symbol() — all symbols affected, not just rolled contracts"
  - "Root cause clarification: instrument_map never built in replay path; live pipeline injects via FeaturePipelineExecutor DI"
  - "A4 CONFIRMED comment in replay_symbol() docstring guiding the 131-03 fix approach"
affects: [131-03-PLAN.md, run_historical_pipeline.py, feature_pipeline_executor.py]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Diagnostic-log-then-confirm pattern: add temporary print(), run targeted replay, capture output, remove log, document finding in docstring"

key-files:
  created: []
  modified:
    - production/scripts/run_historical_pipeline.py

key-decisions:
  - "A4 CONFIRMED: asset_class=None for all symbols in replay_symbol() — affects NQM6, YMM6, ESM6 equally; scope is broader than originally scoped to rolled contracts"
  - "Root cause is missing instrument_map construction in replay path, not rolled-contract lookup failure; fix must build asset_class lookup from DB tables (contract_metadata + instruments), not from Settings/get_active_contracts()"

patterns-established:
  - "Diagnostic comment placement: A4 CONFIRMED note lives in replay_symbol() docstring, not inline — survives code churn, immediately visible to any reader of the function"

requirements-completed:
  - D-06

# Metrics
duration: 15min
completed: 2026-06-17
---

# Phase 131 Plan 01: A4 Root Cause Confirmation Summary

**Empirically confirmed asset_class=None universally in replay_symbol() — root cause is missing instrument_map, not rolled-contract lookup; fix scope widened for plan 131-03**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-06-17T13:15:00Z
- **Completed:** 2026-06-17T13:30:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Added temporary diagnostic `print(f"[A4-DIAG] {symbol}/{tf}: asset_class={all_features.get('asset_class')!r}")` immediately before `run_i7_and_persist()` in `replay_symbol()`
- Ran `--include-rolled --symbols NQM6 --timeframes 1m --days 3` replay: all 3,876 bars show `asset_class=None`
- Ran control with ESM6 (front-month June contract): all bars also show `asset_class=None` — confirming universal scope
- Removed diagnostic log; no `[A4-DIAG]` traces remain in the file
- Added A4 CONFIRMED comment block to `replay_symbol()` docstring with root cause explanation and fix direction

## Key Finding: Scope Wider Than Expected

The original A4 hypothesis framed the issue as specific to rolled/expired contracts. The diagnostic reveals:

- ALL symbols in replay mode have `asset_class=None` — active front-month contracts are equally affected
- Root cause: `feature_pipeline_executor.py` injects `asset_class` via `self._instrument_map.get(symbol)` (line 197, 332), which is populated from `Settings.Instrument` objects injected at live-pipeline startup
- `replay_symbol()` has no equivalent lookup — it never constructs an instrument map and never injects `asset_class` into `all_features`
- This means `trade_framer._min_zone_width_atr()` has been using default thresholds for ALL replay signals, not per-asset-class thresholds

## Task Commits

1. **Task T-01: Diagnostic + confirmation** - `81dd1a0b` (fix)

## Files Created/Modified

- `/home/bg/dev/indicagent/.claude/worktrees/agent-ad89d6ae6105a8fff/production/scripts/run_historical_pipeline.py` - Added then removed diagnostic log; added A4 CONFIRMED comment to `replay_symbol()` docstring

## Decisions Made

- Widened scope documentation: A4 CONFIRMED comment explicitly states "affects ALL symbols in replay mode, not just rolled contracts" so plan 131-03 author has accurate scope
- Fix direction documented in docstring: build `symbol->asset_class` lookup from `contract_metadata + instruments` tables at replay startup (not from `get_active_contracts()` which only returns currently-active contracts and would miss rolled symbols)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `--since` flag does not exist in run_historical_pipeline.py**

- **Found during:** T-01 (initial replay attempt)
- **Issue:** Plan specified `--since 2026-04-01` but that argument is not implemented; script rejected it with "unrecognized arguments: --since"
- **Fix:** Used `--days 3` to limit bar window instead; equivalent for diagnostic purposes
- **Files modified:** None (no code change needed; just used correct CLI arg)
- **Verification:** Replay ran successfully with `--days 3`
- **Committed in:** N/A (no file change)

---

**Total deviations:** 1 auto-noted (wrong CLI arg in plan, corrected in execution)
**Impact on plan:** Zero — diagnostic objective achieved with equivalent approach.

## Issues Encountered

Initial replay attempt with `PGPASSWORD=postgres python -u ...` failed — Python not in PATH in worktree shell. Used full venv path `/home/bg/dev/indicagent/.venv/bin/python` instead. First run also omitted `--include-rolled` so rolled symbols returned "No matching contracts" — added flag on second attempt.

## Next Phase Readiness

- Plan 131-03 (A4 fix implementation) can proceed with confirmed root cause and broader scope
- Fix must query DB for asset_class mapping; cannot rely on Settings/get_active_contracts() which omits expired contracts
- Control experiment shows ESM6 is also affected — if any corpus signals had correct asset_class values, they came through a different code path (live pipeline), not replay

---
*Phase: 131-signal-generation-integrity*
*Completed: 2026-06-17*
