---
created: 2026-05-03T18:00:00.000Z
title: I8 Intelligence Extensions
area: intelligence
priority: 8
tier: feature
files:
  - src/intelligence/ai/narrative/
  - src/intelligence/ai/alpha/
  - docs/ideas/i8-intelligence-extensions.md
---

# I8 Intelligence Extensions

**Filed:** 2026-05-03
**Priority:** Medium
**Trigger:** After Phase 78 (7/7 shipped 2026-05-03)

## Problem

Phase 78 closed the I8 alpha feedback loop. Three natural extensions use the same LLM infrastructure to add distinct intelligence value beyond narrative. Each is a self-contained POC.

## Solution

Three extensions (independent, not sequential):

### 1. Counterfactual Insight Generator
- For every generated signal, produce companion analysis: "What needs to be true to validate/invalidate this setup?"
- Specifies required metric deltas, monitoring triggers, time-bound confirmations
- Output to `intelligence.i8` alongside main narrative
- Dashboard: show inline with signal card, collapsible

### 2. Regime Change Explainer / Daily Brief
- On HMM regime transitions, generate LLM-authored explanation of the shift
- Daily digest at session open: cross-instrument regime summary, overnight developments
- Links symbol-level context to macro narrative (ES shift explained via ZN/VIX)

### 3. Anomaly Triage Assistant
- Ops LLM that reads metrics/logs and explains pipeline anomalies
- Reduces mean-time-to-diagnosis for service failures
- Uses existing LLM chain + OTel observability from Phase 77

## Dependencies

- Phase 78 complete (done)
- Counterfactual: needs `llm_calls` write path (exists)
- Regime explainer: benefits from todo 009/010 (HMM improvements)
- Anomaly triage: needs OTel/Loki metrics (Phase 77 shipped)

## Context

Full design: `docs/ideas/i8-intelligence-extensions.md`

---
**Updated 2026-06-22** — v2.x I8 plugin infrastructure is archived, but the underlying value (qualitative/AI-derived features) is relevant to v3.0 context_features. LLM-scored earnings sentiment, macro regime summaries, and news signals are natural candidates for the TF-agnostic feature store (cadence: daily, joined to `feature_vectors` by date at IC computation time). Revisit after `context_features` table is designed: `.planning/todos/pending/2026-06-22-tf-agnostic-feature-architecture.md`.
