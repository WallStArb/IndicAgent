---
created: 2026-05-03T19:00:00.000Z
title: "Qualitative CTX Schema Foundation (P-CTX-01)"
area: qualitative
priority: 6
tier: infrastructure
files:
  - docs/ideas/qualitative-intelligence-layer.md
  - docs/plans/2026-05-02-unified-intelligence-design.md
  - src/core/stream_keys.py
---

# Qualitative CTX Schema Foundation (P-CTX-01)

**Filed:** 2026-05-03
**Priority:** High — first implementation slice of qualitative layer
**Prerequisite:** Phase 78 shipped (done)

## Problem

IndicAgent's I1-I8 pipeline is entirely OHLCV-derived. Qualitative/fundamental data (earnings, macro events, news sentiment) has no storage, no ingestion path, no integration point. The architecture design is complete but no infrastructure exists.

## Solution

Build the schema and writer skeleton — the substrate all qualitative lanes depend on:

1. **TimescaleDB tables:** `ctx_events` (append-only raw payloads) + `ctx_snapshots` (normalized features with valid_from/valid_to validity ranges)
2. **Kafka topics:** `topic_ctx_snapshot()` in `stream_keys.py` — single consumer topic for all compute agents
3. **CtxWriterAgent:** consumes `topic_ctx_snapshot` → persists to `ctx_events` + `ctx_snapshots`
4. **ctx column migration:** `ALTER TABLE intelligence_features ADD COLUMN ctx JSONB`
5. **AIContextCache update:** `seed_from_db_row()` exposes `ctx` as additive field
6. **Prompt rendering:** `_render_full_features()` renders `ctx` tiers into LLM features

### Schema details (from qualitative-intelligence-layer.md)

- `ctx_events`: event_ts, symbol (NULL for global), event_type, source, payload JSONB
- `ctx_snapshots`: (symbol, event_type, valid_from) PK, valid_to, ctx JSONB
- `ctx` JSONB structure: per-event-type object with schema_version, source, valid_from, computed_at, confidence, stale_after + event-specific fields
- "As-of" join pattern: bar writer resolves active snapshot at insert time

### Independence rules

- Qualitative layer runs independently of quant pipeline
- No bar-driven cadence — events are irregular (quarterly, monthly, intraday)
- Bridge into `intelligence_features.ctx` is optional, not required
- Missing ctx = graceful absence, not stub values

## Context

Architecture: `docs/ideas/qualitative-intelligence-layer.md`
Implementation plan: `docs/plans/2026-05-02-unified-intelligence-design.md` (Phase 1: P-CTX-01)
