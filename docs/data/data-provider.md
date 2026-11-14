# Provider and Bar Architecture

**Version:** 2.8
**Status:** stale (v2.x, see banner)
**Last Updated:** 2026-04-21

> How raw market data flows from any provider into the canonical bar stream — provider isolation, failover, source tagging, and bar quality guarantees.

---

> **Staleness note (2026-08-01, extended 2026-11-13):** Most of this doc (provider isolation,
> `ProviderMerger`, bar normalization) still describes the streaming architecture, but the
> streaming path is DORMANT while no live feed exists. Its IBKR dual-stream (RTB + official)
> framing describes a removed world: IBKR was removed entirely (owner ruling 2026-11-13; the
> provider is disabled and deletion-listed), and today's data arrives by nightly batch into
> `ohlcv_raw`, with canonical `market_data_ohlcv` selected from raw by `bar_source_policy`
> (Massive historical + Alpaca forward). Its `intelligence_features` rationale and its claim
> that `IntelligencePipeline` consumes HTF bars name the ARCHIVED v2.x pipeline (no live
> consumer as of 2026-07-02 per CLAUDE.md) — the live consumer is `FeatureVectorPipeline`.
> Not yet rewritten for v3.0 -- tracked for a future doc pass, not fixed here.

## Provider Isolation Pattern

IndicAgent is **provider-neutral** — canonical instrument symbols, stream keys, and DB schema carry no provider identity. Any data source is wired in by implementing `BaseProvider`:

```
<Provider A> → BarNormalizer → market.bars.raw.<provider_a>  ─┐
<Provider B> → BarNormalizer → market.bars.raw.<provider_b>  ─┤→ ProviderMerger → market.bars (canonical 1m)
<Provider N> → BarNormalizer → market.bars.raw.<provider_n>  ─┘
```

**All providers run simultaneously.** Each publishes a continuous stream of normalized `BarMessage` payloads to its own isolated raw topic. `ProviderMerger` subscribes to all of them at once and selects which bars reach `market.bars` based on routing config.

**Adding a provider:** implement `BaseProvider`, normalize output via `bar_normalizer.py`, publish to `market.bars.raw.<name>`, add the topic to `settings.provider_raw_topics`.

---

## Bar Normalization

Before publishing to a raw topic, every provider normalizes its native bar format to the canonical `BarMessage` schema via `src/core/bar_normalizer.py`. This is where provider-specific quirks (IBKR local symbol mapping, tick format differences, timestamp alignment) are resolved. Downstream services only ever see `BarMessage` — no provider-specific logic leaks past this boundary.

Source constants defined in `bar_normalizer.py` tag each bar's origin (the live list;
`SOURCE_IBKR_RTB` no longer exists and `SOURCE_IBKR_GENERIC` carries the value `"ibkr"`):
```python
SOURCE_IBKR_NAMED      = "ibkr_named"           # Named-contract direct IBKR fetch
SOURCE_IBKR_CONTINUOUS = "ibkr_continuous_adj"  # Continuous back-adjusted IBKR fetch
SOURCE_IBKR_OFFICIAL   = "ibkr_official"        # Official 1m bars from TWS reconciliation
SOURCE_IBKR_GENERIC    = "ibkr"                 # Generic IBKR fetch (RTB / fallback)
SOURCE_IBKR_SEED       = "ibkr_seed"            # Historical seed bar from DB backfill
SOURCE_HTF_DERIVED     = "htf_derived"          # Aggregated from 1m bars by BarAccumulator
SOURCE_DERIVED_1M      = "derived_1m"           # Aggregated from 1m bars in DB
SOURCE_IBKR_VENUE      = "ibkr_venue"           # Former-primary-venue volume routing (todo 433)
SOURCE_UNKNOWN         = "unknown"              # Source missing from payload
```

---

## ProviderMerger — Routing, Failover, Quality

`ProviderMerger` is the single source of truth for `market.bars`. Routing is **per asset class** — `settings.provider_routing_config` maps `asset_class → authoritative_provider`. This means different asset classes can use different authoritative providers simultaneously (e.g. IBKR for futures, a separate feed for equities).

**Routing logic per bar:**
1. Determine `asset_class` for the bar's symbol
2. Look up authoritative provider from `provider_routing_config[asset_class]`
3. If bar is from the authoritative provider (or a promoted failover): publish to `market.bars` + emit `ProviderQualityEvent`
4. Otherwise: update silence-detection tracking, check if failover threshold exceeded — bar is dropped

**Auto-failover is per-symbol** — `_promoted[symbol]` tracks which symbols have been promoted to a secondary. One symbol can failover independently of others. When the primary resumes for a symbol, the promotion is cleared and a recovery event is published.

**Quality side-channel:** every routed bar, failover, and recovery emits a `ProviderQualityEvent` to `market.data.quality`. This feeds monitoring without touching the hot path.

---

## IBKR Provider — Dual Stream Internal Design

`IBKRAdapter` runs two IBKR streams concurrently to balance latency vs accuracy:

| Stream | IBKR API | Source Tag | Purpose |
|--------|----------|------------|---------|
| RTB (5s real-time bars) | `reqRealTimeBars` | `ibkr_rtb` | Low-latency aggregated 1m bars for the hot path |
| Official 1m bars | `reqHistoricalData(keepUpToDate=True)` | `ibkr_official` | Authoritative ground truth for reconciliation |

Both streams publish to `market.bars.raw.ibkr` with their source tag.

This is an IBKR implementation detail. `ProviderMerger` and all downstream services see only canonical `BarMessage` payloads from `market.bars`.

---

## Source Tagging

`src/core/bar_normalizer.py` defines source constants applied at ingestion; canonical rows carry
`(vendor, kind)` since plan 191-13 (the map is `src/intelligence/bars/vendor_kind.py`). See the
live constant list in the Bar Normalization section above.

The `market_data_ohlcv.source` column preserves the tag.

---

## Flat Bar Pattern — Continuity Guarantee

During zero-volume periods (pre-market, post-market, circuit breakers), the pipeline emits flat bars to maintain a gap-free time series:

- `BarMessage.is_flat_bar = True`
- OHLCV: `open = high = low = close = last_traded_close`, `volume = 0`
- `BarAggregator` propagates the flag into HTF bars

**Why:** `intelligence_features` requires a continuous temporal index for seasonal ML analysis. Flat bars push the continuity guarantee into the data layer — no gap-filling logic needed in any downstream consumer.

---

## BarAccumulator — Stateless HTF Aggregation

`BarAccumulator` (`src/core/bar_accumulator.py`) consumes 1m bars and emits HTF bars on period boundaries (5m, 15m, 1h, 4h, 1d). Stateless windowed aggregation — no DB reads. Session break logic at RTH close prevents cross-session bar contamination.

HTF bars are published to `market.bars.htf` and consumed directly by `IntelligencePipeline` — real-time consumers get HTF context without DB read latency.

---

## Key Files

| File | Role |
|------|------|
| `src/providers/base_provider_agent.py` | `BaseProvider` — abstract contract for all providers |
| `src/providers/ibkr.py` | All ib_async logic; `stream_official_bars()`, `stream_real_time_bars()` |
| `src/providers/ibkr_adapter.py` | `IBKRAdapter` — dual IBKR streams, publishes `BarMessage` to Kafka |
| `services/ibkr_provider.py` | `IBKRProvider` — systemd service wrapper |
| `services/provider_merger.py` | `ProviderMerger` — routing, failover, quality side-channel |
| `src/core/bar_normalizer.py` | Source tag constants; bar normalization utilities |
| `src/core/bar_accumulator.py` | `BarAccumulator` — stateless windowed HTF aggregation |
| `src/core/schemas/bar_message.py` | `BarMessage` schema — canonical bar payload including `is_flat_bar` |

---

## See Also

- **Reference data & roll logic:** `data-foundation.md` — instruments, contract_metadata, roll lifecycle
- **Hot/warm/cold tiers:** `data-pipeline.md` — Redpanda topics, processing services, TimescaleDB writers
- `docs/architecture/architecture-dag-topology.md` — the service DAG map (v2.x revival reference)
- `src/providers/CLAUDE.md` — IBKR contract setup, asset class rules, troubleshooting
