# IndicAgent Intelligence Platform Architecture

**Version:** 2.0
**Last Updated:** 2026-03-22
**Status:** I1-I8 production complete — 98 plugins + 2 aggregation components

## Executive Summary

IndicAgent is a real-time market intelligence platform that transforms raw IBKR market data into actionable trading intelligence through a layered plugin-native architecture. The full I1-I8 pipeline is production-complete: 98 plugins across 8 intelligence tiers, 2 aggregation components, and a typed event bus persisted to TimescaleDB.

**Architecture Philosophy:** Plugin pipeline hosted within a unified `feature_compute_agent` for I1-I6, with separate services for signals (I7) and AI (I8). The real-time pipeline never touches the database directly — all cold persistence is decoupled through the `feature_writer_service`.

---

## Architecture Layers

```
Layer 4: AI Intelligence (I8)              → LLM analysis, local Ollama (qwen3.5:9b / phi4-mini:3.8b)
Layer 3: Pattern Intelligence (I5-I7)      → Pattern detection, confluence, trading signals
Layer 2: Mathematical Intelligence (I1-I6) → Technical indicators, second-derivative events, market structure, regime context, SMC
Layer 1: Data Foundation                   → IBKR TWS collection, Redpanda topics, TimescaleDB
```

**Full pipeline:**
```
IBKR TWS → feature_compute_agent (I1→I6) →
  signal_generator_service (I7) → signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard
```

---

## Layer 1: Data Foundation

### DataProviderAgent (`services/data_provider_agent.py`)
- Collects tick and OHLCV bar data from Interactive Brokers TWS at `10.0.0.33:7497`
- All ib_insync logic isolated to `src/providers/ibkr.py`
- Multi-timeframe aggregation: 1m → 5m → 15m → 1h → 4h → 1d
- 60 active instruments defined in `src/config/settings.py`

### Redpanda (Hot Tier)
- Kafka-compatible streaming backbone for real-time pipeline communication
- Sub-millisecond latency for inter-service messaging
- Topic names use dots: `development.market.bars`, `development.intelligence`, etc.
- Topic keys constructed exclusively via `src/core/stream_keys.py`

### TimescaleDB (Cold Tier)
- Populated only by `feature_writer_service` (real-time) and `historical_backfill.py` (backfill)
- Real-time pipeline services never write to the database directly
- PostgreSQL/TimescaleDB Docker on :5432, database `indicagent`

---

## Layer 2: Mathematical & Market Intelligence (I1–I6)

Unified in `services/feature_compute_agent.py`.

### I1-I6 Tiers
Covers 98 plugins including technical indicators (RSI, MA, etc.), market structure (Swing, SR), regime context (VolRegime, GARCHVol), and Smart Money Concepts (BOS/CHoCH, FVG).

Output stream: `{env}:intelligence:{symbol}:{tf}` (typed `IntelligenceEvent`).

---

## Layer 3: Signal Intelligence (I7)

Runs in `services/signal_generator_service.py`.

### I7 — 17 Setup Plugins + 2 Aggregation Components
**Setup plugins:** TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion, VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup, CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition, GapAnalysis, CandlestickPatternSetup, SessionExtremes

**Aggregation components:**
- `CISScorer` — Composite Intelligence Score
- `SignalAggregator` — selects winner from `all_ranked`

Output stream: `{env}:signals:{symbol}:{tf}:aggregated`
Cold persistence: `signal_ledger` table

---

## Layer 4: AI Intelligence (I8)

### AI Narrative Service (`services/ai_narrative_service.py`, :9113)
- Consumes `{env}:intelligence:{symbol}:{tf}` events
- Calls local Ollama Docker (:11434)
  - **qwen3.5:9b** — per-signal narrative synthesis
  - **phi4-mini:3.8b** — group synthesis
- Output stream: `{env}:narratives:{symbol}:{tf}`

---

## Services

All services are systemd-managed.

| Service Unit | Purpose | Metrics Port |
|---|---|---|
| `indicagent-data-provider` | IBKR tick + bar collection | — |
| `indicagent-feature-compute` | Unified I1+I2+I3+I4+I5+SMC+I6 | :9125 |
| `indicagent-signal-generator` | I7 → `signals:` + `signal_ledger` | :9112 |
| `indicagent-signal-tracker` | Zone-aware lifecycle, MAE/MFE tracking, 8-class outcome | :9115 |
| `indicagent-ai-narrative` | I8 LLM → `narratives:` | :9113 |
| `indicagent-feature-writer` | `intelligence:` → `intelligence_features` | :9116 |
| `indicagent-api` | FastAPI + SSE on :8000 | — |

---

## Stream Architecture

All stream keys are constructed via `src/core/stream_keys.py`.

| Stream | Producer | Consumer(s) |
|---|---|---|
| `{env}:market:{symbol}:{tf}` | indicagent-data-provider | feature_compute_agent, signal_tracker_agent |
| `{env}:intelligence:{symbol}:{tf}` | feature_compute_agent | signal_generator_service, ai_narrative_service, feature_writer_service |
| `{env}:signals:{symbol}:{tf}:aggregated` | signal_generator_service | indicagent-api (SSE) |
| `{env}:narratives:{symbol}:{tf}` | indicagent-ai-narrative | indicagent-api (SSE) |

---

## Related Documentation

- `docs/concepts/intelligence-tiers.md`
- `docs/reference/schemas/stream-schemas.md`
- `src/intelligence/CLAUDE.md` — Plugin protocol and LLM provider chain
