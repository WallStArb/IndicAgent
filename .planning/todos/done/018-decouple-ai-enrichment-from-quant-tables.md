---
created: 2026-05-07T00:00:00.000Z
title: "Decouple AI Enrichment from Quant-Owned Tables (AI-SEP-01)"
area: architecture
priority: 14
tier: refactoring
files:
  - services/alpha_swarm_agent.py
  - services/swarm_ledger_writer_agent.py
  - services/llm_writer_service.py
---

# Decouple AI Enrichment from Quant-Owned Tables (AI-SEP-01)

**Filed:** 2026-05-07
**Priority:** Medium
**Prerequisite:** None — self-contained refactor

## Principle

The AI layer is a pure consumer of intelligence verticals (quant, fundamental, news, etc.).
It reads from any intelligence stream as input but never writes back into infrastructure
owned by those verticals. AI enrichment lives in AI-owned tables, joined at read time.
Quant pipeline must run unaffected if the AI layer is down.

## Current Violations

Two places where AI outputs mutate quant-owned rows:

1. `LlmWriterService` → `UPDATE intelligence_features SET i8 = ...`
   - `intelligence_features` is the quant ML training dataset; AI should not mutate it

2. `SwarmLedgerWriterAgent` → `UPDATE signal_ledger SET adjusted_confidence, swarm_multiplier, swarm_agent_count`
   - `signal_ledger` is the canonical quant signal record; immutable after quant write

## Solution

Create two AI-owned enrichment tables:

```sql
-- AI-owned: swarm consensus per signal
CREATE TABLE signal_ai_enrichment (
    signal_id UUID PRIMARY KEY REFERENCES signal_ledger(signal_id),
    swarm_multiplier FLOAT,
    adjusted_confidence FLOAT,
    swarm_agent_count INT,
    enriched_at TIMESTAMPTZ NOT NULL
);

-- AI-owned: LLM output per feature bar
CREATE TABLE intelligence_ai_enrichment (
    ts TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    tf TEXT NOT NULL,
    i8 JSONB,
    narrative_id UUID,
    enriched_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (ts, symbol, tf)
);
```

Migrate writers:
- `SwarmLedgerWriterAgent` → INSERT/UPSERT `signal_ai_enrichment` (no signal_ledger touch)
- `LlmWriterService` → INSERT/UPSERT `intelligence_ai_enrichment` (no intelligence_features touch)

Update read layer:
- Dashboard signal queries → LEFT JOIN `signal_ai_enrichment` ON `signal_id`
- ML training queries → LEFT JOIN `intelligence_ai_enrichment` ON `(ts, symbol, tf)`
- Enrichment present when AI ran, NULL when it didn't — no structural dependency

## Why This Matters

- **Attribution isolation:** can measure AI overlay alpha independently of quant signals
- **Replay integrity:** quant signal history is never contaminated by AI mutations
- **Graceful degradation:** AI layer down → quant pipeline unaffected, dashboard degrades gracefully
- **Independent scaling:** AI enrichment latency doesn't matter; it's not on the hot path

## Notes

AI enrichment is not latency-sensitive. Joins at query time add negligible overhead
compared to existing TimescaleDB query costs. No hot-path consumers require
swarm_multiplier or i8 collocated on source rows.
