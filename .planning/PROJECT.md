# IndicAgent

## What This Is

IndicAgent is a real-time market intelligence platform covering 23 instruments across equity index, energy, metals, rates, volatility, agriculture, FX, and crypto. It ingests live IBKR tick data, runs a 7-tier plugin pipeline (I1–I8) producing 103 plugins of technical indicators, market structure analysis, pattern detection, smart money concepts, CIS composite scoring, and AI-generated signal narratives. Every intelligence output flows through a canonical typed `IntelligenceEvent` bus persisted to a TimescaleDB feature store with complete i7/i8/days_to_expiry enrichment. Signal integrity is enforced via regime-aware gating, Hurst/Shannon entropy quality gates, and freshness decay; setup performance feeds back adaptively into aggregator rankings. A live React dashboard displays all tiers in real time via SSE including Signal Scorecard, signal history, GARCH/Kalman context, and SMC detail fields. A drift detection service monitors feature distribution health and per-setup win rate degradation.

## Core Value

Every intelligence output — indicator, pattern, signal, narrative — flows through one canonical typed bus that both internal and external consumers can trust.

## Requirements

### Validated

(Shipped and verified in production)

**v1.8 Signal Intelligence (2026-03-13):**
- ✓ Signal Scorecard panel: I7 all-ranked signals with confidence, direction, composite rank, suppression labels via SSE `signal_scorecard` event — v1.8
- ✓ Drill panel DB signal history: `signal_ledger` loaded on mount, merged with SSE, deduplicated by `signal_id`; `GET /api/signals/recent` — v1.8
- ✓ GARCH/Kalman I4 fields + SMC BSL/SSL detail + premium/discount surfaced in drill panel — v1.8
- ✓ Tier tooltips: I1–I8 labels show hover explanations — v1.8
- ✓ CIS constituent contributions JSONB: per-setup feature score breakdown on every computation — v1.8
- ✓ Alpha decay (QUAL-02): repeated same-setup same-direction signals down-weighted within `alpha_half_life` bars — v1.8
- ✓ Freshness decay (QUAL-03): active signal confidence decays as `exp(-λ × bars_since_fire)`; in-memory, ML ground truth unchanged — v1.8
- ✓ Per-setup cooldown (QUAL-04): same setup/direction blocked within `_SIGNAL_COOLDOWN_BARS` (1m=3, 5m+=2) — v1.8
- ✓ rel_volume CIS boost/suppress (QUAL-05): rel_volume > 1.5 → boost, < 0.5 → suppress in momentum bucket — v1.8
- ✓ Killzone CIS gate (QUAL-06): confidence boosted during London/NY opens, reduced in dead sessions — v1.8
- ✓ HurstExponentPlugin I4 (QUAL-07): H > 0.65 suppresses mean-reversion; H < 0.45 suppresses trend setups — v1.8
- ✓ ShannonEntropyPlugin I4 (QUAL-08): high entropy reduces all signal confidence 30–50% as universal noise gate — v1.8
- ✓ KS drift detection (QUAL-09): background `drift_monitor_service` compares feature distributions to baseline; emits flag when p < 0.05; `drift_monitor` hypertable — v1.8
- ✓ CUSUM drift detection (QUAL-10): detects per-setup win rate degradation vs baseline; `CUSUMMonitor` wired into `weight_updater`; `/api/drift` endpoint — v1.8

**v1.7 Data Integrity (2026-03-12):**
- ✓ `historical_backfill.py` passes `features=` kwarg → CIS fields populated on new backfill runs — v1.7
- ✓ `repair_cis_nulls.py` audit+repair script: NULL count query, batch UPDATE recoverable rows, log orphans — v1.7 (code complete; infra execution blocked by PostgreSQL shared memory)
- ✓ Signal generator DB seed: `_seed_bar_history_from_db()` seeds bar_history from `intelligence_features` at startup; eliminates 50-min warmup wait — v1.7
- ✓ `_publish_terminal_event()` in `signal_lifecycle_service`: direction=0 event with signal_id/status/outcome/exit_price on every exit — v1.7
- ✓ SSE snapshot age filter: entries older than `2×TF` skipped on reconnect — v1.7
- ✓ `GET /api/signals/{symbol}?timeframe=` correctly filters to specific TF (was silently ignored) — v1.7
- ✓ Dashboard resolved signal state: dimmed + outcome badge (EXPIRED/STOPPED/T1 HIT/T1+T2 HIT/FULL TARGET) matched by signal_id — v1.7

**v1.6 Signal Quality (2026-03-10):**
- ✓ Signal generator onset detection: `_check_gate()` suppresses repeated fires when condition is already true — only onset triggers a signal — v1.6
- ✓ Direction flip suppression: cross-bar memory prevents immediate reversal signals — v1.6
- ✓ 4h/1d TF exclusion documented as day-trading scope boundary; `InputSpec.timeframe='.*'` dead-code intent made explicit — v1.6
- ✓ HMAPlugin (I1) registered as 25th indicator; `hma_slope` and `hma_accel` live in pipeline — v1.6
- ✓ ExhaustionScore (I2) + AccelerationRegime (I2): RSI-gated exhaustion vote + 4-vote acceleration regime — v1.6
- ✓ SwingMomentumPlugin (I3): HMA-based swing momentum detection — v1.6
- ✓ Exhaustion boost/guard wired into MomentumBreakout + TrendFollowing + 2 other I7 setups — v1.6

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

**v1.5 Production Hardening (2026-03-10):**
- ✓ Epsilon tolerance (1e-9) for all float comparisons in trade_framer.py and CIS scorer — v1.5
- ✓ All ATR multipliers, regime thresholds, RSI zero-loss guard documented as named constants — v1.5
- ✓ Configurable ibkr_timeout_sec / llm_timeout_sec in Settings; all providers use Settings values — v1.5
- ✓ per-key asyncio.Lock() in market_analysis_service, indicator_service, ai_narrative_service — v1.5
- ✓ PluginCircuitBreaker for all 4 LLM providers and IBKR provider — v1.5
- ✓ retry_utils.py: exponential_backoff_with_jitter() + retry_with_backoff() async wrapper — v1.5
- ✓ Characterization tests: RSI zero-loss (100.0), zero-ATR fallback, concurrent lock isolation — v1.5
- ✓ DataFrame cache invalidated only on buffer overflow (indicator + market_analysis services) — v1.5
- ✓ CIS scorer: numpy/BLAS vectorized weighted aggregation — v1.5
- ✓ Plugin call metrics: modulo sampling (PLUGIN_METRICS_SAMPLE_RATE=10), errors always recorded — v1.5
- ✓ Three-tier I8 narrative: action_tag (instant) + narrative_short (~500ms) + narrative_deep (~5-8s) — v1.5
- ✓ Concurrent asyncio tasks for narrative_short / narrative_deep; independent SSE routing — v1.5
- ✓ Dashboard progressive disclosure: action_tag badge → short narrative → expandable deep — v1.5
- ✓ Old single-call per_signal path retired cleanly — v1.5

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

### Current State (v1.8 shipped 2026-03-13)

- 103 plugins + 2 aggregation components (I1: 24, I2: 8, I3: 3, I4: 7, I5: 24, SMC: 11+1 confluence, I7: 17 setups + 2 agg); +2 I4 plugins: HurstExponentPlugin, ShannonEntropyPlugin
- 1,659 unit tests passing · Ruff: 167 errors (E501 line-too-long, non-blocking)
- 11 active systemd services + weight-updater timer (new: `indicagent-drift-monitor`)
- `intelligence_features`: complete feature vectors per bar — i7/i8 JSONB + days_to_expiry live
- `signal_ledger`: labeled outcome data accumulating (8-class, MAE/MFE, regime status); constituent_contributions JSONB in CIS
- `setup_performance`: rolling 30-day setup analytics feeding adaptive aggregator weights
- `llm_calls`: full LLM audit log — narrative_short + narrative_deep paths captured, outcome back-fill live
- `llm_model_scores`: per-model win rate/avg_pnl_r/p-value refreshed every 15 min
- `drift_monitor` hypertable: KS p-values per feature tracked over time; CUSUM alerting for win rate drift
- Dashboard: Signal Scorecard (I7 all-ranked), signal history from DB + SSE, GARCH/Kalman/SMC fields, tier tooltips, resolved outcome badges
- Signal quality layer: alpha decay, freshness decay, per-setup cooldown, vol/killzone CIS gates, Hurst/Shannon I4 gates

**Infrastructure:** Ollama (:11434, qwen3.5:9b default), PostgreSQL/TimescaleDB (:5432), DragonflyDB (:6379), IBKR TWS at 10.0.0.33:7497

**Known issues / tech debt:**
- indicagent-timeframes.service — legacy, import bug (src.data → src.core), non-blocking
- feature_writer_service base loop still uses sequential stream polling (enrich loop is concurrent); pre-existing todo
- CIS NULL repair: `repair_cis_nulls.py` code complete + tested; blocked by PostgreSQL shared memory error on 1.8M row JOIN; batch-by-symbol workaround not yet attempted
- SIG requirements (SIG-01 to SIG-05): delivered in v1.7 but never checked off in REQUIREMENTS.md (now archived)
- 24 systemd service contracts registered (CLAUDE.md)

**Next milestone candidates:** LLM call tracking improvements, candlestick pattern expansion (18 patterns), ML scoring model (needs ~90 days labeled outcomes), Auth + External Access

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
| EPSILON_TOLERANCE = 1e-9 for all float comparisons | Financial math: floating-point equality is unreliable; explicit epsilon tolerance prevents degenerate stops and direction misclassification | ✓ Good — trade_framer + CIS scorer + RSI guard all use named constant |
| per-key asyncio.Lock() for shared plugin state | Shared state dicts accessed from concurrent tasks; per-key granularity allows parallelism across symbols while protecting individual state | ✓ Good — market_analysis, indicator, ai_narrative all hardened |
| Module-level circuit breaker singletons (IBKR + LLM) | Failure history must persist across chain iterations; module scope is natural singleton for one connection (IBKR) or provider pool (LLM) | ✓ Good — state transitions emit Prometheus metrics |
| Three-tier I8 narrative: action_tag + short + deep | Single blocking LLM call per signal left dashboard waiting; tier separation delivers instant tag, fast short, deferred deep independently | ✓ Good — concurrent asyncio.create_task() fires both without blocking processing loop |
| narrative_short/narrative_deep as independent stream messages | Routing in dashboard and llm_writer_service based on narrative_type field; no coupling between tier arrivals | ✓ Good — spread-merge SSE pattern handles async arrival; backward-compat via narrative alias |
| Freshness decay in-memory only; ML ground truth never mutated | Decaying signal_ledger.confidence would corrupt the labeled training dataset — future ML must compute decay at inference time | ✓ Good — original confidence preserved; decay_half_life constants documented for replay |
| intelligence_i7 SSE domain check before intelligence: check | startswith("intelligence:") would shadow intelligence_i7: stream — ordering is load-bearing | ✓ Good — explicit ordering in known_domains + test coverage prevents regression |
| CIS bucket methods return (float, dict) tuple | Constituent contributions needed without changing public score() signature; tuple return unpacks cleanly | ✓ Good — zero consumer breakage; contribution keys use feature names for direct attribution |
| KS drift in "warming up" state until baseline fills | Cannot compute meaningful KS p-values without a reference window; warming-up state is explicit vs silent wrong results | ✓ Good — service self-reports warming_up=True until baseline_size bars accumulated |
| CUSUM integrated into weight_updater (not separate service) | Weight update job already reads setup_performance; CUSUM requires the same data; single process avoids scheduling drift | ✓ Good — CUSUM runs at same 15-min cadence as weight updates |

## Constraints

- **Stack**: Python 3.13, FastAPI, DragonflyDB, TimescaleDB, asyncpg — no stack changes
- **No ib_insync outside providers**: All IBKR logic in `src/providers/ibkr.py`
- **No retention on intelligence_features**: Keep indefinitely for seasonal ML
- **IBKR dependency**: Live data requires TWS connection on Windows LAN

---
*Last updated: 2026-03-13 after v1.8 milestone*
