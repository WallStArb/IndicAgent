---
created: 2026-03-04T00:00:00.000Z
title: Add roll premium/discount feature to intelligence_features
area: database
files:
  - services/feature_writer_service.py
  - src/providers/ibkr.py
---

## Problem

The spread between front and back month contracts at roll time is the contango/backwardation signal. For CL (oil storage stress) and equity index (dividend/rate expectations) this is a genuinely informative regime feature. Not currently captured anywhere in the pipeline.

## Solution

At roll windows, compute `front_price - back_price` (or normalized as %) and store in `intelligence_features` as `roll_premium_pct`. May require fetching back-month quote from IBKR alongside the front-month bar. Nullable — only populated near roll dates.

Coordinate with the gap-fill service todo and contract roll logic in `src/providers/ibkr.py`.
