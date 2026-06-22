---
created: 2026-05-25T09:00:00.000Z
title: Macro & Cross-Asset Intelligence — Wire, Segment, Extend
area: intelligence
priority: 2
files:
  - docs/ideas/intel-08-macro-cross-asset.md
---

## Problem

Macro compute and cross-asset services produce `ftq_score`, `yield_curve_slope`,
`yield_curve_regime`, `ftq_regime`, and `corr_z` — but none of these flow into `I4Context`,
`intelligence_features`, or ML training. Every bar is a wasted training sample. No signal is
gated or weighted by macro regime. The data exists; the wiring doesn't.

## Solution

Full design at `docs/ideas/macro-cross-asset-intelligence-improvements.md`. Prioritized:

**P1 — Wire existing signals (~2-3 days):**
- Join macro fields into `intelligence_features` (labels data against outcomes immediately)
- Add 3 thin I4 plugins: `FTQContext`, `YieldCurveContext`, `CorrZContext` — read pre-computed
  values from `frames["cross_asset"]`, surface into `I4Context`. No computation in plugins.
- Add 5 fields to `I4Context` schema

**P2 — Regime segmentation (~1 day):**
- `setup_performance` win rates segmented by `(yield_curve_regime, ftq_regime)` bucket
- I7 signal gating by macro regime, shadow-only, `n >= 100` before any promotion

**P3 — New enrichment services (~3-4 days, after P1+P2 prove signal):**
- `StockBondCorrelationAgent` — rolling ES vs ZB Pearson correlation + break detection
- VX term structure — contango/backwardation slope + transitions

## Renaissance Rationale

"Segment relentlessly" — a signal that works globally is weaker than one segmented by regime.
"Never drop data that could contain signal" — `ftq_score` exists in DB but is never joined to
outcomes. Fix the labeling first, then let the data speak on whether regime gating helps.

---
**RETIRED 2026-06-22** — v2.x concept (I4Context, intelligence_features, feature_pipeline_executor all archived in v3.0). The underlying need — macro/cross-asset context feeding the model — is addressed by the TF-agnostic feature store design: `.planning/todos/pending/2026-06-22-tf-agnostic-feature-architecture.md`. The specific signals (ftq_score, yield_curve_slope, corr_z) are candidates for `context_features` when Phase B+ implements that table.
