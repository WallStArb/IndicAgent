---
task: 260528-9as
date: 2026-05-28
status: complete
---

# Summary: Quick Task 260528-9as

Stall detection verification + bar_aggregator retry override removal + systemd restart limits + logrotate install.

## What shipped

- **HF-7 verified**: `bar_writer_agent.py` line 256 already calls `self._record_message_consumed()` inside consume loop — shipped in commit 55196e46, no re-application needed.
- **HF-6 verified**: `llm_writer_service.py` `_stall_watchdog` already reads `self._last_message_ts` with None startup guard — shipped in commit 5d6d637c, no re-application needed.
- **bar_aggregator retry override removed**: deleted `SETUP_RETRY_ATTEMPTS=4` / `SETUP_RETRY_BACKOFF_S=2.0` class attributes. Base class defaults (3 attempts, 2.0s) now apply. Updated stale test asserting the old 4-attempt value.
- **indicagent-bar-aggregator.service**: `StartLimitBurst=0` (unlimited) -> `StartLimitBurst=5`; OTEL endpoint `4317` -> `4318` to match fleet.
- **indicagent-alerting-agent.service**: `StartLimitIntervalSec=0` -> `StartLimitIntervalSec=300` + `StartLimitBurst=5`.
- **indicagent-dlq-drain.service**: same as alerting-agent.
- **indicagent-service-auditor.service**: kept `StartLimitIntervalSec=0`; added inline comment explaining the meta-watchdog exception.
- **Logrotate**: replaced broken symlink at `/etc/logrotate.d/indicagent` with a root-owned copy; fixed source file permissions from 0664 to 0644.

## Files changed in repo

- `services/bar_aggregator_agent.py` — removed 3-line retry override block
- `tests/unit/services/test_bar_aggregator_agent.py` — updated retry test to assert base class defaults
- `production/systemd/indicagent-bar-aggregator.service` — StartLimitBurst, OTEL port
- `production/systemd/indicagent-alerting-agent.service` — StartLimit
- `production/systemd/indicagent-dlq-drain.service` — StartLimit
- `production/systemd/indicagent-service-auditor.service` — comment added
- `production/indicagent-logrotate.conf` — permissions fixed to 0644

## Host-side changes (not in git)

- `/etc/systemd/system/indicagent-bar-aggregator.service` — updated
- `/etc/systemd/system/indicagent-alerting-agent.service` — updated
- `/etc/systemd/system/indicagent-dlq-drain.service` — updated
- `/etc/systemd/system/indicagent-service-auditor.service` — updated
- `systemctl daemon-reload` — executed
- `/etc/logrotate.d/indicagent` — replaced symlink with root-owned copy (root:root 0644)

## Commits

- `4471fdc5` — code fixes (bar_aggregator, test)
- `aa1c511a` — systemd unit fixes (4 units)

## Follow-ups

- New `StartLimitBurst=5` and OTEL port change on bar-aggregator take effect on next service restart. Operator should restart `indicagent-bar-aggregator` at a convenient maintenance window to pick up the OTEL endpoint change.
- Other three services (alerting-agent, dlq-drain, service-auditor) will pick up new restart limits on their next restart — no urgency.
