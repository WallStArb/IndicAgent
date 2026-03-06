---
created: 2026-02-24T20:52:53.602Z
title: Fix sequential stream polling in feature_writer_service
area: database
files:
  - services/feature_writer_service.py:366-396
---

## Problem

`_process_loop` iterates 23 symbols × 4 timeframes = 92 streams **sequentially**, with `block=100ms` per xreadgroup call. Worst case: 9.2 seconds of lag before a message on the last stream is processed. This defeats the purpose of a low-latency feature writer.

## Solution

`xreadgroup` supports reading multiple streams in a single call by passing a dict of `{stream_name: ">"}` entries. Build the full dict of all 92 streams upfront and issue one `xreadgroup` call per loop tick instead of 92 sequential calls. This collapses the worst-case polling lag from O(streams × block_ms) to O(block_ms).

```python
streams = {sk_intelligence(prefix, sym, tf): ">" for tf in timeframes for sym in symbols}
messages = await self.redis_client.xreadgroup(GROUP, NAME, streams, count=10, block=100)
```
