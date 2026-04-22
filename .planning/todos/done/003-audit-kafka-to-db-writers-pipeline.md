---
created: 2026-04-20
title: Audit Kafka → DB writer pipeline (bar_aggregator, bar_writer, feature_writer, signal_writer)
area: data-pipeline
files:
  - services/bar_aggregator_agent.py
  - services/bar_writer_agent.py
  - services/feature_writer_service.py
  - services/signal_writer_agent.py
  - src/core/bar_accumulator.py
---

## Scope

Audit the middle tier of the data pipeline — from Kafka topics to TimescaleDB persistence. Covers bar aggregation (1m→HTF), bar persistence, intelligence feature persistence, and signal-ledger persistence.

## Areas to review

1. **Batch sizing and backpressure** — how writers batch, what happens on DB slowdown, whether consumer lag surfaces as a metric *and* as a recovery signal (not just a dashboard number)
2. **Idempotency keys** — do writers tolerate at-least-once redelivery without creating duplicate rows? (Expected: unique constraint on `(symbol, ts, tf)` pairs; verify.)
3. **Kafka retention vs DB durability handoff** — retention on `market.bars`, `market.bars.htf`, `intelligence.*` is intentionally minimal; confirm the writer can keep up under worst-case scrape rate without data loss. Current retention tiers: `_HOT_MS=2h`, `_BUFFER_MS=1d`, `_HTF_MS=3d`.
4. **asyncpg timestamp + JSONB handling** — scan for `json.dumps()` around JSONB (wrong), ISO strings for batch inserts to `timestamptz` (wrong — needs `datetime`), naive datetimes.
5. **StreamMerger "Convergence Gate"** — check per the DAG docs; confirm atomic persistence, not best-effort.
6. **HTF emission cadence** — confirm BarAccumulator emits exactly 24× 1h / 6× 4h / 1× 1d per day per symbol, no duplicates across session boundaries.
7. **DLQ paths** — every writer should have `intelligence.<domain>.journal.dlq`; verify topics exist, are monitored, and have a replay mechanism.

## Method

Use Claude Opus 4.7 for structured read-through. Produce a prioritized findings list (HIGH/MEDIUM/LOW) similar to the ingestion-edge audit (see session 2026-04-20).

## Related

- Ingestion-edge audit completed 2026-04-20 (findings surfaced in session log)
- Data-quality loop audit: todo 031
