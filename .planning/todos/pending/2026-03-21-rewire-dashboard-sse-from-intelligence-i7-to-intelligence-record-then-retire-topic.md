---
created: 2026-03-21T13:41:54.002Z
title: Rewire dashboard SSE from intelligence.i7 to intelligence.record then retire topic
area: ui
files:
  - src/api/routes/sse.py
  - src/api/main.py
  - dashboard/src/hooks/use-market-stream.ts
---

## Problem

After Phase 44.2, `development.intelligence.i7` is intentional redundancy — the ranked
signal array is published there for dashboard backward compatibility while
`development.intelligence.record` carries the same data as part of `BarIntelligenceRecord`.
Running two topics with the same data is maintenance debt and wastes Redpanda retention.

## Solution

1. Update SSE broadcaster (`src/api/routes/sse.py`, `src/api/main.py`) to consume
   `development.intelligence.record` instead of `development.intelligence.i7`
2. Extract `ranked_signals` array from `BarIntelligenceRecord` payload in the SSE
   event handler — same data, different envelope
3. Update dashboard `use-market-stream.ts` to parse the new payload shape
4. Retire `development.intelligence.i7` Redpanda topic
5. Remove `topic_intelligence_i7` from `stream_keys.py` (or mark deprecated)

**Priority:** Low — UX is not the product, the data is. Do this after Phase 44.x
pipeline is stable and `intelligence.record` has been validated in production.
Do not block pipeline work on this.
