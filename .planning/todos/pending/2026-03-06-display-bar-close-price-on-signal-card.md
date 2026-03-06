---
created: 2026-03-06T21:29:41.323Z
title: Display bar close price on signal card
area: ui
files:
  - dashboard/src/components/landing/signal-card.tsx:125-134
  - dashboard/src/components/signal-panel.tsx:82-100
  - dashboard/src/lib/types.ts:209
  - dashboard/src/hooks/use-market-stream.ts:560
---

## Problem

The signal card currently shows `entry_price` (the trade setup's entry zone) but never shows `bar_close_price` — the actual market price at the moment the triggering bar closed. This context matters: you need to see what price the intelligence was based on, not just the setup levels.

`bar_close_price` is already fully available:
- Published to Redis stream in `signal_generator_service.py` (line 671: `message["bar_close_price"] = str(float(bar.get("close", 0)))`)
- Typed as `bar_close_price?: number` in `SignalData` (types.ts:209)
- Parsed in `use-market-stream.ts` (line 560)

It is just not rendered anywhere on either the signal-panel or signal-card components.

Also: replace the staleness ratio (`N.N× stale`) and relative age (`5m ago`) with exact timestamps. The current display shows `bar HH:MM:SS → calc HH:MM:SS` which is good, but the outer timestamp row still shows relative age. Show exact timestamps throughout instead of derived/relative values.

## Solution

In `signal-panel.tsx` and `signal-card.tsx`:
1. Add `bar_close_price` display next to the `bar_close_ts` timestamp (e.g. `16:00:00 @ 6750.00`)
2. Remove staleness ratio row — it's a derived multiple, not a direct data point
3. Replace relative age (`5m ago`) with the exact `signal_computed_at` time or `bar_close_ts` where `signal_computed_at` is unavailable
