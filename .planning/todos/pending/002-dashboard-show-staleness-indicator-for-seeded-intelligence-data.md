---
created: 2026-03-14T23:35:06.299Z
updated: 2026-03-28T00:00:00.000Z
title: Dashboard show staleness indicator for seeded intelligence data
area: ui
priority: 18
tier: feature
files:
  - dashboard/src/components/signal-card.tsx
  - dashboard/src/hooks/use-market-stream.ts
---

## Problem

When a seeded intelligence event carries an original bar `ts` that is potentially hours old (e.g. BTCUSD during IBKR weekend gaps), the dashboard currently renders stale values identically to live values. A trader could see BTCUSD RSI from 27 hours ago with no indication that it is not current. The `ts` field is already present in every SSE event, so the data needed to detect staleness is available.

Note: The original todo referenced `market_analysis_service` as the source of seeded events. That service was retired and merged into `services/feature_compute_agent.py`. The seeding behavior may now live in the intelligence compute pipeline — verify the source before implementing.

## Solution

Pure dashboard rendering change — no service or schema changes needed.

In the signal card or SSE consumer, compute `data_age_seconds = (now - event.ts).total_seconds()`.
When age exceeds a threshold (e.g. 15 minutes), render a visual staleness cue:
- Grey/dimmed indicator values
- Small age badge on the card header (e.g. "27h ago")
- Or a subtle warning icon with tooltip

The existing `fmtLagSeconds` / `fmtTimeHMS` utilities in `dashboard/src/lib/format.ts`
can be extended or reused for the age display.
