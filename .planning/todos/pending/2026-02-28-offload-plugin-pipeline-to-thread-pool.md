---
created: 2026-02-28T00:00:00.000Z
title: Offload synchronous plugin pipeline to asyncio thread pool
area: performance
files:
  - services/market_analysis_service.py
  - services/indicator_service.py
  - services/signal_generator_service.py
---

## Problem

`_run_analysis_pipeline` (I3→I4→I5→SMC→I6), I1 plugin execution in indicator_service, and I7 plugin execution in signal_generator_service all run synchronous CPU-bound code on the asyncio event loop. During minute-boundary bursts (up to 23 bars arriving simultaneously across 23 symbols), this starves Redis I/O (xack, xadd, xreadgroup) causing increased end-to-end latency.

## Context

This is Option C from the 2026-02-28 refactor brainstorm. Option B (multi-stream polling + DataFrame caching) should be completed first and latency measured before tackling this.

## Solution

Wrap the synchronous plugin tier execution in `asyncio.to_thread()` so the event loop remains responsive during computation bursts:

```python
tiered = await asyncio.to_thread(self._run_analysis_pipeline, symbol, timeframe, frames)
```

Prerequisites before implementing:
1. Verify plugin registry is read-only after startup (no shared mutable state across calls)
2. Confirm bar_history mutations (deque.append) don't race — each symbol:tf key is written from a single consumer, so should be safe
3. Benchmark to confirm CPU is actually the bottleneck after Option B is applied

## Risk

Medium — thread safety of plugin instances in registry needs verification before shipping.

## Related async concurrency todos (tackle together)

- `2026-03-14-untracked-async-tasks-lifecycle-narrative.md` — fire-and-forget `create_task()` in lifecycle + narrative hot paths
- `2026-03-14-aggregator-rebuild-and-db-seed-concurrency.md` — 240 uncapped concurrent DB queries on seed + aggregator per-bar rebuild
