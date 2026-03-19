# Requirements: IndicAgent v2.0

**Defined:** 2026-03-19
**Core Value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

## v2.0 Requirements

### DATA — Data Quality + DB Health

- [ ] **DATA-01**: CIS null fields (`cis_score`, `cis_attribution`) repaired in `signal_ledger` for all historical rows recoverable from `intelligence_features`
- [ ] **DATA-02**: `validate_alpha.py --promote` re-run for bootstrap-promoted plugins (DerivOsc, AC Osc) once N >= 30 signals accumulated
- [ ] **DATA-03**: `market_data_ohlcv` rebuilt without space partitioning — chunk count < 200 (from 15,740), aggregate queries < 500ms
- [ ] **DATA-04**: `signal_ledger` composite index for lifecycle UPDATEs — UPDATE latency < 5ms (from 34ms average)
- [ ] **DATA-05**: Gap-fill service detects missing 1m bars in `market_data_ohlcv` during RTH windows and fetches only missing windows from IBKR
- [ ] **DATA-06**: `SignalStatus` enum replaces raw string literals (`"pending"`, `"active"`, `"regime_suppressed"`) across all 5 files

### PERF — Machine Hardening

- [ ] **PERF-01**: `feature_writer_service` polling consolidated to single `xreadgroup` per loop — worst-case lag < 100ms (from 920ms across 92 streams)
- [ ] **PERF-02**: Aggregator `_build_all_ranked()` dirty flag cache — rankings only rebuilt when signals, `perf_weights`, or `drift_penalties` change
- [ ] **PERF-03**: `_seed_bar_history_from_db()` asyncio.Semaphore bounded to pool max_size — eliminates 240 uncapped concurrent DB queries on restart
- [ ] **PERF-04**: Calibration curve breakpoints/values pre-converted to `np.ndarray` at cache load — eliminates per-signal-per-bar numpy allocation
- [ ] **PERF-05**: Refresh loop helper coroutine (`_run_refresh_loop`) standardises shutdown/backoff across all 5 loops in `signal_generator_service`
- [ ] **PERF-06**: Signal lifecycle shadow signals indexed by `(symbol, tf)` key — O(1) per-bar lookup (from O(N) full scan)
- [ ] **PERF-07**: Chandelier trailing stop DB write only fires when stop value actually tightens (not every bar)

### INTEL — Intelligence Gap Fill

- [ ] **INTEL-01**: `i6_fvg_tf_alignment` computed from real cross-TF FVG alignment data (replaces hardcoded `0.0` stub in `cross_timeframe.py`)
- [ ] **INTEL-02**: `i6_ob_tf_alignment` computed from real cross-TF Order Block alignment data (replaces hardcoded `0.0` stub)
- [ ] **INTEL-03**: `trade_framer.py` uses POC, VAH, VAL from I4 `ctx_VolumeProfile` as primary T1/T2 targets when price is near value area boundary
- [ ] **INTEL-04**: Roll premium/discount (`roll_premium_pct = front_price - back_price`) stored in `intelligence_features` for futures symbols near roll dates
- [ ] **INTEL-05**: Higher-timeframe S/R levels (1h POC/VAH/VAL + I6 CTF data) available to I7 plugins via `trade_framer` context for stop/target refinement

### CANDLE — Candlestick Pattern Expansion

- [ ] **CANDLE-01**: 18 new I5 candlestick patterns implemented in `candlestick_patterns.py`: Harami Bull/Bear, Harami Cross Bull/Bear, Dark Cloud Cover, Piercing Line, Three White Soldiers, Three Black Crows, Morning Star, Evening Star, Three Inside Up, Three Inside Down, Bullish/Bearish Abandoned Baby, Tweezer Top/Bottom, Belt Hold Bull/Bear, Kicker Bull/Bear
- [ ] **CANDLE-02**: `CandlestickPatternSetup` I7 plugin extended to consume new high-reliability patterns with confidence weights calibrated per pattern reliability tier

### CONF — I6 Confluence Expansion

- [ ] **CONF-01**: `market_analysis_service` subscribes to `development.cross_asset` topic and injects cross-asset features into frames before I6 execution
- [ ] **CONF-02**: `CrossTimeframeConfluencePlugin` scores VIX regime — high VIX suppresses mean-reversion setups, boosts volatility/breakout setups
- [ ] **CONF-03**: `CrossTimeframeConfluencePlugin` scores equity index sector rotation — ES/NQ/RTY/YM alignment via injected cross-asset spread features
- [ ] **CONF-04**: Cross-TF FVG + OB alignment fields (`i6_fvg_tf_alignment`, `i6_ob_tf_alignment`) contribute to I6 composite score with non-zero weights

### SHADOW — Shadow Mode Graduation

- [ ] **SHADOW-01**: `hmm_regime` gating thresholds (`prob >= 0.60`, `duration >= 5`) empirically validated against accumulated shadow signal outcomes — adjusted if data supports different values
- [ ] **SHADOW-02**: `CROSS_ASSET_ENABLED` set to `true` after shadow monitoring confirms data quality and no unintended effects
- [ ] **SHADOW-03**: `ROLL_MONITOR_ENABLED` set to `true` after paper account validation confirms roll detection accuracy
- [ ] **SHADOW-04**: `trad_DualDivergence` promoted from `IS_SHADOW=True` to live after statistical gate passes (N >= 50 resolved signals, win rate > 50%)

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
| DATA-01 through DATA-06 | Phase 39 | Pending |
| PERF-01 through PERF-07 | Phase 40 | Pending |
| INTEL-01 through INTEL-05 | Phase 41 | Pending |
| CANDLE-01 through CANDLE-02 | Phase 42 | Pending |
| CONF-01 through CONF-04 | Phase 43 | Pending |
| SHADOW-01 through SHADOW-04 | Phase 44 | Pending |
| AUTH-01 through AUTH-06 | Phase 45 | Pending |
| ML-01 through ML-07 | Phase 46 | Pending |

**Coverage:**
- v2.0 requirements: 41 total
- Mapped to phases: 41
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-19*
*Last updated: 2026-03-19 after initial definition*
