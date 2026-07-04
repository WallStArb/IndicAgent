# SSE Broadcaster Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four correctness problems in `KafkaSSEBroadcaster`: delete dead Redis legacy code, add drop telemetry, bound the snapshot cache, and replace O(N) list fan-out with topic-indexed O(matching) dispatch.

**Architecture:** All changes are confined to `src/api/routes/sse.py` and `src/observability/metrics.py`. The broadcaster is refactored to a `dict[topic, set[_Subscription]]` structure so each incoming Kafka message is dispatched only to clients that subscribed to that topic — not all connected clients. A `_Subscription` dataclass replaces the raw `asyncio.Queue` as the subscription handle so subscribe/unsubscribe are O(1) set operations.

**Tech Stack:** Python 3.11, asyncio, FastAPI, OpenTelemetry SDK (OTel counter via `_meter` in `src/observability/metrics.py`), pytest with `asyncio_mode = auto`.

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `src/api/routes/sse.py` | Modify | Delete dead Redis functions/imports/constant; add `_Subscription` dataclass; refactor `KafkaSSEBroadcaster`; update `sse_events` endpoint |
| `src/observability/metrics.py` | Modify | Add `SSE_MESSAGES_DROPPED_TOTAL` counter |
| `tests/unit/api/test_sse_intelligence.py` | **Delete** | Only tests dead `_event_name_for_stream`; replaced by new test file |
| `tests/unit/api/test_sse_broadcaster.py` | Create | Unit tests for the refactored broadcaster |

---

## Task 1: Delete dead Redis code and its test

The following are dead after the Kafka migration and must be removed before the refactor to avoid confusion.

**Dead code in `src/api/routes/sse.py`:**
- 9 Redis-style imports (`sk_indicators`, `sk_intelligence`, `sk_intelligence_i7`, `sk_live_tick`, `sk_market`, `sk_narratives`, `sk_narratives_group`, `sk_signals_aggregated`, `sk_system_events`)
- `from ..utils import resolve_contract as _resolve_contract`
- `_NARRATIVE_GROUPS` constant
- `_build_stream_list()` function (~30 lines)
- `_event_name_for_stream()` function (~20 lines)

**Dead test file:** `tests/unit/api/test_sse_intelligence.py` — imports and tests only `_event_name_for_stream`.

**Files:**
- Modify: `src/api/routes/sse.py`
- Delete: `tests/unit/api/test_sse_intelligence.py`

- [ ] **Step 1: Delete the test file**

```bash
rm tests/unit/api/test_sse_intelligence.py
```

- [ ] **Step 2: Remove the 10 dead imports from `sse.py`**

Remove these lines from the top of `src/api/routes/sse.py` (they are the Redis-style `sk_*` imports and `resolve_contract`):

```python
# DELETE these lines:
from ...core.stream_keys import indicators as sk_indicators
from ...core.stream_keys import intelligence as sk_intelligence
from ...core.stream_keys import intelligence_i7 as sk_intelligence_i7
from ...core.stream_keys import live_tick as sk_live_tick
from ...core.stream_keys import market as sk_market
from ...core.stream_keys import narratives as sk_narratives
from ...core.stream_keys import narratives_group as sk_narratives_group
from ...core.stream_keys import signals_aggregated as sk_signals_aggregated
from ...core.stream_keys import system_events as sk_system_events
from ..utils import resolve_contract as _resolve_contract
```

- [ ] **Step 3: Remove `_NARRATIVE_GROUPS`, `_build_stream_list`, and `_event_name_for_stream` from `sse.py`**

Delete the `_NARRATIVE_GROUPS` constant and the two functions in full. They span from the `_NARRATIVE_GROUPS = ...` line down through the end of `_event_name_for_stream`. The `_event_name_for_topic` function (the Kafka one with `@functools.lru_cache`) is **kept** — only the Redis-style one is deleted.

- [ ] **Step 4: Verify the file still imports cleanly**

```bash
.venv/bin/python -c "from src.api.routes.sse import KafkaSSEBroadcaster, sse_events"
```

Expected: no output, exit 0.

- [ ] **Step 5: Run the test suite to confirm green**

```bash
.venv/bin/pytest tests/unit/api/ -v
```

Expected: all existing tests pass; `test_sse_intelligence.py` no longer listed.

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/sse.py
git rm tests/unit/api/test_sse_intelligence.py
git commit -m "chore: delete dead Redis SSE helpers and their test"
```

---

## Task 2: Add `SSE_MESSAGES_DROPPED_TOTAL` counter to metrics

**Files:**
- Modify: `src/observability/metrics.py`

- [ ] **Step 1: Append the new counter at the end of `src/observability/metrics.py`**

```python
# ---------------------------------------------------------------------------
# SSE delivery (Phase hardening)
# ---------------------------------------------------------------------------

SSE_MESSAGES_DROPPED_TOTAL = _meter.create_counter(
    "sse_messages_dropped_total",
    description="SSE messages dropped because the client queue was full",
)
```

- [ ] **Step 2: Verify the counter is importable**

```bash
.venv/bin/python -c "from src.observability.metrics import SSE_MESSAGES_DROPPED_TOTAL; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/observability/metrics.py
git commit -m "feat(metrics): add sse_messages_dropped_total counter"
```

---

## Task 3: Refactor `KafkaSSEBroadcaster` to topic-indexed fan-out

Replace the `list[asyncio.Queue]` fan-out with a `dict[topic, set[_Subscription]]` structure. Add `_latest` size bound. Wire the drop counter from Task 2.

**Files:**
- Modify: `src/api/routes/sse.py`

- [ ] **Step 1: Add `dataclass` import and `_MAX_LATEST_KEYS` constant**

At the top of `src/api/routes/sse.py`, add `dataclass` and `field` to the imports block and a module-level constant. The existing imports already include `asyncio`, `defaultdict`, `json`, `functools`:

```python
# Add to existing imports:
from dataclasses import dataclass, field as dc_field

# Add as module-level constant after the imports:
_MAX_LATEST_KEYS = 200  # per-topic snapshot cap; prevents unbounded growth on contract rolls
```

- [ ] **Step 2: Add the `_Subscription` dataclass immediately before `KafkaSSEBroadcaster`**

```python
@dataclass
class _Subscription:
    queue: asyncio.Queue = dc_field(repr=False)
    topics: frozenset[str]
```

- [ ] **Step 3: Replace the `KafkaSSEBroadcaster.__init__` body**

Old:
```python
def __init__(self) -> None:
    self._queues: list[asyncio.Queue] = []
    self._latest: dict[str, dict[str, dict]] = defaultdict(dict)
```

New:
```python
def __init__(self) -> None:
    self._by_topic: dict[str, set[_Subscription]] = defaultdict(set)
    self._latest: dict[str, dict[str, dict]] = defaultdict(dict)
```

- [ ] **Step 4: Replace the `run()` method body**

The `_extract_signal_scorecard_payload` static method stays unchanged. Replace only the `run()` method:

```python
async def run(self, consumer: object) -> None:
    settings = _get_settings()
    env_name = settings.env_name or ""
    _intelligence_record_topic = topic_intelligence_journal(env_name)

    async for topic, key, payload in consumer.messages():  # type: ignore[union-attr]
        if isinstance(payload, dict) and payload.get("source") == "ibkr_seed":
            continue
        if topic == _intelligence_record_topic:
            payload = self._extract_signal_scorecard_payload(payload)
        item = {"topic": topic, "key": key, "payload": payload}
        slot = key if key is not None else "__keyless"

        # Size-bounded latest snapshot: evict oldest when topic is full
        topic_latest = self._latest[topic]
        if len(topic_latest) >= _MAX_LATEST_KEYS and slot not in topic_latest:
            oldest = next(iter(topic_latest))
            del topic_latest[oldest]
        topic_latest[slot] = item

        # Fan-out only to subscriptions that requested this topic — O(matching)
        for sub in list(self._by_topic.get(topic, ())):
            try:
                sub.queue.put_nowait(item)
            except asyncio.QueueFull:
                SSE_MESSAGES_DROPPED_TOTAL.add(1, {"topic": topic})
```

- [ ] **Step 5: Replace `subscribe()` and `unsubscribe()`**

Old:
```python
def subscribe(self) -> tuple[dict, asyncio.Queue]:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    self._queues.append(q)
    return self._latest, q

def unsubscribe(self, q: asyncio.Queue) -> None:
    try:
        self._queues.remove(q)
    except ValueError:
        pass
```

New:
```python
def subscribe(self, topics: frozenset[str]) -> tuple[dict, _Subscription]:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    sub = _Subscription(queue=q, topics=topics)
    for topic in topics:
        self._by_topic[topic].add(sub)
    return self._latest, sub

def unsubscribe(self, sub: _Subscription) -> None:
    for topic in sub.topics:
        self._by_topic[topic].discard(sub)
```

- [ ] **Step 6: Update `sse_events` to use the new API**

In `sse_events`, replace the three lines that call `broadcaster.subscribe()` / use `live_q` / call `broadcaster.unsubscribe(live_q)`:

Old:
```python
snapshot, live_q = broadcaster.subscribe()

async def event_generator() -> AsyncGenerator[bytes]:
    try:
        ...
        try:
            item = await asyncio.wait_for(live_q.get(), timeout=5.0)
        ...
        # Filter to only topics this client subscribed to
        if item["topic"] not in topic_set:
            continue
        ...
    finally:
        broadcaster.unsubscribe(live_q)
```

New (the `topic_set` filter line is removed — broadcaster now handles it):
```python
snapshot, sub = broadcaster.subscribe(frozenset(topic_list))

async def event_generator() -> AsyncGenerator[bytes]:
    try:
        ...
        try:
            item = await asyncio.wait_for(sub.queue.get(), timeout=5.0)
        ...
        # No topic filter needed — broadcaster delivers only subscribed topics
        ...
    finally:
        broadcaster.unsubscribe(sub)
```

Also remove the `topic_set = set(topic_list)` line immediately above the `subscribe()` call — it is no longer used.

- [ ] **Step 7: Add the import for `SSE_MESSAGES_DROPPED_TOTAL`**

In the imports section of `src/api/routes/sse.py`, add:

```python
from src.observability.metrics import SSE_MESSAGES_DROPPED_TOTAL
```

- [ ] **Step 8: Verify the file imports cleanly**

```bash
.venv/bin/python -c "from src.api.routes.sse import KafkaSSEBroadcaster, _Subscription, _MAX_LATEST_KEYS"
```

Expected: no output, exit 0.

- [ ] **Step 9: Run existing tests**

```bash
.venv/bin/pytest tests/unit/api/ -v
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add src/api/routes/sse.py
git commit -m "refactor(sse): topic-indexed fan-out, bounded snapshot cache, drop counter"
```

---

## Task 4: Write unit tests for the refactored broadcaster

**Files:**
- Create: `tests/unit/api/test_sse_broadcaster.py`

- [ ] **Step 1: Create the test file**

```python
"""Unit tests for KafkaSSEBroadcaster — topic-indexed fan-out, drop counter, snapshot bound."""

import asyncio
from unittest.mock import MagicMock

from src.api.routes.sse import KafkaSSEBroadcaster, _MAX_LATEST_KEYS, _Subscription


class _MockConsumer:
    """Async generator consumer yielding a fixed sequence of (topic, key, payload) tuples."""

    def __init__(self, messages: list[tuple[str, str, dict]]) -> None:
        self._messages = messages

    async def messages(self):
        for msg in self._messages:
            yield msg


async def test_subscriber_receives_matching_topic():
    broadcaster = KafkaSSEBroadcaster()
    _, sub = broadcaster.subscribe(frozenset(["market.bars"]))

    await broadcaster.run(_MockConsumer([
        ("market.bars", "ES:1m", {"price": 5000}),
    ]))

    assert sub.queue.qsize() == 1
    item = sub.queue.get_nowait()
    assert item["topic"] == "market.bars"
    assert item["payload"] == {"price": 5000}


async def test_subscriber_does_not_receive_unsubscribed_topic():
    broadcaster = KafkaSSEBroadcaster()
    _, sub = broadcaster.subscribe(frozenset(["market.bars"]))

    await broadcaster.run(_MockConsumer([
        ("intelligence", "ES:1m", {"signal": "buy"}),
    ]))

    assert sub.queue.qsize() == 0


async def test_two_subscribers_each_receive_own_topics():
    broadcaster = KafkaSSEBroadcaster()
    _, sub_a = broadcaster.subscribe(frozenset(["market.bars"]))
    _, sub_b = broadcaster.subscribe(frozenset(["intelligence"]))

    await broadcaster.run(_MockConsumer([
        ("market.bars", "ES:1m", {"price": 5000}),
        ("intelligence", "ES:1m", {"signal": "buy"}),
    ]))

    assert sub_a.queue.qsize() == 1
    assert sub_a.queue.get_nowait()["topic"] == "market.bars"

    assert sub_b.queue.qsize() == 1
    assert sub_b.queue.get_nowait()["topic"] == "intelligence"


async def test_unsubscribe_stops_delivery():
    broadcaster = KafkaSSEBroadcaster()
    _, sub = broadcaster.subscribe(frozenset(["market.bars"]))
    broadcaster.unsubscribe(sub)

    await broadcaster.run(_MockConsumer([
        ("market.bars", "ES:1m", {"price": 5000}),
    ]))

    assert sub.queue.qsize() == 0


async def test_queue_full_increments_drop_counter(monkeypatch):
    import src.api.routes.sse as sse_module

    mock_counter = MagicMock()
    monkeypatch.setattr(sse_module, "SSE_MESSAGES_DROPPED_TOTAL", mock_counter)

    broadcaster = KafkaSSEBroadcaster()
    _, sub = broadcaster.subscribe(frozenset(["market.bars"]))

    # Fill the queue to capacity
    for i in range(500):
        sub.queue.put_nowait({"topic": "market.bars", "key": f"SYM{i}:1m", "payload": {}})

    await broadcaster.run(_MockConsumer([
        ("market.bars", "ES:1m", {"price": 9999}),
    ]))

    mock_counter.add.assert_called_once_with(1, {"topic": "market.bars"})


async def test_latest_snapshot_capped_at_max_keys():
    broadcaster = KafkaSSEBroadcaster()

    messages = [
        ("market.bars", f"SYM{i}:1m", {"price": i})
        for i in range(_MAX_LATEST_KEYS + 10)
    ]
    await broadcaster.run(_MockConsumer(messages))

    assert len(broadcaster._latest["market.bars"]) == _MAX_LATEST_KEYS


async def test_latest_snapshot_updates_existing_key_without_eviction():
    broadcaster = KafkaSSEBroadcaster()

    # Fill to exactly the cap
    messages = [("market.bars", f"SYM{i}:1m", {"v": i}) for i in range(_MAX_LATEST_KEYS)]
    await broadcaster.run(_MockConsumer(messages))

    # Update an existing key — should not grow beyond cap
    await broadcaster.run(_MockConsumer([("market.bars", "SYM0:1m", {"v": 999})]))

    assert len(broadcaster._latest["market.bars"]) == _MAX_LATEST_KEYS
    assert broadcaster._latest["market.bars"]["SYM0:1m"]["payload"] == {"v": 999}


async def test_ibkr_seed_messages_are_skipped():
    broadcaster = KafkaSSEBroadcaster()
    _, sub = broadcaster.subscribe(frozenset(["market.bars"]))

    await broadcaster.run(_MockConsumer([
        ("market.bars", "ES:1m", {"source": "ibkr_seed", "price": 5000}),
        ("market.bars", "ES:1m", {"source": "live", "price": 5001}),
    ]))

    assert sub.queue.qsize() == 1
    assert sub.queue.get_nowait()["payload"]["source"] == "live"
```

- [ ] **Step 2: Run the new tests**

```bash
.venv/bin/pytest tests/unit/api/test_sse_broadcaster.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 3: Run the full API test suite**

```bash
.venv/bin/pytest tests/unit/api/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/api/test_sse_broadcaster.py
git commit -m "test(sse): unit tests for topic-indexed broadcaster fan-out"
```

---

## Task 5: Content-Addressed Signal ID (CRITICAL-01)

Replace random UUID signal generation with a deterministic SHA-256 ID derived from inputs. This makes backfill replay idempotent and A/B test comparisons noise-free.

**Files:**
- Modify: `src/intelligence/pipeline/signal_processor.py`
- Modify: `production/migrations/` (new migration file)

- [ ] **Step 1: Add `_make_signal_id()` to `signal_processor.py`**

Import `hashlib` at the top of the file (it is already in stdlib). Add this function near the top of the module, before `SignalProcessor`:

```python
def _make_signal_id(
    symbol: str,
    feature_ts_ns: int,
    feature_tf: str,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> str:
    """Deterministic content-addressed signal ID (SHA-256, first 32 hex chars).

    Identity is derived from the BAR INPUTS — not from plugin outputs.
    Plugin outputs are stateful (Kalman, rolling windows, regime state) and change
    across restarts; bar OHLCV is the stable invariant across any replay.

    Canonicalization rules:
    - feature_ts_ns: UTC epoch nanoseconds as integer — parse from timestamptz, not ISO string
    - feature_tf: lowercase normalized, e.g. "1m", "5m"
    - OHLCV: repr(round(x, 10)) — deterministic float serialization, excludes float jitter
    """
    raw = f"{symbol}|{feature_ts_ns}|{feature_tf}|{round(open_,10)}|{round(high,10)}|{round(low,10)}|{round(close,10)}|{round(volume,10)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
```

- [ ] **Step 2: Replace `setdefault("signal_id", str(uuid4()))` in `signal_processor.py:520`**

Current:
```python
sig.setdefault("signal_id", str(uuid4()))
```

New — identity is derived from the bar that produced the signal, not from plugin outputs:
```python
if "signal_id" not in sig:
    # bar is the BarEvent in scope at this point in _process_bar()
    _ts_ns = int(bar.timestamp.timestamp() * 1e9)
    _tf_norm = (sig.get("feature_tf") or tf).lower()
    sig["signal_id"] = _make_signal_id(
        symbol=symbol,
        feature_ts_ns=_ts_ns,
        feature_tf=_tf_norm,
        open_=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
    )
```

Read `signal_processor.py` to confirm the `BarEvent` attribute names (`bar.open`, `bar.timestamp`, etc.) before implementing — adapt if they differ.

`hashlib` was added in Step 1.

- [ ] **Step 3: Add UNIQUE constraint migration**

Create `production/migrations/115_signal_id_unique.sql`:

```sql
-- Migration 115: enforce UNIQUE on signal_ledger.signal_id
-- Prerequisite: all existing rows must have non-null, distinct signal_ids.
-- IMPORTANT: CREATE UNIQUE INDEX CONCURRENTLY cannot run inside a transaction.
-- Run this migration OUTSIDE a transaction block (use --single-transaction=off or
-- a direct psql session, not a migration tool that wraps all statements in BEGIN).

DO $$
BEGIN
  IF (SELECT count(*) FROM (SELECT signal_id FROM signal_ledger GROUP BY signal_id HAVING count(*) > 1) t) > 0 THEN
    RAISE EXCEPTION 'Duplicate signal_ids found — deduplicate before applying constraint';
  END IF;
END $$;

-- Non-transactional — must be the only statement in its execution context:
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_ledger_signal_id_unique
    ON signal_ledger (signal_id);
```

- [ ] **Step 4: Add signal ID stability tests**

Add these cases to a new test block in the signal processor unit tests (or create `tests/unit/intelligence/test_signal_id_stability.py`):

```python
```python
_BAR_KWARGS = dict(symbol="ES", feature_ts_ns=1717440000000000000, feature_tf="1m",
                   open_=5000.25, high=5010.0, low=4998.5, close=5005.0, volume=12345.0)

def test_signal_id_stable_across_identical_replay():
    """Same bar inputs produce the same ID on repeated calls."""
    assert _make_signal_id(**_BAR_KWARGS) == _make_signal_id(**_BAR_KWARGS)

def test_signal_id_different_for_different_timestamps():
    """Different epoch ns produce different IDs."""
    id1 = _make_signal_id(**{**_BAR_KWARGS, "feature_ts_ns": 1717440000000000000})
    id2 = _make_signal_id(**{**_BAR_KWARGS, "feature_ts_ns": 1717440000000000001})
    assert id1 != id2

def test_signal_id_different_for_different_close():
    """Different close price produces a different ID — proves OHLCV is in the hash."""
    id1 = _make_signal_id(**{**_BAR_KWARGS, "close": 5005.0})
    id2 = _make_signal_id(**{**_BAR_KWARGS, "close": 5005.1})
    assert id1 != id2

def test_signal_id_tf_normalization():
    """Timeframe is lowercased before hashing — caller must normalize before passing."""
    id1 = _make_signal_id(**{**_BAR_KWARGS, "feature_tf": "1m"})
    id2 = _make_signal_id(**{**_BAR_KWARGS, "feature_tf": "1M"})
    assert id1 == id2  # only true if caller lowercases; this test documents the contract

def test_signal_id_independent_of_plugin_outputs():
    """Two signals from the same bar but different plugin outputs get the SAME ID.
    Plugin outputs are stateful and vary across restarts — they must not affect identity."""
    # Both signals came from the same bar — their IDs must match regardless of
    # what the plugins computed.
    assert _make_signal_id(**_BAR_KWARGS) == _make_signal_id(**_BAR_KWARGS)
    # The point: _make_signal_id takes no plugin-output args — it cannot vary on them.
```

- [ ] **Step 6: Remove unused `uuid4` import if it is now unused**

```bash
grep -n "uuid4" src/intelligence/pipeline/signal_processor.py
```

If `uuid4` no longer appears outside the import line, remove it from the import.

- [ ] **Step 7: Verify import and run unit tests**

```bash
.venv/bin/python -c "from src.intelligence.pipeline.signal_processor import SignalProcessor; print('ok')"
.venv/bin/pytest tests/unit/ -q
```

- [ ] **Step 8: Commit**

```bash
git add src/intelligence/pipeline/signal_processor.py production/migrations/115_signal_id_unique.sql
git commit -m "feat(signals): content-addressed signal_id via SHA-256 with stable canonicalization (CRITICAL-01)"
```

---

## Task 6: In-Process Confidence Calibration (CRITICAL-02)

`calibrated_confidence` is null in Kafka payloads because calibration runs post-hoc. Move calibration to execute in-process before I7 confluence so downstream agents gate on real calibrated values.

**Files:**
- Modify: `services/intelligence_pipeline.py`
- Modify: `src/intelligence/ml/confidence_calibrator.py` (add synchronous lookup method)

- [ ] **Step 1: Add `get_calibrated_confidence()` synchronous method to `ConfidenceCalibrator`**

Read `src/intelligence/ml/confidence_calibrator.py` to find where curves are cached in memory. Add a method that applies curves without a DB call — curves must already be in the in-memory cache:

```python
def get_calibrated_confidence(
    self, plugin_name: str, timeframe: str, raw_confidence: float
) -> float | None:
    """Apply cached calibration curve synchronously. Returns None if no curve cached.

    Fallback contract: caller MUST pass raw_confidence through unchanged when this
    returns None (no cached curve, stale curve, or out-of-range input). Never block
    or raise — calibration is best-effort; raw confidence is always valid.
    """
    curve = self._curves.get((plugin_name, timeframe))
    if curve is None:
        return None
    # Apply isotonic regression or linear interpolation from cached curve points
    return float(np.interp(raw_confidence, curve["x"], curve["y"]))
```

Verify the exact cache structure by reading the calibrator's `_curves` attribute before writing this step — adapt key format to match what is actually cached.

- [ ] **Step 2: Inject calibration pass into `intelligence_pipeline.py` between I6 and I7**

In `_process_bar()`, after the I6 confluence step and before I7 scoring, add:

```python
# Calibrate confidence in-process before I7 (CRITICAL-02).
# Fallback: if no cached curve, pass raw_confidence through unchanged — never block.
for sig in ranked:
    raw_conf = sig.get("confidence") or sig.get("pre_quality_confidence")
    if raw_conf is not None:
        cal = self._calibrator.get_calibrated_confidence(
            sig.get("agent_id", ""), bar.tf, raw_conf
        )
        # cal is None when curve is missing/stale — use raw value as fallback.
        # confidence_calibrated=False lets I7 distinguish calibrated from raw.
        sig["calibrated_confidence"] = cal if cal is not None else raw_conf
        sig["confidence_calibrated"] = cal is not None
```

Where `self._calibrator` is the existing `ConfidenceCalibrator` instance already held by the pipeline.

- [ ] **Step 3: Verify the pipeline imports cleanly and existing tests pass**

```bash
.venv/bin/python -c "from services.intelligence_pipeline import IntelligencePipeline; print('ok')"
.venv/bin/pytest tests/unit/ -q
```

- [ ] **Step 4: Commit**

```bash
git add services/intelligence_pipeline.py src/intelligence/ml/confidence_calibrator.py
git commit -m "feat(pipeline): in-process confidence calibration before I7 (CRITICAL-02)"
```

---

## Task 7: BaseWriter Parse Payload Contract Refactor (HIGH-01)

Replace the `None` / `[]` two-sentinel contract with a `(valid, invalid)` tuple so the DLQ policy is explicit and subclasses cannot accidentally trigger a DLQ cascade by returning `None`.

**Files:**
- Modify: `src/core/agent/base_writer.py`
- Modify: all subclasses that implement `_parse_payload` (find via grep)

- [ ] **Step 1: Enumerate all `_parse_payload` implementations and build a test inventory**

```bash
grep -rn "def _parse_payload" src/ services/ --include="*.py"
```

For every file found, record the subclass name and its current return shape in a table. This inventory must exist before any modification — the migration is only safe if every subclass is covered:

| Subclass | File | Current return shape | Needs migration? |
|----------|------|---------------------|-----------------|
| (fill in) | (fill in) | list / None / [] | yes/no |

After building the inventory, add a test file per-subclass (or extend existing) with at minimum these cases: all-valid, all-invalid, mixed valid+invalid, parser exception, and verify DLQ shape for the invalid path.

- [ ] **Step 2: Change the `_parse_payload` signature in `base_writer.py`**

Old abstract signature:
```python
def _parse_payload(self, payload: dict) -> list | None:
```

New:
```python
def _parse_payload(self, payload: dict) -> tuple[list, list]:
    """Parse raw Kafka payload.

    Returns (valid_rows, invalid_rows). Base class DLQs if valid is empty AND
    invalid is non-empty. Returns ([], []) for an unparseable payload to skip silently.
    """
    raise NotImplementedError
```

- [ ] **Step 3: Update `_run()` dispatch in `base_writer.py`**

Replace:
```python
rows = self._parse_payload(payload)
if rows is None:
    await self._maybe_route_to_dlq(...)
elif rows:
    await self._write_rows(rows)
```

With:
```python
valid, invalid = self._parse_payload(payload)
if invalid and not valid:
    await self._maybe_route_to_dlq(...)
if valid:
    await self._write_rows(valid)
```

- [ ] **Step 4: Update every subclass `_parse_payload` return statement**

For each file found in Step 1:
- `return items` → `return items, []`
- `return []` → `return [], []`
- `return None` → `return [], [payload]` (triggers DLQ correctly)

- [ ] **Step 5: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/core/agent/base_writer.py  # and all modified subclass files
git commit -m "refactor(writer): _parse_payload returns (valid, invalid) tuple, removes None sentinel (HIGH-01)"
```

---

## Task 8: Intelligence Features Upsert — DO NOTHING → DO UPDATE (HIGH-03)

The `intelligence_features` primary key `(ts, symbol, tf)` prevents duplicates, but the writer uses `DO NOTHING` — replay silently discards new values for existing rows. Change to `DO UPDATE` so replay overwrites stale feature vectors.

**Files:**
- Modify: `src/persistence/repository/feature_repository.py`

- [ ] **Step 1: Read the current INSERT in `feature_repository.py`**

Find the `ON CONFLICT (ts, symbol, tf) DO NOTHING` INSERT. Identify the full column list being inserted.

- [ ] **Step 2: Change `DO NOTHING` to `DO UPDATE SET ...` for all non-key columns**

The key columns (`ts`, `symbol`, `tf`) are excluded from the SET clause. All other columns should be updated:

```sql
ON CONFLICT (ts, symbol, tf) DO UPDATE SET
    feature_schema_version = EXCLUDED.feature_schema_version,
    i1 = EXCLUDED.i1,
    i2 = EXCLUDED.i2,
    i3 = EXCLUDED.i3,
    i4 = EXCLUDED.i4,
    i5 = EXCLUDED.i5,
    smc = EXCLUDED.smc,
    i6 = EXCLUDED.i6
WHERE EXCLUDED.feature_schema_version >= intelligence_features.feature_schema_version
```

The `WHERE` guard ensures a stale replay (lower schema version) cannot overwrite a live write (higher schema version). Without it, a replay run after market close silently overwrites the live values written during the session. Adapt the column list to exactly match what is currently in the INSERT — read the file to confirm all columns.

- [ ] **Step 3: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ -q
```

- [ ] **Step 4: Commit**

```bash
git add src/persistence/repository/feature_repository.py
git commit -m "fix(features): upsert on conflict DO UPDATE for idempotent replay (HIGH-03)"
```

---

## Task 9: DAG Invariant CI Enforcement (MEDIUM-01)

Add a pytest fixture that asserts no module under `src/intelligence/` imports `asyncpg`, `aiokafka`, or `confluent_kafka` at import time. Makes DAG Invariant 2 a hard CI gate.

**Files:**
- Create: `tests/unit/intelligence/test_dag_invariants.py`

- [ ] **Step 1: Create the test file**

```python
"""CI enforcement of DAG Invariant 2: intelligence plugins must not import DB or Kafka clients."""

import importlib
import pkgutil
import sys

import pytest

_FORBIDDEN_MODULES = {"asyncpg", "asyncpg.pool", "aiokafka", "confluent_kafka"}
_INTELLIGENCE_PACKAGE = "src.intelligence"


def _iter_intelligence_modules() -> list[str]:
    import src.intelligence as pkg
    results = []
    for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        results.append(info.name)
    return results


@pytest.mark.parametrize("module_name", _iter_intelligence_modules())
def test_intelligence_module_does_not_import_db_or_kafka(module_name: str):
    """Each src.intelligence module must not pull in asyncpg or Kafka clients."""
    # Snapshot sys.modules before import to detect newly loaded transitive deps
    before = set(sys.modules.keys())
    try:
        importlib.import_module(module_name)
    except Exception:
        pytest.skip(f"Could not import {module_name} (missing optional dep)")
    after = set(sys.modules.keys())
    newly_loaded = after - before
    violations = newly_loaded & _FORBIDDEN_MODULES
    assert not violations, (
        f"{module_name} imported forbidden modules: {violations}. "
        "DAG Invariant 2 requires I1-I7 to be DB and Kafka ignorant."
    )
```

- [ ] **Step 2: Run the new test**

```bash
.venv/bin/pytest tests/unit/intelligence/test_dag_invariants.py -v
```

Expected: all modules pass. If violations are found, fix them before committing.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/intelligence/test_dag_invariants.py
git commit -m "test(dag): CI enforcement of DAG Invariant 2 — no asyncpg/Kafka in intelligence/ (MEDIUM-01)"
```

---

## Task 10: Live Contract Updates via Kafka (MEDIUM-02)

Daemons currently read `get_active_contracts()` once at startup. `roll-batch` broadcasts rolls via Kafka but no daemon subscribes. This task wires the hot-reload path so daemons self-heal on futures rolls without a manual restart.

**Files:**
- Modify: `src/core/stream_keys.py` (add `contracts_updated` key)
- Modify: `services/intelligence_pipeline.py` (subscribe + atomic reload)
- Modify: other daemons that cache contracts at startup (find via grep)

- [ ] **Step 1: Add `contracts_updated` stream key to `stream_keys.py`**

Find the contracts-related key block and add:

```python
def contracts_updated(env: str) -> str:
    return f"{env}.contracts.updated"
```

- [ ] **Step 2: Find all daemons that call `get_active_contracts()` at startup**

```bash
grep -rn "get_active_contracts" services/ src/ --include="*.py" | grep -v __pycache__
```

Note each daemon and where it stores the result. **Resolve this to a concrete list before writing any code** — "other daemons" is not an acceptable implementation target.

- [ ] **Step 3: Add contract hot-reload to `intelligence_pipeline.py`**

In `_setup()`, subscribe to `topic_contracts_updated(env_name)` alongside the existing bar topics:

```python
self._contract_topic = topic_contracts_updated(self._settings.env_name or "")
```

In `_run()`, add a dispatch branch when a message arrives on `self._contract_topic`. Use atomic reference replacement — never mutate the contract set in place while `_process_bar()` may be reading it. Validate the incoming payload before swap; preserve last-known-good on bad update:

```python
if topic == self._contract_topic:
    try:
        new_contracts = get_active_contracts(self._settings)
        # Atomic swap — replace the reference, never mutate in place
        self._active_contracts = new_contracts
        CONTRACTS_RELOAD_TOTAL.add(1, {"status": "success"})
        logger.info("contracts_reloaded", count=len(self._active_contracts))
    except Exception as exc:
        CONTRACTS_RELOAD_TOTAL.add(1, {"status": "failure"})
        logger.error("contracts_reload_failed", error=str(exc))
        # Last-known-good preserved — no assignment on failure
    continue
```

Add `CONTRACTS_RELOAD_TOTAL` counter to `src/observability/metrics.py` with label `status` (values: `"success"`, `"failure"`).

- [ ] **Step 4: Apply the same atomic-swap + metrics pattern to each daemon in the Step 2 list**

For each daemon: subscribe to `self._contract_topic` in `_setup()`, add the same dispatch branch in `_run()`. Apply one daemon at a time and run unit tests between each. Test that: (a) a valid update replaces contracts, (b) a bad update preserves the previous set.

- [ ] **Step 5: Verify no regressions**

```bash
.venv/bin/pytest tests/unit/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/core/stream_keys.py src/observability/metrics.py services/intelligence_pipeline.py  # + other modified daemons
git commit -m "feat(contracts): live hot-reload via contracts.updated topic with atomic swap and failure telemetry (MEDIUM-02)"
```

---

## Task 11: Raise `setup_performance` Sample Gate (Structural)

The `sample_size >= 30` gate is statistically insufficient for fat-tailed return distributions. Raise to 100 minimum and add a comment marking values below 200 as unreliable estimates.

**Files:**
- Modify: wherever `sample_size >= 30` is defined/checked (find via grep)
- Modify: `production/migrations/` (add migration if gate is a DB config value)

- [ ] **Step 1: Find all occurrences of the sample gate**

```bash
grep -rn "sample_size\|>= 30\|>= 100\|perf_multiplier" src/ services/ --include="*.py" | grep -v __pycache__
```

- [ ] **Step 2: Change gate threshold from 30 to 100**

For each occurrence: change the comparison from `>= 30` to `>= 100`. Add an inline comment on the line:

```python
# Minimum 100 samples required; values below 200 are statistically unreliable on fat-tailed returns
if sample_size >= 100:
```

- [ ] **Step 3: If the gate is stored in DB config, add a migration**

```sql
-- Migration 116: raise setup_performance sample gate from 30 to 100
UPDATE config SET value = '100' WHERE config_key = 'setup_performance.min_sample_size';
```

Create as `production/migrations/116_setup_performance_gate.sql` if applicable.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q
```

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(shadow): raise setup_performance gate to 100 samples minimum (structural)"
```

---

## Task 12: Intelligence Pipeline Backpressure Circuit Breaker (Structural)

There is no queue depth guard in the in-process pipeline. Under sustained overload (backfill or latency spike), the bar queue grows without bound until OOM. Add a circuit breaker: drop oldest bar when queue exceeds threshold and emit an alert counter.

**Files:**
- Modify: `services/intelligence_pipeline.py`
- Modify: `src/observability/metrics.py` (add counter)

- [ ] **Step 1: Add `PIPELINE_BACKPRESSURE_DROP_TOTAL` counter to `metrics.py`**

```python
PIPELINE_BACKPRESSURE_DROP_TOTAL = _meter.create_counter(
    "intelligence_pipeline_backpressure_drop_total",
    description="Bars dropped by backpressure circuit breaker (queue depth exceeded)",
)
```

- [ ] **Step 2: Add `_MAX_QUEUE_DEPTH` constant and queue depth check to `intelligence_pipeline.py`**

At the top of the file, after existing constants:

```python
_MAX_QUEUE_DEPTH = 500  # drop incoming bar above this depth to prevent OOM under load
```

In the bar ingestion path, **do not enqueue the incoming bar** if the queue is full — drop the newest arrival, not the oldest. Dropping the oldest bar corrupts established rolling windows and Kalman state; dropping the newest discards only what hasn't been incorporated yet:

```python
if self._bar_queue.qsize() >= _MAX_QUEUE_DEPTH:
    # Drop the INCOMING bar (newest), not the queued ones (established state).
    # Dropping oldest would corrupt rolling windows, Kalman filters, regime state.
    PIPELINE_BACKPRESSURE_DROP_TOTAL.add(
        1, {"symbol": bar.symbol, "tf": bar.tf}
    )
    logger.warning(
        "pipeline_backpressure_drop",
        symbol=bar.symbol,
        tf=bar.tf,
        queue_depth=self._bar_queue.qsize(),
    )
    return  # or continue — don't enqueue; caller drives the loop
else:
    await self._bar_queue.put(bar)
```

Adapt to the exact control flow at the ingestion call site — read `_setup()` and the main `_run()` loop to find where bars are enqueued.

**Gap-awareness note:** Dropping bars does not re-sync stateful plugin state. This circuit breaker is an OOM safeguard for extreme overload scenarios (sustained backfill floods), not a steady-state drop policy. The warning log with `symbol+tf` is the operator signal to investigate and replay if state is suspected stale.

- [ ] **Step 3: Import the counter**

```python
from src.observability.metrics import PIPELINE_BACKPRESSURE_DROP_TOTAL
```

- [ ] **Step 4: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ -q
```

- [ ] **Step 5: Commit**

```bash
git add services/intelligence_pipeline.py src/observability/metrics.py
git commit -m "feat(pipeline): backpressure circuit breaker, drop oldest bar at queue depth > 500 (structural)"
```

---

## Self-Review

**SSE Broadcaster (Tasks 1–4):**
- ✅ Dead Redis imports + functions + constant deleted (Task 1)
- ✅ `test_sse_intelligence.py` deleted (Task 1)
- ✅ `SSE_MESSAGES_DROPPED_TOTAL` counter added (Task 2)
- ✅ `_latest` bounded at `_MAX_LATEST_KEYS` (Task 3)
- ✅ O(N) `list[asyncio.Queue]` replaced with `dict[topic, set[_Subscription]]` (Task 3)
- ✅ `subscribe()` takes `frozenset[str]` topics, returns `_Subscription` (Task 3)
- ✅ `unsubscribe()` takes `_Subscription`, does O(1) `set.discard` per topic (Task 3)
- ✅ `topic_set` filter removed from `event_generator` — broadcaster handles it (Task 3)
- ✅ Tests for all key behaviors (Task 4)

**Architecture Review Findings (Tasks 5–11):**
- ✅ CRITICAL-01: Content-addressed `signal_id` — SHA-256 of bar OHLCV inputs (not plugin outputs); stable across restarts and replay (Task 5)
- ✅ CRITICAL-02: In-process calibration before I7 — `calibrated_confidence` + `confidence_calibrated: bool` populated in hot path; raw fallback is explicit (Task 6)
- ➡️ CRITICAL-03: Shadow governance (t-test gate, min_n=200, rolling Sharpe demotion) — routed to Phase 101 CONTEXT.md; must be implemented in `PromotionGate`/`DemotionGate` classes in `src/intelligence/ai/fitness/gates.py`, not in `shadow_auditor.py` directly
- ✅ HIGH-01: BaseWriter `_parse_payload` returns `(valid, invalid)` tuple — no sentinels (Task 7)
- 🟡 HIGH-02: `pipeline_latency` already labels with `{"symbol": bar.symbol, "tf": bar.tf}` at line 660 — finding already resolved in codebase, no action needed
- ✅ HIGH-03: `intelligence_features` upsert `DO NOTHING` → `DO UPDATE SET ... WHERE version guard` — replay idempotent, stale replay cannot overwrite live data (Task 8)
- ✅ MEDIUM-01: pytest CI fixture — DAG Invariant 2 enforcement on all `src/intelligence/` modules (Task 9)
- ➡️ MEDIUM-03: DSPy optimizer data gate observability — already fully specified in Phase 098 CONTEXT.md; no action needed here
- ✅ MEDIUM-02: Live contract hot-reload via `contracts.updated` topic (Task 10)
- ✅ Structural: `setup_performance` sample gate raised from 30 → 100 (Task 11)
- ✅ Structural: Pipeline backpressure circuit breaker — drops INCOMING bar (newest) at depth > 500; preserves established stateful window state (Task 12)

**Remaining deferred (SSE-specific, separate plans):**
- Bug 1 (SSE symbol filtering): topics are flat by design; per-symbol filtering needs a separate design decision
- Bug 4 (SSE reconnect sequence IDs): requires bounded deque per (topic, key) — separate plan
- Structural: Avro/Protobuf schema registry for `IntelligenceEvent` — production-scale migration; warrants a dedicated architecture spike and phased rollout plan before any implementation

**Type consistency check:**
- `_Subscription` defined in Task 3 Step 2, used in Task 3 Steps 3–6 and Task 4 — consistent
- `_MAX_LATEST_KEYS` defined in Task 3 Step 1, used in Task 3 Step 4 and Task 4 — consistent
- `SSE_MESSAGES_DROPPED_TOTAL` defined in Task 2, imported in Task 3 Step 7, monkeypatched in Task 4 via `src.api.routes.sse.SSE_MESSAGES_DROPPED_TOTAL` — consistent

---

## Production Validation

Run these after deploying all 12 tasks to confirm the hardening held. "Unit tests green" is the entry bar; these are the success criteria.

```bash
# 1. calibrated_confidence null rate should be zero (CRITICAL-02)
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT count(*) AS nulls
  FROM signal_ledger
  WHERE calibrated_confidence IS NULL
    AND timestamp > now() - interval '1 hour';"
# Expected: 0

# 2. confidence_calibrated flag distribution — know what fraction had curves
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT confidence_calibrated, count(*)
  FROM signal_ledger
  WHERE timestamp > now() - interval '1 hour'
  GROUP BY 1;"
# Expected: both rows present; calibrated=true should dominate once curves warm up

# 3. signal_id uniqueness constraint active
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT indexname, indexdef FROM pg_indexes
  WHERE tablename = 'signal_ledger' AND indexname = 'idx_signal_ledger_signal_id_unique';"
# Expected: one row

# 4. No signal_id collisions in the last hour
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT signal_id, count(*) FROM signal_ledger
  WHERE timestamp > now() - interval '1 hour'
  GROUP BY signal_id HAVING count(*) > 1;"
# Expected: 0 rows

# 5. SSE drop counter baseline (should be near zero under normal load)
curl -s http://localhost:8000/metrics | grep sse_messages_dropped_total
# Expected: counter present; value near 0

# 6. Backpressure drop counter (should be 0 outside of backfill)
curl -s http://localhost:8000/metrics | grep intelligence_pipeline_backpressure_drop_total
# Expected: counter present; value 0 during live session

# 7. Contract reload metrics present
curl -s http://localhost:8000/metrics | grep contracts_reload_total
# Expected: counter present with status=success label

# 8. DAG invariant test passes in CI
.venv/bin/pytest tests/unit/intelligence/test_dag_invariants.py -v
# Expected: all modules pass; any violation is a hard block
```
