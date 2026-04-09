---
created: 2026-03-22T23:17:49.009Z
updated: 2026-03-28T00:00:00.000Z
title: Fix detect_gaps false positives for market closures
area: tooling
priority: 9
tier: near-term
files:
  - production/scripts/historical_backfill.py:1028-1061
---

## Problem

`detect_gaps()` in the backfill script treats any interval between consecutive bars exceeding the expected bar duration as a gap. It has no awareness of market closures, so overnight windows (e.g. ES 5pm–6pm ET daily maintenance), weekends (Friday 5pm → Sunday 6pm ET), and holidays all get flagged as gaps and trigger unnecessary IBKR `fetch_historical_bars` calls that return no data — wasting pacing budget and slowing backfills.

Flagged by CodeRabbit during post-reboot cleanup session (2026-03-22).

## Solution

Two viable approaches:

1. **Tolerance multiplier (simpler):** Only treat an interval as a gap if `delta > interval * N` where N=3 for intraday TFs (`1m`, `5m`, `15m`, `1h`). Skip gap detection entirely for `1d` bars. Lives entirely in `detect_gaps()`.

2. **Session calendar (robust):** Integrate a trading-hours helper (e.g. `exchange_calendars` or a hand-rolled futures session map) to exclude known non-trading windows before appending a gap. More accurate but adds a dependency.

Start with option 1 (tolerance multiplier) — zero dependencies, handles the common cases. Can graduate to option 2 if false negatives become a problem.
