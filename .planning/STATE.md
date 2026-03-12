---
gsd_state_version: 1.0
milestone: v1.7
milestone_name: Data Integrity
status: Defining requirements
stopped_at: Completed 28-02-PLAN.md (RankedSignal types + scorecardByTf state + signal_scorecard SSE handler)
last_updated: "2026-03-12T21:31:57.346Z"
last_activity: 2026-03-11 — Milestone v1.8 started, requirements defined
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 23
  completed_plans: 13
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-11)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Current focus:** v1.8 Signal Intelligence — defining requirements

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-03-11 — Milestone v1.8 started, requirements defined

Progress: [░░░░░░░░░░] 0% (v1.8)

## Performance Metrics

**Velocity (cumulative):**
- Total plans completed: 85 (v1.0–v1.7)
- Average duration: ~30 min/plan
- Total execution time: ~43 hours

**Recent phases (v1.7):**

| Phase | Plans | Notes |
|-------|-------|-------|
| 25. CIS Data Repair | 2 | Backfill fix + repair script |
| 26. Signal Generator Warmup | 1 | DB seed on startup, graceful fallback |
| Phase 27-signal-lifecycle-stream-events P05 | 1 | 1 tasks | 0 files |
| Phase 27 P01 | 1 | 1 tasks | 0 files |
| Phase 27-signal-lifecycle-stream-events P03 | 3 | 2 tasks | 2 files |
| Phase 27-signal-lifecycle-stream-events P04 | 6 | 2 tasks | 2 files |
| Phase 27-signal-lifecycle-stream-events P06 | 1 | 1 tasks | 0 files |
| Phase 27-signal-lifecycle-stream-events P02 | 3 | 2 tasks | 0 files |
| Phase 27-signal-lifecycle-stream-events P07 | 5 | 1 tasks | 1 files |
| Phase 27-signal-lifecycle-stream-events P08 | 205 | 2 tasks | 3 files |
| Phase 29-renaissance-signal-quality P01 | 4 | 1 tasks | 2 files |
| Phase 28-dashboard-completion P01 | 2 | 2 tasks | 2 files |
| Phase 28-dashboard-completion P04 | 8 | 2 tasks | 2 files |
| Phase 28-dashboard-completion P07 | 2 | 2 tasks | 2 files |
| Phase 28-dashboard-completion P02 | 5 | 2 tasks | 3 files |

## Accumulated Context

### Decisions

- [v1.8 scope]: Phase 27 (Signal Lifecycle Stream Events) — fully designed and planned, execute directly
- [v1.8 scope]: Phase 28 (Dashboard Completion) — design written 2026-03-11; I7 all_ranked scorecard, drill signal history, GARCH/Kalman/SMC gaps, tooltips
- [v1.8 scope]: Phase 29 (Renaissance Signal Quality) — T0-B + T1 (all 5 wire-ins) + T2-A/B (Hurst + Shannon entropy)
- [v1.8 scope]: Phase 30 (Candlestick Expansion) — Tier 1 + Tier 2 (18 new patterns); Tier 3 deferred (gap-dependent, poor futures applicability)
- [Phase 27-signal-lifecycle-stream-events]: NO-OP: SignalData resolved/outcome/exit_price/pnl_r fields already present in types.ts from prior phase work
- [Phase 27]: Plan 27-01: _publish_terminal_event() was already implemented in v1.6 monolith; verified passing with 23 tests
- [Phase 27-03]: SSE snapshot age filter skips signal entries older than 2xTF to prevent stale replay on reconnect; cursor still advances for all entries
- [Phase 27-signal-lifecycle-stream-events]: signals.py timeframe filter was already correctly implemented; plan 27-04 was test-only
- [Phase 27-signal-lifecycle-stream-events]: NO-OP: Resolved event handling (dir=0 with signal_id matching, resolved SignalData construction) already implemented in use-market-stream.ts from prior phase work
- [Phase 27-signal-lifecycle-stream-events]: Plan 27-02: Both terminal event exit path calls (active + shadow) already present in v1.6 monolith; verified passing with 23 tests
- [Phase 27-signal-lifecycle-stream-events]: SignalPanel is a standalone component encapsulating price strip + resolved overlays, enabling reuse outside signal-card
- [Phase 27-signal-lifecycle-stream-events]: signal-panel.tsx is the canonical home for OutcomeBadge — file retained as utility (SignalPanel deleted), single OutcomeBadge export used by both signal-banner and drill-panel
- [Phase 27-signal-lifecycle-stream-events]: signal-panel.tsx is the canonical home for OutcomeBadge — file retained as utility, SignalPanel deleted
- [Phase 27-signal-lifecycle-stream-events]: OutcomeBadge small prop added for compact banner use; signal-banner redesigned to two-line layout based on human verify feedback
- [Phase 29-01]: Bucket methods return (float, dict[str,float]) tuple — public score() signature unchanged; contributions assembled in score()
- [Phase 28-01]: intelligence_i7 startswith check placed before intelligence: to prevent shadowing; intelligence_i7 added to known_domains for env-prefix stripping
- [Phase 28-dashboard-completion]: Route /signals/recent placed before /signals/{symbol} path param to prevent FastAPI matching 'recent' as symbol
- [Phase 28-dashboard-completion]: Summary query runs against full signal_ledger (no LIMIT) so aggregate reflects full window, not just paged slice
- [Phase 28-07]: TierTooltip uses existing CSS-only Tooltip component (no new Radix dep); Section label widened to ReactNode
- [Phase 28-02]: scorecardByTf not added to pipeline_reset handler — current-bar-only, new bars overwrite naturally

### Pending Todos (addressed in v1.8)

- 2026-03-06-dashboard-intelligence-field-gaps.md → Phase 28
- 2026-03-11-drill-panel-signal-history-from-db.md → Phase 28
- 2026-02-27-add-tooltips-to-intelligence-level-indicators.md → Phase 28
- 2026-02-27-add-signal-history-view-to-dashboard.md → Phase 28
- 2026-03-03-expand-i5-candlestickpatterns-and-i7-candlestickpatternsetup.md → Phase 30

### Blockers/Concerns

None blocking v1.8.

## Session Continuity

Last session: 2026-03-12T21:31:57.344Z
Stopped at: Completed 28-02-PLAN.md (RankedSignal types + scorecardByTf state + signal_scorecard SSE handler)
Resume file: None
