---
phase: 47-shadow-mode-graduation
verified: 2026-03-22T12:50:16Z
status: gaps_found
score: 14/18 must-haves verified
re_verification: false
gaps:
  - truth: "ROLL_MONITOR_ENABLED=true set and validated against D-21 accuracy gates before enabling"
    status: failed
    reason: "D-21 offline validation returned SKIP (exit code 2) because market_data_5m view is empty after DB cleanup. ROLL_MONITOR_ENABLED was never set to true. Roll monitor is still disabled."
    artifacts:
      - path: "src/config/settings.py"
        issue: "roll_monitor_enabled field still present (Field(default=False, ...)) — was supposed to be removed after enablement + soak"
    missing:
      - "Re-run validate_roll_detection.py after market_data_5m populates (5m historical backfill required)"
      - "Set ROLL_MONITOR_ENABLED=true in .env and restart affected services"
      - "Apply production/migrations/049_roll_premium_pct.sql to DB"
      - "Soak 5 clean trading days before removing scaffolding"

  - truth: "roll_monitor_enabled flag and all conditional branches removed from all 5 services"
    status: failed
    reason: "Plan 03 Task 2 was deliberately deferred — cannot remove scaffolding before enablement + soak. Conditionals remain in tws_daemon, indicator_service, market_analysis_service, signal_generator_service, and feature_writer_service."
    artifacts:
      - path: "services/tws_daemon.py"
        issue: "self._enabled = settings.roll_monitor_enabled still in RollMonitor.__init__; if self._roll_monitor.is_enabled guard at line ~566"
      - path: "services/indicator_service.py"
        issue: "if _settings.roll_monitor_enabled: conditional on system_events subscription at line 695"
      - path: "services/market_analysis_service.py"
        issue: "if _settings.roll_monitor_enabled: conditional at line 771"
      - path: "services/signal_generator_service.py"
        issue: "self._roll_monitor_enabled = getattr(settings, 'roll_monitor_enabled', False) at line 436; if self._roll_monitor_enabled: at line 767"
      - path: "services/feature_writer_service.py"
        issue: "self._roll_monitor_enabled: bool at line 269; if self._roll_monitor_enabled: at line 385"
    missing:
      - "Complete todo 023 (.planning/todos/pending/023-retry-roll-detection-validation-when-market-data-5m-populates.md)"

  - truth: "Settings no longer contains roll_monitor_enabled field"
    status: failed
    reason: "src/config/settings.py line 95 still contains roll_monitor_enabled: bool = Field(default=False, validation_alias='ROLL_MONITOR_ENABLED'). Cannot remove until feature is enabled + soaked."
    artifacts:
      - path: "src/config/settings.py"
        issue: "roll_monitor_enabled field present at line 95"
    missing:
      - "Remove field only after 5-day soak per D-22 and D-23 ceremony"

  - truth: "All services unconditionally subscribe to system_events topic"
    status: failed
    reason: "indicator_service.py (line 695) and market_analysis_service.py (line 771) still gate system_events subscription on roll_monitor_enabled. signal_generator_service.py and feature_writer_service.py also gated."
    artifacts:
      - path: "services/indicator_service.py"
        issue: "if _settings.roll_monitor_enabled: topics.append(topic_system_events(...))"
      - path: "services/market_analysis_service.py"
        issue: "if _settings.roll_monitor_enabled: (conditional at line 771)"
    missing:
      - "Dedent topic_system_events subscription in all 5 services after graduation"

human_verification:
  - test: "Confirm CROSS_ASSET_ENABLED was set to true in .env before scaffolding removal"
    expected: "CROSS_ASSET_ENABLED=true appears in production .env file; services were restarted with this value active"
    why_human: "Cannot verify .env file contents or service state at time of Plan 04 Task 1 checkpoint from codebase inspection alone"
  - test: "Confirm 5 clean trading days soaked with cross-asset enabled before scaffolding removal"
    expected: "No error spikes on Prometheus dashboards for feature-pipeline (:9125) and signal-generator (:9112) over 5 trading days with cross-asset active"
    why_human: "Soak period is a runtime/time-based observation; cannot retroactively verify from code"
  - test: "Confirm D-11 pre-enable gate: cross-asset fields non-null in intelligence_features for 7+ days"
    expected: "SELECT symbol, COUNT(*) FROM intelligence_features WHERE ts > NOW() - INTERVAL '7 days' AND i6->>'ctf_vix_level' IS NOT NULL returns non-zero counts for EQ_INDEX symbols"
    why_human: "Requires live DB query against production data"
---

# Phase 47: Shadow Mode Graduation Verification Report

**Phase Goal:** Graduate shadow-mode features to production — enable cross-asset intelligence and roll monitor after validated shadow periods, remove feature-flag scaffolding.
**Verified:** 2026-03-22T12:50:16Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Regime gate thresholds configurable via REGIME_PROB_MIN/REGIME_DUR_MIN env vars | VERIFIED | settings.py lines 119-120; apply_regime_gate(prob_min=0.30, dur_min=1) |
| 2 | Default regime gate thresholds are safety floors (0.30/1), not quality filters | VERIFIED | aggregator.py _REGIME_PROB_MIN/DUR_MIN deleted; defaults lowered from 0.55/3 to 0.30/1 |
| 3 | Shadow plugin stats for trad_DualDivergence computed every 30 min as Prometheus gauges | VERIFIED | compute_shadow_plugin_stats() in weight_updater.py wired at line 450 inside run_weight_update() |
| 4 | shadow_promotion_ready emits 0 when signal_ledger is empty (not error) | VERIFIED | weight_updater.py line 525: INFO log "0 resolved shadow signals — normal on empty ledger" |
| 5 | SHADOW-01 empirical validation documented (analysis or deferral with rationale) | VERIFIED | 47-01-SUMMARY.md contains dated decision log (2026-03-22): N=0, deferral documented with safety-floor justification |
| 6 | Roll detection uses calendar-driven windows + volume z-score confirmation | VERIFIED | tws_daemon.py: check_roll() uses get_roll_window() gate + z_score < -2.0; D-16 bug eliminated |
| 7 | update_volume() only takes current_vol (no next_vol parameter) | VERIFIED | tws_daemon.py line 172: def update_volume(self, base_symbol: str, current_vol: float); D-16 call site fixed |
| 8 | get_expiry_date() and get_roll_window() exist in contracts.py | VERIFIED | contracts.py lines 101 and 152; _QUARTERLY_SYMBOLS at line 86 |
| 9 | roll_premium_pct column migration SQL exists | VERIFIED | production/migrations/049_roll_premium_pct.sql: ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS roll_premium_pct |
| 10 | roll_premium_pct flows end-to-end: _on_roll_confirmed → Kafka → feature_writer → DB | VERIFIED | tws_daemon.py line 309; feature_writer_service.py lines 523-557 |
| 11 | ROLL_MONITOR_ENABLED=true set after D-21 validation passes | FAILED | D-21 validation returned SKIP (market_data_5m empty); ROLL_MONITOR_ENABLED never set to true |
| 12 | roll_monitor_enabled flag and all conditional branches removed from all 5 services | FAILED | Conditionals still in tws_daemon, indicator_service, market_analysis_service, signal_generator_service, feature_writer_service |
| 13 | Settings no longer contains roll_monitor_enabled field | FAILED | settings.py line 95: roll_monitor_enabled: bool = Field(default=False, ...) |
| 14 | All services unconditionally subscribe to system_events topic | FAILED | indicator_service line 695 and market_analysis_service line 771 still gate on roll_monitor_enabled |
| 15 | Cross-asset fields confirmed non-null in intelligence_features for 7 days (D-11) | UNCERTAIN | 47-04-SUMMARY.md claims human checkpoint was completed; cannot verify from code |
| 16 | cross_asset_enabled flag and all conditional branches removed from all 4 services | VERIFIED | Zero hits for _cross_asset_enabled in services/, src/, tests/ |
| 17 | Settings no longer contains cross_asset_enabled field | VERIFIED | settings.py: no cross_asset_enabled field (Phase 47-04 comment present confirming removal) |
| 18 | cross_asset_service always runs (no exit path for disabled state) | VERIFIED | cross_asset_service.py start() has no early-exit guard; always initializes DB and runs |

**Score:** 14/18 truths verified (4 failed — all in SHADOW-03 deferred graduation; 1 uncertain — D-11 human gate)

---

## Required Artifacts

### Plan 01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/config/settings.py` | regime_prob_min and regime_dur_min Settings fields | VERIFIED | Lines 119-120: Field(default=0.30) and Field(default=1) |
| `src/intelligence/pipeline/regime_gate.py` | Parametric regime gate with prob_min and dur_min | VERIFIED | def apply_regime_gate(..., *, prob_min: float = 0.30, dur_min: int = 1) |
| `src/observability/metrics.py` | Shadow monitoring Prometheus gauges (shadow_n_resolved) | VERIFIED | 6 gauges at lines 217-226 |
| `src/intelligence/weight_updater.py` | compute_shadow_plugin_stats function | VERIFIED | def compute_shadow_plugin_stats at line 478; _bootstrap_ci_lower at line 457 |

### Plan 02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/config/contracts.py` | get_expiry_date(), get_roll_window(), _QUARTERLY_SYMBOLS | VERIFIED | All three present; derive_roll_chain() includes expiry_date per entry |
| `services/tws_daemon.py` | Fixed RollMonitor with z_score | VERIFIED | update_volume single-arg; check_roll uses get_roll_window + z_score < -2.0 |
| `production/migrations/049_roll_premium_pct.sql` | roll_premium_pct column migration | VERIFIED | Contains ADD COLUMN IF NOT EXISTS roll_premium_pct DOUBLE PRECISION |
| `tests/unit/test_roll_detection_algorithm.py` | Tests for calendar + z-score detection | VERIFIED | 41 tests; get_roll_window referenced; all pass |
| `production/scripts/validate_roll_detection.py` | Offline validation script with detection_rate | VERIFIED | Contains DETECTION_RATE_GATE=0.90 and FALSE_POSITIVE_RATE_GATE=0.10 |

### Plan 03 Artifacts (deferred)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/tws_daemon.py` | RollMonitor always active (no enabled check) | STUB | Still has self._enabled = settings.roll_monitor_enabled and is_enabled guard |
| `services/signal_generator_service.py` | Unconditionally consuming roll events | STUB | self._roll_monitor_enabled still set at line 436; conditional at line 767 |
| `src/config/settings.py` | Settings without roll_monitor_enabled | STUB | Field still present at line 95 |

### Plan 04 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/cross_asset_service.py` | No feature flag, no disabled exit | VERIFIED | No _cross_asset_enabled; start() has no early-exit; always runs |
| `services/signal_generator_service.py` | Unconditionally consuming cross-asset | VERIFIED | topic_cross_asset appended at line 769 unconditionally |
| `src/config/settings.py` | Settings without cross_asset_enabled | VERIFIED | Zero hits for cross_asset_enabled in settings.py |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| services/signal_generator_service.py | src/intelligence/pipeline/regime_gate.py | prob_min=self._regime_prob_min, dur_min=self._regime_dur_min | WIRED | Lines 1154-1155: passes both thresholds at apply_regime_gate call site |
| src/intelligence/weight_updater.py | src/observability/metrics.py | SHADOW_N_RESOLVED.labels(plugin=...).set() | WIRED | Line 521 and run_weight_update wiring at line 450 |
| services/tws_daemon.py | src/config/contracts.py | RollMonitor.check_roll calls get_roll_window | WIRED | Line 207 in check_roll: roll_window = get_roll_window(base_symbol, utc_now.date()) |
| services/tws_daemon.py | src/config/contracts.py | _on_roll_confirmed calls derive_roll_chain | WIRED | _on_roll_confirmed derives new_symbol from derive_roll_chain(base_symbol) |
| services/tws_daemon.py | services/feature_writer_service.py | _on_roll_confirmed publishes roll_premium_pct | WIRED | tws_daemon line 309 in payload; feature_writer lines 523-557 extract and persist to DB |
| services/signal_generator_service.py | services/cross_asset_service.py | Unconditional topic_cross_asset subscription | WIRED | topic_cross_asset appended at line 769 with no conditional; topic consumed at line 1504 |
| services/feature_pipeline_service.py | services/cross_asset_service.py | Unconditional topic_cross_asset subscription | WIRED | _cross_asset_topic = topic_cross_asset(env) at line 1006; if topic == _cross_asset_topic at line 1018 (no conditional prefix) |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SHADOW-01 | Plan 01 | HMM regime gate thresholds to Settings fields; empirical validation or documented deferral | SATISFIED | regime_prob_min/dur_min in Settings; N=0 deferral documented in 47-01-SUMMARY.md |
| SHADOW-02 | Plan 04 | CROSS_ASSET_ENABLED=true after D-11 gate; flag removed from 4 services | SATISFIED | cross_asset_enabled fully removed; services unconditionally subscribe; D-11 human checkpoint in 47-04-SUMMARY |
| SHADOW-03 | Plans 02+03 | ROLL_MONITOR_ENABLED=true after D-21 validation; flag removed from 5 services after 5-day soak | BLOCKED | D-21 returned SKIP (market_data_5m empty); ROLL_MONITOR_ENABLED never set; scaffolding not removed — tracked in todo 023 |
| SHADOW-04 | Plan 01 | trad_DualDivergence promotion monitoring — shadow_* gauges emitting per weight_updater cycle | SATISFIED | 6 gauges registered; compute_shadow_plugin_stats wired; promotion correctly blocked at N=0 (gate not yet met — expected) |
| INTEL-04 | Plan 02 | roll_premium_pct column in intelligence_features; flow from roll detection through feature_writer | SATISFIED (code only) | Migration SQL exists; end-to-end wiring confirmed; note: DB migration not yet applied (requires live DB step with ROLL_MONITOR_ENABLED=true) |

**Note on SHADOW-03 status:** The REQUIREMENTS.md checkbox `[x]` at line 60 is inaccurate — it was pre-marked but the full requirement (ROLL_MONITOR_ENABLED=true + flag removal + 5-day soak) was not achieved. The traceability table at line 133 correctly shows "Pending". Todo 023 tracks the remaining steps.

**Note on INTEL-04 status:** The migration SQL file (`049_roll_premium_pct.sql`) is correct and the wiring is complete in code. The migration has not been applied to the live DB — this is an intentional operational gate tied to ROLL_MONITOR_ENABLED enablement.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/intelligence/weight_updater.py | 169-170 | `ic_score = None  # TODO: Phase 46 ML analysis` | Info | Pre-existing issue from Phase 46 — not introduced in Phase 47; ic_score=None is a DB column that accepts NULL, not a user-visible stub |
| services/tws_daemon.py | 101 | `self._enabled = settings.roll_monitor_enabled` | Warning | Intentional deferred graduation gate (todo 023) — RollMonitor still disabled, no live check_roll occurs |

No blocker anti-patterns found in Phase 47 code additions. The warning in tws_daemon is documented and expected per the deferred graduation ceremony.

---

## Human Verification Required

### 1. D-11 Cross-Asset Pre-Enable Gate

**Test:** Run `docker exec timescaledb psql -U postgres -d indicagent -c "SELECT symbol, COUNT(*) AS rows_with_vix FROM intelligence_features WHERE ts > NOW() - INTERVAL '7 days' AND i6->>'ctf_vix_level' IS NOT NULL GROUP BY symbol ORDER BY symbol;"`
**Expected:** Non-zero counts for EQ_INDEX symbols (ES, NQ, RTY, YM) — confirming cross-asset fields were non-null before CROSS_ASSET_ENABLED was set to true
**Why human:** This is a retroactive DB data quality check; the SUMMARY claims it passed but cannot be verified from the codebase

### 2. D-22 Cross-Asset 5-Day Soak

**Test:** Review Prometheus dashboards for feature-pipeline (:9125) and signal-generator (:9112) error rates over the 5 trading days after CROSS_ASSET_ENABLED was set to true
**Expected:** No regression in error rates; cross_asset frame injection functioning without exceptions
**Why human:** Soak period is a time-series runtime observation, not verifiable from current code state

### 3. Roll Monitor D-21 Re-Validation (actionable)

**Test:** After market_data_5m populates (requires 5m historical backfill), run: `.venv/bin/python production/scripts/validate_roll_detection.py`
**Expected:** Exit code 0 (PASS) with detection_rate >= 90% and FP < 10% for all futures symbols
**Why human:** Requires live DB data; the validation script itself is correct but SKIP was returned due to empty view

---

## Gaps Summary

Phase 47 achieved its goal partially. SHADOW-01, SHADOW-02, SHADOW-04, and INTEL-04 (code) are complete. SHADOW-03 is the sole outstanding gap.

**Root cause of SHADOW-03 gaps:** The `market_data_5m` view was empty after a recent DB cleanup when Plan 03 ran. The D-21 offline validation script returned SKIP (exit code 2), which correctly triggered the graduation ceremony rule: do NOT enable without validated accuracy gates. As a result:

1. ROLL_MONITOR_ENABLED was never set to true in `.env`
2. The DB migration (049_roll_premium_pct.sql) was not applied to the live DB
3. The 5-day soak never started
4. Plan 03 Task 2 (remove scaffolding from 5 services and Settings) was deferred

All four SHADOW-03 must_haves from Plan 03 therefore remain unmet. This is an intentional and documented deferral — not a coding defect. Todo 023 at `.planning/todos/pending/023-retry-roll-detection-validation-when-market-data-5m-populates.md` tracks the full graduation ceremony with all remaining steps.

The roll detection algorithm itself (Plan 02) is correctly implemented and verified by 41 passing tests. The SHADOW-03 gap is purely operational (data availability + live enablement steps) rather than a code correctness issue.

**SHADOW-02 graduated cleanly.** The cross_asset_enabled flag is gone from all 4 services and Settings. Cross-asset participates unconditionally in the intelligence DAG.

---

_Verified: 2026-03-22T12:50:16Z_
_Verifier: Claude (gsd-verifier)_
