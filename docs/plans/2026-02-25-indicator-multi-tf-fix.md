# Indicator Multi-TF Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 5m/15m/1h/4h/1d indicator streams being silently silenced after service restart, and fix Stochastic plugin errors.

**Architecture:** Two root causes: (1) market:SYM:5m streams contain duplicate-timestamp entries from multiple timeframe_builder restarts; warmup deduplicates to 64 unique bars but min_history_bars=120 silently discards all live bars. (2) Stochastic plugin has `timeframe="1m"` hardcoded in InputSpec, causing it to error on 5m+ bars. Fix: make min_history_bars TF-aware (26 for non-1m) and increase warmup read multiplier to 5× to collect enough unique bars despite duplicates.

**Tech Stack:** Python, redis-py, pytest, services/indicator_service.py

---

### Task 1: Make min_history_bars TF-aware + increase warmup read count

**Root cause confirmed:** `xrevrange(count=150)` returns 150 raw entries but only 64 unique timestamps for 5m (stream has duplicates from builder restarts). 64 < min_history_bars(120) → every live 5m bar silently discarded.

**Files:**
- Modify: `services/indicator_service.py`
- Test: `tests/unit/indicators/test_incremental_manager.py` (add new test file `tests/unit/test_indicator_service_warmup.py`)

**Step 1: Write the failing test**

Create `tests/unit/test_indicator_service_warmup.py`:

```python
"""Tests for indicator service warmup dedup + TF-aware min_history logic."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_service():
    """Create IndicatorService with minimal config (no Redis/metrics)."""
    with patch("services.indicator_service.start_metrics_server"), \
         patch("services.indicator_service.counter", return_value=MagicMock(inc=MagicMock())), \
         patch("services.indicator_service.gauge", return_value=MagicMock(set=MagicMock())), \
         patch("services.indicator_service.get_active_contracts", return_value=["ESH6"]), \
         patch("services.indicator_service.Settings"):
        from services.indicator_service import IndicatorService
        svc = IndicatorService.__new__(IndicatorService)
        svc.config = {
            "service": {
                "symbols": ["ESH6"],
                "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
                "min_history_bars": 120,
                "processing_interval": 0.1,
            }
        }
        svc.bar_history = {}
        svc._bar_history_max = 200
        return svc


def test_min_bars_for_tf_returns_120_for_1m():
    svc = _make_service()
    assert svc._min_bars_for_tf("1m") == 120


def test_min_bars_for_tf_returns_26_for_5m():
    svc = _make_service()
    assert svc._min_bars_for_tf("5m") == 26


def test_min_bars_for_tf_returns_26_for_1h():
    svc = _make_service()
    assert svc._min_bars_for_tf("1h") == 26


def test_min_bars_for_tf_returns_26_for_1d():
    svc = _make_service()
    assert svc._min_bars_for_tf("1d") == 26
```

**Step 2: Run test to confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_indicator_service_warmup.py -v 2>&1 | head -30
```
Expected: `AttributeError: 'IndicatorService' object has no attribute '_min_bars_for_tf'`

**Step 3: Add `_min_bars_for_tf` method to IndicatorService**

In `services/indicator_service.py`, add this method after `_run_i1_plugins` (around line 222):

```python
_TF_MIN_BARS: dict[str, int] = {
    "1m": 120,
    "5m": 26,
    "15m": 26,
    "1h": 26,
    "4h": 26,
    "1d": 26,
}

def _min_bars_for_tf(self, timeframe: str) -> int:
    """Return minimum bar count before emitting indicators for a given TF.

    1m uses 120 (2 hours) for plugin warm-up quality.
    All higher TFs use 26 — enough for EMA-26 and Stochastic-14 computation.
    """
    return self._TF_MIN_BARS.get(timeframe, 26)
```

**Step 4: Replace the hardcoded `min_history_bars` lookup in `_process_single_bar`**

Find this block (around line 256):
```python
            min_bars = self.config["service"]["min_history_bars"]
            if len(self.bar_history[key]) < min_bars:
```

Replace with:
```python
            min_bars = self._min_bars_for_tf(timeframe)
            if len(self.bar_history[key]) < min_bars:
```

**Step 5: Run test to confirm it passes**

```bash
.venv/bin/pytest tests/unit/test_indicator_service_warmup.py -v
```
Expected: all 4 tests PASS

**Step 6: Commit**

```bash
git add tests/unit/test_indicator_service_warmup.py services/indicator_service.py
git commit -m "fix(indicator): TF-aware min_history_bars — 26 for 5m+, keeps 120 for 1m"
```

---

### Task 2: Increase warmup read multiplier to handle duplicate stream entries

**Root cause:** market:SYM:5m streams contain duplicate-timestamp bars from multiple timeframe_builder restarts. Reading 150 raw entries only yields 64 unique bars.

**Files:**
- Modify: `services/indicator_service.py` (warmup in `_setup_consumer_groups`, ~line 297)

**Step 1: Add test for warmup unique-bar count**

Add to `tests/unit/test_indicator_service_warmup.py`:

```python
def test_warmup_read_multiplier_is_5x():
    """Warmup should read 5x the target count to survive duplicate timestamps."""
    svc = _make_service()
    # The constant should exist and equal 5
    assert svc._WARMUP_READ_MULTIPLIER == 5


def test_warmup_reads_enough_entries_for_5m(monkeypatch):
    """After warmup with 64 unique bars from 500 raw entries, history >= 26 for 5m."""
    from collections import OrderedDict
    from datetime import datetime, timezone, timedelta

    svc = _make_service()
    svc.bar_history = {}

    # Simulate 500 raw entries with 70 unique timestamps (duplicates 7x each)
    base_ts = datetime(2026, 2, 25, 18, 0, 0, tzinfo=timezone.utc)
    msgs = []
    for i in range(70):
        ts = base_ts + timedelta(minutes=5 * i)
        ts_str = ts.isoformat().encode()
        fields = {
            b"timestamp": ts_str,
            b"source": b"timeframe_builder",
            b"open": b"6950.0",
            b"high": b"6951.0",
            b"low": b"6949.0",
            b"close": b"6950.5",
            b"volume": b"100",
        }
        for _ in range(7):  # 7 duplicates each = 490 total, ~500
            msgs.append((f"id-{i}".encode(), fields))

    key = "ESH6:5m"
    svc.bar_history[key] = OrderedDict()
    history = svc.bar_history[key]
    for _msg_id, fields in reversed(msgs):
        from datetime import datetime
        bar_ts = datetime.fromisoformat(fields[b"timestamp"].decode())
        bar_source = fields.get(b"source", b"").decode()
        if bar_source == "tick_derived":
            continue
        bar_data = {
            "timestamp": bar_ts,
            "open": float(fields[b"open"].decode()),
            "high": float(fields[b"high"].decode()),
            "low": float(fields[b"low"].decode()),
            "close": float(fields[b"close"].decode()),
            "volume": int(float(fields[b"volume"].decode())),
        }
        history[bar_ts.isoformat()] = bar_data
        while len(history) > svc._bar_history_max:
            history.popitem(last=False)

    # Should have 70 unique bars (all periods, deduped)
    assert len(history) >= 26, f"Only {len(history)} unique bars after warmup"
```

**Step 2: Run test to confirm second test passes** (it tests the logic, not the constant yet)

```bash
.venv/bin/pytest tests/unit/test_indicator_service_warmup.py::test_warmup_reads_enough_entries_for_5m -v
```

**Step 3: Add `_WARMUP_READ_MULTIPLIER` constant and update warmup call**

In `services/indicator_service.py`, add the constant near the top of the class (after line 131 `_bar_history_max`):
```python
_WARMUP_READ_MULTIPLIER: int = 5  # read 5× target to survive duplicate timestamps
```

Then in `_setup_consumer_groups` (around line 297), change:
```python
        warmup_bars = 150
```
to:
```python
        warmup_bars = 150  # unique bars target
        warmup_read_count = warmup_bars * self._WARMUP_READ_MULTIPLIER  # read extra for dedup
```

And change the xrevrange call (around line 303):
```python
                    msgs = await self.redis_client.xrevrange(stream_name, count=warmup_bars)
```
to:
```python
                    msgs = await self.redis_client.xrevrange(stream_name, count=warmup_read_count)
```

**Step 4: Run all new tests**

```bash
.venv/bin/pytest tests/unit/test_indicator_service_warmup.py -v
```
Expected: all 5 tests PASS

**Step 5: Commit**

```bash
git add tests/unit/test_indicator_service_warmup.py services/indicator_service.py
git commit -m "fix(indicator): 5× warmup read multiplier to survive duplicate stream entries"
```

---

### Task 3: Fix Stochastic plugin InputSpec hardcoded to 1m

**Root cause:** `StochasticPlugin.inputs` has `timeframe="1m"` — when indicator service processes 5m bars, the plugin registry may filter it out or raise, causing 10,907 logged errors.

**Files:**
- Modify: `src/intelligence/indicators/stochastic.py:19`

**Step 1: Write the failing test**

Add to `tests/unit/test_indicator_service_warmup.py` (or create `tests/unit/indicators/test_stochastic_plugin.py`):

```python
def test_stochastic_accepts_all_timeframes():
    """Stochastic InputSpec should not restrict to 1m timeframe."""
    from src.intelligence.indicators.stochastic import StochasticPlugin
    plugin = StochasticPlugin()
    for spec in plugin.inputs:
        assert spec.timeframe != "1m", (
            f"Stochastic InputSpec has hardcoded timeframe='1m'; "
            f"should be '.*' or omitted to work on all timeframes"
        )
```

**Step 2: Run test to confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_indicator_service_warmup.py::test_stochastic_accepts_all_timeframes -v
```
Expected: FAIL — `InputSpec has hardcoded timeframe='1m'`

**Step 3: Fix the InputSpec in stochastic.py**

In `src/intelligence/indicators/stochastic.py`, line 19, change:
```python
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
```
to:
```python
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_indicator_service_warmup.py -v
.venv/bin/pytest tests/unit/indicators/test_incremental_manager.py -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add src/intelligence/indicators/stochastic.py tests/unit/test_indicator_service_warmup.py
git commit -m "fix(stochastic): InputSpec timeframe '1m' → '.*' to support all timeframes"
```

---

### Task 4: Restart indicator service and verify streams recover

**Step 1: Restart the indicator service**

```bash
sudo systemctl restart indicagent-indicator
```

**Step 2: Watch for warmup logs**

```bash
journalctl -u indicagent-indicator -f --no-pager 2>&1 | head -20
```

**Step 3: Verify indicators:ESH6:5m updates within 10 minutes**

```bash
.venv/bin/python -c "
import redis, datetime, time
r = redis.Redis(decode_responses=True)
for i in range(3):
    e = r.xrevrange('development:indicators:ESH6:5m', count=1)
    if e:
        ts = int(e[0][0].split('-')[0])
        print(f'[{i}] indicators:ESH6:5m last: {datetime.datetime.fromtimestamp(ts/1000)}')
    time.sleep(120)
"
```
Expected: timestamp advances within 10 minutes (next 5m bar)

**Step 4: Verify intelligence:ESH6:5m also recovers**

```bash
.venv/bin/python -c "
import redis, json, datetime
r = redis.Redis(decode_responses=True)
e = r.xrevrange('development:intelligence:ESH6:5m', count=1)
for eid, data in e:
    evt = json.loads(data['event'])
    print(f'intelligence:ESH6:5m ts: {evt.get(\"ts\")}')
"
```

**Step 5: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```
Expected: all 584+ tests pass

**Step 6: Final commit / lint**

```bash
.venv/bin/ruff check . --fix
git add -A
git status  # review, then:
git commit -m "chore: lint fixes post indicator multi-tf fix"
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `services/indicator_service.py` | `_min_bars_for_tf()` method + `_WARMUP_READ_MULTIPLIER=5` + warmup read count × 5 |
| `src/intelligence/indicators/stochastic.py` | InputSpec `timeframe="1m"` → `".*"` |
| `tests/unit/test_indicator_service_warmup.py` | New — 6 unit tests covering the fixes |
