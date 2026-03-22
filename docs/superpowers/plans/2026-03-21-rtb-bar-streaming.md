# reqRealTimeBars Bar Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-minute `reqHistoricalDataAsync` polling and tick streaming with IBKR's `reqRealTimeBars` push subscription — 5-second bars from IBKR aggregate to 1m, fixing the after-hours freeze and keeping IBKR as bar source of truth.

**Architecture:** `IBKRProvider.stream_real_time_bars()` mirrors the existing `stream_ticks()` thread-safe bridge (sync ib_insync `updateEvent` callback → `call_soon_threadsafe` → asyncio Queue → async iterator). `TwsDaemon._rtb_loop()` consumes `(symbol, RealTimeBar)` tuples, accumulates per-symbol OHLCV state, and emits a complete 1m bar on each minute boundary. Both `_tick_loop` and `poll_1m_bars` are removed; `_rtb_loop` is the sole data stream from the daemon. Each 5s bar's close is also published to `market.ticks` for dashboard price display (~5s updates replace per-tick updates).

**Tech Stack:** ib_insync ≥ 0.9.86, `RealTimeBar` (ib_insync), asyncio Queue, confluent-kafka (Redpanda), pytest-asyncio

---

## File Map

| File | Change |
|------|--------|
| `src/providers/base.py` | Add `stream_real_time_bars()` to `DataProvider` protocol; keep `stream_ticks()` (other providers may use it) |
| `src/providers/ibkr.py` | Add `stream_real_time_bars()` with thread-safe bridge; add `_rtb_queue` state |
| `services/tws_daemon.py` | Add `_rtb_loop()` + `_emit_bar()`; remove `_tick_loop`, `poll_1m_bars`, `_fetch_bars_for_symbol`, polling trigger, `last_bar_poll_minute`; replace `_tick_task` with `_rtb_task` |
| `tests/unit/daemons/test_tws_daemon.py` | Fix existing tick test; add RTB aggregation tests |

---

## Key Implementation Notes

- `RealTimeBar.volume` is a **`float`** (not int) per ib_insync `objects.py`. Accumulated volume is serialized as `str(float(...))` — this is consistent with how IBKR returns it. Downstream consumers already use `float(bar_data["volume"])`.
- `RealTimeBar.time` is the **close** time of the 5s bar (IBKR convention). Floor to minute with `rtb.time.replace(second=0, microsecond=0)`.
- `stream_ticks()` is **kept** in both `ibkr.py` and `base.py` — not removed, just unused by the daemon. Other providers or future use cases may need it.
- `ticks_processed` metric now counts 5s bar publishes (not order-book ticks) — semantics change is acceptable since the metric is informational only.
- `bar_close_ts` is set to `bar_minute.isoformat()` — this matches IBKR's 1m historical bar convention (timestamp = bar start/open time).
- `timedelta` import in `tws_daemon.py` is **still needed** by `RollMonitor` — do not remove it.

---

## Task 1: Add `stream_real_time_bars()` to `DataProvider` protocol

**Files:**
- Modify: `src/providers/base.py:80-87`

- [ ] **Step 1: Add method stub to protocol**

In `src/providers/base.py`, after `stream_ticks()` (after line 87) and before `fetch_historical_bars()`, add:

```python
async def stream_real_time_bars(
    self, symbols: list[str]
) -> AsyncIterator[tuple[str, object]]:
    """Async iterator yielding (symbol, RealTimeBar) tuples as 5-second bars arrive.

    RealTimeBar fields: time (UTC close time), open_, high, low, close, volume (float).
    Usage:
        async for symbol, bar in provider.stream_real_time_bars(["ES", "NQ"]):
            accumulate(symbol, bar)
    """
    ...
```

- [ ] **Step 2: Run existing tests to confirm no regression**

```bash
cd /home/bg/dev/indicagent && .venv/bin/pytest tests/unit/daemons/ -v
```
Expected: all existing tests pass (protocol change is additive)

- [ ] **Step 3: Commit**

```bash
git add src/providers/base.py
git commit -m "feat(tws): add stream_real_time_bars to DataProvider protocol"
```

---

## Task 2: Implement `stream_real_time_bars()` in `IBKRProvider`

**Files:**
- Modify: `src/providers/ibkr.py` (add after `stream_ticks()` ending ~line 579)
- Modify: `tests/unit/daemons/test_tws_daemon.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/daemons/test_tws_daemon.py`:

```python
@pytest.mark.asyncio
async def test_ibkr_stream_real_time_bars_yields_symbol_bar_tuple():
    """stream_real_time_bars must yield (symbol, bar) tuples via async iterator."""
    import asyncio
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    class FakeRTB:
        time = datetime(2026, 3, 21, 14, 0, 5, tzinfo=timezone.utc)
        open_ = 5500.0
        high = 5505.0
        low = 5498.0
        close = 5503.0
        volume = 50.0
        wap = 5501.5
        count = 12

    # FakeEvent correctly captures the callback registered via +=
    class FakeEvent:
        def __init__(self):
            self._cb = None
        def __iadd__(self, cb):
            self._cb = cb
            return self
        def __isub__(self, cb):
            return self

    fake_event = FakeEvent()
    fake_bars = MagicMock()
    fake_bars.updateEvent = fake_event

    ib_mock = MagicMock()
    ib_mock.reqRealTimeBars.return_value = fake_bars

    from src.providers.ibkr import IBKRProvider
    provider = IBKRProvider.__new__(IBKRProvider)
    provider._ib = ib_mock
    provider._qualified_contracts = {"ES": MagicMock(secType="FUT")}
    provider._rtb_queue = None
    provider._loop = None

    results = []

    async def consume():
        async for sym, bar in provider.stream_real_time_bars(["ES"]):
            results.append((sym, bar))
            break  # consume one then stop

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let iterator start and register callback

    # Simulate IBKR pushing a 5s bar via the registered callback
    assert fake_event._cb is not None, "updateEvent callback not registered"
    fake_event._cb([FakeRTB()], True)  # (bars_list, hasNewBar)

    await asyncio.wait_for(task, timeout=1.0)
    assert len(results) == 1
    sym, bar = results[0]
    assert sym == "ES"
    assert bar.close == 5503.0
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/daemons/test_tws_daemon.py::test_ibkr_stream_real_time_bars_yields_symbol_bar_tuple -v
```
Expected: FAIL — `AttributeError: IBKRProvider has no stream_real_time_bars`

- [ ] **Step 3: Implement `stream_real_time_bars()` in ibkr.py**

Add after `stream_ticks()` (around line 580):

```python
async def stream_real_time_bars(
    self, symbols: list[str]
) -> AsyncIterator[tuple[str, object]]:
    """Async iterator yielding (symbol, RealTimeBar) tuples as 5-second bars arrive.

    Bridges ib_insync's sync updateEvent callbacks to asyncio via a bounded Queue.
    whatToShow per asset class: CASH -> MIDPOINT, all others -> TRADES.
    useRTH=False: include all sessions (pre/post market, 24h crypto/FX).

    Note: AGGTRADES is only valid for reqHistoricalData, not reqRealTimeBars.
    Crypto (PAXOS) uses TRADES here; verify BTCUSD/ETHUSD on paper account.
    """
    self._loop = asyncio.get_event_loop()
    self._rtb_queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)

    subscribed: list = []
    for symbol in symbols:
        contract = self._qualified_contracts.get(symbol)
        if not contract or not self._ib:
            continue
        sec_type = getattr(contract, "secType", "")
        what = "MIDPOINT" if sec_type == "CASH" else "TRADES"
        bars = self._ib.reqRealTimeBars(contract, barSize=5, whatToShow=what, useRTH=False)

        def _on_bar(bars_list, has_new_bar, *, _symbol=symbol):
            """ib_insync callback — runs on ib_insync thread; bridge to asyncio queue."""
            if not has_new_bar or not bars_list:
                return
            bar = bars_list[-1]
            try:
                self._loop.call_soon_threadsafe(
                    self._rtb_queue.put_nowait, (_symbol, bar)
                )
            except Exception:
                pass  # drop on full queue — backpressure

        bars.updateEvent += _on_bar
        subscribed.append((bars, _on_bar))

    try:
        while True:
            item = await self._rtb_queue.get()
            yield item
    finally:
        for bars, cb in subscribed:
            bars.updateEvent -= cb
            try:
                self._ib.cancelRealTimeBars(bars)
            except Exception:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/unit/daemons/test_tws_daemon.py::test_ibkr_stream_real_time_bars_yields_symbol_bar_tuple -v
```
Expected: PASS

- [ ] **Step 5: Run full daemon unit suite**

```bash
.venv/bin/pytest tests/unit/daemons/ -v
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/providers/ibkr.py tests/unit/daemons/test_tws_daemon.py
git commit -m "feat(tws): implement stream_real_time_bars in IBKRProvider"
```

---

## Task 3: Add `_rtb_loop()` and `_emit_bar()` to `TwsDaemon`

**Files:**
- Modify: `services/tws_daemon.py`
- Modify: `tests/unit/daemons/test_tws_daemon.py`

- [ ] **Step 1: Write the failing aggregation test**

Add to `tests/unit/daemons/test_tws_daemon.py`:

```python
@pytest.mark.asyncio
async def test_rtb_loop_aggregates_5s_bars_to_1m():
    """_rtb_loop must emit a 1m bar to Kafka when a new minute starts.

    IBKR RealTimeBar.time is the bar CLOSE time. First bar of a minute closes
    at :05, last at :60 (= start of next minute, triggers emit of prior minute).
    """
    from collections import defaultdict
    from services.tws_daemon import TwsDaemon
    from unittest.mock import AsyncMock, MagicMock
    from datetime import datetime, timezone

    daemon = TwsDaemon.__new__(TwsDaemon)
    daemon.env_name = "dev"
    daemon.running = True
    daemon.bars_processed = 0
    daemon.ticks_processed = 0
    daemon.m_bars = MagicMock()
    daemon.m_ticks = MagicMock()
    daemon.seen_bar_timestamps = defaultdict(set)
    daemon.seen_bar_timestamps_order = defaultdict(list)
    daemon._roll_monitor = MagicMock(is_enabled=False)

    kafka_producer = AsyncMock()
    kafka_producer.publish = AsyncMock()
    daemon._kafka_producer = kafka_producer

    # 12 bars closing at :05, :10, ..., :60 (IBKR close-time convention)
    # :60 floors to 14:01:00 — different minute → triggers emit of 14:00 bar
    class FakeRTB:
        def __init__(self, second, o, h, l, c, vol):
            self.time = datetime(2026, 3, 21, 14, 0, second % 60,
                                 tzinfo=timezone.utc).replace(
                minute=0 + (second // 60))
            self.open_ = o; self.high = h; self.low = l
            self.close = c; self.volume = float(vol)

    # Build properly: seconds 5,10,...,55 in minute :00, then second :05 in minute :01
    bars_min0 = [FakeRTB(s, 5500.0, 5510.0, 5498.0, 5505.0, 100.0)
                 for s in range(5, 60, 5)]  # 11 bars at :05..:55
    # 12th bar closes exactly at :60 = 14:01:00 → triggers emit
    class Bar60:
        time = datetime(2026, 3, 21, 14, 1, 0, tzinfo=timezone.utc)
        open_ = 5505.0; high = 5510.0; low = 5498.0; close = 5506.0; volume = 100.0
    class Bar65:
        time = datetime(2026, 3, 21, 14, 1, 5, tzinfo=timezone.utc)
        open_ = 5506.0; high = 5508.0; low = 5504.0; close = 5507.0; volume = 50.0

    all_bars = bars_min0 + [Bar60(), Bar65()]

    async def fake_stream(symbols):
        for bar in all_bars:
            yield "ES", bar

    provider_mock = MagicMock()
    provider_mock.stream_real_time_bars = fake_stream
    daemon.provider = provider_mock
    daemon.contracts = [{"symbol": "ES"}]

    await daemon._rtb_loop()

    # Exactly 1 bar published (completed minute :00)
    bar_publishes = [c for c in kafka_producer.publish.call_args_list
                     if "bars" in str(c.args[0])]
    assert len(bar_publishes) == 1

    bar_data = bar_publishes[0].args[1]
    assert bar_data["symbol"] == "ES"
    assert bar_data["timeframe"] == "1m"
    assert float(bar_data["open"]) == 5500.0    # first bar open
    assert float(bar_data["high"]) == 5510.0    # max high
    assert float(bar_data["low"]) == 5498.0     # min low
    assert float(bar_data["close"]) == 5506.0   # last bar close (Bar60)
    assert float(bar_data["volume"]) == 1200.0  # 11×100 + 100 = 1200
    assert bar_data["source"] == "authoritative"
    assert bar_data["timeframe"] == "1m"
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/daemons/test_tws_daemon.py::test_rtb_loop_aggregates_5s_bars_to_1m -v
```
Expected: FAIL — `AttributeError: TwsDaemon has no _rtb_loop`

- [ ] **Step 3: Implement `_rtb_loop()` and `_emit_bar()` in tws_daemon.py**

Add after `_tick_loop()` (around line 492):

```python
async def _rtb_loop(self) -> None:
    """Consume 5-second RealTimeBars from IBKRProvider and aggregate to 1m bars.

    Maintains per-symbol OHLCV state. Emits a complete 1m bar to development.market.bars
    when the minute boundary changes (RealTimeBar.time is bar close time).
    Also publishes each 5s close to development.market.ticks for dashboard display.

    Note: ticks_processed counter now counts 5s bar publishes, not order-book ticks.
    """
    if not self.provider:
        return
    symbols = [c["symbol"] for c in self.contracts]

    def _init_state() -> dict:
        return {
            "bar_minute": None,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "volume": 0.0,
        }

    state: dict[str, dict] = {}

    try:
        async for symbol, rtb in self.provider.stream_real_time_bars(symbols):
            if not self.running:
                break
            try:
                bar_minute = rtb.time.replace(second=0, microsecond=0)
                s = state.setdefault(symbol, _init_state())

                # Minute boundary crossed → emit completed 1m bar, reset state
                if s["bar_minute"] is not None and bar_minute != s["bar_minute"]:
                    await self._emit_bar(symbol, s)
                    s.update(_init_state())

                # Accumulate 5s bar into current minute
                if s["open"] is None:
                    s["open"] = rtb.open_
                    s["bar_minute"] = bar_minute
                s["high"] = max(s["high"] or rtb.high, rtb.high)
                s["low"] = min(s["low"] or rtb.low, rtb.low)
                s["close"] = rtb.close
                s["volume"] += rtb.volume

                # Publish 5s close as price update for dashboard
                await self._kafka_producer.publish(
                    topic_market_ticks(self.env_name),
                    {
                        "symbol": symbol,
                        "price": str(rtb.close),
                        "timestamp": rtb.time.isoformat(),
                        "source": "ibkr",
                    },
                    key=symbol,
                )
                self.ticks_processed += 1
                self.m_ticks.inc()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("RTB loop error", symbol=symbol, error=str(e))

    except asyncio.CancelledError:
        logger.info("RTB loop cancelled (disconnect or shutdown)")

async def _emit_bar(self, symbol: str, state: dict) -> None:
    """Publish completed 1m bar to development.market.bars."""
    bar_minute = state["bar_minute"]
    bar_timestamp = bar_minute.isoformat()

    # Dedup guard (protects against double-emit on reconnect)
    if bar_timestamp in self.seen_bar_timestamps[symbol]:
        return
    self.seen_bar_timestamps[symbol].add(bar_timestamp)
    order = self.seen_bar_timestamps_order[symbol]
    order.append(bar_timestamp)
    if len(order) > 30:
        evicted = order.pop(0)
        self.seen_bar_timestamps[symbol].discard(evicted)

    bar_data = {
        "timestamp": bar_timestamp,
        "symbol": symbol,
        "timeframe": "1m",
        "open": str(state["open"]),
        "high": str(state["high"]),
        "low": str(state["low"]),
        "close": str(state["close"]),
        "volume": str(state["volume"]),   # float, e.g. "1200.0" — consistent with RealTimeBar
        "source": "authoritative",
        "bar_close_ts": bar_timestamp,    # minute-start timestamp (IBKR 1m convention)
    }
    await self._kafka_producer.publish(
        topic_market_bars(self.env_name),
        bar_data,
        key=message_key(symbol, "1m"),
    )
    self.bars_processed += 1
    self.m_bars.inc()
    logger.info("1m bar emitted", symbol=symbol, close=state["close"], volume=state["volume"])

    # Roll monitor (futures only, when enabled)
    if self._roll_monitor.is_enabled:
        bar_utc = (bar_minute if bar_minute.tzinfo is not None
                   else bar_minute.replace(tzinfo=UTC))
        self._roll_monitor.update_volume(symbol, float(state["volume"]), float(state["volume"]))
        if self._roll_monitor.check_roll(symbol, bar_utc):
            await self._roll_monitor._on_roll_confirmed(
                base_symbol=symbol, old_symbol=symbol, new_symbol=symbol,
                roll_gap=0.0, roll_direction="unknown",
                kafka_producer=self._kafka_producer, env_name=self.env_name,
            )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/unit/daemons/test_tws_daemon.py::test_rtb_loop_aggregates_5s_bars_to_1m -v
```
Expected: PASS

- [ ] **Step 5: Run full daemon unit suite**

```bash
.venv/bin/pytest tests/unit/daemons/ -v
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add services/tws_daemon.py tests/unit/daemons/test_tws_daemon.py
git commit -m "feat(tws): add _rtb_loop and _emit_bar for 5s->1m bar aggregation"
```

---

## Task 4: Wire `_rtb_loop`, remove old polling infrastructure

**Files:**
- Modify: `services/tws_daemon.py`
- Modify: `tests/unit/daemons/test_tws_daemon.py`

Steps must be applied in order — `_rtb_task` is added to `__init__` (Step 1) before `_on_disconnected` and `run()` are updated to reference it (Steps 2-4).

- [ ] **Step 1: Update `__init__` — swap `last_bar_poll_minute` for `_rtb_task`**

In `TwsDaemon.__init__` (around lines 370-408):

Remove:
```python
# Minute-boundary bar polling
self.last_bar_poll_minute: int = -1
```

Change the existing `_tick_task` line (408):
```python
self._tick_task: asyncio.Future | None = None
```
to:
```python
self._rtb_task: asyncio.Future | None = None
```

- [ ] **Step 2: Update `run()` — start RTB task instead of tick task**

Replace (line 541):
```python
self._tick_task = asyncio.run_coroutine_threadsafe(self._tick_loop(), self.loop)
```
with:
```python
self._rtb_task = asyncio.run_coroutine_threadsafe(self._rtb_loop(), self.loop)
```

- [ ] **Step 3: Update reconnect block — restart RTB task on reconnect**

Replace (lines 558-561):
```python
self._tick_task = asyncio.run_coroutine_threadsafe(
    self._tick_loop(), self.loop
)
```
with:
```python
self._rtb_task = asyncio.run_coroutine_threadsafe(
    self._rtb_loop(), self.loop
)
```

- [ ] **Step 4: Update `_on_disconnected` — cancel RTB task**

Replace (lines 598-600):
```python
if self._tick_task is not None and not self._tick_task.done():
    self._tick_task.cancel()
    logger.info("Tick loop task cancelled for reconnect")
```
with:
```python
if self._rtb_task is not None and not self._rtb_task.done():
    self._rtb_task.cancel()
    logger.info("RTB loop task cancelled for reconnect")
```

- [ ] **Step 5: Remove polling trigger from main loop**

In the `while self.running:` loop, remove (lines 577-580):
```python
now = datetime.now()
if now.second >= 5 and self.last_bar_poll_minute != now.minute:
    self.last_bar_poll_minute = now.minute
    self.poll_1m_bars()
```

- [ ] **Step 6: Delete `_tick_loop`, `poll_1m_bars`, `_fetch_bars_for_symbol`**

Delete the three methods entirely:
- `_tick_loop()` (lines 463-491)
- `poll_1m_bars()` (lines 602-621)
- `_fetch_bars_for_symbol()` (lines 623-703)

- [ ] **Step 7: Update test for 5s tick publish (replaces old tick test)**

In `tests/unit/daemons/test_tws_daemon.py`, replace `test_tws_daemon_publishes_tick_to_kafka` (which tested `_tick_loop`) with:

```python
@pytest.mark.asyncio
async def test_rtb_loop_publishes_5s_price_tick_for_display():
    """_rtb_loop must publish each 5s bar close to market.ticks for dashboard display."""
    from collections import defaultdict
    from services.tws_daemon import TwsDaemon
    from unittest.mock import AsyncMock, MagicMock
    from datetime import datetime, timezone

    daemon = TwsDaemon.__new__(TwsDaemon)
    daemon.env_name = "dev"
    daemon.running = True
    daemon.bars_processed = 0
    daemon.ticks_processed = 0
    daemon.m_bars = MagicMock()
    daemon.m_ticks = MagicMock()
    daemon.seen_bar_timestamps = defaultdict(set)
    daemon.seen_bar_timestamps_order = defaultdict(list)
    daemon._roll_monitor = MagicMock(is_enabled=False)

    kafka_producer = AsyncMock()
    kafka_producer.publish = AsyncMock()
    daemon._kafka_producer = kafka_producer

    class FakeRTB:
        time = datetime(2026, 3, 21, 14, 0, 5, tzinfo=timezone.utc)
        open_ = 5500.0; high = 5505.0; low = 5498.0; close = 5503.0; volume = 50.0

    async def fake_stream(symbols):
        yield "ES", FakeRTB()

    provider_mock = MagicMock()
    provider_mock.stream_real_time_bars = fake_stream
    daemon.provider = provider_mock
    daemon.contracts = [{"symbol": "ES"}]

    await daemon._rtb_loop()

    tick_calls = [c for c in kafka_producer.publish.call_args_list
                  if "ticks" in str(c.args[0])]
    assert len(tick_calls) == 1
    tick_data = tick_calls[0].args[1]
    assert tick_data["symbol"] == "ES"
    assert tick_data["price"] == "5503.0"
```

- [ ] **Step 8: Run full daemon unit suite**

```bash
.venv/bin/pytest tests/unit/daemons/ -v
```
Expected: all pass

- [ ] **Step 9: Run full project unit tests**

```bash
.venv/bin/pytest tests/unit/ -v
```
Expected: all pass

- [ ] **Step 10: Commit**

```bash
git add services/tws_daemon.py tests/unit/daemons/test_tws_daemon.py
git commit -m "feat(tws): wire _rtb_loop, remove poll_1m_bars and _tick_loop"
```

---

## Verification

1. **All unit tests pass:**
   ```bash
   .venv/bin/pytest tests/unit/ -v
   ```

2. **Restart daemon and verify live bars flowing:**
   ```bash
   sudo systemctl restart indicagent-tws
   sleep 15
   docker exec redpanda rpk topic consume development.market.bars --offset end -n 5
   # Timestamps must be today's date
   ```

3. **Crypto check** (BTCUSD/ETHUSD trade 24/7 — bars should appear immediately):
   ```bash
   docker exec redpanda rpk topic consume development.market.bars --offset end -n 5 | grep BTC
   ```

4. **After-hours check** — `bars_processed` must keep incrementing after 16:00 ET:
   ```bash
   journalctl -u indicagent-tws -f | grep bars_processed
   ```

5. **Dashboard price display** — prices should update ~every 5 seconds.

6. **If crypto fails with IBKR error** (AGGTRADES not valid for reqRealTimeBars): fall back to tick aggregation for CRYPTO secType only — patch `stream_real_time_bars` to skip CRYPTO symbols and add a separate tick-based path for them.
