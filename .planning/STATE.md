---
gsd_state_version: 1.0
milestone: v1.9
milestone_name: I7 Alpha Engine — In Progress
status: completed
stopped_at: Completed 32-03-PLAN.md
last_updated: "2026-03-17T10:46:02.531Z"
last_activity: 2026-03-17 — 32-03 executed (MACDDivergence + CMFDivergence I5 plugins, OBV extension, DivergenceStack 5-input weighted rewrite, TIER_I5=16, total=106)
progress:
  total_phases: 13
  completed_phases: 2
  total_plans: 12
  completed_plans: 8
  percent: 78
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-16)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Current focus:** v1.9 I7 Alpha Engine — Phase 32 complete (plans 01+03), Phase 34 next

## Current Position

Phase: 32 (in progress — plans 01+03 done)
Plan: 03 complete → Phase 34 next (AVWAP + Volume Profile)
Status: Phase 32 Plan 03 complete — MACD/CMF/OBV divergence I5 plugins, DivergenceStack 5-input weighted rewrite, always-log i7 routing
Last activity: 2026-03-17 — 32-03 executed (MACDDivergence + CMFDivergence I5 plugins, OBV extension, DivergenceStack 5-input weighted rewrite, TIER_I5=16, total=106)

Progress: [████████░░] 78%

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
- **TIER_I7 = 23, TIER_I5 = 16, total registered plugins = 106** — after Phase 32-03; MACDDivergence + CMFDivergence added to TIER_I5
- **Plugin count tests must be updated when tier counts grow** — test_tier_i5_has_N_plugins and test_total_plugin_count have hardcoded values that track plugin totals
- **GARCH_MULTIPLIERS = {0:0.8, 1:1.0, 2:1.35}** — in trade_framer.py; applied to effective_atr in frame_trade(); all 23 I7 plugins inherit vol-regime-scaled stops automatically (032-01)
- **FVG is Priority 0 structural stop** — fvg_low (long) / fvg_high (short) beats demand/supply zone in stop hierarchy (032-01)
- **stop_basis classification** — structure_snap (≤1.5xATR from fallback), garch_adaptive (>1.5xATR or GARCH-scaled ATR), atr_static (no regime); persisted to signal_ledger AND intelligence_features.i7 JSONB (032-01)
- **TF_TTL_BARS = {"1m":20, "5m":12, "15m":8, "1h":6}** — per-TF TTL overrides hardcoded default of 10; applied in signal_generator_service before aggregation (032-01)
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

Last session: 2026-03-17T10:46:02.529Z
Stopped at: Completed 32-03-PLAN.md
Resume file: None
Next action: `/gsd:execute-phase 34` (Phase 34: AVWAP + Volume Profile infrastructure)
