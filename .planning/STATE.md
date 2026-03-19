---
gsd_state_version: 1.0
milestone: v2.1
milestone_name: candidates
status: unknown
stopped_at: Completed 39.1-03-PLAN.md (pre-commit hooks + workflow audit)
last_updated: "2026-03-19T16:35:39.107Z"
progress:
  total_phases: 23
  completed_phases: 0
  total_plans: 12
  completed_plans: 3
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-18)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Current focus:** Phase 39.1 — intelligence-layer-enforcement

## Current Position

Phase: 39.1 (intelligence-layer-enforcement) — EXECUTING
Plan: 2 of 6

## Performance Metrics

**Velocity (cumulative):**

- Total plans completed: 100 (v1.0–v1.8) + ~23 (v1.9) = ~123
- Average duration: ~30 min/plan
- Total execution time: ~62 hours

## Accumulated Context

### Roadmap Evolution

- **Phase 39.1 inserted after Phase 39**: Intelligence Layer Enforcement (URGENT) — 2026-03-19
  - Found: `regime_type` not validated by PatternPlugin Protocol (silent misfire risk)
  - Found: Signal status strings scattered across 4 files (typo risk)
  - Action: Add Protocol enforcement, SignalStatus enum, pre-commit hooks
  - Scope: 4-5 hours focused work; separate from Phase 39 DB rebuild

### Architecture Constraints (SoC / DAG / Microservices)

- **Plugin tier purity**: I5 divergence plugins → `src/intelligence/patterns/`; I7 setups → `src/intelligence/trading/`; I4 context → `src/intelligence/context/`
- **DAG ordering**: I1 → I2 → I3 → I4 → I5 → SMC → I6 → I7; new I4/I5 plugins computed before I7
- **`indicator_service` is per-symbol isolated**: cross-asset features require `cross_asset_service.py` (new service in Phase 37)
- **`lifecycle_tracker.py` is pure-function**: staleness state injected from service; no DB/Kafka in tracker
- **`trade_framer.py` is single source of truth for stop sizing**: all 23 plugins inherit changes; no per-plugin stop logic
- **`CISScorer` stays stateless**: Kalman filter wraps it in service layer (Phase 35)
- **Plugin registry is source of truth**: all new plugins registered in `TIER_I4`, `TIER_I5`, or `TIER_I7`; `registry.validate_tier()` hard-crashes on missing names

### Key Verified Facts

- `weight_updater.py` UPGRADED in 031-02 — trains LogisticRegression on binary WIN_OUTCOMES labels (target_1/target_1_2/target_full=win, rest=loss); ASSET_CLUSTER_MAP (21 symbols, 5 clusters); per-cluster training when N >= 100; is_shadow=FALSE filter; WeightUpdateResult has win_rate (not signal_quality_mean)
- `cis_weights` table has `asset_cluster` column + unique index on (asset_cluster, timeframe, version) — DONE in 031-01
- `signal_features` hypertable EXISTS — 7-day chunks, PK (signal_id, feature_name, computed_at) — DONE in 031-01
- `signal_ledger.is_shadow` column EXISTS — partial index WHERE is_shadow = TRUE — DONE in 031-01
- `CISScorer.update_weights()` EXISTS — GIL-protected hot-swap; service has `_cis_scorer` instance refreshed every 30min from DB
- **TimescaleDB hypertable unique constraint caveat**: PK must include partitioning column (computed_at). `PRIMARY KEY (signal_id, feature_name)` fails on hypertables.
- `cis_attribution` column EXISTS in `signal_ledger` — `signal_features` table (Phase 31) adds raw feature values (not a duplicate)
- CMF (`cmf_20`), OBV (`obv`), MACD histogram (`macd_histogram_12_26_9`) already exist as I1 indicators
- `garch_vol_regime` field already exists in `IntelligenceEvent` (output of VolatilityRegimePlugin)
- Correct outcome taxonomy: `target_1`, `target_1_2`, `target_full` (wins); `stopped_at_entry`, `stopped_in_trade`, `never_activated`, `ttl_expired_ahead`, `ttl_expired_behind`, `condition_expired` (losses)
- `KalmanTrendPlugin` at `src/intelligence/context/kalman_trend.py` — reuse this implementation for CIS Kalman (Phase 35)
- **LedgerEntry.to_insert_params() returns 58 elements** — extended in 035-01 with 4 calibration fields (raw_cis_score, filtered_cis_score, calibrated_confidence, regime_type_at_fire); was 54 after 032-01 (was 39 after 031-03)
- **signal_features writes atomically** — _write_signal_with_features() in signal_generator_service uses asyncpg conn.transaction(); features_per_signal is same mid-bar dict for all entries on a bar
- **promote_shadow.py uses statsmodels not scipy** — scipy 1.17+ removed proportions_ztest from scipy.stats; correct import: `from statsmodels.stats.proportion import proportions_ztest`
- **asyncpg conn.transaction() is synchronous** — returns a sync context manager (Transaction object), not a coroutine; tests must use MagicMock (not AsyncMock) for transaction()
- **TIER_I7 = 23, TIER_I5 = 16, TIER_I4 = 10, total registered plugins = 107** — after Phase 34-01; ctx_AnchoredVWAP added to TIER_I4 (moved from TIER_I3)
- **TIER_I3 = 7** — struct_AnchoredVWAP removed (migrated to I4); I3Structure now has 67 fields (was 75)
- **I4Context has 75 fields** — +15 VWAP fields from 34-01 (was 60): session_vwap, session_vwap_dist_pct, swing_vwap, weekly_vwap, above_session_vwap, above_swing_vwap, above_weekly_vwap, vwap_alignment_score, avwap_upper_band, avwap_lower_band, swing_vwap_upper_band, swing_vwap_lower_band, session_vwap_deviation_sigma, swing_vwap_deviation_sigma, session_vwap_deviation_velocity
- **TIER_I7 = 23, TIER_I5 = 16, total registered plugins = 106 (I3=7, I4=10)** — after Phase 34-01; VWAP moved tiers, net count unchanged
- **Plugin count tests must be updated when tier counts grow** — test_tier_i5_has_N_plugins and test_total_plugin_count have hardcoded values that track plugin totals
- **TIER_I4 = 11, TIER_I5 = 15** — after Phase 34-02; ctx_VolumeProfile added to I4, patt_VolumeProfile removed from I5
- **I4Context has 93 fields** — +18 VP fields from 34-02 (was 75): poc_price, vah, val, poc_price_rolling, vah_rolling, val_rolling, nearest_hvn_above, nearest_hvn_below, nearest_lvn_above, nearest_lvn_below, price_in_value_area, va_width_atr, distance_to_vah_atr, distance_to_val_atr + 4 legacy fields
- **I5Patterns has 75 fields** — -4 VP fields removed in 34-02 (was 79)
- **ctx_VolumeProfile session track**: resets at 09:30 ET using _extract_ts/_et_from_utc from session_context.py; falls back to full df if before NY open or no timestamps
- **ctx_VolumeProfile rolling track**: last min(480, N) bars — continuous window, no session reset
- **ctx_VolumeProfile legacy fields preserved**: nearest_hvn_level, nearest_hvn_dist_atr, nearest_lvn_level, in_lvn — I7 plugins can continue reading these unchanged
- **GARCH_MULTIPLIERS = {0:0.8, 1:1.0, 2:1.35}** — in trade_framer.py; applied to effective_atr in frame_trade(); all 28 I7 plugins inherit vol-regime-scaled stops automatically (032-01)
- **TIER_I7 = 28, total registered plugins = 111 (I3=7, I4=11, I5=15, I7=28)** — after Phase 34-03; 5 new I7 plugins added (AnchoredVWAPReversion, VWAPReclaim, POCRejection, HVNRejection, LVNBreakout)
- **TREND_SETUPS extended**: trad_LVNBreakout added; AnchoredVWAPReversion/VWAPReclaim/POCRejection/HVNRejection are mean_reversion or any regime
- **FVG is Priority 0 structural stop** — fvg_low (long) / fvg_high (short) beats demand/supply zone in stop hierarchy (032-01)
- **stop_basis classification** — structure_snap (≤1.5xATR from fallback), garch_adaptive (>1.5xATR or GARCH-scaled ATR), atr_static (no regime); persisted to signal_ledger AND intelligence_features.i7 JSONB (032-01)
- **TF_TTL_BARS = {"1m":20, "5m":12, "15m":8, "1h":6}** — per-TF TTL overrides hardcoded default of 10; applied in signal_generator_service before aggregation (032-01)
- **Chandelier trailing stop tightens monotonically** — long stop only moves up, short stop only moves down; state in `_chandelier_state[sid]` dict injected to evaluate_signal() (032-02)
- **Staleness formula**: score = 0.6*regime_drift + 0.4*sigma_component; condition_expired fires after 3 consecutive bars with score > 0.5; staleness_consecutive reset to 0 on service restart (032-02)
- **Shadow tracking**: condition_expired signals continue in `_shadow_signals` dict with remaining_ttl_bars = ttl_bars - bars_elapsed; shadow_mae/mfe/outcome written to DB on TTL expiry (032-02)
- **DivergenceStack 5-input weights**: DIVERGENCE_WEIGHTS = {rsi:0.30, macd:0.25, vol:0.20, obv:0.15, cmf:0.10}; gate: score > 0.40 AND n_agreeing >= 3; always-log base_output pattern; divergence_scoring block in _build_i7_payload() routes to intelligence_features.i7 JSONB on every bar (032-03)
- **I5Patterns has 79 fields** — +9 from 032-03 (macd_div_*, obv_div_*, cmf_div_*); extra=forbid enforced; validate_schema_coverage() passes
- **get_active_contracts() returns list[Instrument]** — signature changed from list[str] in 038-01; get_active_symbols() is the new list[str] convenience wrapper; ROLL_MONITOR_ENABLED=false (default) returns config-file contracts unchanged; when true queries contract_metadata WHERE is_front_month=true with 60s cache + fallback
- **derive_roll_chain(base) returns 3-contract list** — in src/config/contracts.py; covers quarterly (ES/NQ/RTY/YM/ZN/ZF/ZB/ZT/VIX), monthly (CL/GC/SI/HG), grain (ZC/ZS/ZW); symbols use 1-digit year suffix (IBKR format e.g. ESM6)
- **Migration 038 ready to apply** — production/migrations/038_roll_monitor_integration.sql; extends contract_metadata (is_front_month, roll_direction, roll_detected_at, confirmation_count) + system_events table + 2 indexes
- **topic_system_events() added** — src/core/stream_keys.py; returns "{env}.system.events"
- **RollMonitor class in services/tws_daemon.py** — 038-02; VOLUME_THRESHOLDS = {ES/NQ/RTY/YM:1.2, CL/GC/SI/HG:1.5, ZN/ZF/ZB/ZT:1.4}; dual gate: ratio >= threshold AND z_score > 2.0; 3-bar confirmation; 30-min cooldown; _apply_tod_adjustment() ET-aware (pre-open 1.3x, close 0.9x, post-close None); PAPER_ACCOUNT_HOSTS = {"192.168.1.157", "127.0.0.1"}; PAPER_SKIP_CONTRACTS = {"BZJ6", "NGJ6", "SR1H6", "ZWH6"}; _on_roll_confirmed() publishes Kafka + atomic DB update; wired into _fetch_bars_for_symbol when ROLL_MONITOR_ENABLED=true
- **Pipeline roll integration (038-03)**: indicator_service._handle_roll_event() migrates (plugin_name, symbol, tf) state keys; PRICE_SENSITIVE_PLUGINS={bollinger_bands, keltner_channel, donchian_channel} adjusted by roll_gap via _adjust_price_state(); volume-neutral copied verbatim; market_analysis_service updates _active_symbols; signal_generator migrates bar_history deques; feature_writer writes roll_boundary marker to i7 JSONB via ON CONFLICT ... || merge; all 4 services conditionally subscribe to topic_system_events() when roll_monitor_enabled=True
- **seed_roll_chain() in production/scripts/historical_backfill.py** — --seed-roll-chain flag; UPSERTs 3-contract chain per futures base symbol with is_front_month=True for index 0; ON CONFLICT (symbol) DO UPDATE; deduplicates base symbols via dict.fromkeys(); per-base errors caught and logged
- **confidence_calibration table + 35-01 fields** — 038_calibration_fields.sql; isotonic regression curves per (plugin_name, timeframe); run_calibration_update() in src/intelligence/ml/confidence_calibrator.py; wired into weight_updater.run_weight_update() after cluster training; LedgerEntry.to_insert_params() now 58 elements ($55-$58: raw_cis_score, filtered_cis_score, calibrated_confidence, regime_type_at_fire)
- **35-02: calibrated_confidence sort key** — _build_all_ranked() step 1d: np.interp maps raw_conf via isotonic curve; calibrated_confidence is new field never mutating confidence; primary sort key when non-None; aggregate() passes calibration_curves + timeframe through
- **35-02: TOD multiplier pre-CIS** — _TOD_SESSION_PRIORS + _TOD_ALPHA=20.0 + _TOD_CLAMP=(0.7,1.3); Bayesian formula; COALESCE(regime_type_at_fire,'any'); applied in _process_bar() after _filter_setup_cooldown() before alpha decay; _load_calibration_curves_from_db (30min), _load_tod_multipliers_from_db (4h); _cis_kalman_state stub added
- **35-03: CIS Kalman filter** — _cis_kalman_update() pure function; _CIS_KALMAN_DEFAULTS+_CIS_KALMAN_PARAMS+_load_cis_kalman_params() at module level; state per (symbol,tf) initialized on first bar with x_est=raw_cis, P_est=R; new fire condition: filtered_cis>0.35 AND raw_cis>0.28 AND buckets_agreeing>=3; old-pass/new-fail sets _kalman_shadow=True with suppression_reason (kalman_filtered_cis_low|raw_cis_low|buckets_agreeing_low); raw_cis_score+filtered_cis_score threaded to all LedgerEntry rows; calibrated_confidence+regime_type_at_fire set on winner-only
- **35-03: dashboard confidence trio** — drill-panel.tsx compact row + expanded header use calibrated_confidence when non-null (fallback to confidence); expanded view Phase 35 trio section shows raw_cis_score/filtered_cis_score/calibrated_confidence side-by-side; types.ts adds 3 optional fields to SignalData; signal-card.tsx does not exist (marketing page only)
- **TIER_I1 = 27, total registered plugins = 113** — after Phase 036-01; OFI (ind_OFI) and CVD (ind_CVD) added to I1
- **OFIPlugin (ind_OFI)**: tick/proxy dual-path; tick rule via frames['tick_buffer']; proxy=(close-low)/(high-low)*vol; EWMA-5/20 with alpha=2/(n+1); spike_z from rolling 100-bar history; divergence = ofi_dir - price_dir (range -2..2); ofi_variant auditing
- **CVDPlugin (ind_CVD)**: cumulative delta with ET session reset at 09:30 (zoneinfo America/New_York); tick rule same as OFI; proxy=(2c-h-l)/(h-l)*vol; 5-bar polyfit slope; divergence = slope_dir - price_dir_5bar; spike_z from 100-bar delta history
- **indicator_service tick buffer**: _tick_buffers defaultdict(list) keyed by symbol; flushed via pop() at bar close; seed path uses tick_buffer=[]; separate KafkaConsumerClient group_id="indicator_service_ticks" subscribed to market.ticks topic
- **TIER_I7 = 35, total registered plugins = 120 (27 indicators + 93 patterns)** — after Phase 036-02; 7 new OFI+CVD microstructure I7 plugins added
- **trad_OFIContinuation**: _state per (symbol,tf) counts consecutive bars with same ofi_ewma_20 sign; fires at N=5; regime_type=trend; in TREND_SETUPS
- **trad_OFIDivergence**: stateless; gate abs(ofi_divergence)>=1.5; direction=sign(ofi_divergence); regime_type=mean_reversion
- **trad_OFISpike**: stateless; gate abs(ofi_spike_z)>2.0; direction=sign(ofi_spike_z); regime_type=any
- **trad_CVDDivergence**: _state N=3 confirmation; dual_divergence flag logged when abs(ofi_div)>=1.0 AND abs(cvd_div)>=1.0; regime_type=mean_reversion
- **trad_CVDSpike**: stateless; gate abs(cvd_spike_z)>2.0; symmetric with OFISpike; regime_type=any
- **trad_DeltaExhaustion**: stateless; dual gate: abs(cvd_spike_z)>1.5 AND price_change<0.3*ATR; direction=opposite of CVD spike; regime_type=mean_reversion
- **trad_DualDivergence**: IS_SHADOW=True; _state N=3 confirmation; both abs(ofi_div)>=1.0 AND abs(cvd_div)>=1.0 with same sign; regime_type=mean_reversion
- **IS_SHADOW plugin-level shadow mechanism**: signal_generator_service.py checks getattr(plugin_instance, 'IS_SHADOW', False) for all entries; marks entry.is_shadow=True; extends Phase 35 Kalman shadow pattern to plugin-level declarations
- **cross_asset_service.py (037-01)**: subscribes to `development.intelligence` topic; CROSS_ASSET_GROUPS = {"EQ_INDEX": frozenset({"ES","NQ","RTY","YM"})}; rolling windows keyed "BASE:tf"; computes es_nq_spread_z + es_rty_spread_z (5-bar log return z-scores) + eq_corr_break (5-bar vs 20-bar Pearson) + eq_vol_imbalance via compute_eq_index_features(); group_id="cross_asset_group"; default CROSS_ASSET_ENABLED=false (shadow mode); publishes to development.cross_asset; seeds from intelligence_features on startup; staleness gate: >1 TF-interval gap suppresses publish; metrics port 9118
- **topic_cross_asset() added**: src/core/stream_keys.py; returns "{env}.cross_asset"
- **Settings: 3 cross_asset fields**: cross_asset_enabled (False), cross_asset_window_bars (20), cross_asset_metrics_port (9118)
- **Redpanda topic development.cross_asset**: created with retention.ms=604800000 (7 days) per CLAUDE.md requirement
- **trad_CrossAssetDivergence (037-02)**: stateless I7 plugin; EQ_INDEX guard (ES/NQ/RTY/YM); gate abs(spread_z)>2.0 on active_pair; low_vol_flag suppression; regime-biased direction (hmm_regime=0→reversion, 1/2→continuation, None→reversion); confidence=0.55+(|z|-2)*0.05 * optional_pair_mult(1.2) * optional_tf_mult(1.2) + optional_vol(+0.05) + optional_regime_prob(+0.10); supporting_factors as dict; frame_trade for stop/targets
- **TIER_I7 = 36, total registered plugins = 121 (27 indicators + 94 patterns)** — after Phase 037-02; CrossAssetDivergencePlugin added
- **037-03 pipeline wiring**: signal_generator_service subscribes to cross_asset topic when cross_asset_enabled=True; injects frames['cross_asset'] + frames['cross_asset_5m'] for EQ_INDEX symbols (startswith ES/NQ/RTY/YM + len>base); feature_writer_service subscribes + _process_cross_asset_message() persists spread features to intelligence_features.i7 JSONB via ON CONFLICT merge for all 4 EQ_INDEX members; cross_asset topic routed BEFORE symbol:tf key-split (group-level payload, no per-symbol key); Phase 037 COMPLETE

### v2.0 Phase Ordering Rationale

- **Phase 39 first**: Data quality and DB health is the foundation — clean OHLCV, repaired CIS nulls, and proper indexes unblock every downstream phase that relies on training data quality
- **Phase 40 second**: Machine hardening after data is clean — profiling lag is meaningful only when the data flowing through the system is correct
- **Phase 41 third**: Intelligence gap fill after performance is stable — new computation paths (cross-TF alignment, VP targets) run on a tuned system
- **Phase 42 fourth**: Candlestick expansion after intelligence gaps are filled — new I5 patterns fire against enriched I6 context
- **Phase 43 fifth**: I6 confluence expansion requires Phase 41 (alignment fields live) and a stable plugin set (Phase 42 complete)
- **Phase 44 sixth**: Shadow graduation requires accumulated data from all prior phases — thresholds validated against real outcomes, not simulations
- **Phase 45 seventh**: Auth before ML exposure — external access secured before ML scores are visible externally
- **Phase 46 last**: ML model requires clean data (39), fast feature writes (40), and a stable auth layer (45) before shadow scores become externally visible

### Design Anchor

Full spec: `docs/ideas/i7-quant-audit-2026-03-16.md` (reviewed + corrected 2026-03-16)

### Pending Todos

**34 pending todos** accumulated across development sessions — use `/gsd:check-todos` to select and work through them.

Recent additions (2026-03-19):

- Clean up dual topic namespaces (infrastructure)
- Fix VWAP plugin timezone error (intelligence)
- Fix ShannonEntropy plugin NaN range handling (intelligence)

## Session Continuity

Last session: 2026-03-19T16:35:39.104Z
Stopped at: Completed 39.1-03-PLAN.md (pre-commit hooks + workflow audit)
Resume file: None
Next action: Run `/gsd:plan-phase 39` to plan Phase 39 (Data Quality + DB Health)
