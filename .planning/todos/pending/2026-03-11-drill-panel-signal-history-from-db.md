---
created: 2026-03-11T00:00:00.000Z
title: Drill panel RecentSignals — load from DB on open, not just SSE session
area: dashboard
files:
  - dashboard/src/components/drill-panel.tsx
  - src/api/routes/signals.py (new or extend)
---

## Problem

`RecentSignals` in `DrillPanel` is populated from in-memory SSE history (`signalsHistory`) — signals accumulated since the page was loaded. On a fresh page load or after a browser refresh, the list is always empty even if signals fired in the last hour.

## Solution

Add an API endpoint to fetch recent signals from `signal_ledger` for a given symbol + timeframe + lookback window. Call it when DrillPanel opens (mount effect). Merge DB results with live SSE history, deduplicate by `signal_id`.

```
GET /api/signals/recent?symbol=ES&timeframe=1m&limit=10
→ signal_ledger rows ordered by bar_close_ts DESC
```

The in-memory SSE history continues to append new live signals on top.

## Notes

- Endpoint should return same `SignalData` shape used by SSE payload (or a subset)
- Use `signal_id` as dedup key when merging DB + SSE results
- Lookback: 10 bars for the requested TF (same as frontend window) or configurable
- Low priority: the panel is useful in isolation even without this; but it makes the drill panel useless right after a restart
