---
status: completed
priority: P3
filed: 2026-09-30
source: 186-18 follow-up
---

# Timer-written service logs are root-owned in the checkout and break single-module unit runs

`logs/regime_coverage_auditor.log` in `/home/bg/dev/indicagent` is owned by root (the 02:00 timer
writes it). `services/regime_coverage_auditor.py` calls `setup_service_logging` at import, so
`pytest tests/unit/services/test_regime_coverage_auditor.py` run alone fails at collection with
`PermissionError` when it is the first module to configure service logging. The full suite passes
because an earlier module configures logging first. Other timer-run services probably share this.

Fix: have the timer units write logs as the checkout owner (`User=bg`), or have
`setup_service_logging` fall back to a temp path when the file is not writable under a test run.

## Resolution (2026-11-26)

Cause: `indicagent-regime-coverage-auditor.service` and `indicagent-feature-parity-auditor.service` had no `User=`, so
the timer runs wrote root-owned files under `logs/`. Both units now declare `User=bg`; the regression test
`tests/unit/test_systemd_units_run_as_checkout_owner.py` fails any unit that runs the repo venv Python without it.
Installed units need a copy and `systemctl daemon-reload` (owner sudo step), and the existing root-owned
`logs/regime_coverage_auditor.log` must be chowned to bg once.
