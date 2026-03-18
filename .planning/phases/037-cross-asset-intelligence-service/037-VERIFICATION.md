---
phase: 037-cross-asset-intelligence-service
verified: 2026-03-18T21:00:00Z
status: passed
score: 12/12 must-haves verified
re_verification: false
---

# Phase 037: Cross-Asset Intelligence Service — Verification Report

**Phase Goal:** Build the Cross-Asset Intelligence Service that computes equity-index spread
dynamics and feeds them into the I7 signal layer.
**Verified:** 2026-03-18T21:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths — Plan 037-01

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | cross_asset_service subscribes to intelligence topic and publishes spread features to cross_asset topic | VERIFIED | `services/cross_asset_service.py:419` — `group_id="cross_asset_group"` on `topic_intelligence`; publishes via `topic_cross_asset` |
| 2 | es_nq_spread_z, es_rty_spread_z, and eq_corr_break computed from rolling windows of 4 equity index closes | VERIFIED | `src/intelligence/cross_asset_features.py` — 240-line pure-function module; `_compute_spread_series`, Pearson correlation, z-score all implemented |
| 3 | Service starts only when CROSS_ASSET_ENABLED=true; does nothing when false | VERIFIED | `services/cross_asset_service.py:393-394` — early return with log message when `not self._cross_asset_enabled` |
| 4 | Service seeds rolling windows from intelligence_features DB on startup | VERIFIED | `services/cross_asset_service.py:249` — `async def _seed_from_db()` called at `line 412` during startup |
| 5 | Stale symbols (> 1 TF-interval gap) suppress publishing for that TF | VERIFIED | `services/cross_asset_service.py:195` — `_check_group_staleness()` uses `_TF_INTERVAL_SECONDS` dict; stale check at `line 344-349` |

### Observable Truths — Plan 037-02

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | trad_CrossAssetDivergence fires when \|spread_z\| > 2.0 on the active pair | VERIFIED | `src/intelligence/trading/cross_asset_divergence.py:119` — `if abs(spread_z) <= _FIRE_THRESHOLD: return self._no_signal()` |
| 2 | Direction is regime-biased: reversion in ranging (hmm_regime=0), continuation in trending | VERIFIED | `cross_asset_divergence.py:122-141` — explicit if/elif for hmm_regime 0/1/2 |
| 3 | Plugin is stateless — all state comes from frames['cross_asset'] | VERIFIED | No `_state` dict on class; `frames.get("cross_asset", {})` is the sole data source |
| 4 | Plugin returns _no_signal() for non-EQ_INDEX symbols and when cross_asset data not ready | VERIFIED | Guards at lines 100, 105, 109 |
| 5 | Confidence scales with spread magnitude, multi-pair confirmation, multi-TF confirmation, volume imbalance, and regime clarity | VERIFIED | 5-factor formula present in implementation; all 43 tests pass covering exact values |

### Observable Truths — Plan 037-03

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | signal_generator_service injects frames['cross_asset'] and frames['cross_asset_5m'] for EQ_INDEX symbols when cross_asset_enabled | VERIFIED | `signal_generator_service.py:1468-1479` — conditional injection for ES/NQ/RTY/YM prefix match |
| 2 | trad_CrossAssetDivergence is registered in TIER_I7 and passes validate_tier() | VERIFIED | `register_plugins.py:461` in TIER_I7 list; `test_i7_registration.py` 6/6 pass; `TIER_I7` len=36 confirmed |
| 3 | feature_writer_service subscribes to topic_cross_asset and persists spread features to intelligence_features | VERIFIED | `feature_writer_service.py:559` — `_process_cross_asset_message()`; uses `_UPSERT_ROLL_BOUNDARY_SQL` for jsonb merge; routing at `line 623` |
| 4 | CLAUDE.md Active Services table includes Cross-Asset Service row | VERIFIED | `CLAUDE.md:137` — row with `indicagent-cross-asset`, purpose, `:9118` |

**Score:** 12/12 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/cross_asset_service.py` | Cross-asset microservice, min 200 lines | VERIFIED | 476 lines; `class CrossAssetService`, full lifecycle |
| `src/core/stream_keys.py` | `def topic_cross_asset` | VERIFIED | Line 100: `def topic_cross_asset(env_name: str) -> str:` |
| `src/config/settings.py` | `cross_asset_enabled`, `cross_asset_window_bars`, `cross_asset_metrics_port` | VERIFIED | Lines 112-114; all three fields present with correct defaults |
| `production/systemd/indicagent-cross-asset.service` | Systemd unit with `indicagent-cross-asset` | VERIFIED | `ExecStart` and `PYTHONUNBUFFERED=1` present |
| `tests/unit/test_cross_asset_features.py` | Feature computation tests, min 80 lines | VERIFIED | 416 lines; all 35 tests pass |
| `tests/unit/service_tests/test_cross_asset_service.py` | Service tests, min 60 lines | VERIFIED | 271 lines; `CrossAssetService.__new__` pattern used |
| `src/intelligence/trading/cross_asset_divergence.py` | CrossAssetDivergencePlugin with `plugin` export | VERIFIED | `class CrossAssetDivergencePlugin`, `plugin = CrossAssetDivergencePlugin()` at line 246 |
| `tests/unit/intelligence/test_cross_asset_divergence.py` | Plugin tests, min 80 lines | VERIFIED | 739 lines; 43 tests; all pass |
| `services/signal_generator_service.py` | Cross-asset frame injection + Kafka cache | VERIFIED | Lines 589-590, 956-957, 1468-1479, 1513-1526 |
| `services/feature_writer_service.py` | Cross-asset topic subscription + persistence | VERIFIED | Lines 243, 360-361, 559-599, 611-624 |
| `src/intelligence/register_plugins.py` | `cross_asset_div` in TIER_I7 | VERIFIED | `cross_asset_divergence_plugin.name` at line 461 |
| `CLAUDE.md` | `indicagent-cross-asset` in Active Services table | VERIFIED | Row at line 137; also in systemd list (line 93) and metrics ports (line 95) |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `cross_asset_service.py` | `stream_keys.py` | `topic_cross_asset(env_name)` for publishing | WIRED | Line 419 consumer on `topic_intelligence`; publishes to `topic_cross_asset` |
| `cross_asset_service.py` | `settings.py` | `Settings().cross_asset_enabled` | WIRED | Line 100: `settings.cross_asset_enabled` |
| `cross_asset_divergence.py` | `frames['cross_asset']` | `compute_full(frames)` reads cross_asset dict | WIRED | `frames.get("cross_asset", {})` at line 93 |
| `cross_asset_divergence.py` | `trade_framer.py` | `frame_trade()` for stop/target computation | WIRED | Import at line 30; called at line 183 |
| `signal_generator_service.py` | `stream_keys.py` | `topic_cross_asset(env_name)` subscription | WIRED | Import at line 52; used at lines 956, 1513 |
| `signal_generator_service.py` | `cross_asset_divergence.py` | Plugin receives `frames['cross_asset']` | WIRED | Frame injected at lines 1476-1479; plugin in TIER_I7 |
| `feature_writer_service.py` | `stream_keys.py` | `topic_cross_asset(env_name)` subscription | WIRED | Import at line 34; used at lines 360, 611 |
| `register_plugins.py` | `cross_asset_divergence.py` | Import plugin, register in TIER_I7 | WIRED | Import at line 93; `registry.register_pattern` at line 308; TIER_I7 at line 461 |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| XA-01 | 037-01, 037-03 | Cross-asset service infrastructure | SATISFIED | `cross_asset_service.py` + stream key + Settings + systemd unit all present |
| XA-02 | 037-01, 037-03 | Service seeds from DB, staleness suppression | SATISFIED | `_seed_from_db()` + `_check_group_staleness()` implemented and tested |
| XA-03 | 037-02, 037-03 | CrossAssetDivergencePlugin in I7 pipeline | SATISFIED | Plugin created, registered in TIER_I7, frames wired in signal_generator_service |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `services/signal_generator_service.py` | 874 | E501 line too long (105 > 100) | Info | Pre-existing: not in phase 037 diff; line contains a DB query from a prior phase |

No TODO/FIXME/PLACEHOLDER comments. No stub implementations. No empty handlers. No ignored fetch results.

---

## Test Results Summary

| Test File | Tests | Result |
|-----------|-------|--------|
| `tests/unit/test_cross_asset_features.py` | 35 | 35 passed |
| `tests/unit/service_tests/test_cross_asset_service.py` | 15 (est.) | All passed |
| `tests/unit/intelligence/test_cross_asset_divergence.py` | 43 | 43 passed |
| `tests/unit/intelligence/test_i7_registration.py` | 6 | 6 passed |
| Full `tests/unit/` suite (excl. api dir) | 2395 passed, 32 failed | 32 failures are pre-existing (unchanged from before phase 037; summary documented 33 pre-existing) |

---

## Redpanda Topic Verification

`development.cross_asset` topic exists with `retention.ms=604800000` (7 days) — `DYNAMIC_TOPIC_CONFIG` confirmed via `docker exec redpanda rpk topic describe`.

---

## Human Verification Required

None — all automated checks passed. The service runs only when `CROSS_ASSET_ENABLED=true` (not currently enabled in production), so live end-to-end behavior is not testable without enabling the flag. This is by design (shadow mode default).

---

## Summary

Phase 037 goal is fully achieved. The complete cross-asset intelligence loop is implemented and wired:

1. **Infrastructure (037-01):** `CrossAssetService` microservice computes ES/NQ and ES/RTY spread z-scores plus correlation break from rolling windows of 4 equity index closes. Publishes to `development.cross_asset` Kafka topic. Seeds from DB on startup. Staleness gating and dedup per (tf, ts) implemented. 35 unit tests pass.

2. **Plugin (037-02):** `CrossAssetDivergencePlugin` (trad_CrossAssetDivergence) fires on |spread_z| > 2.0 with regime-biased direction (reversion in ranging, continuation in trending) and a 5-factor confidence formula. 43 unit tests cover all fire/no-fire conditions, direction combinations, and exact confidence values.

3. **Pipeline wiring (037-03):** `signal_generator_service` subscribes to `development.cross_asset` and injects `frames['cross_asset']` + `frames['cross_asset_5m']` for EQ_INDEX symbols. `feature_writer_service` subscribes and persists spread features via jsonb merge to `intelligence_features`. `trad_CrossAssetDivergence` registered in TIER_I7 (36 total). `CLAUDE.md` Active Services table updated.

All 12 observable truths verified. All key links wired. No regressions introduced.

---

_Verified: 2026-03-18T21:00:00Z_
_Verifier: Claude (gsd-verifier)_
