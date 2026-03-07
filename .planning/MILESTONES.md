# Milestones

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
