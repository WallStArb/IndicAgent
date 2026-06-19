---
phase: 120-shadow-mode-validation
verified: 2026-06-10T21:15:00Z
status: passed
score: 11/11 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 9/11
  gaps_closed:
    - "indicagent-feature-parity-auditor and indicagent-confidence-calibration-monitor now in _ONESHOT_UNITS"
    - "ROADMAP.md success criteria updated from selection_rate>=5% to win_rate>=50% to match implementation"
  gaps_remaining: []
  regressions: []
---

# Phase 120: Shadow Mode Validation Verification Report

**Phase Goal:** Implement rigorous weekly statistical validation for shadow-mode plugin promotion with a 5-criteria sequential gate, separating promotion logic from the 30-minute demotion auditor, and operationalizing the validator as a systemd timer unit with full observability.
**Verified:** 2026-06-10T21:15:00Z
**Status:** PASSED
**Re-verification:** Yes - after gap closure (2 gaps fixed)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A weekly oneshot script evaluates all 22 I7 setups against a 5-gate promotion check | VERIFIED | `services/shadow_validator.py` iterates `_SHADOW_VALIDATION_SETUPS` (frozenset, len==22 asserted at module load); gate assertions pass |
| 2 | Setups passing all 5 gates are promoted by writing is_shadow=FALSE to shadow_registry | VERIFIED | `UPDATE shadow_registry SET is_shadow=FALSE ... WHERE component_name=$2 AND is_shadow=TRUE` at line 227 |
| 3 | Setups failing any gate stay shadow; failing gate + value + threshold is logged | VERIFIED | `logger.info("shadow_validator.gate_fail", plugin=name, reason=reason, detail=detail)` at line 213; early return skips promotion write |
| 4 | Every run emits 6 OTel gauges per setup for all 22 setups | VERIFIED | All 6 SHADOW_VALIDATION_* gauges emitted unconditionally before the early-return on gate failure in `_validate_setup()` |
| 5 | signal_ledger_shadow view exists and returns only is_shadow=true rows | VERIFIED | Live DB confirmed: `SELECT viewname FROM pg_views WHERE viewname='signal_ledger_shadow'` returns one row; migration 121 applied |
| 6 | All 5 gates use pnl_r-based metrics; was_selected NOT used | VERIFIED | `was_selected` absent from shadow_validator.py source (appears only in explanatory comment); `shadow_tracking_start_ts IS NOT NULL` filter present |
| 7 | shadow_auditor.py no longer promotes (promotion path fully removed) | VERIFIED | All 13 promotion-exclusive symbols absent; no `_check_promotion` reference in file |
| 8 | shadow_auditor.py still demotes live components exactly as before | VERIFIED | `_check_demotion` and `bootstrap_ci_lower` retained; 8 demotion unit tests pass |
| 9 | Weekly systemd timer (Mon 07:00 UTC) triggers the shadow_validator oneshot service | VERIFIED | `OnCalendar=Mon *-*-* 07:00:00 UTC`, `Persistent=true`, `Unit=indicagent-shadow-validator.service` confirmed |
| 10 | indicagent-shadow-validator registered in _DAG_ORDER and _ONESHOT_UNITS | VERIFIED | Line 97 (_DAG_ORDER priority 8) and line 177 (_ONESHOT_UNITS) in service_auditor.py |
| 11 | indicagent-feature-parity-auditor and indicagent-confidence-calibration-monitor in _ONESHOT_UNITS | VERIFIED | Lines 188-189 (_ONESHOT_UNITS) and lines 98-99 (_DAG_ORDER) in service_auditor.py |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/shadow_validator.py` | Weekly oneshot 5-gate promotion validator | VERIFIED | 316 lines; ruff-clean; 5-gate assertion suite passes |
| `src/observability/metrics.py` | 6 shadow_validation_* point gauges | VERIFIED | All 6 importable; defined via `point_gauge()` helper (not create_gauge); SHADOW_VALIDATION_WIN_RATE confirmed (not SELECTION_RATE) |
| `production/migrations/121_signal_ledger_shadow_view.sql` | signal_ledger_shadow view | VERIFIED | "CREATE VIEW signal_ledger_shadow AS SELECT * FROM signal_ledger_full WHERE is_shadow = true" present; applied to live DB |
| `services/shadow_auditor.py` | Demotion-only (promotion removed) | VERIFIED | 181 lines; all 13 promotion-exclusive symbols absent; `_check_demotion` + `bootstrap_ci_lower` retained |
| `production/systemd/indicagent-shadow-validator.timer` | Weekly Mon 07:00 UTC timer | VERIFIED | OnCalendar, Persistent=true, Unit= link all correct |
| `production/systemd/indicagent-shadow-validator.service` | oneshot service running shadow_validator.py | VERIFIED | Type=oneshot, ExecStart points to shadow_validator.py, TimeoutStartSec=300 |
| `production/grafana/dashboards/shadow-validation.json` | Shadow validation observability dashboard | VERIFIED | Valid JSON; uid=shadow-validation; all 6 shadow_validation_* metrics + setup_plugin label present |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| shadow_validator.py | shadow_registry | UPDATE is_shadow=FALSE (AND is_shadow=TRUE guard) | WIRED | Line 227-234; concurrent safety guard present |
| shadow_validator.py | signal_ledger + signal_outcomes | 5-gate outcome metrics query | WIRED | Lines 163-178; parameterized $1; shadow_tracking_start_ts IS NOT NULL filter (pre-refactor signal exclusion) |
| shadow_validator.py | topic_alert_requests | CRITICAL Kafka alert per promotion (fail-open) | WIRED | Lines 267-285; alert dict uses "severity"/"message"/"source"; topic passed positionally; Kafka failure does not rollback DB write |
| indicagent-shadow-validator.timer | indicagent-shadow-validator.service | Unit= directive | WIRED | `Unit=indicagent-shadow-validator.service` present |
| indicagent-shadow-validator.service | services/shadow_validator.py | ExecStart | WIRED | ExecStart=.../.venv/bin/python services/shadow_validator.py |
| shadow-validation.json | shadow_validation_* metrics | Prometheus PromQL targets | WIRED | All 6 metric names + "setup_plugin" label confirmed in dashboard JSON |
| shadow_auditor.py::_run_audit | _check_demotion | called for non-shadow rows only; no promotion path | WIRED | Line 71: `if not row["is_shadow"]: await _check_demotion(...)` |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|---------|
| SHADOW-01: SoC split (demotion vs promotion separated) | SATISFIED | shadow_auditor.py is demotion-only (181 lines, zero promotion symbols); shadow_validator.py owns all promotion logic |
| SHADOW-02: 5-gate statistical promotion with OTel observability | SATISFIED | Sequential 5-gate check implemented; 6 gauges emit per setup per run unconditionally |
| SHADOW-03: systemd operationalization + health monitoring | SATISFIED | Timer + service units exist; indicagent-shadow-validator in both _DAG_ORDER and _ONESHOT_UNITS |

### Anti-Patterns Found

None. No TODO/FIXME/placeholder patterns in any phase artifacts. No `was_selected` logic (correctly excluded). Kafka alert is fail-open by design.

### Human Verification Required

None for correctness. One deployment step (not a code issue): the systemd units exist in `production/systemd/` and require manual installation to become active on the live system (documented in 120-03-SUMMARY.md).

## Gap Closure Summary

Both gaps from the prior verification are confirmed closed:

**Gap 1 (closed):** `indicagent-feature-parity-auditor` and `indicagent-confidence-calibration-monitor` are now present in both `_DAG_ORDER` (lines 98-99) and `_ONESHOT_UNITS` (lines 188-189) in `services/service_auditor.py`.

**Gap 2 (closed):** `ROADMAP.md` Phase 120 success criterion 2 now reads `win_rate>=50%`, matching the implementation's Gate 2 (`win_rate < 0.5`). No residual `selection_rate>=5%` language remains.

No regressions detected: shadow auditor demotion unit tests (8 tests) still pass; ruff clean on all modified service files; all 5-gate assertions verified.

---

_Verified: 2026-06-10T21:15:00Z_
_Verifier: Claude (gsd-verifier)_
