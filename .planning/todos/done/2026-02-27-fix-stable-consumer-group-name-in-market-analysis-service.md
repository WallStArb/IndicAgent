---
created: 2026-02-27T15:24:58.383Z
title: Fix stable consumer group name in market_analysis_service
area: general
files:
  - services/market_analysis_service.py:84
---

## Problem

`self.consumer_group = f"market_analysis_{int(time.time())}"` creates a new consumer group on every restart, starting from the latest stream ID. Misses any messages buffered during downtime — recovers quickly since bars arrive continuously, but is still incorrect behavior.

## Solution

Use stable name `"market_analysis"` (same pattern as ai_narrative_service). Also use `"0"` for initial start position on group creation (rewind on first start).

Priority: Low — not blocking current operation.
