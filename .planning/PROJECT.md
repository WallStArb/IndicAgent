# IndicAgent

## What This Is

IndicAgent is a real-time futures trading intelligence platform covering 23 contracts across equity index, energy, metals, rates, volatility, agriculture, FX, and crypto. It ingests live IBKR tick data, runs a 7-tier plugin pipeline (I1–I8) producing 62 plugins of technical indicators, market structure analysis, pattern detection, smart money concepts, CIS composite scoring, and AI-generated signal narratives. Every intelligence output flows through a canonical typed `IntelligenceEvent` bus persisted to a TimescaleDB feature store. A live React dashboard displays all tiers in real time via SSE.

## Core Value

Every intelligence output — indicator, pattern, signal, narrative — flows through one canonical typed bus that both internal and external consumers can trust.

## Requirements

### Validated

(Shipped and verified in production)

**Pre-v1.0 (existing):**
- ✓ Real-time IBKR tick ingestion → 1m bar aggregation — existing
- ✓ Multi-timeframe bar aggregation (1m → 5m/15m/1h/4h/1d) — existing
- ✓ 23 technical indicator plugins (I1 tier) with incremental compute — existing
- ✓ Market structure analysis: I3 swing/S&R/trend, I4 vol/trend/momentum/GARCH/Kalman, I5 patterns/divergence/squeeze, SMC BOS/CHoCH/FVG/order blocks, I6 confluence — existing
- ✓ Signal generation: 9 I7 setup plugins with aggregation → signal_ledger — existing
- ✓ Signal lifecycle tracking with P&L calculation — existing
- ✓ AI narrative generation via Ollama/LangGraph (I8) — existing
- ✓ FastAPI with SSE streaming + historical query endpoints — existing
- ✓ Plugin circuit breaker + Redis state persistence — existing
- ✓ Historical backfill pipeline (IBKR → TimescaleDB) — existing
- ✓ Plugin tier registry as single source of truth with startup validation — existing

**v1.0 MVP (2026-02-28):**
- ✓ GARCH/Kalman quality gates on MeanReversion, VWAPDeviation, SqueezeExpansion — v1.0
- ✓ `IntelligenceEvent` Pydantic schema — typed structured events, tiered JSONB, versioned — v1.0
- ✓ `market_analysis_service.py` sole canonical pipeline — `intelligence_processor_service.py` deleted — v1.0
- ✓ All downstream consumers deserialize `IntelligenceEvent` (signal_generator, API, dashboard) — v1.0
- ✓ `intelligence_features` TimescaleDB hypertable — GIN-indexed, 7-day compression, indefinite retention — v1.0
- ✓ Feature Writer Service — async consumer group batch-writing to `intelligence_features` — v1.0
- ✓ `signal_ledger` feature_ts/feature_tf JOIN columns — v1.0
- ✓ Historical backfill: 413K signals, 482K feature rows, 0 orphans — v1.0
- ✓ Historical query API: GET /api/features/{symbol}/{timeframe}, GET /api/signals/{symbol} — v1.0
- ✓ SSE stream publishes typed `IntelligenceEvent` payloads — v1.0
- ✓ Dashboard live: all 23 contracts qualify, all panels (I1–I8) showing real data — v1.0
- ✓ CIS 6-bucket factor scorer replacing winner-pick aggregator — v1.0
- ✓ 5 new I7 plugins (CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition) — v1.0
- ✓ Adaptive weight learning via logistic regression (weight_updater + cis_weights table) — v1.0
- ✓ at_limit / at_pullback entry types for 4 setup types — v1.0
- ✓ CIS weight updater systemd timer (daily 02:00, Persistent=true) — v1.0
- ✓ Backfill SQL updated for CIS columns — v1.0

### Active

(Next milestone)

- [ ] Dashboard completeness — timeframe matrix wired to per-TF signal data; signal history view; final audit across all symbol profiles
- [ ] i7/i8 columns in intelligence_features — add signal context and narrative to feature rows for richer ML training data
- [ ] ML scoring model — XGBoost/LightGBM trained on intelligence_features + signal_ledger outcomes (needs ~90 days signal history, now accumulating)

### Out of Scope

| Feature | Reason |
|---------|--------|
| Order execution / trade management | Intelligence platform only — no execution engine |
| Portfolio management / position sizing | Out of scope for intelligence layer |
| Real-time latency SLAs / co-location | Not a HFT system; latency target is seconds |
| Full multi-platform build (fundamentals, sentiment, news) | Future milestone — bus designed to accommodate it |
| Auth layer / Cloudflare Tunnel | No external consumers yet; add when Vercel frontend exists |

## Context

**Current state (v1.0, 2026-02-28):**
- 41,300 LOC Python + TypeScript across services, plugins, dashboard
- 62 plugins: 23 I1 indicators + 3 I3 + 5 I4 + 8 I5 + 6 SMC + 1 I6 confluence + 14 I7 trading setups + 2 I7 aggregation
- 787 unit tests passing, 0 ruff errors
- 8 active systemd services + weight-updater timer
- 413K signals and 482K feature rows in TimescaleDB (35-day backfill + live accumulation)
- cis_weights table: version 1 bootstrap weights active; transitions to learned after 100 resolved signals

**Infrastructure:** Ollama (:11434, qwen3:8b default), PostgreSQL/TimescaleDB (:5432), DragonflyDB (:6379), IBKR TWS at 10.0.0.33:7497

**Known issues:**
- indicagent-timeframes.service — legacy, import bug (src.data → src.core), non-blocking
- I3 trend / RSI conf shows stale values in drill panel post-RTH — data display issue, not pipeline failure
- feature_writer_service still uses sequential stream polling (todo: fix to concurrent xreadgroup)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Canonical pipeline: `market_analysis_service.py` only | Eliminate duplicate `intelligence_processor_service.py`; single service, clear ownership | ✓ Good — service deleted Phase 1, pipeline clean |
| `IntelligenceEvent` replaces flat k/v strings | Typed schema enables structured queries, ML feature extraction, external API contracts | ✓ Good — all consumers migrated, no regressions |
| `intelligence_features` hypertable, no retention | Seasonal patterns require long history; TimescaleDB compression manages storage | ✓ Good — 482K rows, 7-day compression active |
| Feature Writer Service as separate process | Decouples persistence from pipeline hot path; consumer group enables fan-out | ✓ Good — async batch writes, metrics on :9116 |
| Plugin state: Redis hash `plugin_state:{symbol}:{tf}:{plugin_name}` | Survives restarts; 7-day TTL prevents stale state | ✓ Implemented (pre-existing, carried forward) |
| `platform` dimension in IntelligenceEvent from day one | Multi-platform future requires bus to partition by platform; retrofitting costly | ✓ Good — platform field in schema |
| CIS 6-bucket factor scorer vs winner-pick | Winner-pick ignores most plugin evidence; factor scorer uses all 14 I7 plugins | ✓ Good — firing signals with full bucket breakdown |
| Adaptive weights via logistic regression | Bootstrap weights → learned weights after 100 resolved signals; no manual tuning | ✓ Good — weight_updater works, timer wired, accumulating training data |
| at_limit / at_pullback entry types for 4 setups | Better RR than entering at current close | ✓ Good — momentum_breakout, squeeze, trend, mtf_alignment all use structural levels |
| Signal aggregator selects one winner per bar | Simple and debuggable; may expose multiple signals per bar in v1.1 | ⚠️ Revisit — single winner may miss concurrent high-conviction setups |
| Auth deferred until external consumer exists | No external consumers; auth adds complexity without benefit today | ✓ Correct deferral |

## Constraints

- **Stack**: Python 3.13, FastAPI, DragonflyDB, TimescaleDB, asyncpg — no stack changes
- **No ib_insync outside providers**: All IBKR logic in `src/providers/ibkr.py`
- **No retention on intelligence_features**: Keep indefinitely for seasonal ML
- **IBKR dependency**: Live data requires TWS connection on Windows LAN

---
*Last updated: 2026-02-28 after v1.0 milestone*
