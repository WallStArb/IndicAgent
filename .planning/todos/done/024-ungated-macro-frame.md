---
created: 2026-06-13T14:25:00.000Z
title: Ungated Macro Frame Fix for Non-EQ_INDEX Symbols
area: intelligence
priority: 2
files:
  - src/intelligence/pipeline/feature_pipeline_executor.py
---

## Problem

The executor gates the creation of `frames["cross_asset"]` on `resolve_eq_index_base(symbol) is not None` in `feature_pipeline_executor.py:205`.
While this is correct for index-specific spreads, it also suppresses global, instrument-agnostic macro factors (ftq_score, ftq_regime, yield_curve_slope, yield_curve_regime) which are merged into the same frame. Consequently, non-EQ_INDEX symbols (e.g. commodities, ETFs, stocks) cannot access macro context.

## Action

Decouple the `cross_asset` frame population:
1. Always populate global macro fields (ftq, yield curve) in `frames["cross_asset"]` for all symbols.
2. Only populate index-specific spread features (e.g. sectors spreads, corr_z) for EQ_INDEX symbols that pass the `resolve_eq_index_base` gate.

## Notes

- This defect was discovered during the Phase 121 Wave 2 investigation of macro data flow.
- Doing so will enable all symbols to benefit from regime-based signal gating.

---
**RETIRED 2026-06-22** — v2.x specific bug in `feature_pipeline_executor.py`, which is archived in v3.0. Underlying need (macro fields available to all symbols) is answered by the TF-agnostic `context_features` design: `.planning/todos/pending/2026-06-22-tf-agnostic-feature-architecture.md`.
