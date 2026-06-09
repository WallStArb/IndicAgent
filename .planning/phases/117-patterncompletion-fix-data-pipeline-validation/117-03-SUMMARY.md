---
phase: 117-patterncompletion-fix-data-pipeline-validation
plan: "03"
subsystem: observability
tags:
  - otel
  - oneshot
  - confidence-calibration
  - systemd
  - signal-quality
dependency_graph:
  requires:
    - "117-01"  # signal_ledger.was_selected column required
  provides:
    - "VAL-03: ConfidenceCalibrationMonitor with per-setup CORR(cis_score, was_selected)"
  affects:
    - "src/observability/metrics.py"
    - "services/confidence_calibration_monitor.py"
    - "production/systemd/indicagent-confidence-calibration-monitor.service"
    - "production/systemd/indicagent-confidence-calibration-monitor.timer"
    - "services/service_auditor.py"
tech_stack:
  added: []
  patterns:
    - "shadow_auditor.py structure: _run_audit + _amain + main() with JOB_COMPLETED_TOTAL + flush_and_shutdown_metrics"
    - "metrics.py canonical meter: all instruments via module-level _meter, no inline get_meter()"
key_files:
  created:
    - services/confidence_calibration_monitor.py
    - production/systemd/indicagent-confidence-calibration-monitor.service
    - production/systemd/indicagent-confidence-calibration-monitor.timer
    - tests/unit/services/test_confidence_calibration_monitor.py
  modified:
    - src/observability/metrics.py
    - services/service_auditor.py
decisions:
  - "Alert framing uses 'not predictive of aggregator selection' (not profitability) per RESEARCH.md Pattern 4 circularity caveat"
  - "Timer interval is 30 minutes matching shadow-auditor; query spans 7 days so sub-minute frequency adds no value"
  - "_run_audit returns processed rows list to support unit testing without mocking logger"
metrics:
  duration: "~18 minutes"
  completed: "2026-06-09T00:29:32Z"
  tasks_completed: 3
  tasks_total: 3
  files_created: 4
  files_modified: 2
---

# Phase 117 Plan 03: ConfidenceCalibrationMonitor Summary

**One-liner:** Per-setup CORR(cis_score, was_selected) monitor with OTel gauge, alert counter at <0.3, and 30-minute systemd timer using the shadow-auditor oneshot pattern.

## What Was Built

`ConfidenceCalibrationMonitor` is a timer-triggered oneshot that measures confidence-formula quality: how well `cis_score` predicts aggregator selection (`was_selected`). It runs every 30 minutes, queries the last 7 days of non-shadow signals grouped by `setup_plugin` (gated at N>=100), and publishes:

- `signal_confidence_calibration{setup_plugin}` - Pearson correlation gauge (0.0-1.0), visible in Grafana per setup
- `confidence_calibration_alerts_total{setup_plugin}` - alert counter incremented when correlation < 0.3

Alert messages use the framing "confidence not predictive of aggregator selection" (not profitability) because `cis_score` is an input to the aggregator and `was_selected` is the output - the correlation is circular by construction, measuring internal consistency rather than external predictive power.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Add SIGNAL_CONFIDENCE_CALIBRATION + CONFIDENCE_CALIBRATION_ALERTS_TOTAL to metrics.py; create confidence_calibration_monitor.py | 45330a79 |
| 2 | Create systemd .service + .timer pair; register bare name in _DAG_ORDER | 67137dc4 |
| 3 | Unit tests for low/high/none calibration alert threshold paths | eba8a661 |

## Verification Results

- `.venv/bin/pytest tests/unit/services/test_confidence_calibration_monitor.py -q` - 3 passed
- `.venv/bin/ruff check src/observability/metrics.py services/confidence_calibration_monitor.py tests/unit/services/test_confidence_calibration_monitor.py` - all passed
- `grep '"indicagent-confidence-calibration-monitor"' services/service_auditor.py` - bare name present, no .timer suffix

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

Files created/modified:
- FOUND: src/observability/metrics.py
- FOUND: services/confidence_calibration_monitor.py
- FOUND: production/systemd/indicagent-confidence-calibration-monitor.service
- FOUND: production/systemd/indicagent-confidence-calibration-monitor.timer
- FOUND: services/service_auditor.py
- FOUND: tests/unit/services/test_confidence_calibration_monitor.py

Commits:
- FOUND: 45330a79
- FOUND: 67137dc4
- FOUND: eba8a661

## Self-Check: PASSED
