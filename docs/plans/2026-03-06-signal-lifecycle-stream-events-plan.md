# Signal Lifecycle Stream Events Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Publish terminal signal lifecycle events to the Redis stream so the dashboard shows resolved signals (dimmed + outcome badge) instead of stale live ones — and fix two supporting issues: SSE snapshot age filter and REST API timeframe filter.

**Architecture:** `signal_lifecycle_service` gains a `_publish_terminal_event()` helper that fires an `xadd` to `signals:SYMBOL:TF:aggregated` with `direction=0` + outcome on every terminal transition. The SSE endpoint skips snapshot entries older than `2×TF` for signal streams. The dashboard state machine handles `direction=0` + `signal_id` matching to render a resolved badge.

**Tech Stack:** Python asyncio, redis.asyncio, FastAPI SSE, TypeScript/React, pytest

---

## Overview of Tasks

| # | Component | What |
|---|-----------|------|
| 1 | `signal_lifecycle_service.py` | `_publish_terminal_event()` helper + tests |
| 2 | `signal_lifecycle_service.py` | Wire helper into both exit paths |
| 3 | `src/api/routes/sse.py` | Snapshot age filter for signal streams |
| 4 | `src/api/routes/signals.py` | Add `timeframe` query param filter |
| 5 | `dashboard/src/lib/types.ts` | Extend `SignalData` with `resolved` + `outcome` |
| 6 | `dashboard/src/hooks/use-market-stream.ts` | Handle resolved events in signal_data handler |
| 7 | `dashboard/src/components/signal-panel.tsx` | Render resolved state with outcome badge |

---

## Task 1: `_publish_terminal_event()` helper + tests

**Files:**
- Modify: `services/signal_lifecycle_service.py`
- Test: `tests/unit/service_tests/test_signal_lifecycle_service.py`

**Context:** The service already calls `redis.xadd` for `llm_outcomes:stream` on exit (lines 305–323 for shadow path, 416–434 for normal path). We add a second `xadd` to `signals:SYMBOL:TF:aggregated` using the same pattern.

The stream key function is `signals_aggregated(env_prefix, symbol, timeframe)` from `src.core.stream_keys` — already imported in `signal_generator_service.py`; add import here.

### Step 1: Write failing tests

Add to `tests/unit/service_tests/test_signal_lifecycle_service.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from services.signal_lifecycle_service import SignalLifecycleService


class TestPublishTerminalEvent:
    """_publish_terminal_event() must xadd correct payload to signals stream."""

    def _make_svc(self):
        svc = SignalLifecycleService.__new__(SignalLifecycleService)
        svc.env_prefix = "development:"
        svc.redis_client = AsyncMock()
        svc.redis_client.xadd = AsyncMock(return_value=b"123-0")
        svc.logger = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_xadd_called_with_direction_zero(self):
        svc = self._make_svc()
        await svc._publish_terminal_event(
            signal_id="uuid-a",
            symbol="ESH6",
            timeframe="5m",
            outcome="ttl_expired_behind",
            exit_price=6750.25,
            bar_ts="2026-03-06T15:20:00+00:00",
        )
        svc.redis_client.xadd.assert_called_once()
        call_args = svc.redis_client.xadd.call_args
        payload = call_args[0][1]  # second positional arg = fields dict
        assert payload["direction"] == "0"
        assert payload["signal_id"] == "uuid-a"
        assert payload["outcome"] == "ttl_expired_behind"
        assert payload["status"] == "ttl_expired_behind"
        assert payload["symbol"] == "ESH6"
        assert payload["timeframe"] == "5m"

    @pytest.mark.asyncio
    async def test_stream_key_uses_env_prefix(self):
        svc = self._make_svc()
        await svc._publish_terminal_event(
            signal_id="uuid-b",
            symbol="ESH6",
            timeframe="5m",
            outcome="stopped_at_entry",
            exit_price=None,
            bar_ts="2026-03-06T15:20:00+00:00",
        )
        stream_key = svc.redis_client.xadd.call_args[0][0]
        assert stream_key.startswith("development:")
        assert "signals:" in stream_key
        assert "ESH6" in stream_key
        assert "5m" in stream_key

    @pytest.mark.asyncio
    async def test_exit_price_empty_string_when_none(self):
        svc = self._make_svc()
        await svc._publish_terminal_event(
            signal_id="uuid-c",
            symbol="NQH6",
            timeframe="1m",
            outcome="never_activated",
            exit_price=None,
            bar_ts="2026-03-06T15:20:00+00:00",
        )
        payload = svc.redis_client.xadd.call_args[0][1]
        assert payload["exit_price"] == ""

    @pytest.mark.asyncio
    async def test_no_xadd_when_redis_none(self):
        svc = self._make_svc()
        svc.redis_client = None
        # Must not raise
        await svc._publish_terminal_event(
            signal_id="uuid-d",
            symbol="ESH6",
            timeframe="5m",
            outcome="target_1",
            exit_price=6700.0,
            bar_ts="2026-03-06T15:20:00+00:00",
        )
        # No assertion needed — no AttributeError = pass
```

### Step 2: Run tests to verify they fail

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_lifecycle_service.py::TestPublishTerminalEvent -v
```

Expected: `AttributeError: 'SignalLifecycleService' object has no attribute '_publish_terminal_event'`

### Step 3: Implement `_publish_terminal_event()`

Add import at top of `services/signal_lifecycle_service.py` (after the existing stream key imports):

```python
from src.core.stream_keys import signals_aggregated as sk_signals_aggregated
```

Add the helper method to `SignalLifecycleService` (after `_build_outcome_payload` function, before the class definition — or as an instance method after `__init__`). Place it after `_signal_handler` method (~line 186):

```python
async def _publish_terminal_event(
    self,
    signal_id: str,
    symbol: str,
    timeframe: str,
    outcome: str,
    exit_price: float | None,
    bar_ts: str,
) -> None:
    """Publish a terminal lifecycle event to the signal aggregated stream.

    direction=0 is the sentinel meaning "this signal is closed".
    Published unconditionally — even if a newer signal has already replaced
    this one on the stream. The dashboard matches by signal_id.
    """
    if not self.redis_client:
        return
    stream_key = sk_signals_aggregated(self.env_prefix, symbol, timeframe)
    payload: dict[str, str] = {
        "direction": "0",
        "signal_id": signal_id,
        "status": outcome,
        "outcome": outcome,
        "exit_price": str(exit_price) if exit_price is not None else "",
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": bar_ts,
    }
    try:
        await self.redis_client.xadd(stream_key, payload, maxlen=200, approximate=True)
    except Exception as e:
        self.logger.warning(
            "Failed to publish terminal signal event",
            signal_id=signal_id,
            error=str(e),
        )
```

### Step 4: Run tests to verify they pass

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_lifecycle_service.py::TestPublishTerminalEvent -v
```

Expected: 4 tests PASS

### Step 5: Commit

```bash
git add services/signal_lifecycle_service.py tests/unit/service_tests/test_signal_lifecycle_service.py
git commit -m "feat(lifecycle): add _publish_terminal_event() helper to signals stream"
```

---

## Task 2: Wire terminal event into both exit paths

**Files:**
- Modify: `services/signal_lifecycle_service.py`

**Context:** There are two exit paths in `_evaluate_signals_against_bar`:
1. **Shadow path** (status == "regime_suppressed"), lines ~291–356: after `update_signal_status` call, signal_id/outcome/exit_price/bar_ts are all in scope.
2. **Normal path** (status == "active" exit), lines ~402–470: after `update_signal_status` call, same variables in scope.

There is NO terminal event for `pending → active` (activation). Only exits need publishing.

### Step 1: Write failing test

Add to `tests/unit/service_tests/test_signal_lifecycle_service.py`:

```python
class TestTerminalEventWiring:
    """Terminal events fire in both shadow and normal exit paths."""

    def _make_svc_with_db(self):
        svc = SignalLifecycleService.__new__(SignalLifecycleService)
        svc.env_prefix = "development:"
        svc.redis_client = AsyncMock()
        svc.redis_client.xadd = AsyncMock(return_value=b"123-0")
        svc.db_manager = AsyncMock()
        svc.logger = AsyncMock()
        svc._mae = {}
        svc._mfe = {}
        svc._activated_at = {}
        svc.lifecycle_transitions_total = AsyncMock()
        svc.lifecycle_transitions_total.inc = lambda: None
        svc.active_signals_count = AsyncMock()
        svc.active_signals_count.set = lambda x: None
        svc.point_values = {"ESH6": 50.0}
        return svc

    @pytest.mark.asyncio
    async def test_terminal_event_fires_on_normal_exit(self):
        """Active signal stopped out → _publish_terminal_event called."""
        from unittest.mock import patch, AsyncMock as AM
        from src.intelligence.trading.lifecycle_tracker import SignalTransition

        svc = self._make_svc_with_db()
        svc._publish_terminal_event = AM()

        # Active signal that stops out
        sig = {
            "signal_id": "uuid-exit",
            "symbol": "ESH6",
            "timeframe": "5m",
            "status": "active",
            "direction": -1,
            "entry_price": 6800.0,
            "stop_loss": 6820.0,
            "targets": [6760.0],
            "confidence": 0.85,
            "timestamp": datetime(2026, 3, 6, 15, 0, tzinfo=UTC),
        }
        bar_time = datetime(2026, 3, 6, 15, 5, tzinfo=UTC)
        transition = SignalTransition(
            new_status="stopped_out",
            exit_reason="stop_hit",
            exit_price=6820.0,
            pnl_ticks=-20.0,
            pnl_r=-1.0,
            pnl_dollars=-1000.0,
            outcome=None,
            activation_price=None,
            zone_entry_pct=None,
            bars_to_activation=None,
            mae=None,
            mfe=None,
        )

        with patch("services.signal_lifecycle_service.evaluate_signal", return_value=transition), \
             patch("services.signal_lifecycle_service.update_signal_status", new_callable=AM):
            await svc._evaluate_signals_against_bar(
                "ESH6", "5m",
                {"high": 6825.0, "low": 6795.0, "close": 6822.0},
                bar_time,
                all_active=[sig],
            )

        svc._publish_terminal_event.assert_called_once()
        call_kwargs = svc._publish_terminal_event.call_args[1]
        assert call_kwargs["signal_id"] == "uuid-exit"
        assert call_kwargs["symbol"] == "ESH6"
        assert call_kwargs["timeframe"] == "5m"
```

### Step 2: Run to verify it fails

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_lifecycle_service.py::TestTerminalEventWiring -v
```

Expected: FAIL — `_publish_terminal_event` is not called (wiring not done yet).

### Step 3: Wire into normal exit path

In `_evaluate_signals_against_bar`, after the `llm_outcomes xadd` task block for the **normal exit path** (~line 434, after `self._activated_at.pop`), add:

```python
                # Publish terminal event to signals stream for dashboard resolved state
                asyncio.create_task(self._publish_terminal_event(
                    signal_id=sid,
                    symbol=symbol,
                    timeframe=timeframe,
                    outcome=outcome,
                    exit_price=transition.exit_price,
                    bar_ts=bar_time.isoformat(),
                ))
```

### Step 4: Wire into shadow exit path

In the shadow path, after `self._activated_at.pop(sid, None)` (~line 346), add the same call:

```python
                    # Publish terminal event to signals stream for dashboard resolved state
                    asyncio.create_task(self._publish_terminal_event(
                        signal_id=sid,
                        symbol=symbol,
                        timeframe=timeframe,
                        outcome=outcome,
                        exit_price=transition.exit_price,
                        bar_ts=bar_time.isoformat(),
                    ))
```

### Step 5: Run tests

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_lifecycle_service.py -v
```

Expected: All tests PASS.

### Step 6: Full unit suite

```bash
.venv/bin/pytest tests/unit/ -x -q
```

Expected: All passing, 0 errors.

### Step 7: Commit

```bash
git add services/signal_lifecycle_service.py tests/unit/service_tests/test_signal_lifecycle_service.py
git commit -m "feat(lifecycle): wire terminal stream events into both exit paths"
```

---

## Task 3: SSE snapshot age filter

**Files:**
- Modify: `src/api/routes/sse.py`

**Context:** The snapshot loop (`sse.py:143–168`) replays the last 2 entries per stream on connect. For signal streams, old entries must be filtered. Redis entry IDs are `"{unix_ms}-{seq}"` — parse the Unix ms from the ID to compute age. No payload parsing needed.

TF minutes: `{"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}`.

Max age = `2 × tf_minutes × 60` seconds.

### Step 1: Write failing test

Create `tests/unit/test_sse_snapshot_filter.py`:

```python
"""Tests for SSE snapshot age filter on signal streams."""
import time
import pytest


def _entry_id_for_age(seconds_ago: float) -> str:
    """Create a Redis entry ID that appears N seconds old."""
    unix_ms = int((time.time() - seconds_ago) * 1000)
    return f"{unix_ms}-0"


def _is_signal_entry_stale(stream_name: str, entry_id: str) -> bool:
    """Mirror of the filter logic to be added to sse.py."""
    _TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    if "signals:" not in stream_name:
        return False
    # Extract TF from stream key: "development:signals:ESH6:5m:aggregated"
    parts = stream_name.split(":")
    # Find the part after the symbol (last segment before "aggregated")
    try:
        agg_idx = parts.index("aggregated")
        tf = parts[agg_idx - 1]
    except (ValueError, IndexError):
        return False
    tf_minutes = _TF_MINUTES.get(tf)
    if tf_minutes is None:
        return False
    max_age_s = 2 * tf_minutes * 60
    try:
        entry_unix_ms = int(entry_id.split("-")[0])
    except (ValueError, IndexError):
        return False
    age_s = (time.time() * 1000 - entry_unix_ms) / 1000
    return age_s > max_age_s


@pytest.mark.unit
class TestSseSnapshotFilter:
    def test_fresh_5m_signal_not_stale(self):
        """Entry 3 minutes old on 5m stream: max_age=600s → not stale."""
        entry_id = _entry_id_for_age(180)
        assert not _is_signal_entry_stale("development:signals:ESH6:5m:aggregated", entry_id)

    def test_old_5m_signal_is_stale(self):
        """Entry 25 minutes old on 5m stream: max_age=600s → stale."""
        entry_id = _entry_id_for_age(1500)
        assert _is_signal_entry_stale("development:signals:ESH6:5m:aggregated", entry_id)

    def test_old_1h_signal_not_stale(self):
        """Entry 90 minutes old on 1h stream: max_age=7200s → not stale."""
        entry_id = _entry_id_for_age(5400)
        assert not _is_signal_entry_stale("development:signals:ESH6:1h:aggregated", entry_id)

    def test_very_old_1h_signal_is_stale(self):
        """Entry 3 hours old on 1h stream: max_age=7200s → stale."""
        entry_id = _entry_id_for_age(10800)
        assert _is_signal_entry_stale("development:signals:ESH6:1h:aggregated", entry_id)

    def test_non_signal_stream_never_stale(self):
        """Intelligence and indicator streams are never filtered."""
        entry_id = _entry_id_for_age(99999)
        assert not _is_signal_entry_stale("development:intelligence:ESH6:5m", entry_id)
        assert not _is_signal_entry_stale("development:indicators:ESH6:5m", entry_id)

    def test_1m_boundary(self):
        """Entry 3 minutes old on 1m stream: max_age=120s → stale."""
        entry_id = _entry_id_for_age(181)
        assert _is_signal_entry_stale("development:signals:ESH6:1m:aggregated", entry_id)
```

### Step 2: Run to verify it fails

```bash
.venv/bin/pytest tests/unit/test_sse_snapshot_filter.py -v
```

Expected: `ModuleNotFoundError` or all pass (it's testing pure logic). If all pass, the helper function already matches the spec — proceed to wiring.

### Step 3: Add `_TF_MINUTES` and `_signal_entry_stale()` to sse.py

Add after the `_NARRATIVE_GROUPS` constant (~line 25):

```python
_TF_MINUTES: dict[str, int] = {
    "1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440
}


def _signal_entry_stale(stream_name: str, entry_id: str | bytes) -> bool:
    """Return True if this signal stream entry is older than 2×TF.

    Uses the Redis entry ID's embedded Unix-ms timestamp — no payload parsing.
    Only applies to signals: streams; other streams always return False.
    """
    import time as _time
    if "signals:" not in stream_name:
        return False
    parts = stream_name.split(":")
    try:
        agg_idx = parts.index("aggregated")
        tf = parts[agg_idx - 1]
    except (ValueError, IndexError):
        return False
    tf_minutes = _TF_MINUTES.get(tf)
    if tf_minutes is None:
        return False
    max_age_s = 2 * tf_minutes * 60
    try:
        id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
        entry_unix_ms = int(id_str.split("-")[0])
    except (ValueError, IndexError):
        return False
    age_s = (_time.time() * 1000 - entry_unix_ms) / 1000
    return age_s > max_age_s
```

### Step 4: Wire filter into snapshot loop

In the snapshot loop (`event_generator`, after `entries = await redis.xrevrange(...)`), add the filter before the `event_name` resolution. Find the block at ~line 156:

```python
                    event_name = _event_name_for_stream(stream_name)
                    for msg_id, fields in reversed(entries):
```

Change to:

```python
                    event_name = _event_name_for_stream(stream_name)
                    for msg_id, fields in reversed(entries):
                        if _signal_entry_stale(stream_name, msg_id):
                            last_ids[stream_name] = msg_id  # advance cursor even when skipping
                            continue
```

### Step 5: Run tests

```bash
.venv/bin/pytest tests/unit/test_sse_snapshot_filter.py -v
.venv/bin/pytest tests/unit/ -x -q
```

Expected: All PASS.

### Step 6: Commit

```bash
git add src/api/routes/sse.py tests/unit/test_sse_snapshot_filter.py
git commit -m "feat(sse): skip stale signal stream entries in snapshot on reconnect"
```

---

## Task 4: REST API timeframe filter

**Files:**
- Modify: `src/api/routes/signals.py`
- Test: `tests/unit/` — new test file

**Context:** `get_signals()` accepts `symbol`, `from_ts`, `to_ts`, `limit` but silently ignores `?timeframe=5m`. Fix by adding a `timeframe` Query param and injecting it as `$5` into both SQL queries.

### Step 1: Write failing test

Create `tests/unit/test_signals_api_timeframe_filter.py`:

```python
"""Test that /api/signals/{symbol} respects ?timeframe= filter."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.mark.unit
class TestSignalsApiTimeframeFilter:
    def _make_client(self, mock_rows):
        from src.api.main import app
        client = TestClient(app)
        return client

    def test_timeframe_param_accepted(self):
        """?timeframe=5m must not return 404 or 422."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])
        with patch("src.api.routes.signals.get_db_manager", return_value=mock_db):
            from src.api.main import app
            client = TestClient(app)
            resp = client.get("/api/signals/ESH6?timeframe=5m")
            assert resp.status_code == 200

    def test_timeframe_filter_passed_to_query(self):
        """fetch() must be called with timeframe as a bound parameter."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])

        with patch("src.api.routes.signals.get_db_manager", return_value=mock_db):
            from src.api.main import app
            client = TestClient(app)
            client.get("/api/signals/ESH6?timeframe=5m")

        call_args = mock_db.fetch.call_args[0]
        # timeframe="5m" must appear somewhere in the positional args
        assert "5m" in call_args
```

### Step 2: Run to verify it fails

```bash
.venv/bin/pytest tests/unit/test_signals_api_timeframe_filter.py -v
```

Expected: `test_timeframe_filter_passed_to_query` FAIL — `"5m"` not in call_args.

### Step 3: Implement the filter

In `src/api/routes/signals.py`, update `get_signals()` signature:

```python
@router.get("/signals/{symbol}")
async def get_signals(
    symbol: str,
    include_features: bool = Query(False, ...),
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    timeframe: str | None = Query(None, description="Filter by timeframe, e.g. 5m"),
    limit: int = Query(100, ge=1, le=1000, ...),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
```

In both SQL queries (with and without features), add `AND ($5::text IS NULL OR sl.timeframe = $5)` to the `WHERE` clause after the existing timestamp conditions:

```sql
WHERE sl.symbol = $1
  AND ($3::timestamptz IS NULL OR sl.timestamp >= $3)
  AND ($4::timestamptz IS NULL OR sl.timestamp <= $4)
  AND ($5::text IS NULL OR sl.timeframe = $5)
ORDER BY sl.timestamp DESC
LIMIT $2
```

Update the `db_manager.fetch` call to pass `timeframe` as fifth arg:

```python
rows = await db_manager.fetch(query, contract, limit, from_ts, to_ts, timeframe)
```

### Step 4: Run tests

```bash
.venv/bin/pytest tests/unit/test_signals_api_timeframe_filter.py -v
.venv/bin/pytest tests/unit/ -x -q
```

Expected: All PASS.

### Step 5: Commit

```bash
git add src/api/routes/signals.py tests/unit/test_signals_api_timeframe_filter.py
git commit -m "fix(api): add timeframe filter to GET /api/signals/{symbol}"
```

---

## Task 5: Extend `SignalData` type

**Files:**
- Modify: `dashboard/src/lib/types.ts`

**No test needed** — TypeScript compilation catches type errors.

### Step 1: Add `resolved` and `outcome` fields to `SignalData`

In `dashboard/src/lib/types.ts`, find `SignalData` interface (~line 185). Add two optional fields after `bid_at_signal`:

```typescript
  bid_at_signal?: number;        // live bid at signal creation
  // Resolved state — set when lifecycle service publishes direction=0 terminal event
  resolved?: boolean;            // true = signal closed, outcome known
  outcome?: string;              // 8-class outcome: "expired" | "stopped_at_entry" | "stopped_in_trade" | "target_1" | "target_1_2" | "target_full" | "never_activated" | "ttl_expired_behind" | "ttl_expired_ahead"
  exit_price?: number;           // price at which signal was closed
```

### Step 2: Verify TypeScript compiles

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

### Step 3: Commit

```bash
git add dashboard/src/lib/types.ts
git commit -m "feat(dashboard/types): add resolved + outcome fields to SignalData"
```

---

## Task 6: Handle resolved events in `use-market-stream.ts`

**Files:**
- Modify: `dashboard/src/hooks/use-market-stream.ts`

**Context:** The `signal_data` handler at line ~481. Current logic for `dir === 0`: `fullSignal = null`, then `signal = isSelectedTf ? (fullSignal ?? old.signal) : old.signal` — the `??` keeps the old signal. We change this: `dir === 0` with a terminal `status` and matching `signal_id` → create a resolved `SignalData`. Non-matching `signal_id` → no-op (keep old signal).

Terminal status values (from lifecycle service): `"ttl_expired_behind"`, `"ttl_expired_ahead"`, `"stopped_at_entry"`, `"stopped_in_trade"`, `"target_1"`, `"target_1_2"`, `"target_full"`, `"never_activated"`.

### Step 1: No automated test (EventSource is not testable in unit env)

This is a UI state handler. Verify manually after implementation. TypeScript compilation is the gate.

### Step 2: Implement resolved signal handling

In `use-market-stream.ts`, find the `signal_data` handler. The block currently reads (~lines 507–537):

```typescript
const fullSignal: SignalData | null = dir !== 0
  ? {
      direction: dir > 0 ? "long" : "short",
      ...
    }
  : null;
```

Replace the `dir === 0` null branch with resolved state logic. Change to:

```typescript
let fullSignal: SignalData | null = null;
if (dir !== 0) {
  fullSignal = {
    direction: dir > 0 ? "long" : "short",
    signal_type: String(payload.signal_type || ""),
    setup_plugin: String(payload.setup_plugin || ""),
    confidence: parseFloat(String(payload.confidence || "0")),
    entry_price: parseFloat(String(payload.entry_price || "0")),
    entry_type: String(payload.entry_type || "at_close"),
    stop_loss: parseFloat(String(payload.stop_loss || "0")),
    stop_type: String(payload.stop_type || "atr"),
    profit_target: _parseOptFloat(payload.profit_target),
    profit_target_2: _parseOptFloat(payload.profit_target_2),
    profit_target_3: _parseOptFloat(payload.profit_target_3),
    target_labels: _parseLabels(payload.target_labels),
    rr_t1: _parseOptFloat(payload.rr_t1) ?? undefined,
    rr_t2: _parseOptFloat(payload.rr_t2) ?? undefined,
    rr_t3: _parseOptFloat(payload.rr_t3) ?? undefined,
    framing_method: String(payload.framing_method || "atr_fallback"),
    risk_reward_ratio: parseFloat(String(payload.risk_reward_ratio || "0")),
    regime_context: String(payload.regime_context || ""),
    timeframe: tf,
    timestamp: String(payload.timestamp || ""),
    signal_computed_at: _signalComputedAt,
    bar_close_ts: _barCloseTs,
    pipeline_lag_s: pipelineLagS(_signalComputedAt, _barCloseTs) ?? undefined,
    bar_close_price: _parseOptFloat(payload.bar_close_price) ?? undefined,
    market_price_at_signal: _parseOptFloat(payload.market_price_at_signal) ?? undefined,
    ask_at_signal: _parseOptFloat(payload.ask_at_signal) ?? undefined,
    bid_at_signal: _parseOptFloat(payload.bid_at_signal) ?? undefined,
  };
} else if (payload.status && payload.signal_id) {
  // Terminal lifecycle event — direction=0 sentinel from signal_lifecycle_service
  // Only apply if signal_id matches currently displayed signal (epoch tag)
  setSymbolData((prev) => {
    const old2 = prev[sym];
    if (!old2) return prev;
    const currentSignal = isSelectedTf ? old2.signal : old2.signalsByTf[tf];
    const resolvedId = String(payload.signal_id);
    if (!currentSignal || (currentSignal as SignalData & { signal_id?: string }).signal_id !== resolvedId) {
      return prev; // stale resolved event for preempted signal — no-op
    }
    const resolvedSignal: SignalData = {
      ...currentSignal,
      resolved: true,
      outcome: String(payload.status),
      exit_price: _parseOptFloat(payload.exit_price) ?? undefined,
    };
    return {
      ...prev,
      [sym]: {
        ...old2,
        signal: isSelectedTf ? resolvedSignal : old2.signal,
        signalsByTf: { ...old2.signalsByTf, [tf]: resolvedSignal },
        lastUpdate: Date.now(),
      },
    };
  });
  touch();
  return; // early return — state already updated above
}
```

**Note:** `signal_id` is not currently on `SignalData`. The signal birth event from `signal_generator_service` includes `signal_id` in the stream message (added in Phase 17 task 1). We need to store it. In the `dir !== 0` branch, add `signal_id` to the fullSignal object:

```typescript
    signal_id: String(payload.signal_id || ""),  // add after bid_at_signal
```

And add `signal_id?: string` to `SignalData` in types.ts (add alongside `resolved`).

### Step 3: Verify TypeScript compiles

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

### Step 4: Commit

```bash
git add dashboard/src/hooks/use-market-stream.ts dashboard/src/lib/types.ts
git commit -m "feat(dashboard): handle resolved signal lifecycle events in SSE stream"
```

---

## Task 7: Render resolved state in `signal-panel.tsx`

**Files:**
- Modify: `dashboard/src/components/signal-panel.tsx`

**Context:** When `signal.resolved === true`, render dimmed display with an outcome badge. Keep entry/SL/targets visible for context. Remove staleness ratio (signal is definitively closed).

Outcome → badge label mapping:
- `ttl_expired_behind`, `ttl_expired_ahead`, `never_activated` → `EXPIRED`
- `stopped_at_entry`, `stopped_in_trade` → `STOPPED`
- `target_1` → `T1 HIT`
- `target_1_2` → `T1+T2 HIT`
- `target_full` → `FULL TARGET`

### Step 1: Add outcome badge helper and resolved rendering

In `signal-panel.tsx`, add a helper function after `_abbreviateLabel`:

```typescript
function _outcomeLabel(outcome: string | undefined): string {
  if (!outcome) return "CLOSED";
  if (outcome.startsWith("ttl_expired") || outcome === "never_activated") return "EXPIRED";
  if (outcome.startsWith("stopped")) return "STOPPED";
  if (outcome === "target_full") return "FULL TARGET";
  if (outcome === "target_1_2") return "T1+T2 HIT";
  if (outcome === "target_1") return "T1 HIT";
  return "CLOSED";
}
```

In the `SignalPanel` component, add resolved state rendering. After the `if (!signal)` early return and before the `isLong` line, add:

```typescript
  if (signal.resolved) {
    const badgeLabel = _outcomeLabel(signal.outcome);
    const badgeColor =
      signal.outcome?.startsWith("target") ? "var(--green-dim)"
      : signal.outcome?.startsWith("stopped") ? "var(--red-dim)"
      : "var(--text-muted)";
    const badgeText =
      signal.outcome?.startsWith("target") ? "var(--green)"
      : signal.outcome?.startsWith("stopped") ? "var(--red)"
      : "var(--text-secondary)";

    return (
      <div className="px-2 py-1 space-y-0.5 opacity-50">
        {/* Row 1: label · TF · time · direction · plugin · OUTCOME BADGE */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="zone-label shrink-0 w-10">SIG</span>
          <span
            className="inline-flex items-center px-1 py-0 rounded text-[0.5rem] font-bold uppercase tracking-wider"
            style={{ backgroundColor: "var(--bg-secondary)", color: "var(--text-muted)" }}
          >
            {signal.timeframe || "1m"}
          </span>
          {signal.timestamp && (
            <span className="text-[0.55rem] font-data text-[var(--text-muted)]">
              {new Date(signal.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}
            </span>
          )}
          {/* Outcome badge */}
          <span
            className="inline-flex items-center px-1.5 py-0 rounded text-[0.5rem] font-bold uppercase tracking-widest"
            style={{ backgroundColor: badgeColor, color: badgeText }}
          >
            {badgeLabel}
          </span>
          <span className="text-[0.6rem] text-[var(--text-muted)] font-medium line-through">
            {_abbreviatePlugin(signal.setup_plugin)}
          </span>
        </div>
        {/* Row 2: entry · SL (greyed out context) */}
        <div className="flex items-center gap-2 pl-[3.25rem] flex-wrap">
          <span className="text-[0.55rem] text-[var(--text-muted)] whitespace-nowrap opacity-60">
            <span className="opacity-60">E </span>
            <span className="font-data">{fmtPrice(signal.entry_price)}</span>
          </span>
          {signal.exit_price && (
            <>
              <span className="opacity-40 text-[0.5rem]">→</span>
              <span className="text-[0.55rem] text-[var(--text-muted)] whitespace-nowrap opacity-60">
                <span className="opacity-60">X </span>
                <span className="font-data">{fmtPrice(signal.exit_price)}</span>
              </span>
            </>
          )}
        </div>
      </div>
    );
  }
```

### Step 2: Verify TypeScript compiles

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

### Step 3: Verify dashboard renders

```bash
# If dev server not running:
cd dashboard && npm run dev -- --port 3000 --hostname 0.0.0.0 > /tmp/dash.log 2>&1 &
```

Check: open dashboard in browser. When a signal closes (or manually test by sending a mock terminal event via redis-cli equivalent), the signal card should show dimmed with outcome badge.

### Step 4: Run lint and full test suite

```bash
.venv/bin/ruff check . --fix
.venv/bin/pytest tests/unit/ -q
```

Expected: 0 ruff errors, all tests pass.

### Step 5: Commit

```bash
git add dashboard/src/components/signal-panel.tsx
git commit -m "feat(dashboard): render resolved signal state with outcome badge"
```

---

## Final Verification

```bash
# Full test suite
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20

# Ruff
.venv/bin/ruff check .

# TypeScript
cd dashboard && npx tsc --noEmit
```

### Manual smoke test (live system)

After deploying (restart `indicagent-signal-lifecycle`):

```bash
# Watch for terminal events in the signals stream
.venv/bin/python3 -c "
import redis, time
r = redis.Redis(decode_responses=True)
# Poll for any direction=0 entries
for sym in ['ESH6', 'NQH6']:
    for tf in ['1m', '5m', '15m', '1h']:
        key = f'development:signals:{sym}:{tf}:aggregated'
        entries = r.xrevrange(key, count=3)
        for eid, data in entries:
            if data.get('direction') == '0':
                print(f'TERMINAL: {sym} {tf} outcome={data.get(\"outcome\")} sid={data.get(\"signal_id\")[:8]}')
"
```

```bash
# Verify API timeframe filter
curl -s 'http://localhost:8000/api/signals/ESH6?timeframe=5m&limit=5' | python3 -m json.tool | grep timeframe
# Expected: all "timeframe": "5m"
```
