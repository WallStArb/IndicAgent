# Milestones

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
