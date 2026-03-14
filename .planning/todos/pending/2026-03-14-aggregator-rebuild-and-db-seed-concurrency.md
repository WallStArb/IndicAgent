# Aggregator Per-Bar Rebuild + DB Seed Concurrency Cap

**Priority:** Medium
**Effort:** Medium (3–4h)
**Created:** 2026-03-14
**Related:** `2026-02-28-offload-plugin-pipeline-to-thread-pool.md` (async concurrency patterns)

## Problem: Two Independent Efficiency Issues

### 1. Aggregator full rebuild every bar (`aggregator.py`)

`_build_all_ranked()` is called on every bar (line 174 of `aggregate()`). It:
- Copies all signal dicts with `{**sig, ...}` — O(N) allocations per bar
- Re-sorts signals each time — O(N log N) per bar even when signals haven't changed
- Recomputes Hurst/Shannon/drift multipliers every bar from features dict
- `perf_weights` are refreshed every 15 min but rankings are recomputed every bar regardless

Under full load: 60 symbols × 4 TFs = 240 aggregator calls/min, each rebuilding all ranked signals from scratch.

**Fix:** Cache the ranked order and only rebuild when inputs change (new signal fired, `perf_weights` updated, `drift_penalties` refreshed):
```python
# Add a dirty flag: set True on new signal, perf_weights reload, or drift reload
self._rankings_dirty: dict[tuple[str,str], bool] = defaultdict(lambda: True)
self._rankings_cache: dict[tuple[str,str], list] = {}

def _build_all_ranked(self, symbol, tf, signals, features, perf_weights):
    key = (symbol, tf)
    if not self._rankings_dirty[key]:
        return self._rankings_cache[key]
    result = self._rebuild_rankings(...)  # existing logic
    self._rankings_cache[key] = result
    self._rankings_dirty[key] = False
    return result
```

**Files:** `src/intelligence/trading/aggregator.py`

---

### 2. Uncapped concurrent DB fetches in bar history seed (`signal_generator_service.py`)

`_seed_bar_history_from_db()` creates 240 concurrent DB queries (60 symbols × 4 TFs) via `asyncio.gather()` with no concurrency limit. If the asyncpg pool has `max_size=10`, the first 10 get connections immediately; the remaining 230 queue — causing timeout cascades if any query is slow.

**Fix:** Add a semaphore bounded to the pool max_size:
```python
sem = asyncio.Semaphore(10)  # match pool max_size from settings

async def _fetch_one(symbol: str, tf: str) -> tuple[str, str, list]:
    async with sem:
        result = await self.db_manager.execute_query(query, symbol, tf)
    return symbol, tf, result or []
```

**Files:** `services/signal_generator_service.py` — `_seed_bar_history_from_db()`, around line 695

## Implementation Order

1. DB semaphore cap — low risk, 30-min fix, eliminates connection exhaustion on restart
2. Aggregator dirty flag — slightly higher risk (must not suppress rankings when signals change), needs test coverage

## Notes

- For the aggregator: dirty flag must be set whenever `self._signals[key]` changes (new signal appended or removed), when `self._perf_weights` reloads, and when `self._drift_penalties` refreshes
- The semaphore value should ideally read from `db_manager.pool.get_size()` or a config constant rather than hardcoded 10
- See also `2026-02-28-offload-plugin-pipeline-to-thread-pool.md` for the broader async/concurrency work in the pipeline
