# Milestones

## v2.1 Data Foundation & Signal Confidence (Shipped: 2026-03-28)

**Phases completed:** 13 phases (48, 49, 49.1, 49.2, 51, 52.1–52.8)

**Key accomplishments:**

1. **Live tick aggregation + I7 reuse** — 5s RTBs → canonical 1m bars via IBKR push; 3 shared I7 utilities (microstructure, state, volume_profile) removing 550+ lines duplication; 40–60% per-bar latency reduction
2. **Signal ledger completeness** — ALL I7 signals written unconditionally; regime_type_at_fire + hmm_regime_at_fire populated; composite lifecycle index drops UPDATE latency 34ms → <5ms
3. **BaseAgent DAG standard** — Lifecycle contract (setup/teardown, metrics_port, tracer, topic manifest) on all 4 pipeline agents; ProcessManifest replaces singleton AgentRegistry; uniform SIGTERM drain
4. **Autonomous shadow parity** — FeatureSnapshotWriterAgent dual-writes via independent consumer group; ParityAuditorAgent validates 60 consecutive clean cycles before publishing `SHADOW_PARITY_CERTIFIED`
5. **End-to-end distributed tracing** — Grafana Tempo as 6th Docker service; W3C `traceparent` in Kafka transport; bar-to-signal waterfall trace visible across all agents in Grafana Tempo
6. **Per-layer automated validation** — I1→I7 sanity checks run on each deploy; signal outcome completeness audited; setup_performance gate verified

---

## v2.0 Signal Integrity & ML Foundation (Shipped: 2026-03-22)

**Phases completed:** 14 phases, 60 plans, 111 tasks

**Key accomplishments:**

- signal_ledger enriched with effective_ts trigger column, pipeline_lag_ms latency instrumentation, two CHECK constraints, and signal_stats_daily materialized view (33,859 rows) for fast IC computation
- Exit-1 completeness gate added to repair_cis_nulls.py; DATA-02 deferred — 0 resolved outcomes for DerivOsc and AC Osc (N < 30 gate)
- OHLCV hypertable rebuild script with chunk-count/latency verification gate and signal_ledger composite index migration for lifecycle UPDATE performance
- Self-healing gap-fill service detecting missing 1m RTH bars via asyncpg set-diff, fetching from IBKR, inserting with ON CONFLICT DO NOTHING; scheduled daily at 09:20 ET via systemd timer
- signal_performance_segmented table with Pearson IC scores per plugin-regime slice; 3,227 rows written; trad_MeanReversion leads at IC=0.81 (15m); 512/3,227 slices statistically significant
- 1. [Rule 1 - Bug] Fixed no-label Gauge .labels() call
- PatternPlugin Protocol extended with mandatory regime_type field and validate_tier() now hard-crashes service startup if any I7 plugin is missing or has an invalid regime_type value
- One-liner:
- One-liner:
- Before:
- 1. SignalOutcome Enum (`src/intelligence/trading/signal_outcome.py`)
- Hardcoded string scan results:
- CircuitBreaker, DataQualityMonitor, and Stage base class for 6-stage signal pipeline DAG with fault tolerance, schema validation, and attribution emission
- 6 DAG pipeline stage services (QualityGate → RegimeGate → TODAdjuster → Calibrator → Ranker → WinnerSelector) implementing the typed, attributed signal processing chain with circuit breaker protection
- 8 Redpanda pipeline topics and 6 systemd microservices deployed — full DAG stage infrastructure running on :9119–:9124
- Removed:
- Replaced hardcoded 0.0 stubs in CrossTimeframeConfluencePlugin with direction-weighted FVG and Order Block proximity scores across higher timeframes, including per-TF contribution decomposition for full auditability.
- 1. [Rule 1 - Bug] Fixed test scenario with logically inconsistent entry vs POC for near-boundary long test
- 1. [Rule 1 - Bug] TF guard broke all existing tests that don't set frames["timeframe"]
- 1. [Rule 1 - Bug] Fixed incorrect test fixtures from plan spec
- CandlestickPatternSetup I7 plugin extended to read DB-driven pattern weights from frames injection with fallback priors, and 10 new Phase 42 patterns integrated via scalable pattern_flags loop
- Pattern reliability calibration function added to weight_updater.py closing the Renaissance feedback loop, with 7-day ES 1m backtest confirming 4/5 pattern groups (97 tweezer + 85 belt_hold + 17 kicker + 1 harami fires)
- 4 new Python modules establishing shared I7 utility foundation: plugin_utils (no_signal/extract_ohlcv/signal_type helpers), atr_utils (ATR null-guard), confidence_utils ([0.10,0.95] system clamp), utils/common.py (tier-agnostic composites); 58 tests all green
- 1. [Rule 1 - Bug] Test assertions assumed `{}` for insufficient-data paths
- cross_timeframe.py decomposed from 464-line monolith into 3 focused modules (confluence_weights, confluence_alignment, confluence_smc) + 133-line thin orchestrator, with CrossTimeframeConfluencePlugin interface unchanged
- Task 1 — Fix type contracts in all 8 microstructure plugins:
- Task 1 — Plugin wiring (5 transformations):
- 1. [Rule 2 - Missing] Tick buffer from indicator_service
- 1. [Rule 3 - Blocking] Port conflict on metrics endpoint
- Three legacy systemd units deleted, development.indicators Redpanda topic retired, and full 2743-test suite confirmed green — Feature Pipeline Renaissance topology fully clean.
- One-liner:
- One-liner:
- Deleted 6 stage microservice files, stages/ directory, and old stage tests; retired 6 systemd units; SignalGeneratorService running with in-process pipeline confirmed via Prometheus metrics
- 9 pytest-asyncio tests validate the full bar → BarIntelligenceRecord pipeline with mocked I/O — no live infra required
- DB migration adding 11 columns to intelligence_features + FeatureWriterService simplified to single atomic INSERT per bar from BarIntelligenceRecord, eliminating i7/i8 two-phase partial-row writes
- One-liner:
- FeaturePipelineService writes live 1m bars to market_data_ohlcv via async batch (buffer 50, flush 5s, ON CONFLICT DO NOTHING) — market_data_ohlcv is now single OHLCV ground truth
- 1. [Rule 1 - Bug] Fixed broken RankedSignal field names in signal-scorecard.tsx
- One-liner:
- 1. [Rule 1 - Bug] mean_reversion.py already wired
- 15 I7 plugins (SMC family + microstructure family) wired with capture_confluence_features shadow capture and per-plugin exhaustion handling; all emit signal["_shadow"] for Phase 49 ML training
- 10 regression tests verify PERF-04: O(1) active signal index dict lookup and 0.01% chandelier write guard in signal_lifecycle_service
- One-liner:
- `capture_confluence_features()` shadow dict extended to 15 keys with VIX regime and EQ_INDEX sector rotation fields, using None-default semantics per D-06 to distinguish absent data from zero z-scores.
- Two new I4 macro context plugins (VIXRegimePlugin, CrossAssetContextPlugin) registered in TIER_I4; I4Context extended to 97 fields; I6Confluence pass-through removed; CROSS_ASSET_VALID_TFS centralized
- VIX frame injection fixed to VIX_REGIME_TF='1h'; I6 outputs locked by test; capture_signal_features renamed across all 36 I7 plugins with I4 key names
- Query result:
- One-liner:
- Roll monitor graduation checkpoint reached — D-21 validation skipped (market_data_5m empty), ROLL_MONITOR_ENABLED kept false, scaffolding removal deferred to todo 023
- CROSS_ASSET_ENABLED feature flag fully removed from 4 services and Settings — cross-asset intelligence unconditionally active in DAG (SHADOW-02 graduated)
- D-21 validation gate

---

## v1.9 I7 Alpha Engine (Shipped: 2026-03-18)

**Phases completed:** 8 phases (31-38), 23 plans
**Timeline:** 2026-03-16 → 2026-03-18 (2 days)
**Plugins:** 121 + 2 aggregation (was 103) · **Requirements:** 47/47 ✓
**Files changed:** 104 · **LOC delta:** +15,446 / -1,934

**Key accomplishments:**

- CIS self-improving learning loop: binary win/loss labels, asset-cluster logistic regression (5 clusters), `signal_features` hypertable for mid-bar ML snapshots; `is_shadow` column + A/B promotion gate (Phase 31)
- Structure-first stop architecture centralized in `trade_framer.py`: FVG-priority stop, GARCH-adaptive ATR (0.8×/1.0×/1.35×), `stop_basis` logging; Chandelier trailing stop + staleness decay + shadow tracking (Phase 32)
- 5 new I7 setups (FailedBreakout, ORB15, ORB30, PrevDayLevelTest, SecondLegContinuation, VCP) + 5-input divergence stack (RSI 0.30/MACD 0.25/vol 0.20/OBV 0.15/CMF 0.10) (Phase 32-33)
- I4 AnchoredVWAP + VolumeProfile infrastructure: 93-field I4Context; 5 new I7 VWAP/VP plugins (Phase 34)
- Full confidence pipeline: isotonic regression calibration + TOD Bayesian multiplier (120 cells) + CIS Kalman filter (per (symbol, tf), dual fire gate); dashboard shows raw/filtered/calibrated trio (Phase 35)
- OFI + CVD I1 indicators with tick/proxy dual-path; 7 I7 microstructure plugins; IS_SHADOW plugin flag pattern established (Phase 36)
- `cross_asset_service` microservice: ES/NQ/RTY/YM spread z-scores + correlation break; CrossAssetDivergencePlugin I7; shadow mode default (Phase 37)
- Automated futures roll detection: volume z-score + 3-bar confirmation + TOD adjustment; full pipeline propagation; `seed_roll_chain` backfill script (Phase 38)

---

## v1.8 Signal Intelligence (Shipped: 2026-03-13)

**Phases completed:** 2 phases (28-29), 15 plans
**Timeline:** 2026-03-12 → 2026-03-13 (2 days)
**Tests:** 1,659 passing · **Ruff:** 167 errors (E501 line-too-long, non-blocking) · **Plugins:** 103 (101 + 2 agg)
**LOC:** ~69,326 Python · ~8,654 TypeScript · **Files changed:** 147

**Key accomplishments:**

- Signal Scorecard panel: full I7 signal competition in dashboard — all ranked signals with confidence, direction, composite rank, suppression labels, and regime eligibility via SSE `signal_scorecard` event (Phase 28)
- DB signal history in drill panel: `signal_ledger` history loaded on mount, merged with live SSE, deduplicated by `signal_id`; `GET /api/signals/recent` endpoint (Phase 28)
- GARCH/Kalman I4 fields + SMC detail surfaced: volatility regime context + BSL/SSL dist_atr/touches/significance + premium/discount in drill panel (Phase 28)
- Tier tooltips: I1–I8 tier labels show hover explanations for each intelligence tier (Phase 28)
- CIS constituent contributions: per-setup feature score breakdown on every CIS computation — enables future attribution analysis without recomputation (Phase 29)
- Alpha decay + freshness decay: repeated same-setup signals down-weighted; active signal confidence decays as `exp(-λ × bars_since_fire)` — in-memory, ML ground truth preserved (Phase 29)
- HurstExponentPlugin + ShannonEntropyPlugin (I4): Hurst suppresses setups in wrong regime (H>0.65 mean-reversion, H<0.45 trend); Shannon entropy reduces confidence 30–50% during noisy market periods (Phase 29)
- KS + CUSUM drift detection: `drift_monitor_service` background job monitors feature distribution drift (p<0.05) and per-setup win rate degradation; `/api/drift` endpoint exposed; `drift_monitor` TimescaleDB hypertable (Phase 29)

---

## v1.5 Production Hardening (Shipped: 2026-03-10)

**Phases completed:** 5 phases (18-22), 25 plans
**Timeline:** 2026-03-07 → 2026-03-09 (2 days)
**Tests:** 1,318 passing · **Ruff:** 74 errors (E501 line-too-long, non-blocking)
**Plugins:** 91 + 2 aggregation · **LOC:** ~62,600 Python · **Files changed:** 134

**Key accomplishments:**

- Epsilon tolerance (1e-9) for all floating-point comparisons in trade_framer + CIS scorer; all ATR multipliers, regime thresholds, and magic numbers documented as named constants (Phase 18)
- Configurable IBKR/LLM timeouts in Settings; per-key asyncio.Lock() concurrency protection across market_analysis_service, indicator_service, and ai_narrative_service (Phase 18)
- Characterization tests pinning RSI zero-loss behavior (100.0), zero-ATR emergency fallback, and concurrent lock isolation (Phase 19)
- retry_utils.py with exponential backoff + jitter; PluginCircuitBreaker wired to all 4 LLM providers and IBKR provider; circuit breaker Prometheus metrics on all state transitions (Phase 20)
- DataFrame cache invalidated only on buffer capacity exceeded (indicator + market_analysis); CIS scorer numpy/BLAS vectorization; plugin call metrics modulo sampling (PLUGIN_METRICS_SAMPLE_RATE=10) (Phase 21)
- Three-tier I8 narrative redesign: action_tag (deterministic, instant), narrative_short (~500ms), narrative_deep (~5-8s) — concurrent asyncio tasks, independent SSE routing, dashboard progressive disclosure; old single-call path retired (Phase 22)

---

## v1.4 Quant Foundation (Shipped: 2026-03-07)

**Phases completed:** 6 phases (12-17), 29 plans
**Timeline:** 2026-03-04 → 2026-03-07 (4 days)
**Tests:** 1,286 passing · **Ruff:** 34 errors (E501 line-too-long, non-blocking)
**Plugins:** 91 + 2 aggregation · **LOC:** ~59,000 Python

**Key accomplishments:**

- Regime-aware gating on all 17 I7 plugins (hmm_regime + prob≥0.60 + duration≥5 gates); shadow signals track counterfactual MAE/MFE/outcome for empirical gate tuning
- `intelligence_features` enriched with `i7 JSONB` (all_ranked signals per bar), `i8 JSONB` (narrative metadata), `days_to_expiry` — complete, permanent ML training dataset with no missing samples
- `setup_performance` table + daily weight-update job + adaptive aggregator `perf_multiplier` — outperforming setups rank higher automatically; Renaissance promotion gate (n≥30) prevents overfitting
- `validate_alpha.py` statistical promotion gate (Pearson r>0, p<0.05, N≥30 + ADF stationarity) + 4 new live alpha sources: DerivativeOscillator (I2), 10 Candlestick Tier 1 patterns (I5/I7), MACD histogram acceleration (I2), AC Oscillator (I1)
- Full LLM audit log (`llm_calls` TimescaleDB hypertable, every call captured), outcome back-fill from signal lifecycle exits, 15-min `llm_model_scores` recompute, adaptive model routing per regime (Phase 16)
- E2E Flows 3+4 restored by Phase 17: `signal_id` UUID threaded through `signals:aggregated` stream into `llm_calls`, regime vocabulary standardized for score routing

---

## v1.0 MVP (Shipped: 2026-02-28)

**Phases completed:** 9 phases, 29 plans, 4 tasks

**Key accomplishments:**

- 62 plugins + 4 aggregation components + feature store + typed intelligence bus
- 796 tests passing
- 22 contracts active across equity index, energy, metals, rates, volatility, agriculture, FX, crypto
- 8 systemd services + weight-updater timer running in production
- 413K signals + 482K feature rows in TimescaleDB

---

## v1.1 Code Quality Sprint (Shipped: 2026-03-01)

**Phases completed:** 1 phase, 1 plan

**Key accomplishments:**

- Ruff errors: 206 → 0 (entire codebase)
- Tests: 787 → 803 passing
- Service startup: 9.2s → 1-2s (parallel warmup reads)
- 3 pattern files O(N²) → O(N)
- All 6 services use `ensure_consumer_group_with_reset`
- VX contract rolled to VXM6

---

## v1.2 Intelligence Palette Expansion (Shipped: 2026-03-02)

**Phases completed:** 4 phases, 8 tasks

**Key accomplishments:**

- 84 plugins + 2 aggregation components total (I2, I5, I6 expanded within this milestone)
- Tests: 803 → 965 passing (+162 tests)
- I2 composite events: 5 plugins running on I1 features
- I5 patterns: +7 new pattern plugins (CupHandle, FlagPennant, TriangleWedge, HeadShoulders, DoubleTopBottom, Candlestick, MeasuredMove)
- I6 SMC: +5 new SMC plugins (ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount)
- I6 confluence: recency weighting + I2 event scoring (CrossTimeframeConfluence expanded to 10 output fields)
- I1-I6 correctness audit: 35 tests verifying mathematical correctness across tiers
- Code simplification: 5 SMC plugins + refactor review findings addressed
- Documentation: CLAUDE.md updated to v5.10.0, plugin counts aligned

---

## v1.3 Signal Intelligence Expansion (Shipped: 2026-03-04)

**Phases completed:** 4 phases + Signal Lifecycle redesign

**Key accomplishments:**

- 88 plugins + 2 aggregation components (I2: +1 MomentumAcceleration; I7: +3 new setups)
- Tests: 965 → 1083 passing (+118 tests)
- Phase 08: MomentumAcceleration (I2) — RSI/MACD/ROC 2nd-derivative + inflection detection
- Phase 09: GapAnalysisSetup (I7) — opening gap fade/continuation for ES/NQ (3 sub-setups)
- Phase 10: CandlestickPatternSetup (I7) — confluence-gated candlestick setups consuming I5 output
- Phase 11: SessionExtremesSetup (I7) — Asian session H/L fade during London/NY sessions
- Signal Lifecycle redesign: zone-aware activation, MAE/MFE tracking, 8-class outcome classification
- New `signal_lifecycle_service` (replaces `signal_tracker_service`), migration 015

---
