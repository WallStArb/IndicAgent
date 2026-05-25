---
plan: 107-03-1
phase: 107-infrastructure-hygiene
status: complete
wave: 3.1
---

## 107-03-1: DAG/systemd Correctness

**Result:** Complete

Added `indicagent-ibkr-restart` to _DAG_ORDER (priority 0) and _ONESHOT_UNITS. Created missing `production/systemd/indicagent-bar-aggregator.service` unit file with correct After= dependencies.

- _DAG_ORDER now has 105 entries (target: 42+)
- ibkr-restart oneshot guard added
- bar-aggregator systemd unit created with After=provider-merger dependency
