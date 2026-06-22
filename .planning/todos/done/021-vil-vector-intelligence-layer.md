---
created: 2026-06-13T00:00:00Z
title: Implement VIL Vector Intelligence Layer
area: general
files:
  - docs/ideas/vil-01-vector-intelligence-layer.md
  - docs/ideas/vil-02-predictive-feature-intelligence.md
  - docs/ideas/vil-03-scoring-engine.md
  - docs/ideas/vil-04-correlation-intelligence.md
  - docs/ideas/vil-05-signal-combiner.md
  - docs/ideas/vil-06-platform-ideas.md
---

## Problem

The VIL (Vector Intelligence Layer) design exists as 6 idea docs but has never been implemented or added to the roadmap. It represents a significant capability upgrade: cross-signal correlation, predictive feature scoring, and a unified signal combiner that sits above I7. Currently, signals are evaluated independently -- there is no layer that reasons about inter-signal relationships or computes a vectorized view of the full feature space.

## Solution

Defer until signals and features are stable and well-calibrated (post v2.9 Signal Quality Renaissance). Once the feature vector is trusted and signals are earning promotion through shadow governance, revisit the VIL docs (`vil-01` through `vil-06`) and plan a milestone. The scoring engine (vil-03) and correlation intelligence (vil-04) are likely the highest-value starting points. Treat as a Layer 5 above the existing I1-I7 stack.

---
**RETIRED 2026-06-22** — AlphaEngine (Phase 138) is the v3.0 answer to VIL. The IC ensemble with Ledoit-Wolf effective-N adjustment handles cross-feature correlation; IC Sharpe weighting is the scoring engine; FDR + walk-forward is the gate. VIL's 6 idea docs (vil-01 through vil-06) are superseded by the IC methodology spec at `docs/plans/2026-06-20-alphaengine-ic-spec.md`.
