# Canonical Truth Registry

**Version:** 3.0
**Status:** current
**Last Updated:** 2026-06-21
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
| Signal detection (SLA) | `{env}.intelligence.i7.signals` | `signal_events` | `SignalWriter` | Detection layer: one row per I7 plugin fire. Fields: `raw_confidence`, `factor_scores`, `context_features`, `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `status`. |
| Trade hypotheses (SLA) | `{env}.intelligence.i7.signals` | `trade_frames` | `SignalWriter` | Hypothesis layer: one row per `entry_type` per signal. Fields: `entry_type`, `entry_price`, `stop_price`, `target_price`, `counterfactual_pnl_r`, `was_selected`. ML trains on this. |
| Trade executions (SLA) | execution event from `stream_keys.py` | `trade_executions` | `ExecutionWriter` | Execution layer: one row per live trade. Fields: `actual_pnl_r`, `actual_fill_price`, `exit_reason`. |
| Signal lifecycle transitions | lifecycle transition topic from `stream_keys.py` | `signal_events.status` | `LifecycleWriter` | Tracker computes transitions; writer updates status on `signal_events`. Valid transitions: `pending` → `active`, `pending` → `regime_suppressed`, `active` → `expired`. |
| SLA query surface | None | `signal_ledger_full` (view) | — | Join view across all three SLA tables. Canonical read surface for analytics, dashboard, and ML training queries. `signal_ledger` (legacy monolith) is read-only pending drop. |
| Signal-affecting lineage | `topic_signal_lineage()` | `signal_lineage` | `LineageWriter` | Canonical audit trail for transforms and swarm `agent_prediction` events. |
| Signal performance metrics | signal metrics topic from `stream_keys.py` | `signal_metrics` tables | `SignalMetricsWriter` | Metrics compute may read canonical outcomes; writer persists metrics. |
| Qualitative raw context | `{env}.ctx.*.raw` | `ctx_events` | `ContextWriter` | Raw qualitative facts are append-only. |
| Qualitative context windows | `{env}.ctx.snapshot` | `ctx_snapshots` | `ContextWriter` | Source of truth for event-time validity. |
| Quant-facing context cache | None | `intelligence_features.ctx` | `FeatureWriter` or optional bridge job | Denormalized projection only; not canonical truth. |
| LLM call audit | `{env}.llm.calls` | `llm_calls` | `LLMWriter` | Every call, including failures, is training/audit data. |
| LLM outcomes | `{env}.llm.outcomes` | `llm_calls` outcome columns | `LLMWriter` | Outcome backfill annotates historical call records. |
| Narratives | `{env}.narratives` | `llm_calls` / narrative projection | `LLMWriter` | Narrative text is explanatory, not a production signal unless promoted separately. |
| Shadow transitions | `{env}.intelligence.shadow.transitions` | shadow governance tables | shadow writer/auditor agents | Shadow state is audit/promotion metadata. |
| v3.0 feature vectors (per-bar) | `{env}.intelligence.feature_vectors` | `feature_vectors` | `FeatureWriter` | 54-scalar typed feature primitives per bar. No JSONB — all columns. IC Engine reads this; never writes to it. |
| v3.0 regime labels (per bar) | None (batch UPDATE) | `feature_vectors.regime` | `RegimeWriter` | HMM Viterbi per-(symbol,tf) sequence; UPDATEs `feature_vectors.regime` and `regime_label_source`. Single canonical writer — IC Engine reads but never writes regime. |
| v3.0 outcome labels (forward returns) | None (batch INSERT) | `forward_returns` | `ForwardReturnWriter` | Causal LEAD()-based log returns `ln(open[T+N+1]/open[T+1])` at 1/5/20/60 bar horizons. IC Engine reads; never writes. Immutable after insert — no updates. |
| v3.0 IC scores (per feature×symbol×tf×regime×lookahead) | None (batch INSERT) | `feature_ic_scores` | `ICEngine` | Spearman IC + bootstrap CI + BH-FDR + walk-forward results. `AlphaDecayMonitor` (Phase 139) writes `is_decaying` flag only — ICEngine owns all other columns. |
| v3.0 IC discovery report | None (file write) | `docs/analysis/ic-discovery-report-{date}.md` | `ICEngine` | Markdown report of features passing FDR + walk-forward gates by regime and TF. Written at end of each IC Engine run. Not a DB table — filesystem artifact. |

<!-- src: signal_events table, trade_frames table, trade_executions table, signal_ledger_full view — verified 2026-06-16 -->
<!-- v3.0 rows added 2026-06-21: feature_vectors, regime labels, forward_returns, feature_ic_scores, IC discovery report -->

## Signal Ledger Architecture (SLA) Note

The SLA replaced the legacy `signal_ledger` monolith beginning Phase 128. The three-table design separates concerns that the monolith conflated:

- **`signal_events`** — detection layer: did the pattern fire?
- **`trade_frames`** — hypothesis layer: what trade was proposed? (ML training target via `counterfactual_pnl_r`)
- **`trade_executions`** — execution layer: what was actually traded?

**Query surface:** use `signal_ledger_full` (join view) for all reads spanning multiple layers. The legacy `signal_ledger` table is read-only; do not write to it. It will be dropped in a future phase once all consumers migrate to `signal_ledger_full`.

**See also:** `docs/foundation/glossary.md` — SLA, ECL, ICC entries.

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
