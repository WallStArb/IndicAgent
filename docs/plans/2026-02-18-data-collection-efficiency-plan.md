> **HISTORICAL DOCUMENT** — `intelligence_processor_service.py` was deleted in Phase 1 (2026-02-23). References to it in this doc are for historical context only. The canonical service is now `market_analysis_service.py`.

# Data Collection Efficiency Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce 1-minute bar latency from 0–60s (avg 30s) to 1–10s by adding minute-aligned polling and tick-derived provisional bars, while removing ~65 lines of dead synchronous code.

**Architecture:** The daemon emits two events per minute per symbol: a provisional `tick_derived` bar at `:00` (from tick accumulator) and an authoritative bar at `:05` (from `reqHistoricalData`). Downstream services filter on the `source` field: `tick_derived` runs the pipeline; `authoritative` silently corrects bar history in-place (timestamp dedup).

**Tech Stack:** Python, ib_insync, Redis Streams, asyncio, pytest, pytest-asyncio

---

## Before You Start

Set up an isolated worktree:

```bash
# From repo root
git worktree add .worktrees/data-efficiency -b feature/data-collection-efficiency
cd .worktrees/data-efficiency
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest tests/ -x -q 2>/dev/null | tail -5
```

Expected: 255+ tests passing, 0 failures. If not, stop and investigate.

**Key files:**
- `production/daemons/high_frequency_tws_daemon.py` — the daemon to modify
- `services/intelligence_processor_service.py` — downstream source filter
- `tests/unit/daemons/` — new directory for daemon tests
- `tests/unit/service_tests/` — existing directory for processor tests

---

## Task 1: Remove Dead Code from Daemon

Dead code: `tick_buffer`, `process_tick_buffer()`, and the legacy synchronous tick path in `on_pending_tickers`. These are unreachable when `HF_ASYNC_PUBLISH=True` (the default). Removing them reduces confusion and sets a clean baseline.

**Files:**
- Modify: `production/daemons/high_frequency_tws_daemon.py`
- Create: `tests/unit/daemons/__init__.py`
- Create: `tests/unit/daemons/test_daemon_dead_code_removed.py`

**Step 1: Write the failing tests**

Create `tests/unit/daemons/__init__.py` (empty file).

Create `tests/unit/daemons/test_daemon_dead_code_removed.py`:

```python
"""Verify dead synchronous tick path has been removed from the daemon."""
from unittest.mock import MagicMock, patch


def _make_daemon():
    """Instantiate daemon with all external dependencies mocked."""
    with (
        patch("production.daemons.high_frequency_tws_daemon.prom_counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.prom_gauge", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.prometheus_client", create=True),
        patch(
            "production.daemons.high_frequency_tws_daemon.HighFrequencyTWSDaemon.__init__.__globals__",
            create=True,
        ),
    ):
        # Direct import after patching at module level
        import importlib
        import production.daemons.high_frequency_tws_daemon as mod
        importlib.reload(mod)

        with (
            patch.object(mod, "prom_counter", return_value=MagicMock()),
            patch.object(mod, "prom_gauge", return_value=MagicMock()),
        ):
            from unittest.mock import patch as p2
            with p2("prometheus_client.Counter") as mock_counter:
                mock_counter.return_value = MagicMock()
                daemon = mod.HighFrequencyTWSDaemon.__new__(mod.HighFrequencyTWSDaemon)
                return daemon, mod


def test_tick_buffer_attribute_removed():
    """tick_buffer deque must not exist after dead code removal."""
    from unittest.mock import MagicMock, patch
    with (
        patch("production.daemons.high_frequency_tws_daemon.prom_counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.prom_gauge", return_value=MagicMock()),
        patch("prometheus_client.Counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.Settings"),
    ):
        from production.daemons.high_frequency_tws_daemon import HighFrequencyTWSDaemon
        daemon = HighFrequencyTWSDaemon.__new__(HighFrequencyTWSDaemon)
        assert not hasattr(daemon, "tick_buffer"), "tick_buffer deque should be removed"


def test_process_tick_buffer_method_removed():
    """process_tick_buffer() method must not exist after dead code removal."""
    from production.daemons.high_frequency_tws_daemon import HighFrequencyTWSDaemon
    assert not hasattr(HighFrequencyTWSDaemon, "process_tick_buffer"), (
        "process_tick_buffer should be removed"
    )
```

**Step 2: Run tests to verify they fail**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/daemons/test_daemon_dead_code_removed.py -v
```

Expected: FAIL — `tick_buffer` exists, `process_tick_buffer` exists.

**Step 3: Remove the dead code**

In `production/daemons/high_frequency_tws_daemon.py`, make these removals:

**In `__init__`**, remove these 6 lines:
```python
# REMOVE:
self.tick_buffer = deque(maxlen=1000)  # Buffer for batch processing  (line 91)
self.max_buffer_size = 1000                                            (line 92)
self.last_flush_time: float = 0.0                                      (line 97)
self.flush_interval_sec: float = 0.25                                  (line 98)
self.batch_size = 10  # Process ticks in batches                       (line 105)
```
Also remove `self.bar_polling_interval = 60.0` and `self.last_bar_poll = 0.0` (lines 122-123) — these are replaced in Task 2.

**In `on_pending_tickers`**, remove the entire `else` branch (lines 249-274) and the `if not self.use_async_publish:` block (lines 276-284). The method body for each ticker after extracting tick_data becomes:

```python
if self.use_async_publish and self.publisher and self.loop:
    try:
        asyncio.run_coroutine_threadsafe(
            self.publisher.publish_tick(symbol, tick_data), self.loop
        )
        self.ticks_processed += 1
        self.m_ticks.inc()
    except Exception as e:
        self.dropped_ticks += 1
        self.m_dropped.inc()
        self.m_dropped_by_reason.labels(reason="async_enqueue_error").inc()
        logger.warning("Async enqueue failed", error=str(e))
```

**Remove `process_tick_buffer()` method** (lines 325-355) entirely.

**In `run()` main loop**, remove (lines 580-583):
```python
# REMOVE:
# Process any remaining buffered ticks
if self.tick_buffer:
    self.process_tick_buffer()
```

**In `cleanup()`**, remove (lines 731-733):
```python
# REMOVE:
if self.tick_buffer:
    logger.info("Processing remaining tick buffer", count=len(self.tick_buffer))
    self.process_tick_buffer()
```

**In `health_check()`**, remove `buffer_size=len(self.tick_buffer)` from the logger.info call (line 491).

Also update `g_buffer` usage: the gauge `indicagent_tick_buffer_size` was only updated in the removed else branch. Remove line 141 (`self.g_buffer = prom_gauge(...)`) from `__init__`.

**Step 4: Run tests to verify they pass**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/daemons/test_daemon_dead_code_removed.py -v
```

Expected: PASS (both tests).

Also run the full suite to verify nothing broke:
```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest tests/ -x -q 2>/dev/null | tail -5
```

Expected: 255+ passing, 0 failures.

**Step 5: Commit**

```bash
git add production/daemons/high_frequency_tws_daemon.py \
        tests/unit/daemons/__init__.py \
        tests/unit/daemons/test_daemon_dead_code_removed.py
git commit -m "refactor: remove dead synchronous tick path from hf daemon (~65 lines)"
```

---

## Task 2: Add Tick Accumulator to Daemon

This task adds the per-symbol tick accumulator that tracks OHLCV within the current minute, and the `_update_tick_accumulator()` and `_flush_provisional_bars()` methods.

**Files:**
- Modify: `production/daemons/high_frequency_tws_daemon.py`
- Create: `tests/unit/daemons/test_daemon_tick_accumulator.py`

**Step 1: Write the failing tests**

Create `tests/unit/daemons/test_daemon_tick_accumulator.py`:

```python
"""Tests for per-symbol tick OHLCV accumulator in the HF daemon."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _make_daemon():
    """Instantiate HighFrequencyTWSDaemon with all external deps mocked."""
    with (
        patch("production.daemons.high_frequency_tws_daemon.prom_counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.prom_gauge", return_value=MagicMock()),
        patch("prometheus_client.Counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.Settings") as mock_settings,
        patch("production.daemons.high_frequency_tws_daemon.MarketHoursManager"),
    ):
        mock_settings.return_value.env_name = ""
        mock_settings.return_value.contracts = []
        mock_settings.return_value.metrics_port = "9108"
        mock_settings.return_value.ib_host = "127.0.0.1"
        mock_settings.return_value.ib_port = 7497
        mock_settings.return_value.ib_client_id = 1
        mock_settings.return_value.hf_async_publish = True
        mock_settings.return_value.redis_host = "localhost"
        mock_settings.return_value.redis_port = 6379
        mock_settings.return_value.redis_db = 0
        mock_settings.return_value.redis_max_connections = 10
        from production.daemons.high_frequency_tws_daemon import HighFrequencyTWSDaemon
        return HighFrequencyTWSDaemon()


def test_tick_accum_initialized_empty():
    """tick_accum starts as empty dict on daemon init."""
    daemon = _make_daemon()
    assert hasattr(daemon, "tick_accum")
    assert daemon.tick_accum == {}


def test_update_tick_accumulator_new_minute():
    """First tick of a minute initializes open/high/low/close from last price."""
    daemon = _make_daemon()
    now = datetime(2026, 2, 18, 14, 5, 30)
    tick = {"last": 5100.25, "volume": 15000}

    daemon._update_tick_accumulator("ESH6", tick, now)

    acc = daemon.tick_accum["ESH6"]
    assert acc["minute"] == 5
    assert acc["open"] == 5100.25
    assert acc["high"] == 5100.25
    assert acc["low"] == 5100.25
    assert acc["close"] == 5100.25
    assert acc["vol_start"] == 15000
    assert acc["vol_current"] == 15000


def test_update_tick_accumulator_running_minute():
    """Subsequent ticks within same minute update high/low/close but not open."""
    daemon = _make_daemon()
    now = datetime(2026, 2, 18, 14, 5, 30)
    daemon._update_tick_accumulator("ESH6", {"last": 5100.25, "volume": 15000}, now)

    # Higher tick
    daemon._update_tick_accumulator("ESH6", {"last": 5103.00, "volume": 15050},
                                    now.replace(second=45))
    # Lower tick
    daemon._update_tick_accumulator("ESH6", {"last": 5099.50, "volume": 15080},
                                    now.replace(second=55))

    acc = daemon.tick_accum["ESH6"]
    assert acc["open"] == 5100.25    # unchanged
    assert acc["high"] == 5103.00    # max seen
    assert acc["low"] == 5099.50     # min seen
    assert acc["close"] == 5099.50   # most recent
    assert acc["vol_current"] == 15080


def test_update_tick_accumulator_minute_rollover():
    """Tick in a new minute resets the accumulator cleanly."""
    daemon = _make_daemon()
    now = datetime(2026, 2, 18, 14, 5, 30)
    daemon._update_tick_accumulator("ESH6", {"last": 5100.25, "volume": 15000}, now)

    # New minute
    new_now = datetime(2026, 2, 18, 14, 6, 5)
    daemon._update_tick_accumulator("ESH6", {"last": 5105.00, "volume": 15200}, new_now)

    acc = daemon.tick_accum["ESH6"]
    assert acc["minute"] == 6
    assert acc["open"] == 5105.00    # reset to new first tick
    assert acc["vol_start"] == 15200  # reset to current cumulative volume
```

**Step 2: Run tests to verify they fail**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/daemons/test_daemon_tick_accumulator.py -v
```

Expected: FAIL — `tick_accum` attribute doesn't exist, `_update_tick_accumulator` doesn't exist.

**Step 3: Add tick accumulator to daemon**

In `production/daemons/high_frequency_tws_daemon.py`:

**Add `timedelta` to import at line 21:**
```python
from datetime import datetime, timedelta
```

**In `__init__`**, after removing `bar_polling_interval` / `last_bar_poll` (done in Task 1), add:
```python
# Minute-boundary bar polling (replaces 60s countdown)
self.last_bar_poll_minute: int = -1       # wall-clock minute of last authoritative poll
self.last_provisional_minute: int = -1    # wall-clock minute of last provisional flush
# Per-symbol tick accumulator for provisional bars
self.tick_accum: dict[str, dict] = {}
```

**Add `_update_tick_accumulator` method** (add before `poll_1m_bars`):

```python
def _update_tick_accumulator(self, symbol: str, tick_data: dict, now: datetime) -> None:
    """Update per-symbol OHLCV accumulator from a tick. Thread-safe under Python GIL."""
    last = tick_data.get("last")
    volume = tick_data.get("volume")
    if not last:
        return
    current_minute = now.minute
    if symbol not in self.tick_accum or self.tick_accum[symbol].get("minute") != current_minute:
        self.tick_accum[symbol] = {
            "minute": current_minute,
            "open": last,
            "high": last,
            "low": last,
            "close": last,
            "vol_start": volume or 0,
            "vol_current": volume or 0,
        }
    else:
        acc = self.tick_accum[symbol]
        if last > acc["high"]:
            acc["high"] = last
        if last < acc["low"]:
            acc["low"] = last
        acc["close"] = last
        if volume is not None:
            acc["vol_current"] = volume
```

**In `on_pending_tickers`**, in the async path after the ticks_processed increment, call the accumulator:

```python
# In the async path (after self.ticks_processed += 1):
self._update_tick_accumulator(symbol, tick_data, current_time)
```

Full updated async path:
```python
if self.use_async_publish and self.publisher and self.loop:
    try:
        asyncio.run_coroutine_threadsafe(
            self.publisher.publish_tick(symbol, tick_data), self.loop
        )
        self.ticks_processed += 1
        self.m_ticks.inc()
        self._update_tick_accumulator(symbol, tick_data, current_time)
    except Exception as e:
        self.dropped_ticks += 1
        self.m_dropped.inc()
        self.m_dropped_by_reason.labels(reason="async_enqueue_error").inc()
        logger.warning("Async enqueue failed", error=str(e))
```

**Step 4: Run tests to verify they pass**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/daemons/test_daemon_tick_accumulator.py -v
```

Expected: PASS (4 tests).

**Step 5: Commit**

```bash
git add production/daemons/high_frequency_tws_daemon.py \
        tests/unit/daemons/test_daemon_tick_accumulator.py
git commit -m "feat: add per-symbol tick OHLCV accumulator to hf daemon"
```

---

## Task 3: Add Provisional Bar Flush and Minute-Boundary Poll

This task adds `_flush_provisional_bars()`, updates `poll_1m_bars()` to use `source="authoritative"`, and replaces the 60s countdown in `run()` with minute-boundary logic.

**Files:**
- Modify: `production/daemons/high_frequency_tws_daemon.py`
- Create: `tests/unit/daemons/test_daemon_provisional_bar.py`

**Step 1: Write the failing tests**

Create `tests/unit/daemons/test_daemon_provisional_bar.py`:

```python
"""Tests for provisional bar flushing and minute-boundary poll logic."""
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest


def _make_daemon():
    with (
        patch("production.daemons.high_frequency_tws_daemon.prom_counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.prom_gauge", return_value=MagicMock()),
        patch("prometheus_client.Counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.Settings") as mock_settings,
        patch("production.daemons.high_frequency_tws_daemon.MarketHoursManager"),
    ):
        mock_settings.return_value.env_name = ""
        mock_settings.return_value.contracts = []
        mock_settings.return_value.metrics_port = "9108"
        mock_settings.return_value.ib_host = "127.0.0.1"
        mock_settings.return_value.ib_port = 7497
        mock_settings.return_value.ib_client_id = 1
        mock_settings.return_value.hf_async_publish = True
        mock_settings.return_value.redis_host = "localhost"
        mock_settings.return_value.redis_port = 6379
        mock_settings.return_value.redis_db = 0
        mock_settings.return_value.redis_max_connections = 10
        from production.daemons.high_frequency_tws_daemon import HighFrequencyTWSDaemon
        daemon = HighFrequencyTWSDaemon()
    daemon.redis_client = MagicMock()
    daemon.redis_client.xadd = MagicMock()
    daemon.m_bars = MagicMock()
    return daemon


def test_flush_provisional_bar_publishes_tick_derived():
    """_flush_provisional_bars publishes a bar with source='tick_derived'."""
    daemon = _make_daemon()
    # Accumulator has data for minute 5 (the just-closed minute)
    daemon.tick_accum["ESH6"] = {
        "minute": 5,
        "open": 5100.0, "high": 5108.0, "low": 5097.0, "close": 5104.0,
        "vol_start": 1000, "vol_current": 1250,
    }
    # now = 14:06:02 → closed minute = 14:05:00
    now = datetime(2026, 2, 18, 14, 6, 2)
    daemon._flush_provisional_bars(now)

    assert daemon.redis_client.xadd.called
    call_args = daemon.redis_client.xadd.call_args
    bar_data = call_args[0][1]  # second positional arg = the fields dict
    assert bar_data["source"] == "tick_derived"
    assert bar_data["open"] == "5100.0"
    assert bar_data["high"] == "5108.0"
    assert bar_data["low"] == "5097.0"
    assert bar_data["close"] == "5104.0"
    assert bar_data["volume"] == "250"           # 1250 - 1000
    assert bar_data["timeframe"] == "1m"
    assert bar_data["symbol"] == "ESH6"
    assert "14:05:00" in bar_data["timestamp"]   # start of closed minute


def test_flush_provisional_bar_skips_wrong_minute():
    """_flush_provisional_bars skips symbols whose accumulator minute doesn't match."""
    daemon = _make_daemon()
    # Accumulator for minute 3, but we're flushing for minute 5 (closed)
    daemon.tick_accum["ESH6"] = {
        "minute": 3,  # stale
        "open": 5100.0, "high": 5100.0, "low": 5100.0, "close": 5100.0,
        "vol_start": 1000, "vol_current": 1050,
    }
    now = datetime(2026, 2, 18, 14, 6, 2)  # closed minute = 5 != 3
    daemon._flush_provisional_bars(now)

    assert not daemon.redis_client.xadd.called


def test_minute_boundary_attributes_exist():
    """Daemon must have last_bar_poll_minute and last_provisional_minute initialized."""
    daemon = _make_daemon()
    assert hasattr(daemon, "last_bar_poll_minute")
    assert daemon.last_bar_poll_minute == -1
    assert hasattr(daemon, "last_provisional_minute")
    assert daemon.last_provisional_minute == -1
```

**Step 2: Run tests to verify they fail**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/daemons/test_daemon_provisional_bar.py -v
```

Expected: FAIL — `_flush_provisional_bars` doesn't exist, `last_provisional_minute` doesn't exist.

**Step 3: Add `_flush_provisional_bars` and update `run()`**

**Add `_flush_provisional_bars` method** to `HighFrequencyTWSDaemon` (add after `_update_tick_accumulator`):

```python
def _flush_provisional_bars(self, now: datetime) -> None:
    """Publish tick-derived provisional bars for the just-closed minute.

    Called at the start of each new minute (second 0-4). Emits bars with
    source='tick_derived' so downstream services can trigger immediately.
    The authoritative reqHistoricalData correction arrives ~5s later.
    """
    if not self.redis_client:
        return
    closed_minute_ts = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    closed_minute = closed_minute_ts.minute

    for symbol, acc in list(self.tick_accum.items()):
        if acc.get("minute") != closed_minute:
            continue
        if not acc.get("close"):
            continue
        volume = max(0, acc["vol_current"] - acc["vol_start"])
        bar_data = {
            "timestamp": closed_minute_ts.isoformat(),
            "symbol": symbol,
            "timeframe": "1m",
            "open": str(acc["open"]),
            "high": str(acc["high"]),
            "low": str(acc["low"]),
            "close": str(acc["close"]),
            "volume": str(volume),
            "source": "tick_derived",
        }
        stream_name = sk_market(self.env_prefix, symbol, "1m")
        self.redis_client.xadd(stream_name, bar_data, maxlen=2000, approximate=True)
        self.m_bars.inc()
        logger.info(
            "Provisional 1m bar flushed",
            symbol=symbol,
            ts=closed_minute_ts.isoformat(),
            close=acc["close"],
        )
```

**Update `poll_1m_bars()`** — change `"source": "hf_tws_daemon_poll"` to `"source": "authoritative"`:

```python
bar_data = {
    "timestamp": bar_timestamp,
    "symbol": symbol,
    "timeframe": "1m",
    "open": str(bar.open),
    "high": str(bar.high),
    "low": str(bar.low),
    "close": str(bar.close),
    "volume": str(bar.volume),
    "source": "authoritative",   # ← changed from "hf_tws_daemon_poll"
}
```

**Update `run()` main loop** — replace the 60s countdown (lines 575-578) with minute-boundary logic:

```python
# Old (remove this):
# Poll for 1m bars (since reqRealTimeBars doesn't work reliably)
if now_ts - self.last_bar_poll >= self.bar_polling_interval:
    self.poll_1m_bars()
    self.last_bar_poll = now_ts

# New (add this):
now = datetime.now()
# Flush provisional bar at start of each new minute (seconds 0-4)
if now.second < 5 and self.last_provisional_minute != now.minute:
    self.last_provisional_minute = now.minute
    self._flush_provisional_bars(now)
# Fire authoritative poll at :05+ past each minute
if now.second >= 5 and self.last_bar_poll_minute != now.minute:
    self.last_bar_poll_minute = now.minute
    self.poll_1m_bars()
```

Note: The existing `now_ts = time.time()` is used for mode_check_interval above this block. Keep it. Add `now = datetime.now()` just before the bar polling section.

**Step 4: Run tests to verify they pass**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/daemons/ -v
```

Expected: PASS (all 9 daemon tests).

**Step 5: Commit**

```bash
git add production/daemons/high_frequency_tws_daemon.py \
        tests/unit/daemons/test_daemon_provisional_bar.py
git commit -m "feat: add provisional bar flush and minute-aligned authoritative poll"
```

---

## Task 4: Source Filter in Intelligence Processor

The downstream service must skip pipeline execution for `source="authoritative"` bars but still update bar history (timestamp dedup for corrections, append for new bars).

**Files:**
- Modify: `services/intelligence_processor_service.py`
- Create: `tests/unit/service_tests/test_intelligence_source_filter.py`

**Step 1: Write the failing tests**

Create `tests/unit/service_tests/test_intelligence_source_filter.py`:

```python
"""Tests for source-based bar filtering in IntelligenceProcessorService."""
from collections import deque
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_service():
    with patch("services.intelligence_processor_service.start_metrics_server"):
        from services.intelligence_processor_service import IntelligenceProcessorService
        svc = IntelligenceProcessorService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xack = AsyncMock()
    svc.db_manager = None
    return svc


def _make_fields(
    ts: datetime,
    source: str | None = None,
    open_: float = 5100.0,
    high: float = 5105.0,
    low: float = 5097.0,
    close: float = 5103.0,
    volume: int = 1234,
) -> dict:
    """Build a bytes-keyed field dict like xreadgroup returns."""
    fields = {
        b"timestamp": ts.isoformat().encode(),
        b"open": str(open_).encode(),
        b"high": str(high).encode(),
        b"low": str(low).encode(),
        b"close": str(close).encode(),
        b"volume": str(volume).encode(),
    }
    if source is not None:
        fields[b"source"] = source.encode()
    return fields


@pytest.mark.asyncio
async def test_authoritative_bar_skips_pipeline():
    """source='authoritative' must NOT trigger _calculate_intelligence."""
    svc = _make_service()
    svc._calculate_intelligence = AsyncMock(return_value={})

    ts = datetime(2026, 2, 18, 14, 5, 0, tzinfo=timezone.utc)
    fields = _make_fields(ts, source="authoritative")
    await svc._process_single_bar("ESH6", "1m", fields, "market:ESH6:1m", b"1-0")

    svc._calculate_intelligence.assert_not_called()


@pytest.mark.asyncio
async def test_authoritative_bar_updates_history():
    """source='authoritative' bar must still be added to bar_history."""
    svc = _make_service()
    svc._calculate_intelligence = AsyncMock(return_value={})

    ts = datetime(2026, 2, 18, 14, 5, 0, tzinfo=timezone.utc)
    fields = _make_fields(ts, source="authoritative", close=5103.0)
    await svc._process_single_bar("ESH6", "1m", fields, "market:ESH6:1m", b"1-0")

    history = svc.bar_history["ESH6:1m"]
    assert len(history) == 1
    assert history[-1]["close"] == 5103.0


@pytest.mark.asyncio
async def test_authoritative_bar_deduplicates_matching_timestamp():
    """Authoritative bar with same timestamp as last history entry replaces it in-place."""
    svc = _make_service()
    svc._calculate_intelligence = AsyncMock(return_value={})

    ts = datetime(2026, 2, 18, 14, 5, 0, tzinfo=timezone.utc)
    # Pre-populate history with the provisional tick_derived bar
    svc.bar_history["ESH6:1m"].append({
        "timestamp": ts, "open": 5100.0, "high": 5104.0,
        "low": 5098.0, "close": 5102.0, "volume": 200,
    })

    # Authoritative correction: same timestamp, authoritative OHLCV
    fields = _make_fields(ts, source="authoritative",
                          open_=5100.25, high=5106.0, low=5097.5, close=5103.75, volume=250)
    await svc._process_single_bar("ESH6", "1m", fields, "market:ESH6:1m", b"2-0")

    history = svc.bar_history["ESH6:1m"]
    assert len(history) == 1, "Should replace, not append"
    assert history[-1]["close"] == 5103.75
    assert history[-1]["volume"] == 250


@pytest.mark.asyncio
async def test_tick_derived_source_runs_pipeline():
    """source='tick_derived' must call _calculate_intelligence normally."""
    svc = _make_service()
    svc._calculate_intelligence = AsyncMock(return_value={})

    ts = datetime(2026, 2, 18, 14, 5, 0, tzinfo=timezone.utc)
    fields = _make_fields(ts, source="tick_derived")
    await svc._process_single_bar("ESH6", "1m", fields, "market:ESH6:1m", b"1-0")

    svc._calculate_intelligence.assert_called_once()


@pytest.mark.asyncio
async def test_missing_source_field_runs_pipeline():
    """Bars with no source field (old daemon, backward compat) must run the pipeline."""
    svc = _make_service()
    svc._calculate_intelligence = AsyncMock(return_value={})

    ts = datetime(2026, 2, 18, 14, 5, 0, tzinfo=timezone.utc)
    fields = _make_fields(ts, source=None)  # no source field
    await svc._process_single_bar("ESH6", "1m", fields, "market:ESH6:1m", b"1-0")

    svc._calculate_intelligence.assert_called_once()
```

**Step 2: Run tests to verify they fail**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/service_tests/test_intelligence_source_filter.py -v
```

Expected: FAIL — `_process_single_bar` doesn't filter on source.

**Step 3: Add source filter to `_process_single_bar`**

In `services/intelligence_processor_service.py`, update `_process_single_bar` (lines 334-393).

Replace the bar_data parsing + history append block (current lines 343-353):

```python
# Current:
bar_data = {
    "timestamp": datetime.fromisoformat(fields[b"timestamp"].decode()),
    "open": float(fields[b"open"].decode()),
    "high": float(fields[b"high"].decode()),
    "low": float(fields[b"low"].decode()),
    "close": float(fields[b"close"].decode()),
    "volume": int(float(fields[b"volume"].decode())),
}

key = f"{symbol}:{timeframe}"
self.bar_history[key].append(bar_data)
```

Replace with:

```python
bar_ts = datetime.fromisoformat(fields[b"timestamp"].decode())
bar_source = fields.get(b"source", b"").decode()
bar_data = {
    "timestamp": bar_ts,
    "open": float(fields[b"open"].decode()),
    "high": float(fields[b"high"].decode()),
    "low": float(fields[b"low"].decode()),
    "close": float(fields[b"close"].decode()),
    "volume": int(float(fields[b"volume"].decode())),
}

key = f"{symbol}:{timeframe}"
history = self.bar_history[key]

if bar_source == "authoritative":
    # Correction: update history, skip pipeline
    if history and history[-1]["timestamp"] == bar_ts:
        history[-1] = bar_data  # in-place correction
    else:
        history.append(bar_data)  # no prior provisional; add to history
    await self.redis_client.xack(stream_name, self.consumer_group, message_id)
    return

history.append(bar_data)
```

The rest of `_process_single_bar` (calculation, publish, persist, metrics, xack) is unchanged.

**Step 4: Run tests to verify they pass**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/service_tests/test_intelligence_source_filter.py -v
```

Expected: PASS (5 tests).

Run the full suite:
```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest tests/ -x -q 2>/dev/null | tail -5
```

Expected: 267+ passing (255 + 12 new), 0 failures.

**Step 5: Commit**

```bash
git add services/intelligence_processor_service.py \
        tests/unit/service_tests/test_intelligence_source_filter.py
git commit -m "feat: add source filter and timestamp dedup to intelligence processor"
```

---

## Task 5: Final Verification and CLAUDE.md Update

**Step 1: Run the full test suite**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest tests/ -q 2>/dev/null | tail -10
```

Expected: 267+ passing, 0 failures.

**Step 2: Run the linter**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m ruff check \
  production/daemons/high_frequency_tws_daemon.py \
  services/intelligence_processor_service.py
```

Expected: 0 errors.

**Step 3: Update CLAUDE.md**

In `CLAUDE.md`, update the version header to v4.2.1 and add to the architecture section:

```
## Bar Source Field (added 2026-02-18)
- `source: "tick_derived"` — provisional bar from tick accumulator, triggers pipeline (~1s latency)
- `source: "authoritative"` — confirmed bar from reqHistoricalData, updates history only (5-10s latency)
- `source: "hf_tws_daemon_poll"` — legacy, treated as tick_derived (backward compat)
```

**Step 4: Commit CLAUDE.md**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md v4.2.1 — data collection efficiency complete"
```

**Step 5: Summary**

Verify changes are complete:
- `production/daemons/high_frequency_tws_daemon.py` — dead code removed, tick accumulator, minute-boundary poll, provisional bar flush, `source="authoritative"` on poll output
- `services/intelligence_processor_service.py` — source filter, timestamp dedup
- 12 new tests across 3 test files
- Bar latency: worst case 10s (was 60s), provisional path 1s

**Note for signal_orchestrator_service.py:** That service (being built in the parallel session under `feature/signal-orchestrator`) should also apply the source filter pattern — only `tick_derived` triggers plugin execution; `authoritative` silently updates history. This should be built in from the start when implementing Task 2/4 of that plan.
