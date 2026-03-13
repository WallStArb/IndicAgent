---
phase: 28-dashboard-completion
plan: 04
subsystem: api
tags: [fastapi, postgresql, signal_ledger, setup_performance, drill-panel]

# Dependency graph
requires:
  - phase: 27-signal-lifecycle-stream-events
    provides: signal_ledger with outcome/pnl_r/exit_price lifecycle fields
  - phase: 28-dashboard-completion-01
    provides: dashboard drill panel frontend context
provides:
  - GET /api/signals/recent endpoint with paginated signal history
  - Per-signal setup performance context (win_rate, avg_pnl_r from setup_performance JOIN)
  - Aggregate summary block (n_total, n_resolved, n_suppressed, win_rate, avg_pnl_r)
affects:
  - dashboard drill panel (consumes /api/signals/recent for DB-backed signal history)
  - 28-07 (frontend wiring of this endpoint)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Double-query pattern: main paginated query + separate aggregate summary query"
    - "LEFT JOIN setup_performance ON setup_type = signal_type for per-row context annotation"
    - "Optional timeframe filter: $2::text IS NULL OR timeframe = $2"

key-files:
  created: []
  modified:
    - src/api/routes/signals.py
    - tests/unit/api_tests/test_signals_routes.py

key-decisions:
  - "Route placed before /signals/{symbol} to avoid FastAPI path conflict (recent would match as symbol)"
  - "Summary uses separate aggregate query (not computed from returned rows) to cover full history window, not just the limit"
  - "win_rate computed in SQL with CASE expression — wins=1.0, resolved-non-wins=0.0, pending/active=NULL (excluded from AVG)"

patterns-established:
  - "Double-query pattern: fetch paginated rows + fetchrow aggregate summary — reusable for other history endpoints"

requirements-completed: [DASH-03]

# Metrics
duration: 8min
completed: 2026-03-12
---

# Phase 28 Plan 04: GET /api/signals/recent — Signal History with Setup Performance Context Summary

**FastAPI endpoint returning paginated signal_ledger rows annotated with setup_performance win_rate/avg_pnl_r and an aggregate summary block for drill panel DB-backed history**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-12T17:06:07Z
- **Completed:** 2026-03-12T17:14:00Z
- **Tasks:** 2 (TDD: RED + GREEN combined)
- **Files modified:** 2

## Accomplishments
- Added `GET /api/signals/recent` route to `src/api/routes/signals.py` with symbol + optional timeframe filter, default limit 20 (max 100)
- LEFT JOIN to `setup_performance` on `signal_type` annotates each signal with its setup's 30d win_rate and avg_pnl_r (null if fewer than 30 samples — FEED-02 gate by design)
- Separate aggregate summary query computes n_total, n_resolved, n_suppressed, win_rate, avg_pnl_r across the full window (not just the paginated slice)
- 8 new unit tests covering all specified behaviors; all 14 tests (6 existing + 8 new) pass

## Task Commits

Each task was committed atomically:

1. **Tasks 1+2: Route implementation + tests (TDD RED then GREEN)** - `ef812d1` (feat)

**Plan metadata:** (next commit — docs)

_Note: TDD tasks interleaved — tests written first (RED), then route implemented (GREEN), single commit captures final GREEN state_

## Files Created/Modified
- `src/api/routes/signals.py` - Added `get_recent_signals()` route, `_WIN_OUTCOMES` constant; route placed before `get_signals()` to avoid path conflict
- `tests/unit/api_tests/test_signals_routes.py` - Added `TestGetRecentSignals` class (8 tests), `_make_recent_signal_row()`, `_make_summary_row()`, `_make_recent_mock_db()` helpers

## Decisions Made
- Route registered as `/signals/recent` before `/signals/{symbol}` path param route — FastAPI would match "recent" as a symbol value otherwise
- Summary query runs against full `signal_ledger` (no LIMIT) so the summary reflects the true window, not just the page returned
- win_rate uses SQL CASE AVG pattern: wins=1.0, resolved-non-wins=0.0, pending/active=NULL (excluded); result is mathematically correct resolved win rate

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `GET /api/signals/recent` is ready for frontend consumption in 28-07 (drill panel wiring)
- Response schema: `{"signals": [{signal_id, setup_plugin, signal_type, direction, entry_price, stop_loss, confidence, status, outcome, exit_price, pnl_r, computed_at, timeframe, setup_win_rate, setup_avg_pnl_r}], "summary": {n_total, n_resolved, n_suppressed, win_rate, avg_pnl_r}}`

---
*Phase: 28-dashboard-completion*
*Completed: 2026-03-12*
