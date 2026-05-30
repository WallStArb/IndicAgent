---
phase: 260528-9ar-fix-service-auditor
plan: 01
status: complete
completed: 2026-05-28
commit: 3ba63eab
---

# Summary: Fix Service Auditor DAG Order Ghost + Oneshot Registration

Fixed `services/service_auditor_agent.py` in commit `3ba63eab`.

## Changes

- **Removed ghost**: `indicagent-ibkr-restart` removed from `_DAG_ORDER` and `_ONESHOT_UNITS` (no backing file in `production/systemd/`; present only in `/etc/systemd/system/`)
- **Added infra sentinel**: `indicagent-timescaledb-ready` added to `_DAG_ORDER` (priority 0) and `_ONESHOT_UNITS`
- **Added to `_ONESHOT_UNITS`**: `indicagent-redpanda-ready` (was in `_DAG_ORDER` but not in oneshot set)
- **Added timer oneshots**: `indicagent-feature-validation` (daily) and `indicagent-hmm-training` (monthly) added to both `_DAG_ORDER` (priority 8) and `_ONESHOT_UNITS`

## Verification

All Python import checks passed; auditor no longer attempts off-schedule restarts on sentinel/timer services; ruff clean.
