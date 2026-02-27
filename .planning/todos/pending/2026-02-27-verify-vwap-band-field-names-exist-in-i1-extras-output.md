---
created: 2026-02-27T15:38:24.811Z
title: Verify VWAP band field names exist in I1 extras output
area: general
files:
  - src/intelligence/plugins/
  - src/intelligence/schemas.py
---

## Problem

VWAP bands (vwap_upper_1/2, vwap_lower_1/2) are expected as I1 extras and would appear in intelligence_features if the VWAP plugin emits them. It's unconfirmed whether these field names actually exist in the I1 extras output.

## Solution

Inspect the VWAP plugin's compute_next() return value and verify the exact field names emitted. Cross-check against I1Indicators schema and any downstream consumers. Fix field names or add them if missing.
