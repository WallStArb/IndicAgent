---
created: 2026-04-02T03:24:10.326Z
title: Audit I1/I7 plugins for GIL release — move non-releasing plugins off asyncio.to_thread
area: intelligence
files:
  - src/intelligence/register_plugins.py
  - services/intelligence_pipeline_agent.py
---

## Problem

After pipeline parallelization ships, I1 (27 plugins) and I7 (36 plugins) all run via `asyncio.to_thread()`. Plugins that are pure Python (no numpy/pandas) don't release the GIL — so `to_thread` adds thread scheduling overhead with zero parallelism benefit for those plugins.

We don't currently know which plugins fall into this category.

## Solution

1. Use per-plugin latency metrics added in the parallelization phase (`intelligence_pipeline_plugin_duration_ms` labeled by `plugin_name`) to identify outliers
2. Inspect slow or suspicious plugins — if they're pure Python loops, they don't benefit from threading
3. Move non-releasing plugins to direct synchronous calls within the gather loop (call directly, no `to_thread`)
4. Re-benchmark to confirm improvement

**Prerequisite:** Per-plugin latency metrics from the pipeline parallelization phase must be running and have collected at least one RTH session of data before this audit is meaningful.
