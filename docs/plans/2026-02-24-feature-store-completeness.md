# Feature Store Completeness: I7 and I8 Gaps

**Date:** 2026-02-24
**Status:** Shipped — i7 + i8 JSONB columns added to `intelligence_features`

## Current State

`intelligence_features` stores I1–I6 per bar as tiered JSONB columns:

| Column | Tier | Content |
|--------|------|---------|
| `bar`  | —    | OHLCV bar |
| `i1`   | I1   | 23 technical indicators |
| `i3`   | I3   | Market structure (BOS/CHoCH, swing points) |
| `i4`   | I4   | Context (GARCH, Kalman, regime) |
| `i5`   | I5   | Patterns (FVG, order blocks, etc.) |
| `smc`  | SMC  | Smart money context |
| `i6`   | I6   | Confluence scores |

**I7** → `signal_ledger` (separate table)
**I8** → `narratives:SYMBOL:TF` Redis stream only (ephemeral, not persisted)

## Why This Happened (Organic Growth)

- `signal_ledger` predates `intelligence_features` — it was built first to track trading signals
- When Phase 2 added `intelligence_features` as the unified ML feature store, `signal_ledger` already existed and worked
- I8 persistence was never prioritized — narratives are text, the "what would you do with them?" question was deferred

## Decision: What to Keep Separate

**`signal_ledger` stays as a separate operational table.** It is not just "I7 data" — it is a trading log with:
- Signal lifecycle state machine (`pending → active → exit`)
- Entry price, stop, target
- P&L outcomes for signal performance analysis
- Query pattern: "what's the win rate for TrendFollowing on ES?" — not a feature-store query

**But:** `signal_ledger` only tells you outcomes. It does not tell you "which setups fired on this bar?" from the feature store perspective. That information belongs in `intelligence_features.i7` too.

## Gaps to Fix

### 1. Add `i7 JSONB` to `intelligence_features`

Store **which setups fired and their scores** per bar — not lifecycle/outcomes (those stay in `signal_ledger`). This lets you:
- Query "which bars had TrendFollowing fire with confidence > 0.8?"
- Train ML on "what features preceded high-confidence I7 setups?"
- JOIN `intelligence_features.i7` → `signal_ledger` outcomes for full picture

**Content:** setup names, confluence scores, direction, confidence — same fields as the signal aggregator produces, minus the operational lifecycle columns.

### 2. Add `i8 JSONB` to `intelligence_features`

Store AI narrative per bar. This lets you:
- Show historical narratives on the dashboard without re-running LLM inference
- Analyse narrative quality over time (correlation with signal outcomes)
- Avoid re-inference cost during backfill replay

**Content:** narrative text, model used, generation latency ms, token count, prompt version.

## Schema Change

```sql
ALTER TABLE intelligence_features
    ADD COLUMN i7 JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN i8 JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_intel_features_i7_gin ON intelligence_features USING GIN (i7);
CREATE INDEX IF NOT EXISTS idx_intel_features_i8_gin ON intelligence_features USING GIN (i8);
```

## Writer Changes

- `feature_writer_service.py` — already consumes `intelligence:SYMBOL:TF` stream (IntelligenceEvent). Add `i7`/`i8` fields to `IntelligenceEvent` schema and INSERT SQL.
- `signal_generator_service.py` — currently publishes to `signals:` stream AND writes to `signal_ledger`. Also needs to write `i7` data into the IntelligenceEvent or a separate enrichment event.
- `ai_narrative_service.py` — currently publishes to `narratives:` stream only. Needs to also write `i8` into the IntelligenceEvent or publish an enrichment event.

### Open Question: Enrichment Pattern

Two options for getting I7/I8 into `intelligence_features`:

**Option A: Extend IntelligenceEvent** — add optional `i7`/`i8` fields; signal_generator and ai_narrative publish enriched events back to `intelligence:` stream; feature_writer upserts.

**Option B: Separate enrichment streams** — `intelligence_i7:SYMBOL:TF` and `intelligence_i8:SYMBOL:TF`; feature_writer consumes both and UPSERTs the relevant columns.

Option A is simpler (one stream, one writer) but requires signal_generator and ai_narrative to re-publish to the intelligence stream — which is currently upstream of them. Option B avoids circular stream dependencies but adds complexity.

**Preferred: Option B** — keeps pipeline direction clean (intelligence flows downstream, not back upstream). Feature writer gains two additional consumer groups.
