# IndicAgent

## What This Is

IndicAgent is a real-time market intelligence platform covering 23 instruments across equity index, energy, metals, rates, volatility, agriculture, FX, and crypto. It ingests live tick data, runs a 7-tier plugin pipeline (I1–I8) producing 121 plugins of technical indicators, market structure analysis, pattern detection, smart money concepts, CIS composite scoring, and AI-generated signal narratives. Every intelligence output flows through a canonical typed `IntelligenceEvent` bus persisted to a TimescaleDB feature store with complete i7/i8/days_to_expiry enrichment. Signal integrity is enforced via regime-aware gating, Hurst/Shannon entropy quality gates, Kalman-smoothed CIS, isotonic calibration, and time-of-day Bayesian multipliers. OFI and CVD microstructure features provide order-flow intelligence at I1. A dedicated cross-asset service monitors equity index spread dynamics. Automated futures roll detection propagates contract transitions through the pipeline without restarts.

## Core Value

Every intelligence output — indicator, pattern, signal, narrative — flows through one canonical typed bus that both internal and external consumers can trust.

## Requirements

### Validated

(Shipped and verified in production)

**v1.9 I7 Alpha Engine (2026-03-18):**
- ✓ CIS self-improving learning loop: DB weight loading, binary win labels, asset-cluster segmented logistic regression (5 clusters) — v1.9
- ✓ Structure-first stop architecture in `trade_framer.py`: FVG-priority stops, GARCH-adaptive ATR (0.8×/1.0×/1.35×), stop_basis classification — v1.9
- ✓ Extended divergence stack: 5-input weighted convergence (RSI 0.30, MACD 0.25, vol 0.20, OBV 0.15, CMF 0.10) — v1.9
- ✓ Chandelier trailing stop + staleness decay + shadow tracking for condition_expired signals — v1.9
- ✓ 10 new I7 plugins: FailedBreakout, ORB15, ORB30, PrevDayLevelTest, SecondLegContinuation, VCP, AnchoredVWAPReversion, VWAPReclaim, POCRejection, HVNRejection, LVNBreakout (18 total in this milestone including microstructure + cross-asset) — v1.9
- ✓ I4 AnchoredVWAP + VolumeProfile infrastructure: session/rolling POC/VAH/VAL, AVWAP deviation bands — v1.9
- ✓ Isotonic regression confidence calibration per (plugin, tf); sorted by calibrated_confidence when available — v1.9
- ✓ TOD Bayesian multiplier ∈ [0.7, 1.3] per (regime_type, tf, hour_et), 120 cells — v1.9
- ✓ CIS Kalman filter per (symbol, tf): Q=0.01, R=TF-adaptive; dual fire gate filtered_cis>0.35 AND raw_cis>0.28 AND buckets≥3 — v1.9
- ✓ OFI + CVD I1 indicators: tick/proxy dual-path, EWMA-5/20, spike_z, divergence scores; 7 new I7 microstructure plugins — v1.9
- ✓ CrossAssetService microservice: ES/NQ/RTY/YM spread z-scores, correlation break features; CrossAssetDivergencePlugin I7 — v1.9
- ✓ Automated futures roll detection: volume z-score > 2.0, 3-bar confirmation, TOD adjustment, full pipeline propagation, plugin state migration — v1.9

**v2.1 DAG Extraction — BarAggregatorComputeAgent (2026-03-28):**
- ✓ `is_flat_bar` field in `BarMessage`: BarAccumulator tracks `all_flat` across constituent 1m bars, DataProviderAgent stamps flat-fill path with `True` — downstream consumers can distinguish canonical empty-minute bars — v2.1
- ✓ `BarAggregatorComputeAgent` (`bar_aggregator_agent.py`): standalone DB-ignorant compute node consuming `market.bars`, publishing completed HTF bars to `market.bars.htf`; Golden Signals on :9120; systemd unit installed — v2.1
- ✓ `feature_compute_agent` simplified: BarAccumulator extracted, `_publish_htf_bar()` removed, now subscribes to both `market.bars` (1m) and `market.bars.htf` (completed HTF); pure intelligence consumer — v2.1

**v2.1 Data Foundation & Signal Confidence (2026-03-28):**
- ✓ Live tick aggregation: 5s RTBs → canonical 1m bars via IBKR push; eliminated bars_processed=0 freeze; 3 shared I7 utilities removing 550+ lines of duplication — v2.1
- ✓ Signal ledger completeness: ALL signals written unconditionally regardless of regime suppression; regime_type_at_fire + hmm_regime_at_fire populated for ML segmentation; lifecycle composite index (34ms → <5ms) — v2.1
- ✓ BaseAgent DAG standard: lifecycle contract (setup/teardown, metrics_port, tracer, topic manifest) on all 4 pipeline agents; ProcessManifest replaces singleton AgentRegistry; uniform SIGTERM drain across fleet — v2.1
- ✓ Autonomous shadow parity: FeatureSnapshotWriterAgent dual-writes to shadow table via independent consumer group; ParityAuditorAgent validates 60 consecutive clean cycles before SHADOW_PARITY_CERTIFIED — zero human judgment required — v2.1
- ✓ End-to-end distributed tracing: Grafana Tempo deployed as 6th Docker service; W3C traceparent injected/extracted in Kafka transport (_KafkaHeadersCarrier); bar-to-signal waterfall visible in Grafana Tempo — v2.1
- ✓ Per-layer automated validation: I1→I7 sanity checks on each deploy; signal outcome completeness audit; setup_performance gate verification — v2.1

**v2.0 Signal Integrity & ML Foundation (2026-03-22):**
- ✓ Intelligence pipeline refactored into clean DAG: FeaturePipelineService (I1–I6, 3 hops→1), SignalGeneratorService (6-stage in-process, 8 hops→2), atomic BarIntelligenceRecord INSERT; 18 services → 9 — v2.0
- ✓ DB hardening: `signal_ledger` generated columns, CHECK constraints, composite lifecycle index; `market_data_ohlcv` rebuilt (15,740→21 chunks); data_quality_check.py 15-min timer with 10 Prometheus gauges — v2.0
- ✓ Intelligence gap fill: real FVG/OB CTF alignment (was 0.0 stubs), VP as T1/T2 targets, HTF 1h cache injection; 18 new I5 candlestick patterns with DB-driven weight feedback — v2.0
- ✓ I6 Confluence Expansion: VIXRegimePlugin + CrossAssetContextPlugin in I4; 4 new CTF measurement fields; cross-asset + VIX frame injection into FeaturePipelineService — v2.0
- ✓ All 36 I7 plugins emit `_shadow` dict via `capture_confluence_features()` — ML training data foundation for v2.3 — v2.0
- ✓ Shadow graduation: CROSS_ASSET_ENABLED removed (unconditionally active); regime gate parametrized (REGIME_PROB_MIN/REGIME_DUR_MIN) — v2.0
- ✓ Code quality: SignalStatus + SignalOutcome enums; regime_type Protocol enforcement; pre-commit hooks; 3 production bug fixes; dual topic namespace cleanup — v2.0

**v2.0 Intelligence Gap Fill (2026-03-20):**
- ✓ Cross-TF FVG/OB alignment scores in `CrossTimeframeConfluencePlugin` — `_proximity_decay()` weighted direction-match scores — v2.0
- ✓ Volume Profile as T1/T2 targets in `trade_framer.py` — `_select_vp()` + `_vp_regime_active()` with ATR bypass — v2.0
- ✓ TF guards in 6 VWAP/session plugins — block 1h bars from intraday-only setups (AnchoredVWAPReversion, VWAPReclaim, POCRejection, ORB15, ORB30, PrevDayLevelTest) — v2.0
- ✓ HTF 1h intel cache in `signal_generator_service` — `_htf_intel_cache` + `frames["htf_1h"]` injection (zero new subscriptions) — v2.0
- ✓ `htf_1h_poc_price/vah/val` merged into features before I7 plugin execution — v2.0
- ✓ CRITICAL INVARIANT comment at aggregator `active` derivation — prevents perf_weights bypass — v2.0
- ✓ CRITICAL write-back comments at plugin state loops in market_analysis and indicator services — v2.0

**v2.0 Code Quality Enforcement (2026-03-19):**
- ✓ PatternPlugin `regime_type` enforcement: ClassVar field + runtime validation in `validate_tier()` — v2.0
- ✓ SignalStatus enum: type-safe status literals across 4 files, eliminated typo risk — v2.0
- ✓ SignalOutcome enum: 8-class ML taxonomy with DB CHECK constraint, WIN/STOP/TTL sets consolidated — v2.0
- ✓ Pre-commit hooks: plugin naming, file naming, regime_type validation, dead import detection — v2.0
- ✓ Production bug fixes: VWAP timezone crash, ShannonEntropy NaN/Inf guards, /signals/recent SQL injection hardening — v2.0
- ✓ Dual topic namespace cleanup: 11 orphaned dev.* topics deleted, all services use `stream_keys.py` exclusively — v2.0

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

### Current State (v2.4 Observability Hardening — Phase 68 complete)

- 121 plugins + 2 aggregation (I1: 27, I2: 8, I3: 3, I4: 11, I5: 15, SMC: 11+1 confluence, I7: 36 setups + 2 agg)
- 9 active systemd services: feature-pipeline, signal-generator, signal-lifecycle, ai-narrative, feature-writer, llm-writer, cross-asset, api, gap-fill-timer
- **Phase 053.1 (2026-03-28):** BarWriterAgent + BarAuditorAgent implemented. Bar persistence DAG: `market.bars/htf → BarWriterAgent → market_data_ohlcv`; `BarAuditorAgent → topic_gap_requests → DataProviderAgent (_gap_requests_loop)`. FCA `_ohlcv_buffer` removed (D-08). `gap_fill_service` retired. 25/25 unit tests. 12/12 must-haves verified.
- **Phase 053.3 (2026-03-28):** RollComputeAgent extracted from DataProviderAgent (tws_daemon → data_provider_agent rename). `RollEvent` typed schema (8 fields) + `topic_roll_events()` (`{env}.market.events.roll`). `DataProviderAgent` is now DB-ignorant: no roll detection. `RollComputeAgent(BaseAgent)` owns all roll detection, publishes typed `RollEvent`, Golden Signals on :9122. `signal_generator_agent` migrated from `topic_system_events` to `topic_roll_events`; `parse_roll_event` validates via pydantic `model_validate()`. `ROLL_MONITOR_ENABLED` flag removed. 12/12 must-haves verified.
- **Phase 52.8 (2026-03-28):** W3C trace context propagation wired into Kafka transport layer. `_KafkaHeadersCarrier` adapter bridges OTel propagators to AIOKafka `list[tuple[str, bytes]]` header format. `inject(carrier)` in `KafkaProducerClient.publish()` stamps every outgoing message with `traceparent`. `extract(carrier)` + `otel_context.attach/detach` in `KafkaConsumerClient.messages()` attaches upstream span context before yield, detaches in `finally`. Zero signature changes, zero per-message spans, zero conditional guards — OTel no-op handles disabled tracing. Enables end-to-end bar journey traces in Grafana Tempo (IndicatorComputeAgent → SignalGeneratorAgent → FeatureWriterAgent in single waterfall). 15 unit tests passing.
- **Phase 52.7 (2026-03-28):** Grafana Tempo deployed as 6th Docker Compose service (`grafana/tempo:2.10.3`). OTLP HTTP on port 4318 (host-published for systemd agents), 7-day local retention, separate WAL/traces paths. Grafana datasource provisioned at `tempo:3200` (Docker DNS, not host-published) with service map linked to Prometheus. `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` added to 5 agent systemd unit files (the 4 Phase 52.6 pipeline agents — IndicatorComputeAgent, IntelligenceComputeAgent, SignalGeneratorAgent, FeatureWriterAgent — plus FeatureComputeAgent); `indicagent-intelligence-compute.service` recovered into version control (was deployed but not committed); `PYTHONUNBUFFERED=1` completed across all 10 unit files. Validated: TEMPO-01–05.
- **Phase 52.6 (2026-03-28):** BaseAgent enhanced with lifecycle contract (_setup/_teardown, metrics_port, tracer, topics_consumed/produced, running property, _send_to_dlq). ProcessManifest replaces singleton AgentRegistry. All 4 pipeline agents (IndicatorComputeAgent, SignalGeneratorAgent, IntelligenceComputeAgent, FeatureWriterAgent) migrated to enhanced BaseAgent. init_tracing() in all 4 service entrypoints — OTel spans ready for Phase 52.7 Tempo infra. Validated: AGENT-01–05.
- Signal pipeline: in-process 6-stage pipeline in SignalGeneratorAgent (now BaseAgent) (quality_gate → regime_gate → tod_adjuster → calibrator → ranker → winner_selector); publishes `BarIntelligenceRecord` per bar; single atomic INSERT per bar to `intelligence_features`
- FeaturePipelineService: unified I1–I6 execution, live 1m OHLCV written to `market_data_ohlcv`, cross-asset + VIX frames injected before I6
- All 36 I7 plugins emit `_shadow` dict with I6 ctf_* sub-scores — ML training foundation ready for v2.3
- Cross-asset unconditionally active (CROSS_ASSET_ENABLED flag removed); roll monitor awaiting D-21 re-validation (todo 023 in done — scaffolding removed, operational gate pending)
- `signal_ledger`: 58 fields + generated columns (effective_ts, pipeline_lag_ms) + CHECK constraints + composite lifecycle index
- data_quality_check.py on 15-min systemd timer; 10 Prometheus gauges; IC scores for 3,227 plugin-regime slices

**Infrastructure:** Ollama (:11434, qwen3.5:9b default), PostgreSQL/TimescaleDB (:5432), Redpanda, IBKR TWS at 192.168.1.157:7497

**Known issues / tech debt (v2.0 audit):**
- validate_alpha.py re-run needed for DerivOsc + AC Osc once N≥30 signals accumulate (todo 023)
- trad_DualDivergence IS_SHADOW=True (awaiting live confirmation before promotion — tracked in Phase 50)
- Phase 43 broken CI test: test_held_lock_blocks_concurrent_waiter — threading.Lock migration (tracked in Phase 49)
- 6 zombie DAG unit files in production/systemd/ (hygiene — todo 024)
- Stale Wants=indicagent-indicator.service in feature-writer unit (hygiene — todo 024)
- Two migrations share number 043 — next migration must start at 044

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
| Regime-aware gating on all I7 plugins | Jim Simons: signals that ignore regime are noise — enforce hmm_regime + prob + duration gates | ✓ Good — regime_suppressed shadow signals accumulate counterfactual data for gate tuning |
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
| TOD grouping by (regime_type, tf, hour_et) not per-plugin | 120 cells vs 2,688 per-plugin; faster prior convergence; regimes already capture plugin-level behavior | ✓ Good — fast cold-start with meaningful priors; will revisit per-plugin after 90d data |
| `active` derived from `all_ranked` not raw `signals` | Raw signals never get `adjusted_rank` set; perf_weights have zero effect on winner selection unless derived from all_ranked | ✓ Good — caught during v1.9 and corrected; all callers use all_ranked path |
| trad_DualDivergence IS_SHADOW=True | Requires both OFI + CVD divergence simultaneously — fires rarely; accumulate live data before promoting | — Pending — shadow tracking live; Phase 50 graduation |
| CrossAssetService default CROSS_ASSET_ENABLED=false | New microservice with equity-group-only scope; shadow mode validates data quality before enabling | ✓ Good — graduated in Phase 47; flag removed unconditionally |
| ROLL_MONITOR_ENABLED=false default | Roll detection via volume z-score is a new signal path; shadow mode ensures no unintended service restarts | — Pending — D-21 gate blocked by empty market_data_5m; Phase 50 |
| DAG microservices absorbed in-process (Phase 44.2) | 6 DAG microservices created in Phase 40 → absorbed into SignalGeneratorService; 8 Kafka hops → 2; bounded async audit queue for observability | ✓ Good — net: simpler ops, lower latency, same observability |
| BarIntelligenceRecord single atomic INSERT | Eliminate 2-phase i7/i8 partial-row UPSERT pattern; complete rows at insert time; i8 patched via LLMWriterService UPDATE | ✓ Good — no partial rows, no race conditions |
| VIX + cross-asset promoted to I4 (not I6) | Per-TF VIX z-score in I6 poisoned ML training data (different z per TF for same market moment); macro regime belongs in I4 | ✓ Good — I4Context +4 fields; ML training matrix now has stable vix_z feature |
| _shadow dict capture at I7 with placeholder weights | Capture I6 ctf_* scores into _shadow now; Phase 49 learns weights via ML; zero confidence modification today | ✓ Good — dataset complete; weights deferred avoids premature optimization |

## Constraints

- **Stack**: Python 3.13, FastAPI, DragonflyDB, TimescaleDB, asyncpg — no stack changes
- **No ib_insync outside providers**: All IBKR logic in `src/providers/ibkr.py`
- **No retention on intelligence_features**: Keep indefinitely for seasonal ML
- **IBKR dependency**: Live data requires TWS connection on Windows LAN

## Completed: v2.10 — Data Architecture Evolution (SHIPPED 2026-06-20)

ECL boundary restored (37 I7 plugins intrinsic-only). 51 APR constants externalized. 3-table signal architecture deployed (`signal_events` / `trade_frames` / `trade_executions`; `counterfactual_pnl_r` as ML training target). 1.44M rows migrated from `signal_ledger`. Clean replay run. Type safety enforcement via PG ENUM types. Stop geometry corrected. 12 phases, ~58 plans.

Archive: `.planning/milestones/v2.10-ROADMAP.md`

---

## Current Milestone: v3.0 — Intelligence Vectors (AlphaEngine)

**Goal:** Replace binary I7 signal plugins with continuous IC-weighted score producers. The existing indicator→signal pipeline is excellent feature engineering but has a structural flaw: hand-crafted logic decides when a feature combination constitutes a tradeable edge. Renaissance's insight: measure IC empirically, weight predictors by IC × orthogonality, emit alpha when ensemble CI supports positive EV.

**Architecture decisions (made — not conditional):**
- Renaissance first principles: IC must be demonstrated before any ensemble weight; IC Sharpe (stability) beats raw IC
- AlphaEngine first (V1 Quant: existing 138 I1-I7 plugins); AnalogEngine (pgvector/VIL) deferred until AlphaEngine validated
- Phase 133 (binary corpus rebuild) CANCELLED — IC measurement belongs on `intelligence_features` (all bars), not `signal_events` (selection-biased)
- Design docs: `docs/ideas/signal-08-intelligence-refactor.md` (north star), `docs/plans/2026-06-20-intelligence-vectors-architecture.md` (AlphaEngine technical design)

**Build order (AlphaEngine V1 Quant):**
- Phase 137: IC measurement on existing `signal_events` corpus (exploratory; selection-biased baseline)
- Phase B: Plugin continuous scores — I7 plugins emit `alpha_score` unconditionally alongside binary signal
- Phase C: IC measurement on `intelligence_features` (all bars, unbiased) — this is the real IC
- Phase D: Ensemble layer — IC-weighted aggregation → alpha emission; `alpha_quant` replaces hand-crafted confidence

**After AlphaEngine V1:** V2 Microstructure, V3 Macro, V4 Calendar vectors; then AnalogEngine (VIL/pgvector substrate)

---
## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-18
