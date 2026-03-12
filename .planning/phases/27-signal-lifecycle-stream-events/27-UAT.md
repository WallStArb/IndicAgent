---
status: complete
phase: 27-signal-lifecycle-stream-events
source: 27-01-SUMMARY.md, 27-02-SUMMARY.md, 27-03-SUMMARY.md, 27-04-SUMMARY.md, 27-05-SUMMARY.md, 27-06-SUMMARY.md, 27-07-SUMMARY.md, 27-08-SUMMARY.md
started: 2026-03-12T21:23:10Z
updated: 2026-03-12T21:30:00Z
---

## Current Test

[testing complete]

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
  artifacts: []
  missing: []

- truth: "In the drill panel RecentSignalCard, resolved signals display the shared OutcomeBadge"
  status: failed
  reason: "User reported: not that I see"
  severity: major
  test: 3
  artifacts: []
  missing: []

- truth: "On dashboard refresh/reconnect, recent signals load from the DB and display immediately"
  status: failed
  reason: "User reported: when we refresh no signals are shown they should load from the db"
  severity: blocker
  test: 5
  artifacts: []
  missing: []
