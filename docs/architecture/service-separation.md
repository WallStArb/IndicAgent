# Service Separation of Duties

**Last Updated:** 2026-03-15
**Status:** Production — I1-I8 complete, 9 active services

---

## Principle

Each service has **one reason to change**. Services communicate exclusively via Redis Streams —
no direct HTTP calls between services in the pipeline. A service can be restarted, redeployed,
or scaled independently without affecting others.

---

## Services and Responsibilities

### `market_data_daemon`

**Responsibility:** Connect to IBKR TWS, ingest live ticks, form 1-minute OHLCV bars, and build higher timeframe bars internally.

Two data streams produced simultaneously:
- **Live ticks** via `reqMktData` → `ticks:SYMBOL:live` stream + `price:SYMBOL:latest` hash
- **1m bars**: provisional bar at :00 (from tick accumulator, `source: "tick_derived"`) and
  authoritative bar at :05 (from `reqHistoricalData`, `source: "authoritative"`) → `market:SYMBOL:1m`

Also builds higher timeframe bars (5m, 15m, 1h, 4h, 1d) internally from 1m bars. Multi-timeframe
aggregation is embedded in the daemon — there is no separate `bar_aggregator_service`.

This service owns the IBKR connection. Restarting it disconnects from the broker. All other
services are insulated from broker connectivity by the stream bus.

**Publishes:** `market:SYMBOL:1m`, `market:SYMBOL:5m`, `market:SYMBOL:15m`, `market:SYMBOL:1h`, `market:SYMBOL:4h`, `market:SYMBOL:1d`, `ticks:SYMBOL:live`, `price:SYMBOL:latest`
**Consumes:** nothing (source of truth)

---

### `indicator_service`

**Responsibility:** Compute all I1 + I2 indicators (35 total) incrementally for every incoming bar.

- **25 I1 technical indicators** — RSI, MACD, ATR, Bollinger Bands, VWAP, Parabolic SAR, StochRSI, CMF, Aroon, ADX/DI, Supertrend, ROC, AO, AC, etc.
- **11 I2 second-derivative/event plugins** — MACD Events, RSI Events, Stoch Events, ADX Events, Volume Events, MomentumAccel, DonchianPos, OBVMomentum, DerivOsc, ExhaustionScore

Publishes **one combined message per bar** containing OHLCV + all I1/I2 fields as flat key-value
pairs. This design is deliberate: a single combined message avoids the coordination problem of
waiting for N separate indicator messages before downstream analysis can proceed.

Subscribes to `market:SYMBOL:*` for all timeframes — 1m bars from `market_data_daemon` and
higher timeframe bars also produced by `market_data_daemon`.

**Publishes:** `indicators:SYMBOL:TF`
**Consumes:** `market:SYMBOL:1m`, `market:SYMBOL:5m`, `market:SYMBOL:15m`, `market:SYMBOL:1h`, `market:SYMBOL:4h`, `market:SYMBOL:1d`

---

### `market_analysis_service`

**Responsibility:** Run the sequential I3→I4→I5→SMC→I6 analysis pipeline on each enriched bar.

Plugins run in DAG order on the same bar's data:
- **I3 Market Structure** — swing detection (HH/HL/LH/LL), support/resistance, trend structure
- **I4 Context** — volatility regime, trend regime, momentum context, GARCH vol, Kalman trend
- **I5 Patterns** — RSI divergence, Bollinger squeeze, volume divergence, chart patterns (8 plugins)
- **SMC Smart Money (13 plugins)** — BOS/CHoCH, FVG, order blocks, liquidity sweeps, killzones, AMD cycle, breaker blocks, premium/discount zones
- **I6 Confluence** — cross-timeframe alignment scoring

These tiers are co-located because they run sequentially on the same bar's data, share context
(e.g. I4 outputs feed I5 confidence scores, I6 reads across all timeframe caches), and have
identical failure semantics — if this service restarts, all tiers restart together, which is
correct behaviour.

Publishes a fully enriched bar message: OHLCV + all I1 fields + all I3–I6 outputs.

Does **NOT** write to the database — intelligence features are persisted by `feature_writer_service`.

**Publishes:** `intelligence:SYMBOL:TF`
**Consumes:** `indicators:SYMBOL:TF`

---

### `feature_writer_service`

**Responsibility:** Async decoupled persistence of intelligence features from hot path to cold storage.

Consumes `intelligence:SYMBOL:TF` stream (consumer group `feature_writer:persist`). Batches writes
to the `intelligence_features` hypertable — 100ms batch window or 50 events, whichever comes first.
This decoupling means the real-time pipeline never touches the database directly.

Also processes historical backfill replay (source='backfill') using the same batch write path.

**Publishes:** nothing (writes to DB only)
**Consumes:** `intelligence:SYMBOL:TF`
**Writes:** `intelligence_features` hypertable

---

### `signal_generator_service`

**Responsibility:** Detect trading setups and produce actionable signals.

On each enriched bar: runs all 17 I7 setup plugins + 2 aggregation components (CISScorer, SignalAggregator),
applies the rules-based aggregator to select the winning signal, inserts all candidates to the
`signal_ledger` hypertable, and publishes the aggregated winner to the signals stream.

**I7 setup plugins:** TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment,
SqueezeExpansion, VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup,
CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition, GapAnalysis,
CandlestickPatternSetup, SessionExtremes

Does **not** evaluate open signal lifecycle — that belongs to `signal_lifecycle_service`.

Requires ~50 live 1m bars (~50 min) warmup after restart before signals fire.

**Publishes:** `signals:SYMBOL:TF:aggregated`
**Consumes:** `intelligence:SYMBOL:TF`
**Writes:** `signal_ledger` (new signal rows)

---

### `signal_lifecycle_service`

**Responsibility:** Zone-aware lifecycle tracking for all pending and active signals.

Reads every incoming `market:SYMBOL:1m` bar and evaluates all pending/active signals:
- **Activation:** signal becomes active when price enters the zone bounds (zone_low/zone_high from TradeFrame)
- **MAE/MFE tracking:** in-memory max adverse/favorable excursion per signal_id; written to DB on exit
- **8-class outcome:** `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`

Replaced `signal_tracker_service` (which used a simpler 3-state model with no zone awareness).

Subscribes to `market:SYMBOL:1m` (not `intelligence:SYMBOL:TF`) because lifecycle evaluation
only needs OHLCV. This subscription choice is intentional: the lifecycle service keeps running
and protecting open positions even if `market_analysis_service` or `signal_generator_service`
are stopped for maintenance or redeployment.

**Publishes:** `llm_outcomes:stream` (signal exits with outcome/pnl_r/mae/mfe) — consumed by `llm_writer_service`
**Consumes:** `market:SYMBOL:1m`
**Writes:** `signal_ledger` (lifecycle state updates, MAE/MFE, outcome)

---

### `ai_narrative_service`

**Responsibility:** Synthesise AI narratives from aggregated signals using a local LLM.

Subscribes to `signals:SYMBOL:TF:aggregated`. For each signal above a confidence threshold,
calls Ollama (qwen3.5:9b per-signal, phi4-mini:3.8b group synthesis) to generate a human-readable
market narrative. Publishes to the narratives stream and caches the latest narrative as a hash
with a 90s TTL.

Every LLM call is published to `llm_calls:stream` for audit and model scoring (consumed by
`llm_writer_service`).

Consumer group `"ai_narrative"` is stable across restarts (idempotent creation). Uses `xack`
in a `finally` block so messages are always acknowledged, even if the Redis write fails.

**Publishes:** `narratives:SYMBOL:TF`, `narrative:SYMBOL:TF:latest` (hash, 90s TTL), `llm_calls:stream`
**Consumes:** `signals:SYMBOL:TF:aggregated`

---

### `llm_writer_service`

**Responsibility:** Persist LLM call audit records and update model performance scores.

Consumes `llm_calls:stream` — every LLM call from `ai_narrative_service` (success, failure,
counterfactual). Writes each call to the `llm_calls` hypertable. Also listens for
`llm_outcomes:stream` from `signal_lifecycle_service` to back-fill realized P&L and outcome
onto historical llm_call records. Refreshes `llm_model_scores` (per-model win rate / avg
pnl_r / p-value) every 15 minutes.

**Publishes:** nothing (writes to DB only)
**Consumes:** `llm_calls:stream`, `llm_outcomes:stream`
**Writes:** `llm_calls` hypertable, `llm_model_scores` table

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
    ├──► market:SYMBOL:1m
    └──► market:SYMBOL:5m/15m/1h/4h/1d  (built internally)
              │
              ▼
    indicator_service
    (25 I1 + 11 I2 plugins, incremental)
    one combined message per bar
              │
              ▼
    indicators:SYMBOL:TF
    (OHLCV + all I1/I2 fields, one message per bar)
              │
              ▼
    market_analysis_service
    (I3 → I4 → I5 → SMC → I6)
    does NOT write to DB
              │
              ▼
    intelligence:SYMBOL:TF
    (fully enriched bar — OHLCV + I1–I6 outputs)
              │
              ├──────────────────────────────────────────┐
              ▼                                          ▼
    signal_generator_service              feature_writer_service
    (17 I7 plugins + CISScorer            (batched write to
     + SignalAggregator)                   intelligence_features)
              │
              ├──────────────────────────────────────────┐
              ▼                                          │
    signals:SYMBOL:TF:aggregated        signal_lifecycle_service
              │                         (subscribes to market:SYMBOL:1m
              ▼                          zone-aware activation + MAE/MFE
    ai_narrative_service                 8-class outcome classification)
    (qwen3.5:9b per-signal,                       │
     phi4-mini:3.8b group synthesis)              ▼
              │                         llm_outcomes:stream
              ├──► llm_calls:stream ──────────────┐
              ▼                                   ▼
    narratives:SYMBOL:TF           llm_writer_service
              │                    (writes llm_calls hypertable,
              └──────────────────► llm_model_scores; back-fills
                                    outcome from llm_outcomes:stream)
                                               │
    All streams ──────────────────────────► api_service ──► SSE ──► Dashboard
```

---

## What Does NOT Belong in Each Service

| Service | Must NOT do |
|---------|------------|
| `market_data_daemon` | Any indicator computation, pattern detection, or DB writes |
| `indicator_service` | Market structure, patterns, or regime analysis |
| `market_analysis_service` | I1/I2 computation (consume from indicators stream instead); signal generation; direct DB writes (feature persistence is `feature_writer_service`'s job) |
| `feature_writer_service` | Any computation — pure persistence only |
| `signal_generator_service` | Lifecycle tracking of open signals |
| `signal_lifecycle_service` | Must NOT run I7 plugins or generate new signals |
| `ai_narrative_service` | Signal generation or lifecycle decisions |
| `llm_writer_service` | Must NOT generate narratives or make LLM calls |
| `api_service` | Any computation or persistence |

---

## Stream Key Reference

| Stream | Producer | Consumers |
|--------|----------|-----------|
| `market:SYMBOL:1m` | `market_data_daemon` | `indicator_service`, `signal_lifecycle_service` |
| `market:SYMBOL:5m/15m/1h/4h/1d` | `market_data_daemon` | `indicator_service` |
| `ticks:SYMBOL:live` | `market_data_daemon` | `api_service` (SSE) |
| `price:SYMBOL:latest` | `market_data_daemon` | `api_service` (REST) |
| `indicators:SYMBOL:TF` | `indicator_service` | `market_analysis_service` |
| `intelligence:SYMBOL:TF` | `market_analysis_service` | `signal_generator_service`, `feature_writer_service`, `api_service` |
| `signals:SYMBOL:TF:aggregated` | `signal_generator_service` | `narrative_service`, `api_service` |
| `narratives:SYMBOL:TF` | `ai_narrative_service` | `api_service` |
| `llm_calls:stream` | `ai_narrative_service` | `llm_writer_service` |
| `llm_outcomes:stream` | `signal_lifecycle_service` | `llm_writer_service` |

---

## Related Documents

- Decision record: `docs/plans/2026-02-20-service-separation-design.md`
- Stream schemas: `docs/architecture/stream-schemas.md`
- Intelligence tier details: `docs/concepts/intelligence-tiers.md`
- Plugin registry and DAG execution: `docs/architecture/plugin-registry-and-dag-execution.md`
