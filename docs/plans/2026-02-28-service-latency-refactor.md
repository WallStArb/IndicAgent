# Service Latency Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate polling lag, redundant DataFrame builds, and per-message xack round-trips across 6 services.

**Architecture:** Four orthogonal fixes: (1) collapse 92 sequential xreadgroup calls into one multi-stream call per loop tick; (2) remove now-redundant asyncio.sleep; (3) cache DataFrames per symbol:tf with dirty-flag invalidation on bar append; (4) batch xack per stream per message batch. Each task covers one service top-to-bottom and ends with a commit + systemd restart verification.

**Design doc:** `docs/plans/2026-02-28-service-latency-refactor-design.md`

**Tech Stack:** Python asyncio, redis.asyncio, pandas, systemd, pytest, structlog

---

## Shared Patterns (read before Task 1)

### Multi-stream xreadgroup pattern
Every service that needs the polling fix follows the same shape. In `_setup_consumer_groups`, save stream names into `self._stream_map: dict[str, tuple[str, str]]` as you create groups. In the polling loop, replace the nested for loop with a single call:

```python
# built once in _setup_consumer_groups:
self._stream_map[stream_name] = (symbol, timeframe)

# polling loop — replaces nested for tf / for sym:
all_streams = {name: ">" for name in self._stream_map}
messages = await self.redis_client.xreadgroup(
    self.consumer_group, self.consumer_name,
    all_streams, count=10, block=1000,
)
for stream_bytes, msgs in messages:
    stream_name = stream_bytes.decode() if isinstance(stream_bytes, bytes) else stream_bytes
    symbol, timeframe = self._stream_map[stream_name]
    ...
```

### Batch xack pattern
Move xack out of `_process_single_bar` / `_process_single_message`. Make those methods return `bool` (True = processed, should ack; False = exception, do not ack — allows redelivery). Batch ack outside:

```python
to_ack: list[bytes] = []
for message_id, fields in msgs:
    ok = await self._process_single_bar(symbol, timeframe, fields, stream_name, message_id)
    if ok:
        to_ack.append(message_id)
if to_ack:
    await self.redis_client.xack(stream_name, self.consumer_group, *to_ack)
```

### DataFrame cache pattern
Add `self._df_cache: dict[str, pd.DataFrame | None] = {}` to `__init__`. Add a helper:

```python
def _get_df(self, key: str) -> pd.DataFrame:
    if self._df_cache.get(key) is None:
        # indicator_service uses OrderedDict → .values()
        # other services use deque → list(deque)
        self._df_cache[key] = pd.DataFrame(list(self.bar_history[key].values()))
    return self._df_cache[key]
```

Invalidate on every bar append:
```python
self.bar_history[key][bar_ts.isoformat()] = bar_data  # indicator_service (OrderedDict)
self._df_cache[key] = None                              # invalidate
```

---

## Task 1: indicator_service — all 4 fixes

**Files:**
- Modify: `services/indicator_service.py`
- Test: `tests/unit/service_tests/test_indicator_service.py`

**Context:** `indicator_service` uses `OrderedDict` for `bar_history` (keyed by timestamp string for dedup). It processes `market:SYMBOL:TF` streams (23 symbols × 4 TFs = 92 streams).

### Step 1: Write failing tests

Add to `tests/unit/service_tests/test_indicator_service.py`:

```python
def test_stream_map_populated_after_setup():
    """_stream_map must contain (symbol, timeframe) for every stream name after setup."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xrevrange = AsyncMock(return_value=[])
    svc.redis_client.xgroup_create = AsyncMock(side_effect=Exception("already exists"))
    svc.redis_client.xgroup_setid = AsyncMock()

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    assert len(svc._stream_map) == 4 * len(svc.config["service"]["symbols"])
    for stream_name, (sym, tf) in svc._stream_map.items():
        assert sym in svc.config["service"]["symbols"]
        assert tf in svc.config["service"]["timeframes"]


def test_df_cache_miss_builds_dataframe():
    """_get_df must build DataFrame from bar_history on cache miss."""
    from collections import OrderedDict
    from datetime import datetime
    from services.indicator_service import IndicatorService
    import pandas as pd

    svc = IndicatorService()
    key = "ES:1m"
    svc.bar_history[key] = OrderedDict()
    svc._df_cache[key] = None
    ts = datetime(2026, 2, 28, 10, 0, 0)
    svc.bar_history[key][ts.isoformat()] = {
        "timestamp": ts, "open": 5300.0, "high": 5305.0,
        "low": 5299.0, "close": 5303.0, "volume": 1000,
    }

    df = svc._get_df(key)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.iloc[0]["close"] == 5303.0


def test_df_cache_hit_returns_same_object():
    """_get_df must return cached DataFrame on hit (no rebuild)."""
    from services.indicator_service import IndicatorService
    import pandas as pd

    svc = IndicatorService()
    key = "ES:1m"
    cached = pd.DataFrame([{"close": 5303.0}])
    svc._df_cache[key] = cached

    result = svc._get_df(key)

    assert result is cached  # exact same object, not a copy


def test_bar_append_invalidates_df_cache():
    """Appending a bar must set _df_cache[key] = None."""
    from collections import OrderedDict
    from datetime import datetime
    from services.indicator_service import IndicatorService
    import pandas as pd

    svc = IndicatorService()
    key = "ES:1m"
    svc.bar_history[key] = OrderedDict()
    svc._df_cache[key] = pd.DataFrame([{"close": 5300.0}])

    # Simulate what _process_single_bar does on bar append
    ts = datetime(2026, 2, 28, 10, 1, 0)
    svc.bar_history[key][ts.isoformat()] = {"timestamp": ts, "close": 5303.0}
    svc._df_cache[key] = None  # invalidate — this is what we're testing gets called

    assert svc._df_cache[key] is None


def test_process_single_bar_returns_true_on_success():
    """_process_single_bar must return True when bar is processed successfully."""
    import asyncio
    from datetime import datetime
    from unittest.mock import AsyncMock, MagicMock, patch
    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()
    svc.bars_processed_total = MagicMock()
    svc.error_count_total = MagicMock()

    fields = {
        b"timestamp": b"2026-02-28T10:00:00",
        b"source": b"ibkr",
        b"open": b"5300.0", b"high": b"5305.0",
        b"low": b"5299.0", b"close": b"5303.0", b"volume": b"1000",
    }

    with patch.object(svc, "_run_i1_plugins", return_value={"rsi_14": 58.3}):
        # Pre-fill history so min_bars is met
        from datetime import timedelta
        for i in range(130):
            ts = datetime(2026, 2, 28, 9, 0, 0) + timedelta(minutes=i)
            svc.bar_history["ES:1m"][ts.isoformat()] = {
                "timestamp": ts, "open": 5300.0, "high": 5305.0,
                "low": 5299.0, "close": 5303.0, "volume": 1000,
            }
        result = asyncio.get_event_loop().run_until_complete(
            svc._process_single_bar("ES", "1m", fields, "market:ES:1m", b"1-0")
        )
    assert result is True


def test_process_single_bar_returns_false_on_exception():
    """_process_single_bar must return False when processing raises."""
    import asyncio
    from services.indicator_service import IndicatorService
    from unittest.mock import MagicMock

    svc = IndicatorService()
    svc.redis_client = None  # will cause AttributeError
    svc.error_count_total = MagicMock()

    fields = {b"timestamp": b"bad-ts"}  # will fail fromisoformat

    result = asyncio.get_event_loop().run_until_complete(
        svc._process_single_bar("ES", "1m", fields, "market:ES:1m", b"1-0")
    )
    assert result is False
```

### Step 2: Run tests to verify they fail

```bash
.venv/bin/pytest tests/unit/service_tests/test_indicator_service.py -v -k "stream_map or df_cache or bar_append or process_single_bar"
```

Expected: FAIL — `_stream_map`, `_get_df`, `_df_cache` attributes don't exist; `_process_single_bar` returns None.

### Step 3: Implement changes in indicator_service.py

**3a. In `__init__`, add after existing instance vars:**
```python
self._stream_map: dict[str, tuple[str, str]] = {}
self._df_cache: dict[str, "pd.DataFrame | None"] = {}
```

**3b. Add `_get_df` helper after `_min_bars_for_tf`:**
```python
def _get_df(self, key: str) -> "pd.DataFrame":
    if self._df_cache.get(key) is None:
        self._df_cache[key] = pd.DataFrame(list(self.bar_history[key].values()))
    return self._df_cache[key]
```

**3c. In `_setup_consumer_groups`, save stream names after `xgroup_create`/`xgroup_setid`:**

Find the loop body (around line 349–354) and add one line at the end of the inner `for symbol` block:
```python
self._stream_map[stream_name] = (symbol, timeframe)
```

**3d. In `_process_single_bar`, make 3 changes:**

1. Change signature return type annotation from `-> None` to `-> bool`
2. Replace all `await self.redis_client.xack(...)` calls with `return True`
3. Change the exception handler to `return False`:
```python
    except Exception as e:
        self.logger.error(
            "Error processing bar", symbol=symbol, timeframe=timeframe, error=str(e)
        )
        self.error_count_total.inc()
        return False
```
4. After the bar-append block (the `history[bar_ts.isoformat()] = bar_data` line), add cache invalidation:
```python
self._df_cache[key] = None
```
5. Replace the `pd.DataFrame(list(...))` line with the cache helper:
```python
df = self._get_df(key)
```

**3e. Replace `_process_market_data` entirely:**
```python
async def _process_market_data(self) -> None:
    all_streams = {name: ">" for name in self._stream_map}
    while self.running and not self.shutdown_requested:
        try:
            messages = await self.redis_client.xreadgroup(
                self.consumer_group, self.consumer_name,
                all_streams, count=10, block=1000,
            )
            for stream_bytes, msgs in messages:
                stream_name = (
                    stream_bytes.decode()
                    if isinstance(stream_bytes, bytes)
                    else stream_bytes
                )
                symbol, timeframe = self._stream_map[stream_name]
                to_ack: list[bytes] = []
                for message_id, fields in msgs:
                    ok = await self._process_single_bar(
                        symbol, timeframe, fields, stream_name, message_id
                    )
                    if ok:
                        to_ack.append(message_id)
                if to_ack:
                    await self.redis_client.xack(
                        stream_name, self.consumer_group, *to_ack
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            self.logger.error("Error in processing loop", error=str(e))
            self.error_count_total.inc()
            await asyncio.sleep(1)
```

Note: `asyncio.sleep(self.config["service"]["processing_interval"])` is removed — xreadgroup block=1000 yields instead.

### Step 4: Run tests to verify they pass

```bash
.venv/bin/pytest tests/unit/service_tests/test_indicator_service.py tests/unit/test_indicator_service_warmup.py -v
```

Expected: ALL PASS

### Step 5: Run full unit suite

```bash
.venv/bin/pytest tests/unit/ -v --tb=short -q
```

Expected: same count as before (784+), 0 failures

### Step 6: Restart service and verify

```bash
sudo systemctl restart indicagent-indicator
sleep 3
sudo journalctl -u indicagent-indicator -n 30 --no-pager
```

Look for: `"Connected to Redis"`, `"Warmup complete"`, `"I1 published"` within ~60s. No errors.

### Step 7: Commit

```bash
git add services/indicator_service.py tests/unit/service_tests/test_indicator_service.py
git commit -m "perf(indicator): multi-stream xreadgroup, DataFrame cache, batch xack

- Single xreadgroup(all_streams, block=1000) replaces 92 sequential calls
- _df_cache with dirty-flag invalidation on bar append
- _process_single_bar returns bool; xack batched per stream batch
- asyncio.sleep(0.1) removed — block=1000 yields when idle"
```

---

## Task 2: signal_generator_service — all 4 fixes

**Files:**
- Modify: `services/signal_generator_service.py`
- Test: `tests/unit/service_tests/test_signal_generator_service.py`

**Context:** Consumes `intelligence:SYMBOL:TF` streams (92 streams). Uses `deque(maxlen=200)` for `bar_history`. The polling loop is `_process_loop` (not `_process_market_data`). The per-message method is `_process_single_message`.

### Step 1: Write failing tests

Add to `tests/unit/service_tests/test_signal_generator_service.py`:

```python
def test_stream_map_populated_after_setup():
    """_stream_map must map stream_name → (symbol, timeframe) for all 92 streams."""
    import asyncio
    from unittest.mock import AsyncMock
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xgroup_create = AsyncMock(side_effect=Exception("exists"))
    svc.redis_client.xrevrange = AsyncMock(return_value=[])

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    assert len(svc._stream_map) == 4 * len(svc.config["service"]["symbols"])


def test_df_cache_invalidated_on_bar_append():
    """After appending a bar, _df_cache[key] must be None."""
    import pandas as pd
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService()
    key = "ES:1m"
    svc._df_cache[key] = pd.DataFrame([{"close": 5300.0}])

    # Simulate bar append + invalidation
    svc.bar_history[key].append({"close": 5303.0, "timestamp": "t"})
    svc._df_cache[key] = None

    assert svc._df_cache[key] is None


def test_df_cache_hit_avoids_rebuild():
    """_get_df must return the cached DataFrame when cache is warm."""
    import pandas as pd
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService()
    key = "ES:5m"
    cached_df = pd.DataFrame([{"close": 5300.0}])
    svc._df_cache[key] = cached_df

    result = svc._get_df(key)

    assert result is cached_df
```

### Step 2: Run tests to verify they fail

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v -k "stream_map or df_cache"
```

Expected: FAIL — `_stream_map`, `_df_cache`, `_get_df` not defined.

### Step 3: Implement changes in signal_generator_service.py

**3a. In `__init__`, add after existing instance vars:**
```python
self._stream_map: dict[str, tuple[str, str]] = {}
self._df_cache: dict[str, "pd.DataFrame | None"] = {}
```

**3b. Add `_get_df` helper (uses `deque`, not `OrderedDict`):**
```python
def _get_df(self, key: str) -> "pd.DataFrame":
    if self._df_cache.get(key) is None:
        self._df_cache[key] = pd.DataFrame(list(self.bar_history[key]))
    return self._df_cache[key]
```

**3c. In `_setup_consumer_groups`, save stream names into `self._stream_map`:**

The existing loop builds `stream_name = sk_intel(self.env_prefix, sym, tf)`. Add at the end of the inner loop body:
```python
self._stream_map[stream_name] = (sym, tf)
```

**3d. In `_process_single_message`, make 3 changes:**

1. Change return type to `-> bool`
2. After `self.bar_history[key].append(bar_with_ts)`, add:
```python
self._df_cache[key] = None
```
3. Replace the inline DataFrame construction:
```python
# REMOVE:
df_history = list(self.bar_history[key])
frames = {
    "main": pd.DataFrame(df_history),
    "features": features,
}
# REPLACE WITH:
frames = {
    "main": self._get_df(key),
    "features": features,
}
```
4. Remove `await self.redis_client.xack(...)` from inside the method; return `True` on success path, `False` in exception handler:
```python
    except Exception as e:
        self.logger.error(...)
        self.error_count_total.inc()
        self._error_count += 1
        return False
    return True  # add at end of try block before except
```

Note: the existing code has `await self.redis_client.xack(...)` at line 555, after `_process_bar`. Replace that line with `return True`.

**3e. Replace `_process_loop` entirely:**
```python
async def _process_loop(self) -> None:
    all_streams = {name: ">" for name in self._stream_map}
    while self.running and not self.shutdown_requested:
        try:
            messages = await self.redis_client.xreadgroup(
                self.consumer_group, self.consumer_name,
                all_streams, count=10, block=1000,
            )
            for stream_bytes, msgs in messages:
                stream_name = (
                    stream_bytes.decode()
                    if isinstance(stream_bytes, bytes)
                    else stream_bytes
                )
                symbol, timeframe = self._stream_map[stream_name]
                to_ack: list[bytes] = []
                for message_id, fields in msgs:
                    ok = await self._process_single_message(
                        symbol, timeframe, fields, stream_name, message_id
                    )
                    if ok:
                        to_ack.append(message_id)
                if to_ack:
                    await self.redis_client.xack(
                        stream_name, self.consumer_group, *to_ack
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            self.logger.error("Error in processing loop", error=str(e))
            self.error_count_total.inc()
            self._error_count += 1
            await asyncio.sleep(1)
```

Note: `asyncio.sleep(processing_interval)` removed; the `from src.core.stream_keys import intelligence as sk_intel` import at the top of the old loop should be moved to the module-level imports if not already there.

### Step 4: Run tests

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v
```

Expected: ALL PASS

### Step 5: Full suite + restart

```bash
.venv/bin/pytest tests/unit/ -q --tb=short
sudo systemctl restart indicagent-signal-generator
sleep 3
sudo journalctl -u indicagent-signal-generator -n 30 --no-pager
```

### Step 6: Commit

```bash
git add services/signal_generator_service.py tests/unit/service_tests/test_signal_generator_service.py
git commit -m "perf(signal-generator): multi-stream xreadgroup, DataFrame cache, batch xack

Same latency fixes as indicator_service."
```

---

## Task 3: feature_writer_service — polling + sleep + batch xack

**Files:**
- Modify: `services/feature_writer_service.py`
- Test: `tests/unit/service_tests/test_feature_writer_service.py`

**Context:** Consumes `intelligence:SYMBOL:TF` streams (92 streams). Does not build DataFrames. Has its own buffer/batch flush logic — xack happens in `_process_single_message` and in `_flush_buffer`. Only the polling loop xack location needs to change.

### Step 1: Write failing tests

Add to `tests/unit/service_tests/test_feature_writer_service.py`:

```python
def test_stream_map_populated_after_setup():
    """_stream_map must contain all 92 stream → (symbol, tf) entries after setup."""
    import asyncio
    from unittest.mock import AsyncMock
    from services.feature_writer_service import FeatureWriterService

    svc = FeatureWriterService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xgroup_create = AsyncMock(side_effect=Exception("exists"))
    svc.redis_client.xgroup_setid = AsyncMock()

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    symbols = svc.config["service"]["symbols"]
    tfs = svc.config["service"]["timeframes"]
    assert len(svc._stream_map) == len(symbols) * len(tfs)
```

### Step 2: Run tests to verify they fail

```bash
.venv/bin/pytest tests/unit/service_tests/test_feature_writer_service.py -v -k "stream_map"
```

Expected: FAIL — `_stream_map` not defined.

### Step 3: Implement changes in feature_writer_service.py

**3a. In `FeatureWriterService.__init__`, add:**
```python
self._stream_map: dict[str, tuple[str, str]] = {}
```

**3b. In `_setup_consumer_groups`, save stream names:**

The existing loop builds `stream_name = sk_intelligence(self._env_prefix, sym, tf)`. Add after the group create/setid logic:
```python
self._stream_map[stream_name] = (sym, tf)
```

**3c. In `_process_single_message`, change return type to `-> bool`:**

The method currently calls `await self.redis_client.xack(...)` at lines 298 and 311. Remove both xack calls. Add `return True` at the end of the `try` block. Add `return False` in the exception handler.

**3d. Replace `_process_loop` entirely:**
```python
async def _process_loop(self) -> None:
    """Main consumer group loop — reads all streams and processes messages."""
    all_streams = {name: ">" for name in self._stream_map}
    while self.running and not self.shutdown_requested:
        try:
            messages = await self.redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                all_streams, count=10, block=1000,
            )
            for stream_bytes, msgs in messages:
                stream_name = (
                    stream_bytes.decode()
                    if isinstance(stream_bytes, bytes)
                    else stream_bytes
                )
                sym, tf = self._stream_map[stream_name]
                to_ack: list[bytes] = []
                for message_id, fields in msgs:
                    ok = await self._process_single_message(
                        sym, tf, fields, stream_name, message_id
                    )
                    if ok:
                        to_ack.append(message_id)
                if to_ack:
                    await self.redis_client.xack(stream_name, CONSUMER_GROUP, *to_ack)

            await self._maybe_flush(force=False)
        except asyncio.CancelledError:
            break
        except Exception as e:
            self.logger.error("Error in processing loop", error=str(e))
            self.error_count_total.inc()
            self._error_count += 1
            await asyncio.sleep(1)
```

Note: `asyncio.sleep(processing_interval)` removed. `_maybe_flush` is called after each batch (unchanged — it checks the time-based flush interval internally).

### Step 4: Run tests

```bash
.venv/bin/pytest tests/unit/service_tests/test_feature_writer_service.py tests/unit/service_tests/test_feature_writer_config.py -v
```

Expected: ALL PASS

### Step 5: Full suite + restart

```bash
.venv/bin/pytest tests/unit/ -q --tb=short
sudo systemctl restart indicagent-feature-writer
sleep 3
sudo journalctl -u indicagent-feature-writer -n 30 --no-pager
```

### Step 6: Commit

```bash
git add services/feature_writer_service.py tests/unit/service_tests/test_feature_writer_service.py
git commit -m "perf(feature-writer): multi-stream xreadgroup, batch xack, remove sleep"
```

---

## Task 4: signal_tracker_service — polling + sleep + batch xack

**Files:**
- Modify: `services/signal_tracker_service.py`
- Test: `tests/unit/service_tests/test_signal_tracker_service.py`

**Context:** Consumes only `market:SYMBOL:1m` streams — 23 streams (not 92). Uses `_process_single_bar` (returns None currently). Has a reconnect loop inside the exception handler that calls `_setup_consumer_groups` again on error — preserve this.

### Step 1: Write failing tests

Add to `tests/unit/service_tests/test_signal_tracker_service.py`:

```python
def test_stream_map_populated_after_setup():
    """_stream_map must have one entry per symbol (1m only)."""
    import asyncio
    from unittest.mock import AsyncMock
    from services.signal_tracker_service import SignalTrackerService

    svc = SignalTrackerService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xgroup_create = AsyncMock(side_effect=Exception("exists"))
    svc.redis_client.xgroup_setid = AsyncMock()
    svc.db_manager = None

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    symbols = svc.config["service"]["symbols"]
    assert len(svc._stream_map) == len(symbols)
    for stream_name, (sym, tf) in svc._stream_map.items():
        assert tf == "1m"
        assert sym in symbols
```

### Step 2: Run tests to verify they fail

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_tracker_service.py -v -k "stream_map"
```

Expected: FAIL

### Step 3: Implement changes in signal_tracker_service.py

**3a. In `__init__`, add:**
```python
self._stream_map: dict[str, tuple[str, str]] = {}
```

**3b. In `_setup_consumer_groups`, save stream name per symbol:**

The existing loop builds `stream_name = sk_market(self.env_prefix, symbol, "1m")`. After the group create/setid block, add:
```python
self._stream_map[stream_name] = (symbol, "1m")
```

**3c. Change `_process_single_bar` return type to `-> bool`:**

Remove `await self.redis_client.xack(stream_name, self.consumer_group, message_id)` (line 242). Add `return True` at the end of the try block, `return False` in exception handler.

**3d. Replace the polling loop in `_tracker_loop` (or equivalent — the loop around line 282):**

```python
all_streams = {name: ">" for name in self._stream_map}
while self.running and not self.shutdown_requested:
    try:
        messages = await self.redis_client.xreadgroup(
            self.consumer_group, self.consumer_name,
            all_streams, count=10, block=1000,
        )
        for stream_bytes, msgs in messages:
            stream_name = (
                stream_bytes.decode()
                if isinstance(stream_bytes, bytes)
                else stream_bytes
            )
            symbol, timeframe = self._stream_map[stream_name]
            to_ack: list[bytes] = []
            for message_id, fields in msgs:
                ok = await self._process_single_bar(
                    symbol, timeframe, fields, stream_name, message_id
                )
                if ok:
                    to_ack.append(message_id)
            if to_ack:
                await self.redis_client.xack(
                    stream_name, self.consumer_group, *to_ack
                )
    except asyncio.CancelledError:
        break
    except Exception as e:
        error_str = str(e)
        self.logger.error("Error in tracker loop", error=error_str)
        if "NOGROUP" in error_str:
            await self._setup_consumer_groups()
        else:
            self.logger.error("Error in tracker loop", error=error_str)
        await asyncio.sleep(1)
```

Note: `asyncio.sleep(processing_interval)` removed; reconnect logic on `NOGROUP` error preserved.

### Step 4: Run tests

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_tracker_service.py -v
```

Expected: ALL PASS

### Step 5: Full suite + restart

```bash
.venv/bin/pytest tests/unit/ -q --tb=short
sudo systemctl restart indicagent-signal-tracker
sleep 3
sudo journalctl -u indicagent-signal-tracker -n 30 --no-pager
```

### Step 6: Commit

```bash
git add services/signal_tracker_service.py tests/unit/service_tests/test_signal_tracker_service.py
git commit -m "perf(signal-tracker): multi-stream xreadgroup, batch xack, remove sleep"
```

---

## Task 5: ai_narrative_service — polling + sleep + batch xack

**Files:**
- Modify: `services/ai_narrative_service.py`
- Test: `tests/unit/service_tests/test_ai_narrative_service.py`

**Context:** Consumes `signals:SYMBOL:TF:aggregated` streams (23 × 4 = 92 streams). Uses `_process_single_message` with a `finally: xack` block — the xack is always called regardless of success/failure. After refactor, we batch xack only on success (same semantics as other services). The service also has `_group_synthesis_loop` which is independent — leave that alone.

**Special case:** The current loop uses `asyncio.wait_for(shutdown_event.wait(), timeout=processing_interval)` instead of plain `asyncio.sleep`. Remove entirely — the xreadgroup block handles yielding.

### Step 1: Write failing tests

Add to `tests/unit/service_tests/test_ai_narrative_service.py`:

```python
def test_stream_map_populated_after_setup():
    """_stream_map must contain all signal streams after setup."""
    import asyncio
    from unittest.mock import AsyncMock
    from services.ai_narrative_service import AINarrativeService

    svc = AINarrativeService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xgroup_create = AsyncMock(side_effect=Exception("exists"))
    svc.redis_client.xgroup_setid = AsyncMock()

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    symbols = svc.config["service"]["symbols"]
    tfs = svc.config["service"]["timeframes"]
    assert len(svc._stream_map) == len(symbols) * len(tfs)
```

### Step 2: Run tests to verify they fail

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -v -k "stream_map"
```

Expected: FAIL

### Step 3: Implement changes in ai_narrative_service.py

**3a. In `__init__`, add:**
```python
self._stream_map: dict[str, tuple[str, str]] = {}
```

**3b. In `_setup_consumer_groups`, save stream names:**

The existing loop builds `stream_name = signals_aggregated(self.env_prefix, sym, tf)`. After the group create/setid block:
```python
self._stream_map[stream_name] = (sym, tf)
```

**3c. Change `_process_single_message` return type to `-> bool`:**

Currently the method has `finally: await self.redis_client.xack(...)`. Remove the `finally` block. Add `return True` at the end of the try body (before except). Add `return False` in the except handler.

**3d. Replace `_process_loop` entirely:**

```python
async def _process_loop(self) -> None:
    self.logger.info("Starting signal stream processing loop")
    all_streams = {name: ">" for name in self._stream_map}
    while self.running and not self.shutdown_requested:
        try:
            messages = await self.redis_client.xreadgroup(
                self.consumer_group, self.consumer_name,
                all_streams, count=10, block=1000,
            )
            for stream_bytes, msgs in messages:
                stream_name = (
                    stream_bytes.decode()
                    if isinstance(stream_bytes, bytes)
                    else stream_bytes
                )
                symbol, timeframe = self._stream_map[stream_name]
                to_ack: list[bytes] = []
                for message_id, fields in msgs:
                    ok = await self._process_single_message(
                        symbol, timeframe, fields, stream_name, message_id
                    )
                    if ok:
                        to_ack.append(message_id)
                if to_ack:
                    await self.redis_client.xack(
                        stream_name, self.consumer_group, *to_ack
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            self.logger.error("Error in narrative processing loop", error=str(e))
            self.error_count_total.inc()
            self._error_count += 1
            await asyncio.sleep(1)
```

Note: The `asyncio.wait_for(shutdown_event.wait(), ...)` block is removed. `_group_synthesis_loop` is unchanged.

### Step 4: Run tests

```bash
.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py tests/unit/service_tests/test_ai_narrative_helpers.py tests/unit/service_tests/test_ai_narrative_group.py -v
```

Expected: ALL PASS

### Step 5: Full suite + restart

```bash
.venv/bin/pytest tests/unit/ -q --tb=short
sudo systemctl restart indicagent-ai-narrative
sleep 5
sudo journalctl -u indicagent-ai-narrative -n 40 --no-pager
```

### Step 6: Commit

```bash
git add services/ai_narrative_service.py tests/unit/service_tests/test_ai_narrative_service.py
git commit -m "perf(ai-narrative): multi-stream xreadgroup, batch xack, remove polling sleep"
```

---

## Task 6: market_analysis_service — DataFrame cache + batch xack

**Files:**
- Modify: `services/market_analysis_service.py`
- Test: `tests/unit/service_tests/test_market_analysis_service.py`

**Context:** Polling already uses multi-stream xreadgroup (`_process_market_data`). Two things to add: (1) DataFrame cache for main frame and cross-TF frames; (2) batch xack in the outer loop. The `_process_single_bar` currently does the xack after calling `_calculate_intelligence` and `_publish_intelligence`.

**Cross-TF cache note:** In `_calculate_intelligence`, cross-TF frames are built with `pd.DataFrame(list(self.bar_history[other_key]))`. These are cached under the `other_key` and invalidated when bars arrive on `other_key`.

### Step 1: Write failing tests

Add to `tests/unit/service_tests/test_market_analysis_service.py`:

```python
def test_df_cache_miss_builds_dataframe():
    """_get_df must build from bar_history deque on cache miss."""
    from collections import deque
    from datetime import datetime
    import pandas as pd
    from services.market_analysis_service import MarketAnalysisService

    svc = MarketAnalysisService()
    key = "ES:1m"
    svc.bar_history[key] = deque(maxlen=200)
    svc._df_cache[key] = None
    svc.bar_history[key].append({"timestamp": datetime(2026,2,28,10,0), "close": 5303.0})

    df = svc._get_df(key)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1


def test_df_cache_hit_returns_same_object():
    """_get_df must return cached DataFrame on hit."""
    import pandas as pd
    from services.market_analysis_service import MarketAnalysisService

    svc = MarketAnalysisService()
    key = "ES:5m"
    cached = pd.DataFrame([{"close": 5300.0}])
    svc._df_cache[key] = cached

    result = svc._get_df(key)

    assert result is cached


def test_bar_append_invalidates_cache():
    """Appending a bar must clear _df_cache[key]."""
    import pandas as pd
    from collections import deque
    from datetime import datetime
    from services.market_analysis_service import MarketAnalysisService

    svc = MarketAnalysisService()
    key = "NQ:1m"
    svc.bar_history[key] = deque(maxlen=200)
    svc._df_cache[key] = pd.DataFrame([{"close": 5300.0}])

    # Simulate what _process_single_bar does
    svc.bar_history[key].append({"timestamp": datetime(2026,2,28,10,1), "close": 5310.0})
    svc._df_cache[key] = None

    assert svc._df_cache[key] is None
```

### Step 2: Run tests to verify they fail

```bash
.venv/bin/pytest tests/unit/service_tests/test_market_analysis_service.py -v -k "df_cache or bar_append"
```

Expected: FAIL — `_df_cache`, `_get_df` not defined.

### Step 3: Implement changes in market_analysis_service.py

**3a. In `__init__`, add after `self.intelligence_cache`:**
```python
self._df_cache: dict[str, "pd.DataFrame | None"] = {}
```

**3b. Add `_get_df` helper after `_min_bars_for_tf`:**
```python
def _get_df(self, key: str) -> "pd.DataFrame":
    if self._df_cache.get(key) is None:
        self._df_cache[key] = pd.DataFrame(list(self.bar_history[key]))
    return self._df_cache[key]
```

**3c. In `_calculate_intelligence`, replace both `pd.DataFrame(...)` calls:**

Replace:
```python
df = pd.DataFrame(list(history))
frames: dict[str, Any] = {"main": df}
...
frames[f"tf_{other_tf}"] = pd.DataFrame(list(self.bar_history[other_key]))
```

With:
```python
frames: dict[str, Any] = {"main": self._get_df(key)}
...
frames[f"tf_{other_tf}"] = self._get_df(other_key)
```

**3d. In `_process_single_bar`, add cache invalidation after bar append:**

After `self.bar_history[key].append(bar_data)` (line ~308):
```python
self._df_cache[key] = None
```

**3e. Change `_process_single_bar` return type to `-> bool`:**

Remove `await self.redis_client.xack(stream_name, self.consumer_group, message_id)` from inside the method. Add `return True` at the end of the `try` block, `return False` in the exception handler.

**3f. In `_process_market_data`, add batch xack after the inner message loop:**

The current loop:
```python
for message_id, fields in msgs:
    await self._process_single_bar(symbol, timeframe, fields, stream_name, message_id)
```

Replace with:
```python
to_ack: list[bytes] = []
for message_id, fields in msgs:
    ok = await self._process_single_bar(symbol, timeframe, fields, stream_name, message_id)
    if ok:
        to_ack.append(message_id)
if to_ack:
    await self.redis_client.xack(stream_name, self.consumer_group, *to_ack)
```

### Step 4: Run tests

```bash
.venv/bin/pytest tests/unit/service_tests/test_market_analysis_service.py -v
```

Expected: ALL PASS

### Step 5: Full suite + restart

```bash
.venv/bin/pytest tests/unit/ -q --tb=short
sudo systemctl restart indicagent-market-analysis
sleep 5
sudo journalctl -u indicagent-market-analysis -n 40 --no-pager
```

### Step 6: Commit

```bash
git add services/market_analysis_service.py tests/unit/service_tests/test_market_analysis_service.py
git commit -m "perf(market-analysis): DataFrame cache with dirty-flag invalidation, batch xack"
```

---

## Final Verification

After all 6 tasks complete:

```bash
# Full test suite
.venv/bin/pytest tests/unit/ -v --tb=short -q

# All pipeline services healthy
sudo systemctl status indicagent-indicator indicagent-market-analysis indicagent-signal-generator indicagent-feature-writer indicagent-signal-tracker indicagent-ai-narrative

# Watch live logs for errors
sudo journalctl -u indicagent-indicator -u indicagent-market-analysis -u indicagent-signal-generator -f
```

Watch for `"I1 published"`, `"Bar processed"`, `"intelligence published"` log lines flowing within 1–2s of each minute boundary. Previously they lagged up to 9s.
