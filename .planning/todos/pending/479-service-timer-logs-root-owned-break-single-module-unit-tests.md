---
status: pending
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
