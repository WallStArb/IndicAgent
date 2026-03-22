---
created: 2026-03-22T19:00:00.000Z
title: v2.0 hygiene — delete zombie DAG units, stale Wants=, dead stream key, dead SSE entry
area: infrastructure
files:
  - production/systemd/
  - services/indicagent-feature-writer.service
  - src/core/stream_keys.py
  - src/api/sse.py
---

## Problem

Four hygiene items flagged in the v2.0 milestone audit (non-blocking, no runtime failures):

1. **6 zombie DAG unit files** in `production/systemd/`: `indicagent-quality-gate.service`, `indicagent-regime-gate.service`, `indicagent-tod-adjuster.service`, `indicagent-calibrator.service`, `indicagent-ranker.service`, `indicagent-winner-selector.service` — Python files deleted in Phase 44.2; live host clean; but if `install.sh` runs these would fail to start.

2. **Stale `Wants=indicagent-indicator.service`** in `services/indicagent-feature-writer.service` — Phase 44.1 retired the indicator service. Soft dependency, no runtime failure, but misleading.

3. **`topic_intelligence_i7()` deprecated function** in `src/core/stream_keys.py` — marked deprecated, no active producers or consumers. Safe to delete.

4. **Dead `"intelligence.i7"` entry** in `src/api/sse.py` `known_prefixes` — no Redpanda topic with this name. Safe to remove.

## Solution

1. `rm production/systemd/indicagent-{quality-gate,regime-gate,tod-adjuster,calibrator,ranker,winner-selector}.service`
2. Edit `services/indicagent-feature-writer.service` — remove `Wants=indicagent-indicator.service` line
3. Delete `topic_intelligence_i7()` function from `src/core/stream_keys.py`
4. Remove `"intelligence.i7"` from `known_prefixes` in `src/api/sse.py`

All 4 are safe, no behavior change.
