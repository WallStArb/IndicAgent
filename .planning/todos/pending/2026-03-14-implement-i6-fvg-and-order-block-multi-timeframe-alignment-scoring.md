---
created: 2026-03-14T19:11:04.042Z
title: Implement i6 FVG and Order Block multi-timeframe alignment scoring
area: intelligence
files:
  - src/intelligence/confluence/cross_timeframe.py
---

## Problem

`i6_fvg_tf_alignment` and `i6_ob_tf_alignment` in `CrossTimeframeConfluence` are scaffolded as `0.0` placeholders with TODOs. They were intentionally deferred during the intelligence palette expansion (Phase 7 of `docs/plans/2026-03-01-intelligence-palette-expansion.md`).

These fields are output by the I6 confluence layer but carry no signal weight — any downstream consumer (signal scoring, aggregator, dashboard) that references them gets a constant zero.

## Solution

Implement real multi-timeframe alignment scoring for both fields in `cross_timeframe.py`:

- `i6_fvg_tf_alignment`: score alignment of active FVGs across timeframes (1m/5m/15m/1h) — same-direction FVGs on multiple TFs = higher confluence
- `i6_ob_tf_alignment`: score alignment of active Order Blocks across timeframes — stacked OBs = stronger zone

Pattern: follow the existing `_score_smc()` recency-weighted approach. Input data comes from the SMC tier already in the intelligence event (`i6.smc` JSONB fields: `fvg_*`, `ob_*`).
