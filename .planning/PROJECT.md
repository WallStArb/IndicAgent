# IndicAgent

## What This Is

IndicAgent is a real-time market intelligence platform covering 23 instruments across equity index, energy, metals, rates, volatility, agriculture, FX, and crypto. It ingests live IBKR tick data, runs a 7-tier plugin pipeline (I1–I8) producing 91 plugins of technical indicators, market structure analysis, pattern detection, smart money concepts, CIS composite scoring, and AI-generated signal narratives. Every intelligence output flows through a canonical typed `IntelligenceEvent` bus persisted to a TimescaleDB feature store with complete i7/i8/days_to_expiry enrichment. Signal integrity is enforced via regime-aware gating; setup performance feeds back adaptively into aggregator rankings. A live React dashboard displays all tiers in real time via SSE.

## Core Value

Every intelligence output — indicator, pattern, signal, narrative — flows through one canonical typed bus that both internal and external consumers can trust.

## Requirements

### Validated

(Shipped and verified in production)

**v1.4 Quant Foundation (2026-03-07):**
- ✓ Regime-aware I7 gating: hmm_regime type + prob≥0.60 + duration≥5 gates on all 17 setups — v1.4
- ✓ Shadow signals: regime-suppressed signals tracked in signal_ledger with counterfactual MAE/MFE/outcome — v1.4
- ✓ `intelligence_features.i7 JSONB` — all_ranked signals per bar, enriched via intelligence_i7 stream — v1.4
- ✓ `intelligence_features.i8 JSONB` — AI narrative metadata per bar, enriched via intelligence_i8 stream — v1.4
- ✓ `intelligence_features.days_to_expiry` — futures roll proximity signal at write time — v1.4
- ✓ `feature_writer_service` concurrent xreadgroup (enrich loop) — eliminates worst-case 9.2s polling lag — v1.4
- ✓ `setup_performance` table + daily weight-update job + promotion gate (n≥30) — v1.4
- ✓ Aggregator `perf_multiplier` primary sort key — outperforming setups rank higher automatically — v1.4
- ✓ `validate_alpha.py` statistical promotion gate (Pearson r>0, p<0.05, N≥30 + ADF) — v1.4
- ✓ DerivativeOscillatorPlugin (I2) — Constance Brown EMA5→EMA3→SMA9, live — v1.4
- ✓ 10 Candlestick Tier 1 patterns in I5 + I7 (Three White/Black Soldiers, Morning/Evening Star, Three Inside Up/Down, Harami Cross, Dark Cloud Cover, Piercing Line) — v1.4
- ✓ `macd_hist_accel` + `macd_hist_contracting` in MACDEventsPlugin — v1.4
- ✓ ACOscillatorPlugin (I1) — Bill Williams AO + AC — v1.4
- ✓ `llm_calls` TimescaleDB hypertable — full LLM audit log, partitioned by called_at — v1.4
- ✓ `llm_writer_service` — batch INSERT, outcome back-fill, 15-min score recompute — v1.4
- ✓ `llm_model_scores` — per-model win rate/avg_pnl_r/p-value refreshed every 15 min — v1.4
- ✓ Adaptive LLM model routing per call_type + regime (is_significant gate: n≥30, p<0.05) — v1.4
- ✓ `signal_id` UUID threaded through signals:aggregated → llm_calls.signal_id; outcome back-fill WHERE clause works — v1.4
- ✓ SessionExtremesSetup regime vocabulary standardized (session_extreme_london/ny/both) — v1.4

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
- ✓ Dashboard live: all 23 instruments qualify, all panels (I1–I8) showing real data — v1.0
- ✓ CIS 6-bucket factor scorer replacing winner-pick aggregator — v1.0
- ✓ 5 new I7 plugins (CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition) — v1.0
- ✓ Adaptive weight learning via logistic regression (weight_updater + cis_weights table) — v1.0
- ✓ at_limit / at_pullback entry types for 4 setup types — v1.0
- ✓ CIS weight updater systemd timer (daily 02:00, Persistent=true) — v1.0
- ✓ Backfill SQL updated for CIS columns — v1.0

### Active

**v1.5 Production Hardening (2026-03-08):**

Financial safety, concurrency safety, external API resilience, and efficiency improvements:

- [ ] Epsilon tolerance on floating-point comparisons (trade_framer.py, cis_scorer.py)
- [ ] Document magic numbers as named constants (ATR multipliers, regime thresholds)
- [ ] Configurable timeouts for IBKR/LLM providers in Settings
- [ ] asyncio.Lock() for shared state access (market_analysis_service, indicator_service, ai_narrative_service)
- [ ] PluginCircuitBreaker integration for IBKR and LLM providers
- [ ] retry_utils.py with exponential backoff and jitter
- [ ] Characterization tests for division safety, floating precision, concurrent access
- [ ] Plugin state cache persistence optimization
- [ ] CIS scorer vectorization
- [ ] Plugin call metrics sampling

---

**v1.4 Quant Foundation (2026-03-07):**

### Out of Scope

| Feature | Reason |
|---------|--------|
| Order execution / trade management | Intelligence platform only — no execution engine |
| Portfolio management / position sizing | Out of scope for intelligence layer |
| Real-time latency SLAs / co-location | Not a HFT system; latency target is seconds |
| Full multi-platform build (fundamentals, sentiment, news) | Future milestone — bus designed to accommodate it |
| Auth layer / Cloudflare Tunnel | No external consumers yet; add when Vercel frontend exists |

## Context

### Current State (v1.4 shipped 2026-03-07)

- 91 plugins + 2 aggregation components (I1: 24, I2: 8, I3: 3, I4: 5, I5: 24, SMC: 11+1 confluence, I7: 17 setups + 2 agg)
- 1,286 unit tests passing · Ruff: 34 errors (E501 line-too-long, non-blocking)
- 10 active systemd services + weight-updater timer
- `intelligence_features`: complete feature vectors per bar — i7/i8 JSONB + days_to_expiry live
- `signal_ledger`: labeled outcome data accumulating (8-class, MAE/MFE, regime status)
- `setup_performance`: rolling 30-day setup analytics feeding adaptive aggregator weights
- `llm_calls`: full LLM audit log — 3 call paths captured, outcome back-fill live
- `validate_alpha.py`: Pearson+ADF statistical gate for all new alpha sources
- 4 new alpha sources live: DerivOsc (I2), 10 Candlestick Tier 1 (I5/I7), MACD accel (I2), AC Osc (I1)
- Shadow signals: regime-suppressed counterfactual data accumulating for gate tuning

**Infrastructure:** Ollama (:11434, qwen3.5:9b default), PostgreSQL/TimescaleDB (:5432), DragonflyDB (:6379), IBKR TWS at 10.0.0.33:7497

**Known issues:**
- indicagent-timeframes.service — legacy, import bug (src.data → src.core), non-blocking
- feature_writer_service base loop still uses sequential stream polling (enrich loop is concurrent); pre-existing todo

**Next milestone candidates:** Dashboard Complete (timeframe matrix, signal history), ML Scoring Model (needs ~90 days labeled outcomes), Orderflow Integration, Auth + External Access

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
| Regime-aware gating on all I7 plugins | Jim Simons: signals that ignore market state are noise — enforce hmm_regime + prob + duration gates | ✓ Good — regime_suppressed shadow signals accumulate counterfactual data for gate tuning |
| Shadow signals → signal_ledger (not discarded) | Cannot validate gate thresholds without observability into suppressed signals | ✓ Good — counterfactual MAE/MFE/outcome tracked, empirical gate tuning enabled |
| Validated alpha via validate_alpha.py gate | Renaissance: discard unless statistically proven (Pearson r>0, p<0.05, N≥30) | ✓ Good — bootstrap policy for data-absent correct implementations; re-run after data accumulates |
| Bootstrap policy for new plugins without live data | Chicken-and-egg: plugin must be registered before data accumulates; verdict=BOOTSTRAP + audit trail | ✓ Good — avoids permanently blocking correct implementations waiting for live data |
| perf_multiplier as primary aggregator sort key | Flat formula (composite_rank × multiplier) let priority dominate, breaking performance ranking | ✓ Good — multiplier as primary key, SETUP_PRIORITY only as tiebreaker; outperformers rank first |
| signal_id UUID threaded through signals:aggregated | Without ledger UUID in stream, llm_calls.signal_id=NULL; outcome back-fill WHERE clause matches 0 rows | ✓ Good — xdel compensates on DB failure to avoid orphaned signal_ids |
| Canonical regime vocabulary for LLM routing | Raw plugin regime_context ('bullish') ≠ score cache keys ('trending') → cache miss on every lookup | ✓ Good — SessionExtremesSetup uses session_extreme_* as vocabulary; others use canonical trending/ranging/volatile |

## Constraints

- **Stack**: Python 3.13, FastAPI, DragonflyDB, TimescaleDB, asyncpg — no stack changes
- **No ib_insync outside providers**: All IBKR logic in `src/providers/ibkr.py`
- **No retention on intelligence_features**: Keep indefinitely for seasonal ML
- **IBKR dependency**: Live data requires TWS connection on Windows LAN

---
*Last updated: 2026-03-08 after v1.5 milestone definition*
