# Qualitative Intelligence Layer — Architecture Design

**Version:** 1.0
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-02
**Tags:** qualitative, macro, sentiment, earnings, cot, feature-store, ai-context, intelligence

---

## Problem Statement

IndicAgent's intelligence pipeline (I1–I8) is entirely derived from OHLCV price/volume data. This is the right foundation — price is the ultimate arbiter. But systematic edges also exist in non-price information: earnings surprises, macro regime shifts (FOMC, CPI, NFP), futures term structure, COT positioning, and eventually news sentiment. Renaissance famously ingests everything measurable. We should too.

The question is not *whether* to add qualitative data, but *how* to add it without contaminating the bar-driven pipeline or creating manual maintenance burden.

---

## Core Design Constraints

1. **Qualitative data is NOT bar-driven.** Earnings are quarterly. FOMC is 8×/year. News is continuous but irregular. These must NOT block or slow the 1m bar pipeline.
2. **The feature store is the universal integration point.** Every downstream consumer (LLM prompts, ML models, signal generators) reads from `intelligence_features`. Qualitative data must land there — not in a parallel system that requires custom wiring per consumer.
3. **Symbol-keyed, not bar-keyed.** Qualitative events are indexed by `(symbol, event_timestamp)`. They are joined to bar rows at write time using an "as-of" pattern: the latest qualitative snapshot effective at bar close.
4. **Shared hot/warm/cold storage is good architecture here.** TimescaleDB already holds the warm/cold store for signals; qualitative tables can live in the same storage tier without coupling the service runtimes. One backup and retention policy, multiple independently running agents.
5. **New Kafka topics, same broker (Redpanda).** Symbol-keyed topics with appropriate retention. NOT bar-keyed composite keys.
6. **Reuse the existing AI context contract.** The current `AIContext` / `AIContextCache` path already renders open-ended tier data. Qualitative context should extend that shape, not introduce a second prompt contract.
7. **No hard dependency on quant services.** The qualitative layer must ingest, normalize, persist, and serve its own data even if the quant pipeline is offline.

---

## Data Architecture

### Scope Separation

Keep the layer split into three independent concerns:

1. **Raw events** - immutable source payloads.
2. **Normalized context windows** - event-specific features with validity ranges.
3. **Consumption** - feature-store join and prompt rendering.

That split keeps provider cadence, backfill logic, and prompt rendering decoupled while still allowing a shared storage fabric.

### Independence Rule

The qualitative layer is a peer, not a plugin inside the quant stack.

- It must run if `IntelligencePipelineComputeAgent` is down.
- It must continue if feature writers are paused.
- It must expose its own read path for downstream consumers.
- Any integration into `intelligence_features` must be additive and optional, not a prerequisite for the qualitative pipeline itself.
- Shared storage is fine; shared runtime dependencies are not.

### New TimescaleDB Tables

```sql
-- Raw qualitative events (append-only, never mutated)
CREATE TABLE ctx_events (
    event_ts     TIMESTAMPTZ NOT NULL,
    symbol       TEXT,                -- NULL for global events (FOMC, CPI)
    event_type   TEXT NOT NULL,       -- 'earnings', 'fomc', 'cpi', 'nfp', 'news_sentiment'
    source       TEXT NOT NULL,       -- 'ibkr_fundamental', 'openrouter_news', 'manual'
    payload      JSONB NOT NULL,
    ingested_at  TIMESTAMPTZ DEFAULT NOW()
);
SELECT create_hypertable('ctx_events', 'event_ts');
CREATE INDEX ON ctx_events (symbol, event_type, event_ts DESC);

-- Processed qualitative context windows (valid_from / valid_to = "as-of" range)
-- One row per (symbol, event_type, valid_from). valid_to = next event of same type, or NULL (open).
CREATE TABLE ctx_snapshots (
    symbol       TEXT,                -- NULL for global events
    event_type   TEXT NOT NULL,
    valid_from   TIMESTAMPTZ NOT NULL,
    valid_to     TIMESTAMPTZ,         -- NULL = still current
    ctx          JSONB NOT NULL,      -- normalized features for this event window
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, event_type, valid_from)
);
CREATE INDEX ON ctx_snapshots (symbol, valid_from, valid_to);
```

### New Column in `intelligence_features`

```sql
-- Qualitative context snapshot at bar close time (as-of JOIN written by feature_writer).
-- Populated per symbol from ctx_snapshots. NULL when no qualitative data exists yet.
ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS ctx JSONB;
```

Structure of `ctx` JSONB:
```json
{
  "earnings": {
    "schema_version": "1.0",
    "source": "ibkr_fundamental",
    "valid_from": "2026-05-02T14:00:00Z",
    "computed_at": "2026-05-02T14:01:00Z",
    "confidence": 0.92,
    "stale_after": "2026-08-02T14:00:00Z",
    "days_to_next": 42,
    "last_surprise_pct": 8.3,
    "last_direction": 1,
    "consensus_eps": 5.21,
    "surprise_zscore": 1.8
  },
  "macro": {
    "schema_version": "1.0",
    "source": "economic_calendar",
    "valid_from": "2026-05-02T14:00:00Z",
    "computed_at": "2026-05-02T14:01:00Z",
    "confidence": 0.95,
    "stale_after": "2026-05-14T18:00:00Z",
    "fomc_days_away": 12,
    "cpi_days_away": 3,
    "current_regime": "hiking",
    "vix_term_structure_slope": -0.4
  },
  "news": {
    "schema_version": "1.0",
    "source": "finbert_news",
    "valid_from": "2026-05-02T14:00:00Z",
    "computed_at": "2026-05-02T14:01:00Z",
    "confidence": 0.71,
    "stale_after": "2026-05-02T15:00:00Z",
    "sentiment_1d": 0.62,
    "sentiment_7d": 0.54,
    "event_count_1d": 14,
    "high_impact_flag": false
  }
}
```

Required metadata per `ctx.<event_type>` object:

| Field | Purpose |
|---|---|
| `schema_version` | Allows each context lane to evolve independently. |
| `source` | Identifies the upstream provider or compute model. |
| `valid_from` | Event-time start of the context window. |
| `computed_at` | Processing-time timestamp for latency and audit. |
| `confidence` | Provider/model confidence, normalized 0.0-1.0. |
| `stale_after` | Time after which consumers should treat the context as stale or absent. |

Consumers must treat missing `ctx`, missing event types, or stale event types as graceful absence. They must not synthesize neutral stub values that look like observed data.

---

## Kafka Topic Design

All topics via `stream_keys.py`, dots not colons, `{env}` prefix.

| Topic function | Topic string | Key | Retention | Producer |
|---|---|---|---|---|
| `topic_ctx_earnings_raw` | `{env}.ctx.earnings.raw` | symbol | 2 years | EarningsProviderAgent |
| `topic_ctx_macro_raw` | `{env}.ctx.macro.raw` | "global" | 2 years | MacroEventProviderAgent |
| `topic_ctx_news_raw` | `{env}.ctx.news.raw` | symbol | 7 days | NewsProviderAgent |
| `topic_ctx_earnings` | `{env}.ctx.earnings` | symbol | 90 days | EarningsComputeAgent |
| `topic_ctx_macro` | `{env}.ctx.macro` | "global" | 90 days | MacroEventComputeAgent |
| `topic_ctx_snapshot` | `{env}.ctx.snapshot` | symbol or "global" | 90 days | any Ctx ComputeAgent |

`topic_ctx_snapshot` is the single consumer topic for `CtxWriterAgent` — all compute agents publish their normalized snapshot here, and the writer persists to `ctx_events` / `ctx_snapshots`.

`CtxWriterAgent` must not directly update `intelligence_features.ctx`. Any mirror into the quant feature store belongs to either:

- `FeatureWriterAgent` resolving context during the original bar insert, or
- a separate optional bridge/backfill job that can lag or fail without impacting qualitative ingestion.

---

## Service DAG Integration

```
New services slot into the existing DAG at L1 and L5:

L1  earnings-provider, macro-event-provider, news-provider
      — external data ingestion, no compute, publishes raw events
      — NOTE: macro-compute already exists at L5; this is a separate raw-ingest layer
L5  earnings-compute, news-sentiment-compute
      — normalize raw events → ctx snapshot; parallel to intelligence-pipeline
L6  ctx-writer
      — consumes topic_ctx_snapshot → writes ctx_events + ctx_snapshots
      — owns the qualitative persistence path end-to-end
      — any bridge into `intelligence_features` must be optional and non-blocking
```

`ctx-writer` is a new L6 WriterAgent, parallel to `feature-writer`. It maintains the canonical history in `ctx_snapshots` and can serve qualitative consumers directly. A separate bridge, if enabled, may mirror resolved context into `intelligence_features.ctx`, but that bridge must never be required for the qualitative layer to function.

**DAG order:** `indicagent-ctx-writer: 6` (same layer as feature-writer, lifecycle-writer, etc.)

---

## Integration with `full_features` / LLM Prompts

No cross-layer hard dependency required after initial setup. Because:

1. Qualitative consumers can read directly from `ctx_snapshots` or a domain-specific context view.
2. Quant-facing consumers may optionally read `ctx` from `intelligence_features` when the bridge is available.
3. `AIContextCache.seed_from_db_row()` can expose `ctx` as an additive field without making the qualitative layer depend on the quant layer.
4. `_render_full_features()` can render `ctx` automatically for any consumer that already reads the unified context shape.

```
FULL FEATURE VECTOR:
## bar
- close: 5312.2500
...
## cross_asset
- corr_z: -2.1400
- es_nq_spread_z: 1.8300
...
## ctx
### earnings
- days_to_next: 42
- last_surprise_pct: 8.3000
### macro
- fomc_days_away: 12
- cpi_days_away: 3
...
```

---

## "As-Of" Join Pattern

When `ctx-writer` receives a new snapshot for symbol `ESM6`, it:
1. Inserts a row to `ctx_snapshots` with `valid_from = NOW()`.
2. Closes the previous row: `UPDATE ctx_snapshots SET valid_to = NOW() WHERE symbol = 'ESM6' AND valid_to IS NULL`.
3. Leaves existing bar rows unchanged.

The bar writer resolves the active snapshot at insert time:

```sql
SELECT jsonb_object_agg(event_type, ctx ORDER BY event_type)
FROM ctx_snapshots
WHERE (symbol = $symbol OR symbol IS NULL)
  AND valid_from <= $bar_ts
  AND (valid_to IS NULL OR valid_to > $bar_ts)
```
Then a bridge job, if enabled, can write the resolved JSONB into `intelligence_features.ctx`.

For backfills or recomputation, the same lookup is performed against historical `bar_ts` values:
```sql
INSERT INTO intelligence_features (..., ctx) VALUES (
    ...,
    (
      SELECT jsonb_object_agg(event_type, ctx ORDER BY event_type)
      FROM ctx_snapshots
      WHERE (symbol = $symbol OR symbol IS NULL)
        AND valid_from <= $bar_ts
        AND (valid_to IS NULL OR valid_to > $bar_ts)
    )
)
```

This is a LEFT JOIN — if no ctx snapshot exists, `ctx` is NULL. The LLM prompt renders it as `(no features available)` for that tier. No crash, no stub, graceful absence. If the quant bridge is down, the qualitative pipeline still runs and serves its own consumers.

## Refinement Notes

- Avoid a second “world view” schema unless it has a distinct owner and consumer set. `AIContext` already exists as the prompt-facing contract.
- Prefer event-time validity over “latest row” mutation. It is safer for backtests and avoids hidden lookahead bias.
- Keep macro, earnings, and news ingestion separately versioned so each provider can ship independently.
- Treat any bridge into the quant feature store as an integration convenience, not a runtime dependency.
- Keep `ctx_snapshots` as canonical truth; `intelligence_features.ctx` is a denormalized projection for quant-facing consumers.
- Require provenance and staleness metadata on every context object before it is rendered into prompts or used for ML export.
- Do not allow qualitative context to affect I7 signal confidence or sizing until it has passed shadow-mode evaluation against realized outcomes.

---

## Cadence and Staleness

| Event type | Update frequency | Staleness rule |
|---|---|---|
| Earnings | Quarterly (4×/year) | Valid until the next earnings snapshot or declared `stale_after`. |
| FOMC | 8×/year | Valid until the event window closes and a post-event snapshot is written. |
| CPI/NFP | Monthly | Valid until the event window closes and a post-event snapshot is written. |
| News sentiment | Intraday (rolling 1h/24h) | Stale after the rolling window expires; consumers should decay or omit. |
| COT positioning | Weekly (Friday) | Valid until next expected release window; stale if no release appears after grace period. |

The `ctx_snapshots` valid_from/valid_to design handles staleness correctly: each bar gets the qualitative context that was true *at bar close*, enabling clean backtesting without lookahead bias.

Staleness is not the same as validity. A snapshot may remain historically valid for backtesting while being stale for a live decision. Live consumers should check `stale_after`; historical consumers should resolve by `valid_from` / `valid_to`.

---

## Provider Agent Design

Qualitative `ProviderAgent`s follow the same role suffix rules as quantitative ones:

| Agent | File | Systemd unit |
|---|---|---|
| `EarningsProviderAgent` | `services/earnings_provider_agent.py` | `indicagent-earnings-provider` |
| `MacroEventProviderAgent` | `services/macro_event_provider_agent.py` | `indicagent-macro-event-provider` |
| `NewsProviderAgent` | `services/news_provider_agent.py` | `indicagent-news-provider` |
| `EarningsComputeAgent` | `services/earnings_compute_agent.py` | `indicagent-earnings-compute` |
| `NewsSentimentComputeAgent` | `services/news_sentiment_compute_agent.py` | `indicagent-news-sentiment-compute` |
| `CtxWriterAgent` | `services/ctx_writer_agent.py` | `indicagent-ctx-writer` |

Data sources (initial candidates):
- **Earnings:** IBKR Fundamental Data (already available via `src/providers/ibkr.py` extension)
- **Macro events:** Economic calendar API (FRED, Trading Economics)
- **News sentiment:** OpenRouter → LLM summarization pipeline, or pre-computed NLP (FinBERT)
- **COT:** CFTC weekly reports (public, CSV download)

---

## What This Is NOT

- **Not real-time.** Qualitative data has different latency expectations. An earnings surprise is known in seconds; the normalized context snapshot is fine to arrive within a minute.
- **Not a replacement for price intelligence.** Qualitative data is a regime modifier and confidence context for I8 agents, not a standalone signal source.
- **Not a new database.** Same TimescaleDB, new tables. The existing backup, monitoring, and migration patterns apply.
- **Not blocking.** This layer is designed so it can be added incrementally. A single provider (e.g. earnings only) can ship without the others.

---

## Implementation Phases (Suggested)

| Phase | Scope | Prerequisite |
|---|---|---|
| P-CTX-01 | `ctx_events` + `ctx_snapshots` tables, `topic_ctx_snapshot()`, `CtxWriterAgent` skeleton | Plan 078-05 shipped |
| P-CTX-02 | `ctx` column migration, feature-writer as-of lookup, `seed_from_db_row` update, `_render_full_features` open iteration | P-CTX-01 |
| P-CTX-03 | One deterministic context lane: `MacroEventProviderAgent` or `EarningsProviderAgent` + compute agent | P-CTX-02 |
| P-CTX-04 | Shadow evaluation: measure whether the context improves realized signal outcomes before affecting I7 confidence | P-CTX-03 |
| P-CTX-05 | News sentiment provider after deterministic context path is proven | P-CTX-04 |

P-CTX-01 is low-risk because it only adds canonical qualitative storage and a writer skeleton. P-CTX-02 is the first quant-facing bridge and must remain optional. Everything after that adds value incrementally.
