---
created: 2026-03-22T19:00:00.000Z
updated: 2026-03-28T00:00:00.000Z
title: v2.0 hygiene — delete zombie DAG units, stale Wants=, dead stream key
area: infrastructure
priority: 6
tier: immediate
files:
  - production/systemd/
  - services/indicagent-feature-writer.service
  - src/core/stream_keys.py
---

## Problem

Three hygiene items flagged in the v2.0 milestone audit (non-blocking, no runtime failures):

1. **Zombie DAG unit files** in `production/systemd/`: `indicagent-signal-lifecycle.service`, `indicagent-feature-pipeline.service`, `indicagent-tws.service` and others — Python files deleted/renamed; if `install.sh` runs these would fail to start. Review `production/systemd/` for any units whose corresponding service file no longer exists in `services/`.

2. **Stale `Wants=indicagent-indicator.service`** in `services/indicagent-feature-writer.service` line 4 — the indicator service was retired. Soft dependency, no runtime failure, but misleading.

3. **`topic_intelligence_i7()` deprecated function** in `src/core/stream_keys.py` line 70 — marked deprecated, no active producers or consumers. Safe to delete.

Note: The original todo also mentioned a dead `"intelligence.i7"` entry in `src/api/sse.py` `known_prefixes` — this has already been cleaned up (not found in current codebase).

## Solution

1. Audit `production/systemd/` — remove any `.service` files whose `ExecStart=` references a Python file that no longer exists in `services/`. Confirmed candidates: `indicagent-signal-lifecycle.service`, `indicagent-tws.service`, `indicagent-feature-pipeline.service`.
2. Edit `services/indicagent-feature-writer.service` — remove `Wants=indicagent-indicator.service` line
3. Delete `topic_intelligence_i7()` function from `src/core/stream_keys.py`

All 3 are safe, no behavior change.
