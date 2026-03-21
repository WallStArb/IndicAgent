---
created: 2026-03-14T00:00:00.000Z
title: Offload synchronous plugin pipeline to asyncio thread pool
area: performance
files:
  - services/market_analysis_service.py
  - services/indicator_service.py
  - services/signal_generator_service.py
---

## Problem

`_run_analysis_pipeline` (I3→I4→I5→SMC→I6 in `market_analysis_service`) and I1 plugin execution in `indicator_service` call synchronous CPU-bound `compute_full()` / `compute_next()` inside `async` coroutines — blocking the event loop during computation. During minute-boundary bursts (up to 60 bars arriving simultaneously across 60 symbols × 4 TFs), this starves Kafka I/O and delays downstream publishing.

## Architecture Context (updated 2026-03-14)

- **Kafka migration complete.** Both services now use `KafkaConsumerClient` with `async for ... in self._kafka_consumer.messages()`. The original Option B concern (Redis xreadgroup sequential polling) is no longer relevant.
- **`asyncio.Lock` guards plugin state.** `_plugin_states_locks` uses `asyncio.Lock` per `(plugin, symbol, tf)` key. Offloading to `asyncio.to_thread()` requires replacing these with `threading.Lock` (asyncio locks are not thread-safe across thread boundaries).
- **Plugin instances are shared singletons** (`_plugin_cache`, `_i1_plugin_cache`). The state swap pattern (`p._state = ...` → compute → write-back) is not thread-safe without a real lock.

## Prerequisites Before Implementing

1. **Confirm CPU is the bottleneck.** Add per-bar timing metrics (`compute_full` wall time) and look for bars where Kafka ack latency > 500ms. Only proceed if CPU time dominates.
2. **Replace `asyncio.Lock` with `threading.Lock`** in `_get_state_lock()` for both services. The lock still protects the same critical section (state swap → compute → write-back), but must be acquired with a plain `with` (not `async with`).
3. **Verify plugin registry is read-only after startup.** `register_all_plugins()` runs once at init — confirm no plugin mutates the registry dict at runtime.
4. **Scope to per-symbol-tf.** Don't parallelize plugins within a single bar (sequencing within a tier matters for feature sharing across tiers). Parallelize across independent `(symbol, tf)` computations.

## Proposed Solution

```python
# Replace asyncio.Lock with threading.Lock in _get_state_lock:
import threading
self._plugin_states_locks: dict[tuple, threading.Lock] = {}

def _get_state_lock(self, key):
    return self._plugin_states_locks.setdefault(key, threading.Lock())

# _run_tier becomes sync (no async with):
with self._get_state_lock(state_key):
    p._state = self._plugin_states.setdefault(state_key, {})
    out = p.compute_full(frames)
    self._plugin_states[state_key] = p._state

# Offload per-(symbol, tf) in the Kafka consumer loop:
tiered = await asyncio.to_thread(
    self._run_analysis_pipeline_sync, symbol, timeframe, frames
)
```

Note: `_run_analysis_pipeline` would need a sync variant since `threading.Lock` cannot be used with `async with`. The inner `_run_tier` function becomes fully sync.

## Risk

Medium-High — the state swap pattern is not atomic. `threading.Lock` must cover the entire swap → compute → write-back sequence without gaps. Requires load testing before shipping (concurrent bars for same symbol must serialize correctly).

## Related todos (tackle as a cluster)

- `2026-03-14-untracked-async-tasks-lifecycle-narrative.md` — fire-and-forget `create_task()` in hot paths
- `2026-03-14-aggregator-rebuild-and-db-seed-concurrency.md` — uncapped concurrent DB queries + aggregator per-bar rebuild
