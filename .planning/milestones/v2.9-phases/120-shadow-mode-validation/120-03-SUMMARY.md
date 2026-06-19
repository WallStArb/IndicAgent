---
phase: 120-shadow-mode-validation
plan: "03"
subsystem: shadow-governance
tags:
  - shadow-mode
  - promotion-gate
  - systemd
  - grafana
  - observability

dependency_graph:
  requires:
    - plan: "120-01"
      provides: services/shadow_validator.py (weekly 5-gate promotion script with 6 OTel gauges)
  provides:
    - production/systemd/indicagent-shadow-validator.timer (weekly Mon 07:00 UTC trigger)
    - production/systemd/indicagent-shadow-validator.service (oneshot service wrapper)
    - production/grafana/dashboards/shadow-validation.json (per-setup promotion metrics dashboard)
    - docs/reference/cheatsheet.md entry (shadow promotion ceremony documentation)
  affects:
    - service_auditor health monitoring (indicagent-shadow-validator registered in _DAG_ORDER + _ONESHOT_UNITS)
    - Grafana (shadow-validation dashboard importable)

tech-stack:
  added: []
  patterns:
    - oneshot-timer-pair (timer .timer + .service, modeled on hmm-training)
    - grafana-multi-target-table (6 instant PromQL targets merged into one table panel)

key-files:
  created:
    - production/systemd/indicagent-shadow-validator.timer
    - production/systemd/indicagent-shadow-validator.service
    - production/grafana/dashboards/shadow-validation.json
  modified:
    - services/service_auditor.py
    - docs/reference/cheatsheet.md

key-decisions:
  - "TimeoutStartSec=300 (5 min) - generous for 22-setup iteration + DB queries; hmm-training uses 7200 but shadow_validator is much cheaper"
  - "Grafana table uses 6 separate instant targets with merge transformation - matches Grafana pattern for multi-metric table with unified row per label"
  - "shadow-validator NOT added to _AGENT_ID_TO_UNIT (that dict is for BaseDaemon agents with consumer lag; oneshot scripts excluded)"

requirements-completed:
  - SHADOW-03

duration: 3min
completed: 2026-06-10
---

# Phase 120 Plan 03: Operationalize Shadow Validator Summary

**Weekly Mon 07:00 UTC systemd timer + oneshot service wiring shadow_validator.py into the health-monitored service fabric, with a 6-panel Grafana dashboard tracking per-setup N, p-value, win_rate, avg_pnl_r, calibration, and promoted status.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-06-10T20:35:15Z
- **Completed:** 2026-06-10T20:38:30Z
- **Tasks:** 2
- **Files modified:** 5 (2 created systemd units, 1 created dashboard, 1 modified service_auditor, 1 modified cheatsheet)

## Accomplishments

- Wired shadow_validator.py into systemd scheduling - will fire every Monday at 07:00 UTC (post-weekend data settled), with Persistent=true to catch missed fires
- Registered indicagent-shadow-validator in service_auditor _DAG_ORDER (priority 8) and _ONESHOT_UNITS so health monitoring tracks job_completed_total{job="shadow-validator"} per D-06
- Shipped a Grafana dashboard with per-setup promotion metrics table (6 shadow_validation_* metrics by setup_plugin) and N accumulation time-series with N=100 gate reference

## Task Commits

1. **Task 1: Create systemd timer + service units and register in service_auditor** - `cef80aa9` (feat)
2. **Task 2: Create Grafana shadow-validation dashboard and document promotion ceremony** - `77f6a15a` (feat)

**Plan metadata:** committed in SUMMARY commit

## Files Created/Modified

- `production/systemd/indicagent-shadow-validator.timer` - Weekly Mon 07:00 UTC timer; Persistent=true; links to .service
- `production/systemd/indicagent-shadow-validator.service` - Type=oneshot; ExecStart venv python services/shadow_validator.py; TimeoutStartSec=300
- `services/service_auditor.py` - Added indicagent-shadow-validator to _DAG_ORDER (priority 8) and _ONESHOT_UNITS; NOT in _AGENT_ID_TO_UNIT
- `production/grafana/dashboards/shadow-validation.json` - 3 panels: row header, per-setup metrics table (6 metrics), N accumulation time-series
- `docs/reference/cheatsheet.md` - Shadow Mode Validation section with 5-gate criteria, timer schedule, manual run command

## Decisions Made

- TimeoutStartSec=300 matches the shadow_validator's actual workload (22 setup DB queries + OTel flush). hmm-training uses 7200 for ML training; validator is much lighter.
- Grafana table panel uses 6 separate instant PromQL queries with refId mapping (n, win_rate, p_value, avg_pnl_r, calibration, promoted) + merge transformation - standard Grafana pattern for multi-metric tables grouped by label.
- shadow-validator excluded from _AGENT_ID_TO_UNIT - that dict maps BaseDaemon agent_id labels to unit names for consumer lag monitoring. Oneshot scripts don't emit consumer lag metrics.

## Deviations from Plan

None - plan executed exactly as written.

The pre-commit hook couldn't find ruff/black on the first commit attempt because the worktree lacked a .venv symlink to the main repo's venv. Created `/home/bg/dev/indicagent/.claude/worktrees/agent-afe1ed78cbf3a4451/.venv -> /home/bg/dev/indicagent/.venv` to resolve. This is a worktree environment setup issue, not a code deviation.

## Issues Encountered

- Pre-commit hook path resolution: worktree's REPO_ROOT is `/home/bg/dev/indicagent/.clone/worktrees/agent-afe1ed78cbf3a4451`, so hook looked for `.venv/bin/ruff` relative to that path. Created `.venv` symlink pointing to main repo's venv. Hook passed on retry.

## User Setup Required

To activate the timer on the live system (production deployment):

```bash
# Install units
sudo cp production/systemd/indicagent-shadow-validator.timer /etc/systemd/system/
sudo cp production/systemd/indicagent-shadow-validator.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable + start timer
sudo systemctl enable indicagent-shadow-validator.timer
sudo systemctl start indicagent-shadow-validator.timer

# Import Grafana dashboard
# Upload production/grafana/dashboards/shadow-validation.json via Grafana UI
# or via provisioning if Grafana auto-provisioning is configured
```

## Next Phase Readiness

- Plan 120-03 completes the shadow mode validation operationalization track
- shadow_validator.py (Plan 01) + systemd scheduling (Plan 03) = fully operational weekly promotion gate
- Grafana dashboard provides operator visibility into 22 setups' progress toward N=100 gate
- Plans 120-02 (shadow_auditor enhancements) and 120-04 (integration tests) remain if scheduled in wave 2/3

---
*Phase: 120-shadow-mode-validation*
*Completed: 2026-06-10*

## Self-Check

| Artifact | Status |
|----------|--------|
| production/systemd/indicagent-shadow-validator.timer | FOUND |
| production/systemd/indicagent-shadow-validator.service | FOUND |
| production/grafana/dashboards/shadow-validation.json | FOUND |
| services/service_auditor.py (modified) | FOUND |
| docs/reference/cheatsheet.md (modified) | FOUND |
| commit cef80aa9 (Task 1 systemd + service_auditor) | FOUND |
| commit 77f6a15a (Task 2 dashboard + cheatsheet) | FOUND |
