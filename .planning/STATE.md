---
gsd_state_version: 1.0
milestone: v1.9
milestone_name: I7 Alpha Engine — In Progress
status: completed
stopped_at: Completed 34-03-PLAN.md
last_updated: "2026-03-17T20:04:13.039Z"
last_activity: "2026-03-17 — 34-02 executed (VolumeProfile I4 migration: 18 fields, session-reset + rolling dual-track)"
progress:
  total_phases: 14
  completed_phases: 4
  total_plans: 15
  completed_plans: 12
  percent: 80
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-16)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Current focus:** v1.9 I7 Alpha Engine — Phase 32 complete, Phase 34 all 3 plans complete (AVWAP + VolumeProfile I4 migrations + 5 new I7 plugins)

## Current Position

Phase: 34 (complete — all 3 plans done)
Plan: 03 complete → Phase 34 DONE
Status: Phase 34 Plan 03 complete — 5 new I7 plugins registered (AnchoredVWAPReversion, VWAPReclaim, POCRejection, HVNRejection, LVNBreakout), TIER_I7=28, total=111
Last activity: 2026-03-17 — 34-02 executed (VolumeProfile I4 migration: 18 fields, session-reset + rolling dual-track)

Progress: [████████░░] 80%

## Performance Metrics

**Velocity (cumulative):**
- Total plans completed: 100 (v1.0–v1.8)
- Average duration: ~30 min/plan
- Total execution time: ~50 hours

## Accumulated Context

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
- **LedgerEntry.to_insert_params() returns 54 elements** — extended in 032-01 with 15 stop/lifecycle fields; any code calling it must expect 54 (was 39 after 031-03)
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
- **Service __new__ pattern requires new attrs**: `_chandelier_state`, `_staleness_consecutive`, `_shadow_signals` must be set in all test helpers that use SignalLifecycleService.__new__ (032-02)
- **DivergenceStack 5-input weights**: DIVERGENCE_WEIGHTS = {rsi:0.30, macd:0.25, vol:0.20, obv:0.15, cmf:0.10}; gate: score > 0.40 AND n_agreeing >= 3; always-log base_output pattern; divergence_scoring block in _build_i7_payload() routes to intelligence_features.i7 JSONB on every bar (032-03)
- **I5Patterns has 79 fields** — +9 from 032-03 (macd_div_*, obv_div_*, cmf_div_*); extra=forbid enforced; validate_schema_coverage() passes

### v1.9 Phase Ordering Rationale
- **Phase 31 first**: Learning loop + signal_features schema + shadow infrastructure must be in place before any new plugins fire — all downstream phases accumulate labeled training data from day one
- **Phase 32 second**: Stop architecture centralized in trade_framer.py before adding new plugins — all 17 existing + 10 new plugins inherit correct stops automatically
- **Phase 33 third**: Five new I7 plugins added after stop architecture is stable; no per-plugin stop logic needed
- **Phase 34 fourth**: New I4 infrastructure (AVWAP, Volume Profile) before the two I7 plugins that consume them
- **Phase 35 fifth**: Calibration, TOD, Kalman filter applied after full plugin set is stable — no moving target
- **Phase 36 sixth**: Microstructure (OFI/CVD) placed last among plugin phases — tick data dependency requires audit before implementation variant is chosen
- **Phase 37 last**: New microservice with highest SoC complexity; all I7 plugins stable before adding cross-asset dependency

### Design Anchor
Full spec: `docs/ideas/i7-quant-audit-2026-03-16.md` (reviewed + corrected 2026-03-16)

## Session Continuity

Last session: 2026-03-17T19:57:40.642Z
Stopped at: Completed 34-03-PLAN.md
Resume file: None
Next action: `/gsd:execute-phase 34` (Phase 34 Plan 03: I7 POC/HVN/LVN plugins)
