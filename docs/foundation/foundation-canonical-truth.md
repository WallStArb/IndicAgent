# Canonical Truth Registry

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-05
**Tags:** data-ownership, canonical-source, streams, persistence, writer-agents, kafka

This registry defines which stream/table owns each durable business fact. Any new table, stream, read model, or cache must either appear here or explicitly declare that it is a derived projection.

Core rule: **one canonical writer per durable fact**. Read models may duplicate data for query speed, but they must never become a second source of truth.

## Ownership Table

| Entity | Canonical stream | Canonical table | Canonical writer | Notes |
|---|---|---|---|---|
| Raw provider bars | `{env}.market.bars.raw.{provider}` | None | Provider-specific `Provider` | Provider payloads are immutable protocol translations. |
| Canonical 1m bars | `{env}.market.bars` | `market_data_ohlcv` | `BarWriter` | `ProviderMerger` selects the authoritative stream event; writer persists. |
| Higher-timeframe bars | `{env}.market.bars.htf` | `market_data_ohlcv` | `BarWriter` | HTF bars are computed from canonical 1m bars. |
| Roll events | `{env}.market.events.roll` | `contract_metadata` | `roll-batch` nightly timer (`production/scripts/roll_batch.py`) | Calendar-based roll detection; promotes front-month contract; broadcasts Kafka update events. |
| Full I1-I7 feature record | `{env}.intelligence.journal` | `intelligence_features` | `FeatureWriter` | Canonical per-bar feature persistence unit. |
| Ranked I7 signals | `{env}.intelligence.i7.signals` | `signal_ledger` | `SignalWriter` | Signal writer owns initial ledger rows. |
| Signal lifecycle transitions | lifecycle transition topic from `stream_keys.py` | `signal_ledger` | `LifecycleWriter` | Tracker computes transitions; writer persists status/outcome updates. |
| Signal-affecting lineage | `topic_signal_lineage()` | `signal_lineage` | `LineageWriter` | Canonical audit trail for transforms and swarm `agent_prediction` events. |
| Swarm ledger projection | aggregate adjustment event or lineage-derived projection | `signal_ledger` swarm columns | Writer-owned projection | Derived convenience fields: `adjusted_confidence`, `swarm_multiplier`, `swarm_agent_count`; rebuildable from lineage. |
| Signal performance metrics | signal metrics topic from `stream_keys.py` | `signal_metrics` tables | `SignalMetricsWriter` | Metrics compute may read canonical outcomes; writer persists metrics. |
| Qualitative raw context | `{env}.ctx.*.raw` | `ctx_events` | `ContextWriter` | Raw qualitative facts are append-only. |
| Qualitative context windows | `{env}.ctx.snapshot` | `ctx_snapshots` | `ContextWriter` | Source of truth for event-time validity. |
| Quant-facing context cache | None | `intelligence_features.ctx` | `FeatureWriter` or optional bridge job | Denormalized projection only; not canonical truth. |
| LLM call audit | `{env}.llm.calls` | `llm_calls` | `LLMWriter` | Every call, including failures, is training/audit data. |
| LLM outcomes | `{env}.llm.outcomes` | `llm_calls` outcome columns | `LLMWriter` | Outcome backfill annotates historical call records. |
| Narratives | `{env}.narratives` | `llm_calls` / narrative projection | `LLMWriter` | Narrative text is explanatory, not a production signal unless promoted separately. |
| Shadow transitions | `{env}.intelligence.shadow.transitions` | shadow governance tables | shadow writer/auditor agents | Shadow state is audit/promotion metadata. |

## Projection Rules

- A projection must name its canonical source stream/table.
- A projection may lag or fail without blocking the canonical writer.
- A projection must be rebuildable from canonical sources.
- A projection must not mutate canonical source tables.
- Consumers must tolerate missing projections with graceful degradation.

## Adding A New Canonical Fact

Before adding a new durable fact, document:

| Question | Required answer |
|---|---|
| What is the fact? | Business-level description, not implementation detail. |
| Which stream is canonical? | Topic function from `src/core/stream_keys.py`. |
| Which table is canonical? | Table name, or `None` if stream-only. |
| Which agent writes it? | Exactly one writer/owner. |
| Is it replay-safe? | Explain offset-0/backfill behavior. |
| Is it event-time valid? | Include `valid_from` / `valid_to` if applicable. |
| What are projections? | Caches/read models and their rebuild path. |
