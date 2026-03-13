---
status: re-testing
phase: 27-signal-lifecycle-stream-events
source: 27-01-SUMMARY.md, 27-02-SUMMARY.md, 27-03-SUMMARY.md, 27-04-SUMMARY.md, 27-05-SUMMARY.md, 27-06-SUMMARY.md, 27-07-SUMMARY.md, 27-08-SUMMARY.md
gap_closure: 27-09-PLAN.md, 27-10-PLAN.md
started: 2026-03-12T21:23:10Z
updated: 2026-03-12T22:00:00Z
---

## Current Test

number: 5
name: SSE Reconnect — Signals Load from DB on Refresh
expected: |
  Refresh the dashboard. Signals should appear immediately — seeded from the DB via fetchActiveSignals() REST call on mount. No waiting for a new live SSE event.
awaiting: user response

## Tests

### 1. Signal Banner Resolved State — Dimming
expected: When a signal resolves (exits with an outcome), the signal banner in the dashboard renders at 50% opacity (dimmed) compared to an active/live signal. If no resolved signals are currently visible, you can check the signal-banner.tsx source or wait for a signal to resolve.
result: skipped
reason: No resolved signals visible in dashboard to observe

### 2. Signal Banner — OutcomeBadge Display
expected: A resolved signal in the signal banner shows an outcome badge label: one of EXPIRED, STOPPED, T1 HIT, T1+T2 HIT, or FULL TARGET. The badge is green for HIT outcomes, red for STOPPED, gray for EXPIRED.
result: issue
reported: "very few ever shown with a resolved badge"
severity: major

### 3. Drill Panel — Shared OutcomeBadge in Recent Signals
expected: In the drill panel's recent signals list (RecentSignalCard), resolved signals display the shared OutcomeBadge with the same outcome label mapping. There is no separate/duplicate badge implementation — the badge style matches what signal-banner shows.
result: issue
reported: "not that I see"
severity: major

### 4. REST API — Timeframe Filter
expected: Calling GET /api/signals/{symbol}?timeframe=5m returns only signals for the 5m timeframe. Calling without ?timeframe returns all timeframes. You can test via: curl "http://localhost:8000/api/signals/SPY?timeframe=5m" and verify the response only contains 5m entries.
result: skipped
reason: Can't test directly

### 5. SSE Reconnect — No Stale Signal Replay
expected: After reconnecting to the SSE stream (refresh dashboard or briefly disconnect), signals that are older than 2× their timeframe (e.g., a 5m signal older than 10 min, a 1h signal older than 2 hours) are NOT replayed. Only fresh/recent signals appear in the snapshot on reconnect.
result: issue
reported: "when we refresh no signals are shown they should load from the db"
severity: blocker

## Summary

total: 5
passed: 0
issues: 3
pending: 0
skipped: 2

## Gaps

- truth: "A resolved signal in the signal banner shows an outcome badge label (EXPIRED, STOPPED, T1 HIT, etc.)"
  status: failed
  reason: "User reported: very few ever shown with a resolved badge"
  severity: major
  test: 2
  root_cause: "SSE snapshot age filter (sse.py lines 209-211) drops terminal events (direction=0) on reconnect because they are older than 2×TF threshold. Terminal events are written once and sit in the stream; by reconnect time they are stale and filtered out, so the dashboard never sets signal.resolved=true. Secondary: timing hazard when new birth signal arrives before terminal event is processed."
  artifacts:
    - path: "src/api/routes/sse.py"
      issue: "Age filter (lines 209-211) does not exempt direction=0 terminal events — they get dropped on reconnect"
    - path: "dashboard/src/hooks/use-market-stream.ts"
      issue: "Lines 580-582: strict signal_id guard no-ops terminal event if new birth signal arrived first"
  missing:
    - "In sse.py snapshot loop: exempt direction=0 entries from _signal_entry_stale check"
    - "In use-market-stream.ts: handle edge case where new birth signal preempts terminal event processing"

- truth: "In the drill panel RecentSignalCard, resolved signals display the shared OutcomeBadge"
  status: failed
  reason: "User reported: not that I see"
  severity: major
  test: 3
  root_cause: "signalsHistory array in use-market-stream.ts is only populated on signal birth (dir !== 0). When terminal event resolves a signal, signalsByTf[tf] is updated but setSignalsHistory is never called — history entries always have resolved=undefined, so RecentSignalCard never renders OutcomeBadge."
  artifacts:
    - path: "dashboard/src/hooks/use-market-stream.ts"
      issue: "Lines 676-680: setSignalsHistory only called on birth, not on resolution — history entries are never updated to resolved:true"
    - path: "dashboard/src/components/drill-panel.tsx"
      issue: "RecentSignalCard checks signal.resolved which is always undefined on history entries"
  missing:
    - "In use-market-stream.ts dir===0 branch: call setSignalsHistory to replace matching entry by signal_id with resolved:true, outcome, exit_price"

- truth: "On dashboard refresh/reconnect, recent signals load from the DB and display immediately"
  status: failed
  reason: "User reported: when we refresh no signals are shown they should load from the db"
  severity: blocker
  test: 5
  root_cause: "Two compounding gaps: (1) _signal_entry_stale() in sse.py snapshot loop uses 2×TF threshold (2min for 1m, 10min for 5m) — virtually all real signals are older than this so nothing replays on reconnect. (2) No REST call on mount in use-market-stream.ts to seed signal state from DB — signals only appear after a new live event fires post-load."
  artifacts:
    - path: "src/api/routes/sse.py"
      issue: "_signal_entry_stale() in snapshot loop (lines 207-211) drops all signals older than 2×TF — shorter than any realistic signal lifetime"
    - path: "dashboard/src/hooks/use-market-stream.ts"
      issue: "No REST fetch for signals on mount — signalsByTf/signal remain null until a new live signal fires"
  missing:
    - "Remove _signal_entry_stale check from snapshot loop in sse.py (count=2 xrevrange is already a recency guard)"
    - "Add fetchActiveSignals() REST call on mount in use-market-stream.ts, calling GET /api/signals/{symbol} for each symbol to seed signalsByTf from DB"
    - "Optionally add ?status=pending,active filter param to /api/signals/{symbol} endpoint"
