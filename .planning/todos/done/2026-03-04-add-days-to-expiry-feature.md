---
created: 2026-03-04T00:00:00.000Z
title: Add days-to-expiry feature to intelligence_features
area: database
files:
  - services/feature_writer_service.py
  - src/config/settings.py
---

## Problem

Contract behavior changes significantly near expiry (liquidity shifts, basis widening, rollover flows). `intelligence_features` has no `days_to_expiry` column, so this signal is unavailable to any ML model trained on the feature store.

## Solution

Compute `(expiry_date - bar_timestamp).days` at write time in `feature_writer_service`. Expiry dates are available from `get_active_contracts()` in `src/config/settings.py` (`Instrument` has the contract expiry).

Add as a nullable integer column to `intelligence_features`. New migration required.
