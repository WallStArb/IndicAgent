# Service Latency Refactor Design

**Date:** 2026-02-28
**Status:** Shipped — bar-to-stage latency metrics in src/observability/metrics.py
**Motivation:** Real-time lag observed across the pipeline. Root causes identified across 6 services.

---

## Problem Summary

Five services share a sequential xreadgroup polling bug: each polls 92 streams (or 23) one at a time with `block=100ms`, producing worst-case 9.2s lag before a message on the last stream is processed. Additional waste comes from per-bar DataFrame rebuilds and per-message xack round-trips. `market_analysis_service` already has the polling fix but lacks DataFrame caching.

---

## Scope

Six services in total:

| Service | Polling fix | Remove sleep | DataFrame cache | Batch xack |
|---|---|---|---|---|
| `indicator_service` | ✅ | ✅ | ✅ | ✅ |
| `market_analysis_service` | already done | n/a | ✅ | ✅ |
| `signal_generator_service` | ✅ | ✅ | ✅ | ✅ |
| `feature_writer_service` | ✅ | ✅ | n/a | ✅ |
| `signal_tracker_service` | ✅ | ✅ | n/a | ✅ |
| `ai_narrative_service` | ✅ | ✅ | n/a | ✅ |

---

## Fix 1: Multi-stream xreadgroup

**Applies to:** indicator, signal_generator, feature_writer, signal_tracker, ai_narrative

**Before (sequential — O(streams × block_ms) worst-case lag):**
```python
for tf in timeframes:
    for sym in symbols:
        stream_name = sk_...(prefix, sym, tf)
        messages = await self.redis_client.xreadgroup(
            group, consumer, {stream_name: ">"}, count=10, block=100
        )
```

**After (single call — O(block_ms) worst-case lag):**
```python
# Built once in _setup_consumer_groups, stored as self._stream_map
# {stream_name: (symbol, timeframe)}
all_streams = {name: ">" for name in self._stream_map}

messages = await self.redis_client.xreadgroup(
    group, consumer, all_streams, count=10, block=1000
)
for stream_bytes, msgs in messages:
    stream_name = stream_bytes.decode() if isinstance(stream_bytes, bytes) else stream_bytes
    symbol, timeframe = self._stream_map[stream_name]
    ...
```

`_stream_map` is populated during `_setup_consumer_groups` which already iterates all streams — just save the keys rather than discarding them.

For `signal_tracker_service` (1m only, 23 streams): same pattern, `_stream_map` maps `market:SYMBOL:1m → (symbol, "1m")`.

**Impact:** Worst-case polling lag: 9.2s → 1s across all five services.

---

## Fix 2: Remove asyncio.sleep(processing_interval)

**Applies to:** indicator, signal_generator, feature_writer, signal_tracker, ai_narrative

The `asyncio.sleep(0.1)` at the end of each loop tick was needed when xreadgroup was called with no block (or short block) to yield control. With `block=1000`, the xreadgroup call itself yields for up to 1s when there is nothing to read. The sleep adds guaranteed latency on top of every message batch and should be removed.

`asyncio.sleep(1)` in exception handlers is fine — leave those.

---

## Fix 3: DataFrame caching

**Applies to:** indicator_service, market_analysis_service, signal_generator_service

**Pattern:** Add `self._df_cache: dict[str, pd.DataFrame | None]` initialized to `{}`. On every bar append to `bar_history`, set `self._df_cache[key] = None`. In the compute method, rebuild only when the cache is invalidated:

```python
def _get_df(self, key: str) -> pd.DataFrame:
    if self._df_cache.get(key) is None:
        self._df_cache[key] = pd.DataFrame(list(self.bar_history[key]))
    return self._df_cache[key]
```

For `market_analysis_service`, cross-TF frames (`frames[f"tf_{other_tf}"]`) are also cached per `symbol:other_tf` key and invalidated the same way.

**Impact:** Eliminates redundant DataFrame construction on every bar. At 23-symbol minute-boundary bursts, this eliminates up to 368 wasted DataFrame builds per minute (92 main + up to 276 cross-TF in market_analysis).

---

## Fix 4: Batch xack

**Applies to:** all six services

**Before (N round-trips per batch):**
```python
for message_id, fields in msgs:
    await self._process_single_bar(...)
    await self.redis_client.xack(stream_name, group, message_id)
```

**After (1 round-trip per stream per batch):**
```python
processed_ids = []
for message_id, fields in msgs:
    await self._process_single_bar(...)
    processed_ids.append(message_id)
if processed_ids:
    await self.redis_client.xack(stream_name, group, *processed_ids)
```

Note: only ack after successful processing, consistent with existing per-message error handling. If a bar fails mid-batch, the already-processed IDs are still acked (same semantics as now — at-most-once delivery per bar).

---

## What is NOT in scope

- Offloading plugin CPU work to `asyncio.to_thread` (filed as separate todo: `2026-02-28-offload-plugin-pipeline-to-thread-pool.md`)
- Startup warmup parallelization
- Any plugin API or schema changes

---

## Testing

- All existing unit tests must pass unchanged (no public API changes)
- Manual: restart each service, observe `journalctl` for timing logs, confirm no errors
- Metric to watch: `market_analysis_calculation_duration_ms`, `indicagent_bars_total`
