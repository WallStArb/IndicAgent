---
created: 2026-02-24T20:43:27.820Z
title: Add i8 JSONB column to intelligence_features
area: database
files:
  - production/migrations/009_intelligence_features.sql
  - src/intelligence/schemas.py:370-394
  - services/feature_writer_service.py
  - services/ai_narrative_service.py
---

## Problem

I8 AI narratives are published to `narratives:SYMBOL:TF` Redis stream and go nowhere after that — they are ephemeral. There is no `i8` column in `intelligence_features` and no narratives table. This means:
- Historical narratives cannot be shown on the dashboard (would require re-running Ollama inference)
- Narrative quality cannot be analysed over time or correlated with signal outcomes
- LLM inference cost is wasted on every backfill replay

## Solution

Add `i8 JSONB NOT NULL DEFAULT '{}'` column to `intelligence_features` with a GIN index. Store: narrative text, model used, generation latency ms, token count, prompt version.

Use the **enrichment stream pattern**: `ai_narrative_service` publishes i8 data to `intelligence_i8:SYMBOL:TF` stream in addition to `narratives:SYMBOL:TF`; feature_writer gains a consumer group for this stream and UPSERTs `i8` column.

Implement alongside the i7 column work (same migration, same feature_writer changes).

See full design: `.planning/analysis/2026-02-24-feature-store-completeness.md`
