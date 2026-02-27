---
created: 2026-02-27T15:24:58.383Z
title: Add tooltips to intelligence level indicators
area: ui
files:
  - dashboard/src/components/
---

## Problem

The dashboard displays intelligence tiers (I1–I8) but users have no explanation of what each tier means, what data it represents, or how to interpret the values. This makes the UI opaque to anyone unfamiliar with the pipeline architecture.

## Solution

Add hover tooltips to each intelligence level label/indicator in the dashboard that explain:
- What the tier is (e.g. "I1: Technical Indicators — 23 computed indicators including RSI, MACD, Bollinger Bands")
- What it is used for in the pipeline
- How to interpret the values shown

Consider using a lightweight tooltip component (e.g. Radix UI Tooltip or a simple CSS tooltip) consistent with the existing dashboard UI stack.
