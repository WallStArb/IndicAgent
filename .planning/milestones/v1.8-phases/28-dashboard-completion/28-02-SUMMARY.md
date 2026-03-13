---
phase: 28-dashboard-completion
plan: "02"
subsystem: dashboard
tags: [types, sse, signal-scorecard, ranked-signals, state-management]
dependency_graph:
  requires: [28-01]
  provides: [RankedSignal, SignalScorecardData, scorecardByTf state]
  affects: [28-03-PLAN.md, signal-scorecard.tsx component]
tech_stack:
  added: []
  patterns: [SSE event listener pattern, scorecardByTf keyed by timeframe]
key_files:
  created: []
  modified:
    - dashboard/src/lib/types.ts
    - dashboard/src/hooks/use-market-stream.ts
    - dashboard/src/hooks/use-demo-data.ts
decisions:
  - "scorecardByTf not added to system_event pipeline_reset handler — scorecard is current-bar-only, new bars naturally overwrite"
  - "use-demo-data.ts scorecardByTf fix applied as Rule 3 auto-fix (blocking TypeScript compilation)"
metrics:
  duration: "5 min"
  completed_date: "2026-03-12"
  tasks_completed: 2
  files_modified: 3
---

# Phase 28 Plan 02: Signal Scorecard Types and SSE Handler Summary

**One-liner:** Typed RankedSignal/SignalScorecardData interfaces + scorecardByTf state slot wired to signal_scorecard SSE event in use-market-stream.ts.

## What Was Built

- `RankedSignal` interface with 10 fields (setup_type, confidence, direction, regime_eligible, suppression_reason, entry, stop, target, composite_rank, is_winner)
- `SignalScorecardData` interface (ts, symbol, tf, ranked array)
- `SymbolData.scorecardByTf: Record<string, SignalScorecardData>` — per-TF indexed, consistent with intelligenceByTf pattern
- `signal_scorecard` SSE event listener: parses `payload.data` via `JSON.parse` into `RankedSignal[]`, builds `SignalScorecardData`, and updates `scorecardByTf[tf]` for the matching symbol via `setSymbolData` updater

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed use-demo-data.ts missing scorecardByTf**

- **Found during:** Task 2 TypeScript verification
- **Issue:** Adding `scorecardByTf` as required field on `SymbolData` caused TS2741 errors in `use-demo-data.ts` (two SymbolData object literals lacked the field)
- **Fix:** Added `scorecardByTf: {}` to both the `initial[sym]` object (line ~386) and `next[sym]` object (line ~463) in use-demo-data.ts, using `prev[sym]?.scorecardByTf ?? {}` for the tick simulation path to preserve existing state
- **Files modified:** `dashboard/src/hooks/use-demo-data.ts`
- **Commit:** 1c804b3

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 9e36f4e | feat(28-02): add RankedSignal, SignalScorecardData types and scorecardByTf to SymbolData |
| Task 2 | 1c804b3 | feat(28-02): wire signal_scorecard SSE handler and scorecardByTf state |

## Self-Check: PASSED
