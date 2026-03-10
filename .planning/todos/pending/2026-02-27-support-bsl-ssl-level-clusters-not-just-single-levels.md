---
created: 2026-02-27T15:38:24.811Z
title: Support BSL/SSL level clusters, not just single levels
area: general
files:
  - src/intelligence/schemas.py
  - src/intelligence/plugins/
---

## Problem

The schema stores only one BSL and one SSL level. If there's a cluster of liquidity levels nearby, only the most recent is visible — hiding the full picture of liquidity density.

## Solution

Extend the BSL/SSL schema to support a list of levels (e.g., bsl_levels: list[float], ssl_levels: list[float]) with optional metadata (strength, age). Update the SMC plugin to emit clusters. Update downstream consumers (confluence, signals, dashboard) accordingly.
