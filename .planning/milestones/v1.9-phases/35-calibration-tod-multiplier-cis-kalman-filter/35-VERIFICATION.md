---
phase: 35-calibration-tod-multiplier-cis-kalman-filter
verified: 2026-03-17T00:00:00Z
status: passed
score: 13/13 must-haves verified
re_verification: false
human_verification:
  - test: "Verify calibrated_confidence headline renders correctly in dashboard drill panel"
    expected: "Confidence headline shows percentage from calibrated_confidence when non-null (e.g., '73.2%'), falls back to raw confidence percentage otherwise"
    why_human: "Cannot verify React render output or conditional display without a running browser session"
  - test: "Verify TOD multiplier suppresses lunch-chop signals in live trading session"
    expected: "Signals fired between 11:30-13:00 ET have confidence visibly multiplied down (tod_multiplier ~0.9), reducing CIS bucket contribution"
    why_human: "Requires live market data and real signal firing events"
---

# Phase 35: Calibration + TOD Multiplier + CIS Kalman Filter — Verification Report

**Phase Goal:** Signal confidence is calibrated against historical outcomes, adjusted by time-of-day win rates, and smoothed through a Kalman filter — making every confidence number a reliable probability estimate rather than a raw score.
**Verified:** 2026-03-17
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Migration 038 creates confidence_calibration table and adds raw_cis_score, filtered_cis_score, calibrated_confidence, regime_type_at_fire to signal_ledger | VERIFIED | `production/migrations/038_calibration_fields.sql` contains `CREATE TABLE IF NOT EXISTS confidence_calibration` and all 4 `ADD COLUMN IF NOT EXISTS` statements |
| 2 | run_calibration_update() trains isotonic regression curves when N >= 100 per (plugin_name, timeframe) and upserts to confidence_calibration | VERIFIED | `src/intelligence/ml/confidence_calibrator.py` line 97: `if n < _MIN_SAMPLE_SIZE: continue`; upserts via `ON CONFLICT (plugin_name, timeframe) DO UPDATE` at line 111 |
| 3 | run_calibration_update() deletes stale confidence_calibration rows for groups that drop below N=100 | VERIFIED | Two `DELETE FROM confidence_calibration` statements at lines 142 and 150; stale rows cleared whether any curves were trained or not |
| 4 | run_calibration_update() is called from weight_updater.py after run_weight_update() in a try/except — failure does not affect weight update | VERIFIED | `weight_updater.py` lines 300-302: `await run_calibration_update(db_manager)` inside try/except with `logger.error` guard |
| 5 | calibrated_confidence is NULL when N < 100 — never a passthrough of raw confidence | VERIFIED | calibrator skips groups below _MIN_SAMPLE_SIZE=100; CONTEXT.md decision: "Never store raw confidence in calibrated_confidence as a passthrough" |
| 6 | LedgerEntry gains raw_cis_score, filtered_cis_score, calibrated_confidence, regime_type_at_fire fields; to_insert_params() returns 58 elements | VERIFIED | `signal_ledger.py` lines 110-113: all 4 fields present; highest param index is $58 confirmed by Python introspection; 65 dataclass fields total (superset of 58-element tuple) |
| 7 | TOD multiplier applied pre-CIS: each signal's raw confidence multiplied before aggregate() is called | VERIFIED | `signal_generator_service.py` line 1055-1061: `_bar_hour_et` and multiplier application; `aggregate()` called at line 1088 — TOD applied 33 lines earlier |
| 8 | TOD multiplier is Bayesian-smoothed with alpha=20 using session priors per (regime_type, timeframe, hour_et) | VERIFIED | `_TOD_SESSION_PRIORS` dict at line 113; `_TOD_ALPHA = 20.0` at line 126; Bayesian formula at line 1792: `(_TOD_ALPHA * prior_ratio + n * empirical_ratio) / (_TOD_ALPHA + n)` |
| 9 | TOD multiplier is clamped to [0.7, 1.3] and cached in-memory, refreshed every 4h | VERIFIED | `_TOD_CLAMP = (0.7, 1.3)` at line 127; clamp applied at line 1793; `_tod_multipliers_refresh_loop()` uses 14400s interval (4h) at line 1801 |
| 10 | calibrated_confidence is the sort key in _build_all_ranked() when curve exists; raw confidence is fallback | VERIFIED | `aggregator.py` lines 477-484: sort key uses `-(s.get("calibrated_confidence") or 0.0) if s.get("calibrated_confidence") is not None else -(s.get("confidence", 0.0))` |
| 11 | calibrated_confidence added as new field — confidence field NOT mutated | VERIFIED | `aggregator.py` step 1d adds `sig["calibrated_confidence"]`; `confidence` key never reassigned in that block; test `test_calibrated_confidence_does_not_mutate_confidence` passes |
| 12 | Per-(symbol, timeframe) Kalman filter runs on CIS score every bar; filtered_cis_score converges to repeated input | VERIFIED | `_cis_kalman_update()` standalone function at line 160; state dict `_cis_kalman_state` updated every bar at line 1107-1114; `test_cis_kalman_update_convergence` passes (200 steps converge within 0.01) |
| 13 | New fire condition enforced: filtered_cis > 0.35 AND raw_cis > 0.28 AND buckets_agreeing >= 3; old-pass/new-fail written as is_shadow=TRUE | VERIFIED | `signal_generator_service.py` lines 1122-1124: triple condition; lines 1241-1246: `is_shadow=True` and `staleness_trigger_reason` set on entries when `_kalman_shadow` flag set |

**Score:** 13/13 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/migrations/038_calibration_fields.sql` | confidence_calibration table + 4 signal_ledger columns | VERIFIED | Exists; contains `CREATE TABLE IF NOT EXISTS confidence_calibration` with correct columns and all 4 `ADD COLUMN IF NOT EXISTS` on signal_ledger |
| `src/intelligence/ml/confidence_calibrator.py` | run_calibration_update() async function | VERIFIED | Exists; exports `run_calibration_update`; `IsotonicRegression`, `_MIN_SAMPLE_SIZE=100`, 2x `DELETE FROM confidence_calibration` all present |
| `src/intelligence/ml/__init__.py` | Package marker | VERIFIED | Exists |
| `src/intelligence/trading/signal_ledger.py` | LedgerEntry with 58-element to_insert_params() | VERIFIED | 4 Phase 35 fields present (lines 110-113); highest param index $58; docstring says "58-element" |
| `src/intelligence/weight_updater.py` | Imports and calls run_calibration_update | VERIFIED | Import at line 35; call at line 300; try/except guard at line 302 |
| `src/intelligence/trading/aggregator.py` | _build_all_ranked() with calibrated_confidence sort key | VERIFIED | `calibration_curves` and `timeframe` kwargs on both `_build_all_ranked()` and `aggregate()`; np.interp calibration at lines 448-462; sort key at lines 477-484 |
| `services/signal_generator_service.py` | TOD multiplier pre-CIS, calibration refresh loop, Kalman filter | VERIFIED | All three features confirmed: `_TOD_SESSION_PRIORS`, `_calibration_curves_refresh_loop`, `_cis_kalman_update`; all state vars in `__init__` |
| `config/kalman_parameters.json` | cis_kalman block with 1m/5m/15m/1h Q/R | VERIFIED | Exists; `cis_kalman` key present; all 4 timeframes with Q=0.01, R varies (0.08→0.02) |
| `tests/unit/intelligence/test_confidence_calibrator.py` | 5+ tests for calibration logic | VERIFIED | 6 tests; all pass |
| `tests/unit/intelligence/ml/__init__.py` | Package marker | VERIFIED | Exists |
| `tests/unit/service_tests/test_signal_generator_calibration.py` | TOD + calibration + Kalman tests | VERIFIED | 14 tests (5 TOD Bayesian, 4 calibrated sort key, 5 Kalman); all 14 pass |
| `dashboard/src/components/drill-panel.tsx` | Shows raw_cis_score, filtered_cis_score, calibrated_confidence trio | VERIFIED | Lines 1021-1038: conditional trio section present with `.toFixed(3)` and percentage display |
| `dashboard/src/lib/types.ts` | SignalData type with 3 new optional fields | VERIFIED | Lines 289-291: `raw_cis_score?`, `filtered_cis_score?`, `calibrated_confidence?` all present |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `weight_updater.py` | `confidence_calibrator.py` | `await run_calibration_update(db_manager)` | WIRED | Import at line 35; call at line 300 |
| `confidence_calibrator.py` | confidence_calibration table | `INSERT ... ON CONFLICT (plugin_name, timeframe) DO UPDATE` | WIRED | Pattern present at line 111 |
| `aggregator.py _build_all_ranked()` | calibration_curves dict | `np.interp(raw_conf, breakpoints, values)` | WIRED | Lines 448-462; `calibration_curves` kwarg flows from `aggregate()` through to `_build_all_ranked()` |
| `signal_generator_service.py _process_bar()` | `aggregator.aggregate()` | TOD-adjusted `sig['confidence']` via raw_signals before aggregate() | WIRED | TOD applied at lines 1055-1061; aggregate() called at line 1088 — ordering confirmed |
| `signal_generator_service.py _load_tod_multipliers_from_db()` | `signal_ledger.regime_type_at_fire` | `COALESCE(regime_type_at_fire, 'any')` in SQL GROUP BY | WIRED | Line 1764: COALESCE applied in query; column exists in migration 038 |
| `signal_generator_service.py _process_bar()` | `self._cis_kalman_state[(symbol, tf)]` | `_cis_kalman_update(raw_cis, x_est, P_est, Q, R)` | WIRED | Lines 1107-1115: state lookup, update, and re-storage |
| `signal_generator_service.py build_ledger_entries()` | `LedgerEntry` raw_cis_score, filtered_cis_score | kwargs `raw_cis_score=raw_cis, filtered_cis_score=filtered_cis` | WIRED | Lines 1236-1237 in `_process_bar()` call site; lines 345-346 in function signature; lines 428-429 in LedgerEntry construction |
| Service startup | Both caches loaded | `await _load_calibration_curves_from_db()` + `await _load_tod_multipliers_from_db()` in `start()` | WIRED | Lines 1836-1837 in `start()`; both refresh loops in tasks list at lines 1845-1846 |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| CAL-01 | 35-01 | confidence_calibration DB table stores isotonic regression calibration curves per (plugin_name, timeframe) | SATISFIED | Migration 038 creates the table with all specified columns (breakpoints[], values[], ece, sample_size, updated_at, PRIMARY KEY (plugin_name, timeframe)) |
| CAL-02 | 35-01 | Calibration batch job trains isotonic regression when N >= 100; runs alongside weight updater; calibrated_confidence stored in signal_ledger | SATISFIED | `confidence_calibrator.py` with N>=100 gate; wired into `weight_updater.py`; calibrated_confidence column in signal_ledger |
| CAL-03 | 35-02 | Aggregator applies calibrated confidence as final step after quality multipliers; used for winner ranking with raw fallback | SATISFIED | `aggregator.py` step 1d applies after drift penalty (step 1c); sort key conditional on calibrated_confidence presence |
| TOD-01 | 35-02 | Time-of-day win rate computed per (regime_type, timeframe, hour_et) from signal_ledger; seeded with session priors | SATISFIED | Implementation uses regime_type grouping (CONTEXT.md documents intentional design choice over per-plugin grouping — 120 cells vs 2,688 for faster prior convergence); Bayesian formula replaces hard N>=20 switch (documented decision in CONTEXT.md) |
| TOD-02 | 35-02 | TOD multiplier [0.7, 1.3] applied before aggregation; cached in-memory, refreshed every 4h | SATISFIED | Clamp applied at line 1793; `_tod_multipliers_refresh_loop()` at 14400s; pre-CIS application at lines 1055-1061 |
| KAL-01 | 35-03 | Per-(symbol, tf) 1D Kalman filter smooths CIS score; same recursion as KalmanTrendPlugin; state persists across bars | SATISFIED | `_cis_kalman_update()` uses identical predict+update recursion; `_cis_kalman_state` dict persists in service instance |
| KAL-02 | 35-03 | raw_cis_score and filtered_cis_score logged per signal; updated fire condition: filtered_cis > 0.35 AND raw_cis > 0.28 AND buckets_agreeing >= 3 | SATISFIED | Both fields in LedgerEntry and threaded through build_ledger_entries(); triple condition at lines 1122-1124 |

No orphaned requirements — all 7 IDs claimed in plans match the 7 Phase 35 entries in REQUIREMENTS.md.

**Design deviation noted (TOD-01):** REQUIREMENTS.md specifies per-`(setup_plugin, timeframe, hour_et)` grouping; implementation uses per-`(regime_type, timeframe, hour_et)`. This was an intentional architectural decision documented in `35-CONTEXT.md` (line 42): "NOT per individual plugin — 28 plugins × 4 TFs × 24 hours = 2,688 cells; regime_type grouping = ~120 meaningful cells; exits prior-only mode orders of magnitude faster." The requirement's intent (time-of-day win rate adjustment) is fully satisfied; the granularity choice was refined during design.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `services/signal_generator_service.py` | ~855 | E501 line too long (SQL line) | Info | Pre-existing, confirmed via git stash before Phase 35 |
| `services/tws_daemon.py` | 633 | Uncommitted Phase 38 changes break `test_tws_daemon_publishes_bar_to_kafka` — `_roll_monitor` attribute added but test setup not updated | Warning | Pre-existing from Phase 38 partial work (commit 6313155); not introduced by Phase 35 |

No Phase 35 anti-patterns found. No TODOs, placeholders, or stub returns in any Phase 35 artifacts.

---

### Human Verification Required

#### 1. Dashboard calibrated_confidence headline

**Test:** Open the dashboard in a browser; expand a signal in the drill panel; observe the confidence percentage in the header.
**Expected:** When `calibrated_confidence` is non-null (after N>=100 resolved signals per plugin), the drill panel compact row and expanded header show calibrated probability (e.g., "73.2%"); falls back to raw confidence otherwise.
**Why human:** Cannot verify React conditional rendering without a running browser session.

#### 2. TOD multiplier live suppression

**Test:** Monitor `journalctl -u indicagent-signal-generator -f` logs between 11:30-13:00 ET; watch for `"cis_kalman"` log entries with `tod_multiplier` field.
**Expected:** `tod_multiplier` field in logs shows ~0.9 during lunch chop hours for any-regime signals; CIS scores correspondingly lower than non-chop periods.
**Why human:** Requires live market session and signal generation events.

---

### Test Run Summary

```
20/20 Phase 35 unit tests pass:
  - tests/unit/intelligence/test_confidence_calibrator.py: 6/6
  - tests/unit/service_tests/test_signal_generator_calibration.py: 14/14

Pre-existing failures (unrelated to Phase 35):
  - tests/unit/api/test_signals_route.py — ESH6 vs ESM6 contract roll (Phase 38)
  - tests/unit/config/test_settings.py — Phase 38 settings refactor
  - tests/unit/daemons/test_tws_daemon.py — Phase 38 _roll_monitor incomplete
  - tests/unit/service_tests/test_ai_narrative_service.py (11 tests)
  - tests/unit/service_tests/test_signal_generator_service.py (3 tests)
  - tests/unit/test_historical_backfill.py (2 tests)
All confirmed pre-existing via deferred-items.md and git log.
```

---

### Summary

Phase 35 goal is fully achieved. All three components of the confidence pipeline are implemented, wired, and tested:

1. **Isotonic regression calibration (CAL-01/02/03):** The `confidence_calibrator.py` module trains per-(plugin, timeframe) curves when N>=100 resolved signals exist; upserts to `confidence_calibration` table; stale rows deleted; wired into `weight_updater.py` 30-min timer. `_build_all_ranked()` uses calibrated probability as primary sort key, preserving raw confidence as fallback. NULL semantics enforced — calibrated_confidence is never a passthrough.

2. **TOD multiplier (TOD-01/02):** Bayesian-smoothed multiplier with alpha=20 and documented session priors; grouped by regime_type (intentional design deviation from per-plugin grouping for statistical power); clamped to [0.7, 1.3]; applied pre-CIS to signal confidence before aggregation; cached dict refreshed every 4h; loaded at service startup.

3. **CIS Kalman filter (KAL-01/02):** 1D local-level Kalman filter (`_cis_kalman_update()`) runs every bar per (symbol, tf); state persists in `_cis_kalman_state`; new triple gate enforced: `filtered_cis > 0.35 AND raw_cis > 0.28 AND buckets_agreeing >= 3`; old-pass/new-fail signals shadow-written with specific suppression reason; raw_cis_score and filtered_cis_score flow to DB via LedgerEntry. Q/R parameters loaded from `config/kalman_parameters.json` with fallback to defaults.

Dashboard drill panel surfaces all three confidence fields (raw/filtered/calibrated) in the expanded signal view, using calibrated_confidence as the primary headline when available.

---

_Verified: 2026-03-17_
_Verifier: Claude (gsd-verifier)_
