# Fix Feature Writer Sequential Stream Polling

**Created:** 2026-03-11
**Priority:** Medium
**Effort:** Medium (2–3h including tests)
**Source:** CONCERNS.md audit, memory note

## Problem

`feature_writer_service` has 3 separate consumer loops, each blocking independently:
- `_process_loop()` — reads `intelligence:SYMBOL:TF` streams (base features)
- `_enrich_i7_loop()` — reads `intelligence_i7:SYMBOL:TF` streams
- `_enrich_i8_loop()` — reads `intelligence_i8:SYMBOL:TF` streams

Each loop does sequential `xreadgroup` calls per stream with `block=100ms`. With 23 symbols × 4 TFs = 92 base streams, worst-case lag is ~920ms before a feature write.

Additionally, I7/I8 enrichment arriving out of sync with base features causes rows to be written twice (base write + upsert on enrichment arrival).

## Fix

Consolidate to a single `xreadgroup` call per loop with a dict of all streams (proven pattern from `market_analysis_service`):

```python
# Build once at startup:
all_streams = {name: ">" for name in self._stream_map}

# In loop:
messages = await self.redis_client.xreadgroup(
    group, consumer, all_streams, count=10, block=1000
)
for stream_bytes, msgs in messages:
    stream_name = stream_bytes.decode() if isinstance(stream_bytes, bytes) else stream_bytes
    symbol, timeframe = self._stream_map[stream_name]
    # process...
```

## Files

- `services/feature_writer_service.py` — main refactor target
- `tests/unit/service_tests/test_feature_writer_service.py` — update tests

## Notes

- Reference implementation: `services/market_analysis_service.py` `_setup_consumer_groups()` + `_process_loop()`
- Requires building `_stream_map` at init (maps stream name → (symbol, tf))
- The 3 separate loops may still be correct separation of concerns — just consolidate the xreadgroup calls within each loop, not necessarily merge the loops
