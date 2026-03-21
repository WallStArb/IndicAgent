# Market Bars Topic Split + Completeness Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `market.bars` into `market.bars` (1m only, from TWS) and `market.bars.htf` (5m–1d, from timeframe builder), and add `bar_count`/`is_complete` fields to every emitted HTF bar.

**Architecture:** The timeframe builder currently reads from AND writes to `market.bars`, creating a self-referential loop in the DAG. After this change, TWS is the only writer to `market.bars` (1m bars only), and the timeframe builder writes to a new `market.bars.htf` topic. All consumers that need HTF bars subscribe to both topics. The `bar_count` and `is_complete` fields on each HTF bar make partial bars (emitted after a mid-period restart) visible to downstream consumers instead of silently corrupting indicators.

**Tech Stack:** Python 3.13, aiokafka, Redpanda (Kafka-compatible), structlog, pytest

---

## Files Changed

| File | Change |
|------|--------|
| `src/core/stream_keys.py` | Add `topic_market_bars_htf()` |
| `src/core/timeframe_builder.py` | Add `bar_count` tracking to `_update_accumulator` |
| `services/timeframes_builder_service.py` | Produce to `market.bars.htf`; add `bar_count`/`is_complete` to payload |
| `services/indicator_service.py` | Subscribe to both `market.bars` and `market.bars.htf` |
| `services/signal_lifecycle_service.py` | Subscribe to both `market.bars` and `market.bars.htf` |
| `src/api/main.py` | Add `topic_market_bars_htf` to SSE consumer |
| `src/api/routes/sse.py` | Add `market.bars.htf` to `_build_topic_list` and `_build_stream_list` |
| `tests/unit/core/test_stream_keys_htf.py` | New: test `topic_market_bars_htf` |
| `tests/unit/core/test_timeframe_builder.py` | Extend: test `bar_count` in accumulator |
| `tests/unit/test_timeframes_builder_service.py` | New: test completeness fields in emitted bars |

---

## Task 1: Add `topic_market_bars_htf` to stream_keys

**Files:**
- Modify: `src/core/stream_keys.py` (after `topic_market_bars`, ~line 42)
- Create: `tests/unit/core/test_stream_keys_htf.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/core/test_stream_keys_htf.py
from src.core.stream_keys import topic_market_bars_htf


def test_topic_market_bars_htf_with_env():
    assert topic_market_bars_htf("development") == "development.market.bars.htf"


def test_topic_market_bars_htf_no_env():
    assert topic_market_bars_htf("") == "market.bars.htf"
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/unit/core/test_stream_keys_htf.py -v
```
Expected: `ImportError: cannot import name 'topic_market_bars_htf'`

- [ ] **Step 3: Add function to stream_keys.py**

Insert after the `topic_market_bars` function (~line 43):

```python
def topic_market_bars_htf(env_name: str) -> str:
    """Kafka topic for aggregated higher-timeframe bars (5m–1d) from timeframe builder.

    Separate from topic_market_bars (1m only from TWS) to make the DAG acyclic:
    timeframe builder reads market.bars, writes market.bars.htf — no self-reference.
    """
    return f"{env_prefix(env_name)}market.bars.htf"
```

Also update the docstring of `topic_market_bars` to clarify it is 1m only:
```python
def topic_market_bars(env_name: str) -> str:
    """Kafka topic for 1m OHLCV bars from TWS daemon (raw, immutable ground truth)."""
    return f"{env_prefix(env_name)}market.bars"
```

- [ ] **Step 4: Run to verify pass**

```bash
.venv/bin/pytest tests/unit/core/test_stream_keys_htf.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/core/stream_keys.py tests/unit/core/test_stream_keys_htf.py
git commit -m "feat: add topic_market_bars_htf for DAG-clean HTF bar topic"
```

---

## Task 2: Add `bar_count` to accumulator pure functions

The accumulator in `src/core/timeframe_builder.py` tracks OHLCV state across 1m bars.
Adding `bar_count` here lets the service compute `is_complete` at emit time without extra state.

**Files:**
- Modify: `src/core/timeframe_builder.py` (`_update_accumulator`, ~line 62)
- Modify: `tests/unit/core/test_timeframe_builder.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/core/test_timeframe_builder.py`:

```python
from src.core.timeframe_builder import _update_accumulator


def test_update_accumulator_sets_bar_count_on_create():
    bar = {"open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 500}
    acc = _update_accumulator(None, bar, period_ts=1000)
    assert acc["bar_count"] == 1


def test_update_accumulator_increments_bar_count():
    bar1 = {"open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 500}
    bar2 = {"open": 103.0, "high": 107.0, "low": 102.0, "close": 106.0, "volume": 300}
    acc = _update_accumulator(None, bar1, period_ts=1000)
    acc = _update_accumulator(acc, bar2, period_ts=1000)
    assert acc["bar_count"] == 2


def test_update_accumulator_bar_count_does_not_affect_ohlcv():
    bar1 = {"open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 500}
    bar2 = {"open": 103.0, "high": 107.0, "low": 98.0, "close": 106.0, "volume": 300}
    acc = _update_accumulator(None, bar1, period_ts=1000)
    acc = _update_accumulator(acc, bar2, period_ts=1000)
    assert acc["open"] == 100.0    # first bar's open preserved
    assert acc["high"] == 107.0   # max of both highs
    assert acc["low"] == 98.0     # min of both lows
    assert acc["close"] == 106.0  # last bar's close
    assert acc["volume"] == 800   # summed
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/unit/core/test_timeframe_builder.py::test_update_accumulator_sets_bar_count_on_create -v
```
Expected: FAIL — `KeyError: 'bar_count'` or AssertionError

- [ ] **Step 3: Update `_update_accumulator`**

> **Note on dead code:** `src/core/timeframe_builder.py` also contains a legacy `TimeframeBuilder` class (lines 113–473) with its own `_emit_bar` method that writes to Redis. This class is **not imported by any active service** — `timeframes_builder_service.py` only imports the four pure functions. Do NOT update `TimeframeBuilder._emit_bar` — it is dead code and its Redis-mocked tests will break if you try to apply the new signature. Leave the class as-is; it will be deleted in a future cleanup phase.

In `src/core/timeframe_builder.py`, replace the `_update_accumulator` function body:

```python
def _update_accumulator(
    acc: dict[str, Any] | None,
    bar: dict[str, Any],
    period_ts: int,
) -> dict[str, Any]:
    """Update or create an OHLCV accumulator for the given period.

    Args:
        acc: Existing accumulator dict or None if this is the first bar.
        bar: Incoming bar with open/high/low/close/volume/period_ts fields.
        period_ts: Period start timestamp in seconds.

    Returns:
        Updated accumulator dict with bar_count tracking how many 1m bars contributed.
    """
    if acc is None:
        return {
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar["volume"],
            "period_ts": period_ts,
            "bar_count": 1,
        }

    return {
        "open": acc["open"],  # keep first bar's open
        "high": max(acc["high"], bar["high"]),
        "low": min(acc["low"], bar["low"]),
        "close": bar["close"],  # latest bar's close
        "volume": acc["volume"] + bar["volume"],
        "period_ts": period_ts,
        "bar_count": acc["bar_count"] + 1,
    }
```

- [ ] **Step 4: Run all timeframe builder tests**

```bash
.venv/bin/pytest tests/unit/core/test_timeframe_builder.py -v
```
Expected: all PASSED (including pre-existing tests)

- [ ] **Step 5: Commit**

```bash
git add src/core/timeframe_builder.py tests/unit/core/test_timeframe_builder.py
git commit -m "feat: add bar_count tracking to accumulator for completeness metadata"
```

---

## Task 3: Update timeframes_builder_service — new topic + completeness fields

**Files:**
- Modify: `services/timeframes_builder_service.py`
- Create: `tests/unit/test_timeframes_builder_service.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_timeframes_builder_service.py
"""Unit tests for TimeframeBuilderService completeness metadata and topic routing."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.timeframe_builder import _TARGET_TIMEFRAMES, _update_accumulator


def _make_accumulator(bar_count: int, tf: str) -> dict:
    """Build a completed accumulator with the given bar_count."""
    bar = {"open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 500}
    acc = None
    for _ in range(bar_count):
        acc = _update_accumulator(acc, bar, period_ts=1000)
    return acc


def test_is_complete_true_when_bar_count_equals_tf_minutes():
    """A 5m bar built from exactly 5 × 1m bars is complete."""
    tf = "5m"
    tf_minutes = _TARGET_TIMEFRAMES[tf]
    acc = _make_accumulator(bar_count=tf_minutes, tf=tf)
    is_complete = acc["bar_count"] == tf_minutes
    assert is_complete is True


def test_is_complete_false_when_bar_count_less_than_tf_minutes():
    """A 5m bar built from 3 × 1m bars (service restarted mid-period) is incomplete."""
    tf = "5m"
    tf_minutes = _TARGET_TIMEFRAMES[tf]
    acc = _make_accumulator(bar_count=3, tf=tf)
    is_complete = acc["bar_count"] == tf_minutes
    assert is_complete is False


def test_bar_count_correct_for_15m():
    acc = _make_accumulator(bar_count=15, tf="15m")
    assert acc["bar_count"] == 15
    assert acc["bar_count"] == _TARGET_TIMEFRAMES["15m"]


def test_bar_count_correct_for_1h():
    acc = _make_accumulator(bar_count=60, tf="1h")
    assert acc["bar_count"] == 60
    assert acc["bar_count"] == _TARGET_TIMEFRAMES["1h"]


@pytest.mark.asyncio
async def test_emit_bar_includes_completeness_fields():
    """_emit_bar must include bar_count and is_complete in the published payload."""
    from services.timeframes_builder_service import TimeframeBuilderService

    svc = TimeframeBuilderService.__new__(TimeframeBuilderService)
    svc._env_name = "development"
    svc._last_emitted = {}
    svc._bars_built = {tf: 0 for tf in _TARGET_TIMEFRAMES}

    published_payload = {}

    async def _capture_publish(topic, payload, key=None):
        published_payload.update(payload)

    mock_producer = MagicMock()
    mock_producer.publish = AsyncMock(side_effect=_capture_publish)
    svc._producer = mock_producer

    tf = "5m"
    tf_minutes = _TARGET_TIMEFRAMES[tf]
    acc = _make_accumulator(bar_count=3, tf=tf)  # incomplete — only 3 of 5 bars

    await svc._emit_bar("ES", tf, acc, tf_minutes)

    assert "bar_count" in published_payload
    assert published_payload["bar_count"] == 3
    assert "is_complete" in published_payload
    assert published_payload["is_complete"] is False


@pytest.mark.asyncio
async def test_emit_bar_complete_flag_true_when_full():
    """is_complete=True when bar_count equals tf_minutes."""
    from services.timeframes_builder_service import TimeframeBuilderService

    svc = TimeframeBuilderService.__new__(TimeframeBuilderService)
    svc._env_name = "development"
    svc._last_emitted = {}
    svc._bars_built = {tf: 0 for tf in _TARGET_TIMEFRAMES}

    published_payload = {}

    async def _capture_publish(topic, payload, key=None):
        published_payload.update(payload)

    mock_producer = MagicMock()
    mock_producer.publish = AsyncMock(side_effect=_capture_publish)
    svc._producer = mock_producer

    tf = "5m"
    tf_minutes = _TARGET_TIMEFRAMES[tf]
    acc = _make_accumulator(bar_count=5, tf=tf)  # complete

    await svc._emit_bar("ES", tf, acc, tf_minutes)

    assert published_payload["is_complete"] is True
    assert published_payload["bar_count"] == 5
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/unit/test_timeframes_builder_service.py -v
```
Expected: failures on `_emit_bar` tests — signature mismatch or missing fields

- [ ] **Step 3: Update `timeframes_builder_service.py`**

**3a.** Update the import at the top to include `topic_market_bars_htf`:
```python
from src.core.stream_keys import message_key, topic_market_bars, topic_market_bars_htf
```

**3b.** Update `__init__` to store the HTF topic:
```python
self._htf_topic = topic_market_bars_htf(self._env_name)
```

**3c.** Update `_process_bar` signature — pass `tf_minutes` through to `_emit_bar`:

In the `for tf, tf_minutes in _TARGET_TIMEFRAMES.items():` loop, update the emit call:
```python
if acc is not None and acc["period_ts"] != new_period_ts:
    await self._emit_bar(symbol, tf, acc, tf_minutes)
    acc = None
```

**3d.** Update `_emit_bar` signature and payload:
```python
async def _emit_bar(self, symbol: str, timeframe: str, acc: dict[str, Any], tf_minutes: int) -> None:
    """Publish a completed aggregated bar to development.market.bars.htf."""
    period_ts = acc["period_ts"]

    last = self._last_emitted.get(symbol, {}).get(timeframe)
    if last is not None and period_ts <= last:
        self.logger.debug(
            "Skipping duplicate bar",
            symbol=symbol,
            timeframe=timeframe,
            period_ts=period_ts,
        )
        return

    assert self._producer is not None
    period_ts_dt = datetime.fromtimestamp(period_ts, tz=UTC)
    tf_secs = TF_DURATIONS.get(timeframe, 0)
    close_ts = (period_ts_dt + timedelta(seconds=tf_secs)).isoformat()
    bar_count = acc.get("bar_count", 0)
    is_complete = bar_count == tf_minutes

    payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": period_ts_dt.isoformat(),
        "open": str(acc["open"]),
        "high": str(acc["high"]),
        "low": str(acc["low"]),
        "close": str(acc["close"]),
        "volume": str(acc["volume"]),
        "bar_count": bar_count,
        "is_complete": is_complete,
        "source": "timeframe_builder",
        "bar_close_ts": close_ts,
    }

    try:
        await self._producer.publish(
            self._htf_topic,
            payload,
            key=message_key(symbol, timeframe),
        )
        self._bars_built[timeframe] = self._bars_built.get(timeframe, 0) + 1
        self._last_emitted.setdefault(symbol, {})[timeframe] = period_ts
        self.logger.debug(
            "Emitted aggregated bar",
            symbol=symbol,
            timeframe=timeframe,
            period_ts=period_ts,
            bar_count=bar_count,
            is_complete=is_complete,
        )
    except Exception as e:
        self.logger.error(
            "Failed to emit bar",
            symbol=symbol,
            timeframe=timeframe,
            error=str(e),
        )
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/pytest tests/unit/test_timeframes_builder_service.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add services/timeframes_builder_service.py tests/unit/test_timeframes_builder_service.py
git commit -m "feat: timeframe builder writes to market.bars.htf with bar_count/is_complete"
```

---

## Task 4: Update indicator_service to consume both bar topics

The indicator service currently subscribes only to `market.bars`. It needs HTF bars
from `market.bars.htf` for its `bar_history` (5m/15m/1h/4h/1d TFs).

**Files:**
- Modify: `services/indicator_service.py` (~line 44 imports, ~line 690 consumer setup)

- [ ] **Step 1: Update import**

In the imports block near line 44, add `topic_market_bars_htf`:
```python
from src.core.stream_keys import (
    message_key,
    topic_indicators,
    topic_market_bars,
    topic_market_bars_htf,
    topic_market_ticks,
    topic_system_events,
)
```

- [ ] **Step 2: Update consumer topics list (~line 690)**

```python
topics: list[str] = [
    topic_market_bars(self.env_name),
    topic_market_bars_htf(self.env_name),
]
```

- [ ] **Step 3: Run existing indicator unit tests**

```bash
.venv/bin/pytest tests/unit/service_tests/ -v -k "indicator" 2>/dev/null || .venv/bin/pytest tests/unit/ -v -k "indicator" --ignore=tests/unit/intelligence
```
Expected: all PASSED (no logic changes, just topic subscription)

- [ ] **Step 4: Commit**

```bash
git add services/indicator_service.py
git commit -m "feat: indicator_service subscribes to market.bars.htf for HTF bars"
```

---

## Task 5: Update signal_lifecycle_service to consume both bar topics

Signal lifecycle needs HTF bars (5m/15m/1h) to track freshness decay and bars-elapsed
for signals fired on those timeframes.

**Files:**
- Modify: `services/signal_lifecycle_service.py` (`_setup_kafka_clients`, ~line 953)

- [ ] **Step 1: Update import**

Add `topic_market_bars_htf` to the existing stream_keys imports near the top of the file:
```python
from src.core.stream_keys import (
    topic_llm_outcomes,
    topic_market_bars,
    topic_market_bars_htf,
    topic_signals,
)
```

- [ ] **Step 2: Update `_setup_kafka_clients`**

```python
async def _setup_kafka_clients(self) -> None:
    self._kafka_consumer = KafkaConsumerClient(
        topic_market_bars(self.env_name),
        topic_market_bars_htf(self.env_name),
        bootstrap_servers=self._kafka_bootstrap,
        group_id="signal_lifecycle",
        auto_offset_reset="latest",
    )
    self._kafka_producer = KafkaProducerClient(
        bootstrap_servers=self._kafka_bootstrap,
    )
    await self._kafka_consumer.start()
    await self._kafka_producer.start()
```

- [ ] **Step 3: Run existing lifecycle unit tests**

```bash
.venv/bin/pytest tests/unit/ -v -k "lifecycle" 2>/dev/null || echo "no lifecycle tests found"
```
Expected: PASSED or no tests (no logic change)

- [ ] **Step 4: Commit**

```bash
git add services/signal_lifecycle_service.py
git commit -m "feat: signal_lifecycle_service subscribes to market.bars.htf"
```

---

## Task 6: Update SSE broadcaster to consume both bar topics

The API SSE broadcaster fans out all Kafka messages to dashboard clients.
Both bar topics must be included so the dashboard receives 1m and HTF bars.

**Files:**
- Modify: `src/api/main.py` (~line 56 imports, ~line 71 consumer)
- Modify: `src/api/routes/sse.py` (`_build_topic_list`, `_build_stream_list`, ~lines 113, 199)

- [ ] **Step 1: Update `src/api/main.py` imports and consumer**

In the import block (~line 51):
```python
from src.core.stream_keys import (
    topic_indicators,
    topic_intelligence,
    topic_intelligence_i7,
    topic_intelligence_i8,
    topic_market_bars,
    topic_market_bars_htf,
    topic_market_ticks,
    topic_narratives,
    topic_narratives_group,
    topic_signals_aggregated,
)
```

In the `KafkaConsumerClient(...)` call (~line 69), add `topic_market_bars_htf(env_name)` after `topic_market_bars(env_name)`:
```python
_sse_consumer = KafkaConsumerClient(
    topic_market_ticks(env_name),
    topic_market_bars(env_name),
    topic_market_bars_htf(env_name),
    topic_indicators(env_name),
    topic_intelligence(env_name),
    topic_intelligence_i7(env_name),
    topic_intelligence_i8(env_name),
    topic_signals_aggregated(env_name),
    topic_narratives(env_name),
    topic_narratives_group(env_name),
    bootstrap_servers=kafka_bootstrap,
    group_id="sse_broadcaster",
    auto_offset_reset="earliest",
)
```

- [ ] **Step 2: Update `src/api/routes/sse.py` imports and topic lists**

Add `topic_market_bars_htf` to the import block (~line 20):
```python
from ...core.stream_keys import (
    topic_indicators,
    topic_intelligence,
    topic_intelligence_i7,
    topic_intelligence_i8,
    topic_market_bars,
    topic_market_bars_htf,
    topic_market_ticks,
    topic_narratives,
    topic_narratives_group,
    topic_signals_aggregated,
)
```

In `_build_topic_list` (~line 113), add after `topic_market_bars`:
```python
topics.append(topic_market_bars(env_name))
topics.append(topic_market_bars_htf(env_name))
```

> **Do NOT modify `_build_stream_list`** — that function builds Redis-style stream names for legacy backward compatibility and is not used by the active SSE endpoint. The live SSE path only calls `_build_topic_list`.

Note: `_event_name_for_topic` already handles `market.bars.htf` correctly — `candidate.startswith("market.bars")` catches it and returns `"market_data"`. No change needed. Optionally add `"market.bars.htf"` to the `known_prefixes` set for explicitness, but it is not required for correctness.

- [ ] **Step 3: Run API unit tests**

```bash
.venv/bin/pytest tests/unit/ -v -k "sse or api" 2>/dev/null || echo "no SSE tests found"
```

- [ ] **Step 4: Commit**

```bash
git add src/api/main.py src/api/routes/sse.py
git commit -m "feat: SSE broadcaster subscribes to market.bars.htf"
```

---

## Task 7: Create Kafka topic and restart services

- [ ] **Step 1: Create `development.market.bars.htf` Kafka topic with 7-day retention**

```bash
docker exec redpanda rpk topic create development.market.bars.htf \
  --topic-config retention.ms=604800000
```
Expected output: `Created topic "development.market.bars.htf".`

- [ ] **Step 2: Verify topic exists**

```bash
docker exec redpanda rpk topic list | grep market.bars
```
Expected: both `development.market.bars` and `development.market.bars.htf` listed

- [ ] **Step 3: Restart affected services**

```bash
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl restart \
  indicagent-timeframes \
  indicagent-indicator \
  indicagent-signal-lifecycle \
  indicagent-api
```

- [ ] **Step 4: Verify timeframes service is publishing to the new topic**

```bash
sleep 10 && docker exec redpanda rpk topic consume development.market.bars.htf \
  --num 1 --format json 2>/dev/null | head -30
```
Expected: a JSON message with `bar_count` and `is_complete` fields

- [ ] **Step 5: Verify `market.bars` no longer receives HTF bars**

```bash
docker exec redpanda rpk topic consume development.market.bars \
  --num 5 --format json 2>/dev/null | grep '"timeframe"'
```
Expected: only `"timeframe": "1m"` entries — no 5m/15m/1h/4h/1d

- [ ] **Step 6: Check service health**

```bash
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl is-active \
  indicagent-timeframes indicagent-indicator indicagent-signal-lifecycle indicagent-api
```
Expected: `active` for all four

- [ ] **Step 7: Run full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```
Expected: all PASSED

- [ ] **Step 8: Final commit**

```bash
git add -A
git commit -m "ops: create market.bars.htf Kafka topic with 7-day retention"
```

---

## Verification Checklist

After all tasks complete:

- [ ] `topic_market_bars_htf` exported from `stream_keys.py`
- [ ] `_update_accumulator` returns `bar_count` in every accumulator dict
- [ ] `timeframes_builder_service` publishes to `market.bars.htf` only (never `market.bars`)
- [ ] Every HTF bar payload contains `bar_count: int` and `is_complete: bool`
- [ ] `indicator_service` subscribed to both topics
- [ ] `signal_lifecycle_service` subscribed to both topics
- [ ] SSE broadcaster subscribed to both topics
- [ ] `development.market.bars.htf` topic exists with 7-day retention
- [ ] Dashboard shows 5m bars with correct OHLCV (not NaN)
- [ ] All unit tests pass
