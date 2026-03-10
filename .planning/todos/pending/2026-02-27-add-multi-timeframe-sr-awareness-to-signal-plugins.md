---
created: 2026-02-27T15:38:24.811Z
title: Add multi-timeframe S/R awareness to signal plugins
area: general
files:
  - src/intelligence/plugins/
  - src/intelligence/schemas.py
---

## Problem

Signal plugins only use the current timeframe's nearest resistance/support. A 1m signal has no awareness of a 1h S/R cluster above — this leads to signals firing into higher-TF resistance without flagging it as a risk.

## Solution

Design a mechanism to pass higher-TF S/R levels into lower-TF signal evaluation. Options: (1) include HTF S/R in the IntelligenceEvent schema; (2) have signal plugins read from the 1h/4h intelligence stream directly. Evaluate feasibility and pipeline cost before implementing.
