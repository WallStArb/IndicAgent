# IndicAgent Intelligence Platform Architecture

**Version:** 8.0.0
**Last Updated:** 2026-03-11
**Status:** I1-I8 production complete — 95 plugins + 2 aggregation components, 1497 passing tests

## Executive Summary

IndicAgent is a real-time market intelligence platform that transforms raw IBKR market data into actionable trading intelligence through a layered plugin-native architecture. The full I1-I8 pipeline is production-complete: 95 plugins across 7 intelligence tiers, 2 aggregation components, 9 systemd services, and a typed event bus persisted to TimescaleDB.

**Architecture Philosophy:** Service-hosted plugin pipeline with a strict hot/warm/cold data tiering model. The real-time pipeline never touches the database directly — all cold persistence is decoupled through the feature_writer_service.

---

## Architecture Layers

```
Layer 4: AI Intelligence (I8)              → LLM analysis, local Ollama (qwen3.5:9b / phi4-mini:3.8b)
Layer 3: Pattern Intelligence (I5-I7)      → Pattern detection, confluence, trading signals
Layer 2: Mathematical Intelligence (I1-I4) → Technical indicators, second-derivative events, market structure, regime context
Layer 1: Data Foundation                   → IBKR TWS collection, DragonflyDB streams, TimescaleDB
```

**Full pipeline:**
```
IBKR TWS → indicator_service (I1+I2) → market_analysis_service (I3→I4→I5→SMC→I6) →
  signal_generator_service (I7) → signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard
```

---

## Layer 1: Data Foundation

### IBKR TWS Daemon (`indicagent-tws`)
- Collects tick and OHLCV bar data from Interactive Brokers TWS at `10.0.0.33:7497`
- All ib_insync logic isolated to `src/providers/ibkr.py` — no imports outside this file
- Multi-timeframe aggregation: 1m → 5m → 15m → 1h → 1d
- 24 active contracts defined in `src/config/settings.py` via `get_active_contracts()`

### DragonflyDB (Hot Tier)
- Hosts all Redis Streams for real-time pipeline communication
- Sub-millisecond latency for inter-service messaging
- No Redis modules (TS.*, RediSearch unavailable) — time-series handled by TimescaleDB
- Stream keys constructed exclusively via `src/core/stream_keys.py` with `env_prefix`

### TimescaleDB (Cold Tier)
- Populated only by `feature_writer_service` (real-time) and `historical_backfill.py` (backfill)
- Real-time pipeline services never write to the database directly
- PostgreSQL/TimescaleDB Docker on :5432, database `indicagent`

---

## Layer 2: Mathematical Intelligence (I1–I4)

Both I1 and I2 are processed by `indicagent-indicator`. I3 and I4 are processed by `indicagent-market-analysis`.

### I1 — 25 Technical Indicator Plugins
RSI, MA/EMA, MACompare, MACD, ATR, BollingerBands, Stochastic, CCI, WilliamsR, MFI, OBV, VWAP, Supertrend, ADX/DMI, Keltner, Donchian, ROC/PPO, Aroon, ChandelierExit, CMF, HistoricalVolatility, PSAR, StochRSI, ACOscillator, HMA

### I2 — 10 Second-Derivative / Event Plugins
MACD Events, RSI Events, Stoch Events, ADX Events, Volume Events, MomentumAccel, DonchianPos, OBVMomentum, DerivOsc, ExhaustionScore

Output stream: `{env}:indicators:{symbol}:{tf}`

### I3 — 8 Market Structure Plugins
Swing, SR, TrendStructure, MarketProfile, SessionLevels, AnchoredVWAP, FibZones, SwingMomentum

### I4 — 7 Context / Regime Plugins
VolRegime, TrendRegime, MomentumCtx, GARCHVol, KalmanTrend, SessionCtx, MTFVol

I3 and I4 are processed inline within `indicagent-market-analysis` before I5/SMC/I6.

---

## Layer 3: Pattern Intelligence (I5–I7)

I5 and SMC run within `indicagent-market-analysis`. I6 produces the typed `IntelligenceEvent`. I7 runs in `indicagent-signal-generator`.

### I5 — 14 Pattern Plugins
RSIDivergence, BollingerSqueeze, VolDivergence, Confluence, TrendConfluence, DoubleTB, HeadShoulders, TriangleWedge, Candlestick, FlagPennant, CupHandle, MeasuredMove, VolumeProfile, KeyLevelReaction

### SMC — 13 Smart Money Concept Plugins
BOS/CHoCH, FVG, OrderBlocks, LiquiditySweeps, BOCPD, HMM, LiquidityPools, SupplyDemandZones, ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount

### I6 — 1 Cross-Timeframe Confluence Plugin
CrossTimeframeConfluence (CTF scorer) — combines I3+I4+I5+SMC into the typed `IntelligenceEvent` published to `{env}:intelligence:{symbol}:{tf}`

Output stream: `{env}:intelligence:{symbol}:{tf}`

### I7 — 17 Setup Plugins + 2 Aggregation Components
**Setup plugins:** TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion, VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup, CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition, GapAnalysis, CandlestickPatternSetup, SessionExtremes

**Aggregation components:**
- `CISScorer` — Composite Intelligence Score; weights individual setup scores; writes to `signal_ledger` only when `sample_size >= 30` via FEED-02 gate
- `SignalAggregator` — selects winner from `all_ranked`; active signal always derived from `all_ranked` (not raw `signals`) so `perf_weights` affect winner selection

Output stream: `{env}:signals:{symbol}:{tf}:aggregated`
Cold persistence: `signal_ledger` table

---

## Layer 4: AI Intelligence (I8)

### AI Narrative Service (`indicagent-ai-narrative`, :9113)
- Consumes `{env}:intelligence:{symbol}:{tf}` events
- Calls local Ollama Docker (:11434) — AMD Phoenix1 iGPU, 16.3 GiB shared VRAM
  - **qwen3.5:9b** — per-signal narrative synthesis
  - **phi4-mini:3.8b** — group synthesis across multiple signals
- Output stream: `{env}:narratives:{symbol}:{tf}`

### LLM Writer Service (`indicagent-llm-writer`, :9117)
- Reads `{env}:llm_calls:stream` (maxlen=500) — every LLM call (success, failure, counterfactual)
- Reads `{env}:llm_outcomes:stream` (maxlen=200) — signal lifecycle exits with outcome/pnl_r/mae/mfe
- Persists to `llm_calls` hypertable (full audit log per call)
- Back-fills outcome fields on `llm_calls` rows when lifecycle exits arrive
- Maintains `llm_model_scores` table: per-model win_rate, avg_pnl_r, p-value; refreshed every 15 min

---

## Services

All services are systemd-managed with `Restart=always`.

| Service Unit | Purpose | Metrics Port |
|---|---|---|
| `indicagent-tws` | IBKR tick + bar collection, multi-TF aggregation | — |
| `indicagent-indicator` | I1+I2 → `indicators:SYMBOL:TF` | :9109 |
| `indicagent-market-analysis` | I3→I4→I5→SMC→I6 → `intelligence:SYMBOL:TF` | :9114 |
| `indicagent-signal-generator` | I7 → `signals:SYMBOL:TF:aggregated` + `signal_ledger` | :9112 |
| `indicagent-signal-lifecycle` | Zone-aware lifecycle, MAE/MFE tracking, 8-class outcome | :9115 |
| `indicagent-ai-narrative` | I8 LLM → `narratives:SYMBOL:TF` | :9113 |
| `indicagent-feature-writer` | Redis → `intelligence_features` batch writer | :9116 |
| `indicagent-llm-writer` | `llm_calls:stream` → `llm_calls` hypertable + outcome back-fill + score cache | :9117 |
| `indicagent-api` | FastAPI + SSE on :8000 | — |

### Signal Lifecycle Service
`indicagent-signal-lifecycle` replaced the legacy `indicagent-signal-tracker`. It reads live 1m bars and evaluates all pending/active signals per bar with zone-aware activation logic.

**8-class outcome taxonomy:**
- `never_activated` — signal expired without reaching entry zone
- `stopped_at_entry` — stopped out while in entry zone (before full activation)
- `stopped_in_trade` — stopped out after activation
- `target_1` — first partial target hit
- `target_1_2` — both partial targets hit
- `target_full` — full target hit
- `ttl_expired_ahead` — TTL expired with price ahead of entry
- `ttl_expired_behind` — TTL expired with price behind entry

**MAE/MFE** tracked in-memory per signal_id and written to `signal_ledger` on exit.

### Signal Generator Warmup
After restart, `indicagent-signal-generator` requires approximately 50 live 1m bars (~50 minutes) before signals fire. The consumer group is not rewound on restart — warmup proceeds naturally as bars accumulate.

### Feature Writer Service
Dedicated persistence decoupler: reads from Redis streams in batch, writes to `intelligence_features` hypertable. The real-time pipeline (indicator, market analysis, signal generator services) never writes to TimescaleDB directly.

---

## Stream Architecture

All stream keys are constructed via `src/core/stream_keys.py` with environment prefix (`development:` in dev, no prefix in production).

| Stream | Producer | Consumer(s) |
|---|---|---|
| `{env}:market:{symbol}:{tf}` | indicagent-tws | indicator_service, signal_lifecycle_service |
| `{env}:ticks:{symbol}:live` | indicagent-tws | — |
| `{env}:indicators:{symbol}:{tf}` | indicagent-indicator | indicagent-market-analysis |
| `{env}:intelligence:{symbol}:{tf}` | indicagent-market-analysis | indicagent-signal-generator, indicagent-ai-narrative, indicagent-feature-writer |
| `{env}:signals:{symbol}:{tf}:aggregated` | indicagent-signal-generator | indicagent-api (SSE) |
| `{env}:narratives:{symbol}:{tf}` | indicagent-ai-narrative | indicagent-api (SSE) |
| `{env}:llm_calls:stream` | indicagent-ai-narrative | indicagent-llm-writer |
| `{env}:llm_outcomes:stream` | indicagent-signal-lifecycle | indicagent-llm-writer |

**Consumer group gotcha:** `xgroup_create(..., "$")` silently fails when the group already exists — use `ensure_consumer_group_with_reset()` from `src/core/stream_utils`, which calls `xgroup_setid(stream, group, "$")` in the except block to force-reset position.

---

## Hot / Warm / Cold Data Tiers

| Tier | Storage | Latency | Role |
|---|---|---|---|
| Hot | DragonflyDB Streams | sub-ms | Inter-service message bus |
| Warm | Service in-memory state | <10ms | Plugin state, bar history, lifecycle tracking |
| Cold | TimescaleDB | batch, async | ML training dataset, audit log, scoring |

The real-time pipeline never touches TimescaleDB directly. All cold writes go through `feature_writer_service` (features) or `llm_writer_service` (LLM audit).

---

## TimescaleDB Tables

| Table | Purpose | Retention |
|---|---|---|
| `market_data_ohlcv` | Raw OHLCV; populated by backfill only; ground truth | Forever |
| `intelligence_features` | Full feature vectors per bar including I7/I8 JSONB; ML training dataset | Forever |
| `signal_ledger` | I7 signals + lifecycle outcomes (8-class); JOIN to `intelligence_features` on `(symbol, feature_ts, feature_tf)` | Forever |
| `llm_calls` | Full LLM audit log per call; outcome back-filled by llm_writer_service | Forever |
| `llm_model_scores` | Per-model win_rate, avg_pnl_r, p-value; refreshed every 15 min | Rolling |
| `setup_performance` | Per-setup rolling 30d stats (win_rate, avg_pnl_r, sharpe); drives `perf_multiplier` in aggregator; only rows with `sample_size >= 30` written (FEED-02 gate) | Rolling |

Aggregate views: `ohlcv_15m`, `ohlcv_1h`, `ohlcv_4h`, `ohlcv_1d`, `market_data_5m`, `market_data_15m`

---

## Typed Intelligence Bus

`IntelligenceEvent` in `src/intelligence/schemas.py` is the canonical typed event published to `{env}:intelligence:{symbol}:{tf}`. It carries tiered JSONB payloads:

| Field | Content |
|---|---|
| `i1` | Raw indicator values from all 25 I1 plugins |
| `i2` | Second-derivative events from all 10 I2 plugins |
| `i3` | Market structure from all 8 I3 plugins |
| `i4` | Regime context from all 7 I4 plugins |
| `i5` | Pattern signals from all 14 I5 plugins |
| `smc` | Smart money signals from all 13 SMC plugins |
| `i6` | Cross-timeframe confluence score (CTF) |

The full event is persisted as a single row in `intelligence_features` by `feature_writer_service`.

---

## Plugin System

**Total: 95 plugins + 2 aggregation components** across tiers I1–I7.

Plugin tier membership is defined in `src/intelligence/register_plugins.py` (`TIER_I1`…`TIER_I7`) — single source of truth. `registry.validate_tier()` hard-crashes at startup on any missing plugin name.

Plugin state is managed per `(plugin_name, symbol, timeframe)` tuple in service-level dicts (`_plugin_states`, `_i1_plugin_states`). State is swapped onto `p._state` before `compute_full()` and written back after — this write-back is load-bearing for stateful plugins (GARCH, HMM) that fully reassign `_state`.

See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and Ollama provider chain.

---

## Key Files

| File | Purpose |
|---|---|
| `src/intelligence/schemas.py` | `IntelligenceEvent` — canonical typed bus schema |
| `src/core/stream_keys.py` | All Redis stream key construction (env-prefixed) |
| `src/config/settings.py` | `Settings`, `get_active_contracts()`, `Instrument` definitions |
| `src/intelligence/register_plugins.py` | `TIER_I1`…`TIER_I7` tier lists — single source of truth |
| `src/core/database_manager.py` | PostgreSQL/TimescaleDB with connection pooling |
| `src/core/service_utils.py` | `setup_service_logging()`, `min_bars_for_tf()`, `PLUGIN_METRICS_SAMPLE_RATE` |
| `src/providers/ibkr.py` | All ib_insync logic — no imports outside this file |

---

## Related Documentation

- `docs/concepts/intelligence-tiers.md` — I1-I8 intelligence tier specifications
- `docs/reference/schemas/stream-schemas.md` — Stream data formats
- `docs/reference/db-maintenance.md` — DB maintenance runbook
- `src/intelligence/CLAUDE.md` — Plugin protocol and LLM provider chain
- `.planning/ROADMAP.md` — Current milestone phases and backlog
