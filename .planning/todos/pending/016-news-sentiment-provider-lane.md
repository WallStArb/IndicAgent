---
created: 2026-05-03T19:00:00.000Z
title: "News Sentiment Provider Lane (P-CTX-05)"
area: qualitative
priority: 9
tier: feature
files:
  - docs/ideas/qualitative-intelligence-layer.md
---

# News Sentiment Provider Lane (P-CTX-05)

**Filed:** 2026-05-03
**Priority:** Low-Medium
**Prerequisite:** P-CTX-04 (todo 015) — proven deterministic context path first

## Problem

News sentiment is the most complex qualitative lane: NLP quality concerns, provider bias, continuous latency, and lower signal-to-noise ratio than earnings or macro events. Should ship last, after the deterministic substrate is proven.

## Solution

1. **NewsProviderAgent** — fetches headlines per instrument via RSS/API
2. **NewsSentimentComputeAgent** — classifies sentiment (bullish/bearish/neutral)
   - Options: OpenRouter → LLM summarization, or pre-computed FinBERT
   - Computes: sentiment_1d, sentiment_7d, event_count_1d, high_impact_flag
3. **Publishes** to `topic_ctx_snapshot()` with event_type='news'
4. **Staleness:** rolling 1h/24h windows — stale after window expires

### Why this ships last

From architecture doc: "Keep news sentiment out of the first slice; it introduces NLP quality, provider bias, and latency concerns that are easier to handle after the substrate is proven."

### Dependency

- News API subscription (AlphaVantage, Polygon, or similar)
- NLP model selection (LLM pipeline vs FinBERT)
- Proven deterministic context path from P-CTX-03/04

## Context

Architecture: `docs/ideas/qualitative-intelligence-layer.md`
Implementation plan: `docs/plans/2026-05-02-unified-intelligence-design.md` (P-CTX-05)

---
**Updated 2026-06-22** — v2.x qualitative lane superseded, but news sentiment is a valid TF-agnostic feature candidate (cadence: intraday/daily NLP scores, no natural bar alignment). Would live in `context_features` and join at IC computation time. Lower priority than earnings/macro — still needs NLP quality validation. Cross-reference: `.planning/todos/pending/2026-06-22-tf-agnostic-feature-architecture.md`.
