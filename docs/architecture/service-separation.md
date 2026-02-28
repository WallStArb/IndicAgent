# Service Separation of Duties

**Last Updated:** 2026-02-20
**Status:** Target architecture — implementation in progress (see `docs/plans/2026-02-20-service-separation-design.md`)

---

## Principle

Each service has **one reason to change**. Services communicate exclusively via Redis Streams —
no direct HTTP calls between services in the pipeline. A service can be restarted, redeployed,
or scaled independently without affecting others.

---

## Services and Responsibilities

### `market_data_daemon`

**Responsibility:** Connect to IBKR TWS, ingest live ticks, and form 1-minute OHLCV bars.

Two data streams produced simultaneously:
- **Live ticks** via `reqMktData` → `ticks:SYMBOL:live` stream + `price:SYMBOL:latest` hash
- **1m bars**: provisional bar at :00 (from tick accumulator, `source: "tick_derived"`) and
  authoritative bar at :05 (from `reqHistoricalData`, `source: "authoritative"`) → `market:SYMBOL:1m`

This service owns the IBKR connection. Restarting it disconnects from the broker. All other
services are insulated from broker connectivity by the stream bus.

**Publishes:** `market:SYMBOL:1m`, `ticks:SYMBOL:live`, `price:SYMBOL:latest`
**Consumes:** nothing (source of truth)

---

### `indicator_service`

**Responsibility:** Compute all 23 I1 technical indicators (RSI, MACD, ATR, Bollinger Bands,
VWAP, Parabolic SAR, StochRSI, CMF, Aroon, etc.) incrementally for every incoming bar.

Publishes **one combined message per bar** containing OHLCV + all I1 fields as flat key-value
pairs. This design is deliberate: a single combined message avoids the coordination problem of
waiting for N separate indicator messages before downstream analysis can proceed.

Subscribes to `market:SYMBOL:*` for all timeframes — both 1m bars from `market_data_daemon`
and higher timeframe bars from `bar_aggregator_service`.

**Publishes:** `indicators:SYMBOL:TF`
**Consumes:** `market:SYMBOL:1m`, `market:SYMBOL:5m`, `market:SYMBOL:15m`, `market:SYMBOL:1h`, `market:SYMBOL:4h`, `market:SYMBOL:1d`

---

### `bar_aggregator_service`

**Responsibility:** Resample completed 1m bars into higher timeframe bars (5m, 15m, 1h, 4h, 1d).

Publishes each completed higher-timeframe bar as a standard OHLCV market message, which
`indicator_service` then processes to produce I1 features for that timeframe.

**Publishes:** `market:SYMBOL:5m`, `market:SYMBOL:15m`, `market:SYMBOL:1h`, `market:SYMBOL:4h`, `market:SYMBOL:1d`
**Consumes:** `market:SYMBOL:1m`

---

### `market_analysis_service`

**Responsibility:** Run the sequential I3→I4→I5→SMC→I6 analysis pipeline on each enriched bar.

Plugins run in DAG order on the same bar's data:
- **I3 Market Structure** — swing detection (HH/HL/LH/LL), support/resistance, trend structure
- **I4 Context** — volatility regime, trend regime, momentum context, GARCH vol, Kalman trend
- **I5 Patterns** — RSI divergence, Bollinger squeeze, volume divergence, chart patterns (8 plugins)
- **SMC Smart Money** — BOS/CHoCH, FVG, order blocks, liquidity sweeps, BOCPD, HMM regime
- **I6 Confluence** — cross-timeframe alignment scoring

These tiers are co-located because they run sequentially on the same bar's data, share context
(e.g. I4 outputs feed I5 confidence scores, I6 reads across all timeframe caches), and have
identical failure semantics — if this service restarts, all tiers restart together, which is
correct behaviour.

Publishes a fully enriched bar message: OHLCV + all I1 fields + all I3–I6 outputs.

**Publishes:** `intelligence:SYMBOL:TF`
**Consumes:** `indicators:SYMBOL:TF`

---

### `signal_generator_service`

**Responsibility:** Detect trading setups and produce actionable signals.

On each enriched bar: runs all I7 setup plugins (TrendFollowing, MeanReversion,
LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion, VWAPDeviation, MomentumBreakout),
applies the rules-based aggregator to select the winning signal, inserts all candidates to the
`signal_ledger` hypertable, and publishes the aggregated winner to the signals stream.

Does **not** evaluate open signal lifecycle — that belongs to `signal_tracker_service`.

**Publishes:** `signals:SYMBOL:TF:aggregated`
**Consumes:** `intelligence:SYMBOL:TF`
**Writes:** `signal_ledger` (new signal rows)

---

### `signal_tracker_service`

**Responsibility:** Monitor open signals against incoming price bars and update their lifecycle state.

Subscribes to `market:SYMBOL:1m` (not `intelligence:SYMBOL:TF`) because lifecycle evaluation
only needs OHLCV — it checks whether price crossed the signal's stop loss, target levels, or
whether the TTL has expired. This subscription choice is intentional: the tracker keeps running
and protecting open positions even if `market_analysis_service` or `signal_generator_service`
are stopped for maintenance or redeployment.

State machine transitions: `pending` → `active` → `exit` (stop hit / target hit / TTL expired).
Records realised P&L on exit.

**Publishes:** nothing (writes to DB only)
**Consumes:** `market:SYMBOL:1m`
**Writes:** `signal_ledger` (lifecycle state updates, P&L)

---

### `narrative_service`

**Responsibility:** Synthesise AI narratives from aggregated signals using a local LLM.

Subscribes to `signals:SYMBOL:TF:aggregated`. For each signal above a confidence threshold,
calls Ollama (qwen3:8b) to generate a human-readable market narrative. Publishes to the
narratives stream and caches the latest narrative as a hash with a 90s TTL.

Consumer group `"ai_narrative"` is stable across restarts (idempotent creation). Uses `xack`
in a `finally` block so messages are always acknowledged, even if the Redis write fails.

**Publishes:** `narratives:SYMBOL:TF`, `narrative:SYMBOL:TF:latest` (hash, 90s TTL)
**Consumes:** `signals:SYMBOL:TF:aggregated`

---

### `api_service`

**Responsibility:** Expose REST endpoints and Server-Sent Events for the dashboard.

SSE streams: ticks, market bars, indicators, intelligence, signals, narratives. No pipeline
logic lives here — it fans out stream data to connected clients.

**Publishes:** SSE → Dashboard
**Consumes:** all streams (read-only fan-out)

---

## Stream Flow

```
IBKR TWS
    │
    ▼
market_data_daemon
    ├──► ticks:SYMBOL:live          (raw tick stream)
    ├──► price:SYMBOL:latest        (hash, 120s TTL)
    └──► market:SYMBOL:1m
              │
              ├──────────────────────────────────────────┐
              ▼                                          ▼
    indicator_service                        bar_aggregator_service
    (all 23 I1 plugins, incremental)         (1m → 5m/15m/1h/4h/1d)
    one combined message per bar                        │
              │             ◄──────────────────────────┘
              │      (bar_aggregator feeds indicator_service
              │       for higher timeframe bars too)
              ▼
    indicators:SYMBOL:TF
    (OHLCV + all I1 fields, one message per bar)
              │
              ▼
    market_analysis_service
    (I3 → I4 → I5 → SMC → I6)
              │
              ▼
    intelligence:SYMBOL:TF
    (fully enriched bar — OHLCV + I1–I6 outputs)
              │
              ▼
    signal_generator_service
    (9 I7 setup plugins + aggregation)
              │
              ├──────────────────────────────────────────┐
              ▼                                          │
    signals:SYMBOL:TF:aggregated            signal_tracker_service
              │                             (subscribes to market:SYMBOL:1m
              │                              evaluates open signal lifecycle
              ▼                              writes to signal_ledger)
    narrative_service
    (Ollama qwen3:8b)
              │
              ▼
    narratives:SYMBOL:TF ──────────────────► SSE ──► Dashboard
```

---

## What Does NOT Belong in Each Service

| Service | Must NOT do |
|---------|------------|
| `market_data_daemon` | Any indicator computation, pattern detection, or DB writes |
| `indicator_service` | Market structure, patterns, or regime analysis |
| `bar_aggregator_service` | Indicator computation (delegates to indicator_service) |
| `market_analysis_service` | I1 computation (consume from indicators stream instead); signal generation |
| `signal_generator_service` | Lifecycle tracking of open signals |
| `signal_tracker_service` | Running I7 plugins or aggregation logic |
| `narrative_service` | Signal generation or lifecycle decisions |
| `api_service` | Any computation or persistence |

---

## Stream Key Reference

| Stream | Producer | Consumers |
|--------|----------|-----------|
| `market:SYMBOL:1m` | `market_data_daemon` | `indicator_service`, `bar_aggregator_service`, `signal_tracker_service` |
| `market:SYMBOL:TF` (5m+) | `bar_aggregator_service` | `indicator_service` |
| `ticks:SYMBOL:live` | `market_data_daemon` | `api_service` (SSE) |
| `price:SYMBOL:latest` | `market_data_daemon` | `api_service` (REST) |
| `indicators:SYMBOL:TF` | `indicator_service` | `market_analysis_service` |
| `intelligence:SYMBOL:TF` | `market_analysis_service` | `signal_generator_service`, `api_service` |
| `signals:SYMBOL:TF:aggregated` | `signal_generator_service` | `narrative_service`, `api_service` |
| `narratives:SYMBOL:TF` | `narrative_service` | `api_service` |

---

## Related Documents

- Decision record: `docs/plans/2026-02-20-service-separation-design.md`
- Stream schemas: `docs/architecture/stream-schemas.md`
- Intelligence tier details: `docs/concepts/intelligence-tiers.md`
- Plugin registry and DAG execution: `docs/architecture/plugin-registry-and-dag-execution.md`
