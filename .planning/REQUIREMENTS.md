# Requirements: IndicAgent v2.0

**Defined:** 2026-03-19
**Core Value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

## v2.0 Requirements

### DATA — Data Quality + DB Health

- [x] **DATA-01**: CIS null fields (`cis_score`, `cis_attribution`) repaired in `signal_ledger` for all historical rows recoverable from `intelligence_features`
- [ ] **DATA-02**: `validate_alpha.py --promote` re-run for bootstrap-promoted plugins (DerivOsc, AC Osc) once N >= 30 signals accumulated
- [x] **DATA-03**: `market_data_ohlcv` rebuilt without space partitioning — chunk count < 200 (from 15,740), aggregate queries < 500ms
- [x] **DATA-04**: `signal_ledger` composite index for lifecycle UPDATEs — UPDATE latency < 5ms (from 34ms average)
- [x] **DATA-05**: Gap-fill service detects missing 1m bars in `market_data_ohlcv` during RTH windows and fetches only missing windows from IBKR
- [ ] **DATA-06**: `SignalStatus` enum replaces raw string literals (`"pending"`, `"active"`, `"regime_suppressed"`) across all 5 files
- [ ] **DATA-07**: `SignalOutcome` enum replaces raw outcome string literals across lifecycle_tracker, signal_lifecycle_service, and API routes; DB CHECK constraint enforces valid values
- [x] **DATA-08**: `signal_ledger.effective_ts` generated column — `COALESCE(signal_computed_at, feature_ts) STORED`; replaces ad-hoc COALESCE in all queries; enables index-based ordering
- [x] **DATA-09**: `signal_ledger.pipeline_lag_ms` generated column — epoch milliseconds between feature_ts and signal_computed_at; NULL for unprocessed signals; P95 tracked by data quality monitoring
- [x] **DATA-10**: DB CHECK constraints on `signal_ledger.status` (pending/active/regime_suppressed only) and `signal_ledger.direction` (LONG/SHORT/NULL only); complements code-level enums
- [x] **DATA-11**: `signal_performance_segmented` table stores per-(plugin, timeframe, regime_type, symbol) rolling 30d win rates and IC scores; only rows with sample_size >= 30 written (FEED-02 gate)
- [x] **DATA-12**: Information Coefficient computed via `compute_ic.py` — Pearson r(calibrated_confidence, binary_outcome) per plugin; plugins with IC < 0.05 or p > 0.05 flagged; results written to `signal_performance_segmented`
- [x] **DATA-13**: `data_quality_check.py` scheduled every 15 min via systemd timer; exits 1 on critical violations (null_cis_rate > 1%, staleness > 15 min, P95 lag > 500ms); Prometheus gauges exported for all quality dimensions

### PERF — Machine Hardening

- [x] **PERF-01**: `feature_writer_service` polling consolidated to single `xreadgroup` per loop — worst-case lag < 100ms (from 920ms across 92 streams)
- [x] **PERF-02**: Aggregator `_build_all_ranked()` dirty flag cache — rankings only rebuilt when signals, `perf_weights`, or `drift_penalties` change
- [x] **PERF-03**: `_seed_bar_history_from_db()` asyncio.Semaphore bounded to pool max_size — eliminates 240 uncapped concurrent DB queries on restart
- [x] **PERF-04**: Calibration curve breakpoints/values pre-converted to `np.ndarray` at cache load — eliminates per-signal-per-bar numpy allocation
- [x] **PERF-05**: Refresh loop helper coroutine (`_run_refresh_loop`) standardises shutdown/backoff across all 5 loops in `signal_generator_service`
- [x] **PERF-06**: Signal lifecycle shadow signals indexed by `(symbol, tf)` key — O(1) per-bar lookup (from O(N) full scan)
- [ ] **PERF-07**: Chandelier trailing stop DB write only fires when stop value actually tightens (not every bar)

### INTEL — Intelligence Gap Fill

- [x] **INTEL-01**: `i6_fvg_tf_alignment` computed from real cross-TF FVG alignment data (replaces hardcoded `0.0` stub in `cross_timeframe.py`)
- [x] **INTEL-02**: `i6_ob_tf_alignment` computed from real cross-TF Order Block alignment data (replaces hardcoded `0.0` stub)
- [x] **INTEL-03**: `trade_framer.py` uses POC, VAH, VAL from I4 `ctx_VolumeProfile` as primary T1/T2 targets when price is near value area boundary
- [ ] **INTEL-04**: Roll premium/discount (`roll_premium_pct = front_price - back_price`) stored in `intelligence_features` for futures symbols near roll dates
- [ ] **INTEL-05**: Higher-timeframe S/R levels (1h POC/VAH/VAL + I6 CTF data) available to I7 plugins via `trade_framer` context for stop/target refinement

### CANDLE — Candlestick Pattern Expansion

- [x] **CANDLE-01**: 18 new I5 candlestick patterns implemented in `candlestick_patterns.py`: Harami Bull/Bear, Harami Cross Bull/Bear, Dark Cloud Cover, Piercing Line, Three White Soldiers, Three Black Crows, Morning Star, Evening Star, Three Inside Up, Three Inside Down, Bullish/Bearish Abandoned Baby, Tweezer Top/Bottom, Belt Hold Bull/Bear, Kicker Bull/Bear
- [x] **CANDLE-02**: `CandlestickPatternSetup` I7 plugin extended to consume new high-reliability patterns with confidence weights calibrated per pattern reliability tier

### CONF — I6 Confluence Expansion

- [x] **CONF-01**: `market_analysis_service` subscribes to `development.cross_asset` topic and injects cross-asset features into frames before I6 execution
- [x] **CONF-02**: `CrossTimeframeConfluencePlugin` scores VIX regime — high VIX suppresses mean-reversion setups, boosts volatility/breakout setups
- [x] **CONF-03**: `CrossTimeframeConfluencePlugin` scores equity index sector rotation — ES/NQ/RTY/YM alignment via injected cross-asset spread features
- [x] **CONF-04**: Cross-TF FVG + OB alignment fields (`i6_fvg_tf_alignment`, `i6_ob_tf_alignment`) are exposed as independent I6 output fields in `I6Confluence` — Phase 49 learns the predictive weights via ML training; no formula change to `ctf_score` is needed or desired (D-07: adding weights inside ctf_score would destroy feature separability in the training matrix)
- [x] **CONF-05**: `I6Confluence` exposes four new raw measurement fields (`ctf_vix_level`, `ctf_vix_z`, `ctf_eq_spread_z`, `ctf_eq_pairs_confirming`) populated by `CrossTimeframeConfluencePlugin` via injected `frames["vix"]` and `frames["cross_asset"]`; `vix_context.py` pure function module provides VIX z-score computation; `FeaturePipelineService` subscribes to cross_asset topic and injects both frames before I6 execution
- [x] **CONF-06**: `capture_confluence_features()` in `confidence_utils.py` extended to include all four new I6 fields (`ctf_vix_level`, `ctf_vix_z`, `ctf_eq_spread_z`, `ctf_eq_pairs_confirming`) in the `_shadow` dict; `None` (not `0.0`) when upstream data unavailable

### SHADOW — Shadow Mode Graduation

- [ ] **SHADOW-01**: `hmm_regime` gating thresholds moved from hardcoded constants to Settings fields (`REGIME_PROB_MIN`, `REGIME_DUR_MIN`) with safety-floor defaults (0.30 / 1); empirical threshold optimization deferred to Phase 49 ML (D-03) — safety floor maximizes labeled training data (D-04); if signal_ledger contains N>=200 regime-suppressed outcomes, threshold bucket analysis documented
- [ ] **SHADOW-02**: `CROSS_ASSET_ENABLED` set to `true` after shadow monitoring confirms data quality (7 days non-null cross-asset fields per D-11) and no unintended effects; `cross_asset_enabled` flag and all conditional branches removed from all 4 services after 5-day soak
- [ ] **SHADOW-03**: `ROLL_MONITOR_ENABLED` set to `true` after offline validation confirms roll detection accuracy (>=90% detection, <10% FP per D-21); `roll_monitor_enabled` flag and all conditional branches removed from all 5 services after 5-day soak
- [ ] **SHADOW-04**: `trad_DualDivergence` promoted from `IS_SHADOW=True` to live after statistical gate passes: N>=100 resolved shadow signals AND 95% CI lower bound on E[PnL_R] > 0 (D-07); monitoring infrastructure emits `shadow_*` Prometheus gauges per weight_updater cycle (D-08)

### AUTH — Auth + External Access

- [ ] **AUTH-01**: All API endpoints protected by JWT auth via `require_auth` FastAPI dependency (PyJWT library)
- [ ] **AUTH-02**: Auth session delivered via `HttpOnly; Secure; SameSite=None` cookie — SSE `EventSource` connects with `withCredentials: true`
- [ ] **AUTH-03**: CORS configuration uses explicit origins list (not wildcard) — compatible with `allow_credentials=True`
- [ ] **AUTH-04**: Cloudflare Tunnel routes `api.indicagent.com` → `:8000` and `dash.indicagent.com` → Next.js with SSE buffering mitigated (`disableChunkedEncoding: true`)
- [ ] **AUTH-05**: Next.js dashboard runs as standalone production build (`next build --output=standalone`) managed by systemd unit
- [ ] **AUTH-06**: Auth event logging (login/logout/token refresh/failure) and basic rate limiting on auth endpoints

### ML — ML Scoring Model

- [ ] **ML-01**: `feature_builder.py` extracts fire-time feature snapshot from `signal_features` hypertable — no post-fire columns used (prevents lookahead bias)
- [ ] **ML-02**: `stationarity.py` ADF gate — non-stationary features (ATR, price levels) differenced; bounded oscillators (RSI, CIS score) used as-is
- [ ] **ML-03**: Global LightGBM 4.6.0 model trained on all-regime data + 3 regime-specific models (ranging/trending/volatile) gated at N >= 500 per regime
- [ ] **ML-04**: Walk-forward retraining: 60-day expanding train window, 14-day validation hold-out, retrain every 7 days via systemd timer
- [ ] **ML-05**: `ml_score` written to `signal_ledger` in shadow mode — no influence on pipeline, displayed in dashboard drill panel
- [ ] **ML-06**: ML blend promoted to aggregator multiplier (α=0.20 starting value) after 8-week shadow gate: AUC >= 0.56, Brier < 0.25, Pearson r > 0.20 (p < 0.05), win rate lift > +3% at ml_score > 0.6
- [ ] **ML-07**: SHAP attribution stored per signal in `signal_features` — explains which features drove the ML score

### CODE-Q — Code Quality Enforcement

- [x] **CODE-Q-01**: `PatternPlugin` Protocol declares `regime_type: ClassVar[str]`; `validate_tier()` hard-crashes at startup on invalid values (`"trend"`, `"mean_reversion"`, `"any"` only)
- [x] **CODE-Q-02**: `SignalStatus` enum (`PENDING`, `ACTIVE`, `REGIME_SUPPRESSED`) replaces raw status string literals across 4 services; no raw strings in grep
- [x] **CODE-Q-03**: Pre-commit hooks enforce plugin class naming (`PascalCasePlugin`), file naming (`snake_case.py`), regime_type ClassVar on I7 plugins, and no dead imports (ruff F401)
- [ ] **CODE-Q-04**: `SignalOutcome` enum (8-class taxonomy) replaces raw outcome strings in lifecycle_tracker and signal_lifecycle_service; `signal_outcome.py` is single source of truth for WIN/STOP/TTL sets; DB CHECK constraint enforces valid values
- [x] **CODE-Q-05**: `/signals/recent` tier filtering rewritten as parameterized SQL (no f-string interpolation); single stable query string for all 3 tier values

### BUG — Active Production Bugs

- [x] **BUG-01**: VWAP plugin `utc=True` fix — eliminates `Tz-aware datetime.datetime cannot be converted to datetime64` warnings on every bar for all 61 symbols
- [x] **BUG-02**: ShannonEntropy plugin NaN/Inf guard — eliminates `autodetected range of [nan, nan] is not finite` warnings for symbols with degenerate data sequences

### INFRA — Infrastructure Cleanup

- [x] **INFRA-01**: Orphaned `dev.*` Redpanda topics deleted; all services exclusively use `topic_*()` helpers from `stream_keys.py`; only `development.*` topics remain

## v2.1 Requirements (Deferred)

### Performance
- **PERF-V2**: Plugin pipeline offloaded to `asyncio.to_thread()` — CPU-bound tier execution decoupled from event loop (requires CPU profiling to confirm bottleneck first, `threading.Lock` audit)

### Intelligence
- **INTEL-V2**: BSL/SSL level clusters (list of levels vs single nearest) — schema change, high disruption
- **INTEL-V2**: API keyset pagination on `intelligence_features` export endpoint

### ML
- **ML-V2**: Mixture-of-experts soft blending across regime-specific models (once hard routing proves stable)
- **ML-V2**: Online learning / incremental model updates between weekly retraining cycles

## Out of Scope

| Feature | Reason |
|---------|--------|
| Order execution / trade management | Intelligence platform only |
| Portfolio management / position sizing | Out of scope for intelligence layer |
| Real-time latency SLAs / co-location | Not an HFT system |
| Multi-broker support | Defer until second broker integration needed |
| Mobile app | Web-first |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 through DATA-13 | Phase 39 / 39.1 | Complete |
| PERF-01 through PERF-06 | Phase 43 | Complete |
| PERF-07 | Phase 44+ | Pending |
| INTEL-01 through INTEL-03 | Phase 41 | Complete |
| INTEL-05 | Phase 41 | Complete |
| INTEL-04 | Phase 47 | Pending |
| CANDLE-01 through CANDLE-02 | Phase 42 | Complete |
| SHADOW-01 through SHADOW-04 | Phase 47 | Pending |
| AUTH-01 through AUTH-06 | Phase 45 | Pending |
| ML-01 through ML-07 | Phase 46 | Pending |

**Coverage:**
- v2.0 requirements: 41 total
- Mapped to phases: 41
- Unmapped: 0

---
*Requirements defined: 2026-03-19*
*Last updated: 2026-03-22 — SHADOW-01/04 definitions updated per Phase 47 D-01/D-07 locked decisions; SHADOW-02/03 expanded with graduation criteria; traceability updated Phase 44 -> Phase 47*
