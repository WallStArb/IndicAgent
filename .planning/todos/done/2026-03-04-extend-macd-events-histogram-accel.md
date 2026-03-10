---
created: 2026-03-04T00:00:00.000Z
title: Extend MACDEventsPlugin with histogram acceleration outputs
area: intelligence
files:
  - src/intelligence/composites/macd_events.py
  - tests/unit/intelligence/composites/test_macd_events.py
---

## Problem

`MACDEventsPlugin` detects `macd_hist_turning_up` (sign flip) but not histogram acceleration. A shrinking histogram while still positive (`macd_hist_accel < 0` with histogram positive) is an early warning of trend exhaustion — 1-2 bars earlier than the sign flip.

## Solution

Extend `MACDEventsPlugin` with two new outputs (~10 lines):
- `macd_hist_accel`: `hist[t] - hist[t-1]` (float)
- `macd_hist_contracting`: `1` if positive hist is shrinking OR negative hist is expanding toward zero, else `0`

Store `prev_hist` in `_state`. Add to `outputs` set. Update tests.
