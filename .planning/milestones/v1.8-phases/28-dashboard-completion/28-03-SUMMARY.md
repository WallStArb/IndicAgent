---
phase: 28-dashboard-completion
plan: "03"
subsystem: dashboard
tags: [dashboard, signal-scorecard, drill-panel, i7, tsx]
dependency_graph:
  requires: [28-02]
  provides: [signal-scorecard-component, drill-panel-scorecard-section]
  affects: [dashboard/src/components/signal-scorecard.tsx, dashboard/src/components/drill-panel.tsx]
tech_stack:
  added: []
  patterns: [react-client-component, optional-chaining-for-safe-access]
key_files:
  created:
    - dashboard/src/components/signal-scorecard.tsx
  modified:
    - dashboard/src/components/drill-panel.tsx
decisions:
  - "SignalScorecard handles undefined data gracefully (empty state) — no guard required at call site"
  - "Optional chaining data.scorecardByTf?.[timeframe] used in drill-panel for pre-28-02 safety"
  - "Plugin names strip trad_/ind_/smc_ prefixes for compact display"
metrics:
  duration_minutes: 2
  completed_date: "2026-03-12"
  tasks_completed: 2
  files_changed: 2
---

# Phase 28 Plan 03: Signal Scorecard Component Summary

SignalScorecard component displays full I7 signal competition result (winner/suppressed/empty) with suppression reason mapping wired into drill panel below I7 Signal section.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Create signal-scorecard.tsx component | 7dde617 | dashboard/src/components/signal-scorecard.tsx |
| 2 | Wire SignalScorecard into drill-panel.tsx | 398a84c | dashboard/src/components/drill-panel.tsx |

## What Was Built

### signal-scorecard.tsx
- `SignalScorecard` component exported as named export
- Empty state: "No signals this bar" when `data` is undefined or `ranked` is empty
- Summary header: `{fired} fired · {suppressed} regime-gated · winner: {name}`
- Per-signal rows: rank dot (filled ● winner / open ○ others), plugin name (prefix-stripped), direction arrow (▲/▼/–), confidence %, eligibility indicator
- Suppression reason mapping: `regime_prob` → "< 60% conf", `regime_duration` → "< 5 bars", `regime_type` → "wrong regime"; raw string fallback for unknown keys
- Sorted by `composite_rank` ascending (rank 1 = winner at top)

### drill-panel.tsx
- `SignalScorecard` imported from `@/components/signal-scorecard`
- New "Signal Scorecard" section inserted after I7 Signal section
- Uses optional chaining `data.scorecardByTf?.[timeframe]` to handle pre-28-02 data safely

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `dashboard/src/components/signal-scorecard.tsx` exists ✓
- `dashboard/src/components/drill-panel.tsx` modified ✓
- Commits 7dde617 and 398a84c exist ✓
- TypeScript compiles clean (no output from tsc --noEmit) ✓
