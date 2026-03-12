# Requirements: IndicAgent v1.8 Signal Intelligence

**Defined:** 2026-03-11
**Core Value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

## v1 Requirements

### Signal Lifecycle Stream Events (Phase 27)

- [ ] **SIG-01**: `signal_lifecycle_service` publishes a `direction=0` terminal event to `signals:SYMBOL:TF:aggregated` on every signal exit, containing `signal_id`, `status`, `outcome`, and `exit_price`
- [ ] **SIG-02**: Dashboard renders a resolved signal as dimmed with an outcome badge (`EXPIRED` / `STOPPED` / `T1 HIT` / `T1+T2 HIT` / `FULL TARGET`) matched by `signal_id`
- [ ] **SIG-03**: Resolved events for preempted signals (signal B replaced A before A exited) are silently ignored — no stale badge shown
- [ ] **SIG-04**: On SSE reconnect, signal stream entries older than `2×TF` are skipped — no stale signal replays on page load
- [ ] **SIG-05**: `GET /api/signals/{symbol}?timeframe=5m` correctly filters to 5m signals only (was previously accepted but silently ignored)

### Dashboard Completion (Phase 28)

- [x] **DASH-01**: SSE subscribes to `intelligence_i7:SYMBOL:TF` stream and emits a `signal_scorecard` event per bar
- [ ] **DASH-02**: Drill panel shows a Signal Scorecard — all ranked signals for the current bar with confidence, direction, composite rank, regime eligibility, and suppression reason
- [x] **DASH-03**: Suppressed signals display a human-readable suppression label (`< 60% conf` / `< 5 bars` / `wrong regime`)
- [ ] **DASH-04**: `GET /api/signals/recent?symbol=&timeframe=&limit=` returns recent signals from `signal_ledger` for drill panel history
- [ ] **DASH-05**: Drill panel signal history loads from DB on open and merges with live SSE history, deduplicated by `signal_id`
- [ ] **DASH-06**: Drill panel surfaces GARCH/Kalman I4 fields (`garch_sigma`, `garch_vol_ratio`, `garch_vol_regime`, `kalman_trend`, `kalman_slope`, `kalman_price_position`)
- [ ] **DASH-07**: Drill panel surfaces remaining SMC fields: BSL/SSL detail (`dist_atr`, `touches`, `significance`) and premium/discount (`price_in_premium`, `premium_discount_pct`, `equilibrium_level`)
- [ ] **DASH-08**: Tier labels (I1–I8) show hover tooltips explaining what each tier is and how to interpret it

### Renaissance Signal Quality (Phase 29)

- [x] **QUAL-01**: `cis_scorer.py` populates `constituent_contributions` JSONB with per-setup scores for each bucket — no longer always empty
- [ ] **QUAL-02**: Alpha decay multiplier applied in aggregator: repeated same-direction signals from the same setup within `alpha_half_life` bars are down-weighted
- [ ] **QUAL-03**: Signal freshness exponential decay applied in `signal_lifecycle_service`: active signal confidence decays as `exp(-λ × bars_since_fire)`
- [ ] **QUAL-04**: Per-setup cooldown window prevents the same setup firing in the same direction within `_SIGNAL_COOLDOWN_BARS` (3 bars for 1m, 2 bars for 5m+)
- [ ] **QUAL-05**: `rel_volume` (already in I1) wired into CIS momentum bucket: boost when `rel_volume > 1.5`, suppress when `< 0.5`
- [ ] **QUAL-06**: Killzone context wired as CIS time-of-day gate: confidence boosted during killzone opens (London/NY), reduced in dead sessions
- [ ] **QUAL-07**: `HurstExponentPlugin` (I4) computes rolling Hurst exponent; H > 0.65 suppresses mean-reversion setups; H < 0.45 suppresses trend setups
- [ ] **QUAL-08**: `ShannonEntropyPlugin` (I4) computes rolling return entropy; high entropy reduces all signal confidence by 30–50% as a universal noise gate
- [ ] **QUAL-09**: KS distribution drift detection — periodic background job comparing current I1/I4 feature distributions to a baseline reference window; emits monitoring flag when KS p-value < 0.05 on key features; operates in "warming up" state until baseline window is filled
- [ ] **QUAL-10**: CUSUM performance drift detection — detects when per-setup win rates are degrading relative to historical baseline; alerts before losses accumulate; uses `setup_performance` data (setups with N≥30 already active)

### LLM Call Tracking (Phase 31)

- [ ] **LLM-01**: Real token counts (`prompt_eval_count` / `eval_count`) read from Ollama response and stored in `llm_calls` as `tokens_in` / `tokens_out`
- [ ] **LLM-02**: Failed LLM calls store the exception message or HTTP error in an `error_message` column — no more silent `succeeded=False` with no detail
- [ ] **LLM-03**: `cis_score`, `entry_zone_low`, `entry_zone_high` populated in `llm_calls` — values are available in the narrative context but currently not written
- [ ] **LLM-04**: `temperature` and `max_tokens` logged per call in a `request_params` JSONB column

### Candlestick Expansion (Phase 32)

**Tier 1 — 10 new output fields:**
- [ ] **CNDL-01**: `harami_bull` / `harami_bear` — small body inside prior body, directional color check
- [ ] **CNDL-02**: `harami_cross_bull` / `harami_cross_bear` — harami condition + doji body (< 10% of range)
- [ ] **CNDL-03**: `dark_cloud_cover` — prior bullish, open above prior high, close below prior body midpoint
- [ ] **CNDL-04**: `piercing_line` — prior bearish, open below prior low, close above prior body midpoint
- [ ] **CNDL-05**: `three_white_soldiers` — 3 consecutive bullish bars, each opening within prior body
- [ ] **CNDL-06**: `three_black_crows` — 3 consecutive bearish bars, each opening within prior body
- [ ] **CNDL-07**: `morning_star` — bearish + small body/doji + bullish closing above prior midpoint
- [ ] **CNDL-08**: `evening_star` — bullish + small body/doji + bearish closing below prior midpoint

**Tier 2 — 8 new output fields:**
- [ ] **CNDL-09**: `dragonfly_doji` — open ≈ high ≈ close, long lower wick
- [ ] **CNDL-10**: `gravestone_doji` — open ≈ low ≈ close, long upper wick
- [ ] **CNDL-11**: `marubozu_bull` / `marubozu_bear` — full-body candle, wicks < 5% of range
- [ ] **CNDL-12**: `tweezer_top` / `tweezer_bottom` — two highs/lows within 0.05%, directional reversal
- [ ] **CNDL-13**: `three_inside_up` / `three_inside_down` — harami + confirming close bar

**I7 wiring:**
- [ ] **CNDL-14**: `CandlestickPatternSetupPlugin` (I7) extended to consume all 18 new directional fields with appropriate base confidences from research doc
- [ ] **CNDL-15**: Tier 3 patterns (Abandoned Baby, Rising/Falling Three Methods, Kicker) documented as deferred in `candlestick_patterns.py` with comment explaining futures applicability gap (gap-dependent; nearly non-existent in continuous 24/7 futures)

## v2 Requirements (Deferred)

### Dashboard — Deferred field groups
- I3 Fib levels, Value Area, Session levels, Weekly pivots — large field group, needs collapsible section design
- I5 Chart patterns (dt_db, hs, triangle, flag) — needs visual layout decisions
- MTF vol divergence scores — requires cross-TF data alignment

### Candlestick — Tier 3 (futures applicability gap)
- Abandoned Baby — gap-dependent, rarely fires in 24/7 futures
- Rising/Falling Three Methods — 5-bar, fires rarely, high pattern complexity
- Kicker — gap-dependent, nearly non-existent in continuous futures

### LLM Call Tracking
- Real token counts (Ollama `eval_count` / `prompt_eval_count`)
- Error message on failures, retry chain visibility
- Fill `cis_score` / zone fields in `llm_calls`

## Out of Scope

| Feature | Reason |
|---------|--------|
| ML Learning Machine | v1.9+ — needs 60+ days of outcome data for meaningful training |
| I6 Confluence Expansion / Cross-Asset | v1.9+ — own milestone, significant complexity |
| Auth / External Access | Not blocking any internal use case yet |
| Volume Profile POC | No research done; complex to implement correctly |
| Gap-Fill Service | Infrastructure work, deferred |
| TradeAgent / QualAgent / DerivAgent | Separate products, separate repos |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SIG-01 | Phase 27 | Pending |
| SIG-02 | Phase 27 | Pending |
| SIG-03 | Phase 27 | Pending |
| SIG-04 | Phase 27 | Pending |
| SIG-05 | Phase 27 | Pending |
| DASH-01 | Phase 28 | Complete |
| DASH-02 | Phase 28 | Pending |
| DASH-03 | Phase 28 | Complete |
| DASH-04 | Phase 28 | Pending |
| DASH-05 | Phase 28 | Pending |
| DASH-06 | Phase 28 | Pending |
| DASH-07 | Phase 28 | Pending |
| DASH-08 | Phase 28 | Pending |
| QUAL-01 | Phase 29 | Complete |
| QUAL-02 | Phase 29 | Pending |
| QUAL-03 | Phase 29 | Pending |
| QUAL-04 | Phase 29 | Pending |
| QUAL-05 | Phase 29 | Pending |
| QUAL-06 | Phase 29 | Pending |
| QUAL-07 | Phase 29 | Pending |
| QUAL-08 | Phase 29 | Pending |
| QUAL-09 | Phase 29 | Pending |
| QUAL-10 | Phase 29 | Pending |
| LLM-01 | Phase 31 | Pending |
| LLM-02 | Phase 31 | Pending |
| LLM-03 | Phase 31 | Pending |
| LLM-04 | Phase 31 | Pending |
| CNDL-01 | Phase 32 | Pending |
| CNDL-02 | Phase 32 | Pending |
| CNDL-03 | Phase 32 | Pending |
| CNDL-04 | Phase 32 | Pending |
| CNDL-05 | Phase 32 | Pending |
| CNDL-06 | Phase 32 | Pending |
| CNDL-07 | Phase 32 | Pending |
| CNDL-08 | Phase 32 | Pending |
| CNDL-09 | Phase 32 | Pending |
| CNDL-10 | Phase 32 | Pending |
| CNDL-11 | Phase 32 | Pending |
| CNDL-12 | Phase 32 | Pending |
| CNDL-13 | Phase 32 | Pending |
| CNDL-14 | Phase 32 | Pending |
| CNDL-15 | Phase 32 | Pending |

**Coverage:**
- v1 requirements: 46 total
- Mapped to phases: 46
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-11*
*Last updated: 2026-03-11 — v1.8 milestone definition*
