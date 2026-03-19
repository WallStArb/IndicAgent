---
created: 2026-03-19T15:51:25.948Z
title: Fix VWAP plugin timezone error
area: intelligence
files:
  - src/intelligence/i1/vwap.py
---

## Problem

VWAP plugin fails with: `Tz-aware datetime.datetime cannot be converted to datetime64 unless utc=True`

This error recurs on **every bar** for **all 61 symbols**, filling logs with warnings. The root cause is pandas/numpy datetime conversion without the `utc=True` parameter when handling timezone-aware datetime objects.

## Evidence

From `logs/indicator_service.log`:
```
{"plugin": "VWAP", "error": "Tz-aware datetime.datetime cannot be converted to datetime64 unless utc=True", "event": "I1 plugin failed", "level": "warning"}
```

## Solution

Add `utc=True` to any `pd.to_datetime()` or numpy datetime conversion calls in the VWAP plugin. Example:
```python
# Before:
pd.to_datetime(timestamps)

# After:
pd.to_datetime(timestamps, utc=True)
```

## Impact

VWAP is a critical intraday support/resistance indicator. Without it, 61 symbols lack volume-weighted average price anchors, degrading I1 layer signal quality for trend confirmation and S/R zone identification.
