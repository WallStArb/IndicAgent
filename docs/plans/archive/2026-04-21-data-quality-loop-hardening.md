# Data-Quality Loop Hardening Implementation Plan

**Last Updated:** 2026-05-02

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 issues found in the data-quality loop audit: DB-backed gap retry tracking with DLQ escalation, roll-event suppression of false gap alerts, provider idempotency pre-check, and parity alerting threshold.

**Architecture:** All fixes are confined to 3 existing services (`bar_auditor_agent.py`, `base_provider_agent.py`, `parity_auditor_agent.py`) plus one DB migration. No new agents or topics needed — `topic_gap_fill_dlq` and `topic_alert_requests` already exist in `stream_keys.py`. H-3 (feature backfill) is out of scope: gap-filled bars already flow through `market.bars → intelligence_pipeline_agent`, which processes them live. Historical context accuracy is a known limitation deferred to a dedicated replay design.

**Tech Stack:** Python 3.11+, asyncpg, structlog, Prometheus (`src/observability/metrics.py`), existing Kafka topics (`topic_gap_fill_dlq`, `topic_alert_requests`, `topic_roll_events`).

---

## File Map

| File | Change |
|------|--------|
| `production/migrations/068_gap_retry_tracking.sql` | Create — adds `gap_requests_sent`, `last_request_sent_at`, `last_request_id` columns to `market_data_gaps` |
| `services/bar_auditor_agent.py` | Modify — replace set-based dedup with DB retry tracking; add roll-event consumer + suppression |
| `src/providers/base_provider_agent.py` | Modify — add DB pre-check before IBKR historical fetch |
| `services/parity_auditor_agent.py` | Modify — add match_rate < 0.95 alert to `topic_alert_requests` |
| `tests/unit/test_bar_auditor_agent.py` | Create/modify — tests for retry logic and roll suppression |
| `tests/unit/test_parity_auditor_agent.py` | Create/modify — test for alert threshold |

---

## Task 1: DB Migration — Gap Retry Tracking Columns

**Files:**
- Create: `production/migrations/068_gap_retry_tracking.sql`

- [ ] **Step 1: Write migration**

```sql
-- Migration 068: gap retry tracking for market_data_gaps
--
-- Adds retry state columns so bar_auditor can enforce exponential-backoff
-- re-emission and DLQ escalation after MAX_GAP_RETRIES attempts.
-- Replaces the in-memory _requested_today set (which didn't survive restarts
-- and blocked all retries for 24 h regardless of IBKR fetch outcome).

ALTER TABLE market_data_gaps
    ADD COLUMN IF NOT EXISTS gap_requests_sent     integer   NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_request_sent_at  timestamptz,
    ADD COLUMN IF NOT EXISTS last_request_id       text;

COMMENT ON COLUMN market_data_gaps.gap_requests_sent    IS 'Number of BarGapRequests emitted for this gap';
COMMENT ON COLUMN market_data_gaps.last_request_sent_at IS 'UTC timestamp of most recent BarGapRequest emission';
COMMENT ON COLUMN market_data_gaps.last_request_id      IS 'request_id of most recent BarGapRequest (for DLQ correlation)';
```

- [ ] **Step 2: Apply migration**

```bash
docker exec timescaledb psql -U postgres -d indicagent \
  -f /path/to/production/migrations/068_gap_retry_tracking.sql
```

Expected output: `ALTER TABLE`

- [ ] **Step 3: Verify columns exist**

```bash
docker exec timescaledb psql -U postgres -d indicagent \
  -c "\d market_data_gaps"
```

Expected: `gap_requests_sent`, `last_request_sent_at`, `last_request_id` columns present.

- [ ] **Step 4: Commit**

```bash
git add production/migrations/068_gap_retry_tracking.sql
git commit -m "feat(db): migration 068 — gap retry tracking columns on market_data_gaps"
```

---

## Task 2: Bar Auditor — DB-Backed Retry Logic + DLQ Wiring

Replace `_requested_today: set` with DB-backed retry state. Retry schedule: 1st request immediate, 2nd after 5 min, 3rd after 30 min. After 3 attempts without resolution: publish to DLQ.

**Files:**
- Modify: `services/bar_auditor_agent.py`
- Create: `tests/unit/test_bar_auditor_retry.py`

**Background:** `_upsert_market_data_gap` already writes a row per detected gap. We extend it to also update retry columns. A new `_should_emit_gap_request` method checks the DB to decide whether to emit.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_bar_auditor_retry.py`:

```python
"""Tests for bar_auditor_agent DB-backed retry logic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.bar_auditor_agent import BarAuditorAgent, _RETRY_BACKOFFS_SECS, MAX_GAP_RETRIES


@pytest.fixture
def agent():
    with patch("services.bar_auditor_agent.asyncpg"), \
         patch("services.bar_auditor_agent.KafkaProducerClient"), \
         patch("services.bar_auditor_agent.KafkaConsumerClient"):
        a = BarAuditorAgent.__new__(BarAuditorAgent)
        a.name = "bar_auditor_agent"
        a.settings = MagicMock(database_url="postgresql://x", kafka_bootstrap_servers="x")
        a.env_name = "test"
        a.logger = MagicMock()
        a._gap_fill_dlq_depth = MagicMock()
        a._gap_requests_published = MagicMock()
        a._kafka_producer = AsyncMock()
        a._db_pool = None
        return a


@pytest.mark.asyncio
async def test_should_emit_first_request(agent):
    """First request (gap_requests_sent=0) always emits."""
    row = {"gap_requests_sent": 0, "last_request_sent_at": None, "resolved_at": None}
    assert agent._should_emit_gap_request(row) is True


@pytest.mark.asyncio
async def test_should_not_emit_within_backoff(agent):
    """Second request suppressed if within 5-min backoff window."""
    row = {
        "gap_requests_sent": 1,
        "last_request_sent_at": datetime.now(UTC) - timedelta(seconds=100),
        "resolved_at": None,
    }
    assert agent._should_emit_gap_request(row) is False


@pytest.mark.asyncio
async def test_should_emit_after_backoff_elapsed(agent):
    """Second request emits after 5-min backoff window expires."""
    row = {
        "gap_requests_sent": 1,
        "last_request_sent_at": datetime.now(UTC) - timedelta(seconds=400),
        "resolved_at": None,
    }
    assert agent._should_emit_gap_request(row) is True


@pytest.mark.asyncio
async def test_should_not_emit_after_max_retries(agent):
    """No emission after MAX_GAP_RETRIES attempts — DLQ path instead."""
    row = {
        "gap_requests_sent": MAX_GAP_RETRIES,
        "last_request_sent_at": datetime.now(UTC) - timedelta(hours=2),
        "resolved_at": None,
    }
    assert agent._should_emit_gap_request(row) is False


@pytest.mark.asyncio
async def test_dlq_published_at_max_retries(agent):
    """_publish_gap_fill_dlq is called when gap_requests_sent reaches MAX_GAP_RETRIES."""
    agent._publish_gap_fill_dlq = AsyncMock()
    now = datetime.now(UTC)
    symbol, tf = "ES", "1m"
    start_ts = now - timedelta(hours=2)
    end_ts = now - timedelta(hours=1)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "gap_requests_sent": MAX_GAP_RETRIES,
        "last_request_sent_at": now - timedelta(hours=1),
        "last_request_id": "abc",
        "resolved_at": None,
    })

    result = await agent._check_gap_retry(conn, symbol, tf, start_ts, end_ts)
    assert result is False  # should not emit
    agent._publish_gap_fill_dlq.assert_awaited_once()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_bar_auditor_retry.py -v
```

Expected: `ModuleNotFoundError` or `AttributeError` — `_should_emit_gap_request` not defined yet.

- [ ] **Step 3: Add constants and new methods to `bar_auditor_agent.py`**

Add after the existing constants block (after `_ALL_AUDIT_TFS`):

```python
# Retry schedule: after N-th attempt, wait this many seconds before re-emitting.
# Index 0 = after 1st attempt (5 min), index 1 = after 2nd attempt (30 min).
_RETRY_BACKOFFS_SECS: tuple[int, ...] = (300, 1800)
MAX_GAP_RETRIES: int = 3
```

Remove `_requested_today` and `_requested_today_date` from `__init__` (they are replaced by DB state):

```python
# DELETE these two lines from __init__:
#   self._requested_today: set[tuple[str, str]] = set()
#   self._requested_today_date: str = ""
```

Add two new methods to `BarAuditorAgent` after `_resolve_market_data_gap`:

```python
def _should_emit_gap_request(self, row: dict) -> bool:
    """True if a new BarGapRequest should be emitted for this gap row.

    Enforces exponential-backoff retry schedule defined by _RETRY_BACKOFFS_SECS.
    Returns False (suppress) when MAX_GAP_RETRIES is reached — caller handles DLQ.
    """
    sent = row.get("gap_requests_sent", 0)
    if sent >= MAX_GAP_RETRIES:
        return False
    last_sent_at = row.get("last_request_sent_at")
    if last_sent_at is None:
        return True  # never sent — always emit
    backoff_idx = max(0, sent - 1)
    backoff_secs = _RETRY_BACKOFFS_SECS[min(backoff_idx, len(_RETRY_BACKOFFS_SECS) - 1)]
    elapsed = (datetime.now(UTC) - last_sent_at).total_seconds()
    return elapsed >= backoff_secs

async def _check_gap_retry(
    self,
    conn: asyncpg.Connection,
    symbol: str,
    tf: str,
    start_ts: datetime,
    end_ts: datetime,
) -> bool:
    """Check DB retry state for a gap. Returns True if a new request should be emitted.

    Fetches current retry state from market_data_gaps. If MAX_GAP_RETRIES reached,
    publishes to DLQ instead of emitting. Caller is responsible for updating
    gap_requests_sent + last_request_sent_at via _record_gap_request_sent().
    """
    row = await conn.fetchrow(
        """
        SELECT gap_requests_sent, last_request_sent_at, last_request_id, resolved_at
        FROM market_data_gaps
        WHERE symbol = $1 AND tf = $2 AND gap_start_ts = $3
        """,
        symbol,
        tf,
        start_ts,
    )
    if row is None:
        return True  # gap row not yet written — will be upserted, then emit

    if row["resolved_at"] is not None:
        return False  # already resolved

    if not self._should_emit_gap_request(dict(row)):
        if row["gap_requests_sent"] >= MAX_GAP_RETRIES:
            await self._publish_gap_fill_dlq(
                symbol=symbol,
                tf=tf,
                start_ts=start_ts,
                end_ts=end_ts,
                retry_count=row["gap_requests_sent"],
                error="max_retries_exceeded",
            )
        return False

    return True

async def _record_gap_request_sent(
    self,
    conn: asyncpg.Connection,
    symbol: str,
    tf: str,
    start_ts: datetime,
    request_id: str,
) -> None:
    """Increment gap_requests_sent and update last_request_sent_at on the gap row."""
    await conn.execute(
        """
        UPDATE market_data_gaps
        SET gap_requests_sent    = gap_requests_sent + 1,
            last_request_sent_at = $4,
            last_request_id      = $5
        WHERE symbol = $1 AND tf = $2 AND gap_start_ts = $3
        """,
        symbol,
        tf,
        start_ts,
        datetime.now(UTC),
        request_id,
    )
```

- [ ] **Step 4: Replace gap-emission logic in `_detect_gaps`**

In `_detect_gaps`, replace the `gap_key`/`_requested_today` block with the new retry check. The old code:

```python
gap_key = (sym, w.date_start_utc.isoformat())
if gap_key not in self._requested_today:
    ...
    gaps.append(BarGapRequest(...))
    self._requested_today.add(gap_key)
```

Replace with:

```python
req = BarGapRequest(
    symbol=sym,
    tf="1m",
    start_ts=w.date_start_utc,
    end_ts=w.date_end_utc,
)
should_emit = await self._check_gap_retry(
    conn, sym, "1m", w.date_start_utc, w.date_end_utc
)
if should_emit:
    self.logger.warning(
        "bar_auditor_agent.gap_detected",
        symbol=sym,
        date=str(w.target_date),
        actual=actual,
        expected=w.expected,
        completeness=round(completeness, 3),
        threshold=round(threshold, 3),
    )
    gaps.append(req)
    await self._record_gap_request_sent(
        conn, sym, "1m", w.date_start_utc, req.request_id
    )
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/unit/test_bar_auditor_retry.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 6: Run full unit suite to check for regressions**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short --ignore=tests/unit/config/test_settings_equity.py
```

Expected: same pass count as before these changes.

- [ ] **Step 7: Lint**

```bash
.venv/bin/ruff check services/bar_auditor_agent.py --fix
```

- [ ] **Step 8: Commit**

```bash
git add services/bar_auditor_agent.py tests/unit/test_bar_auditor_retry.py
git commit -m "fix(bar-auditor): DB-backed retry tracking + DLQ escalation replaces set-based dedup

- Replace _requested_today set with market_data_gaps retry columns
- _should_emit_gap_request: enforces 5-min / 30-min backoff schedule
- _check_gap_retry: fetches DB state, publishes to gap_fill_dlq at MAX_GAP_RETRIES
- _record_gap_request_sent: increments counter + last_request_sent_at on emission
- Wires existing _publish_gap_fill_dlq() that was previously never called"
```

---

## Task 3: Bar Auditor — Roll Event Suppression

Subscribe to `topic_roll_events`. For 2 hours after a roll is detected, suppress gap requests on the old contract (end-of-life, no new bars expected).

**Files:**
- Modify: `services/bar_auditor_agent.py`
- Modify: `tests/unit/test_bar_auditor_retry.py` (add roll suppression tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_bar_auditor_retry.py`:

```python
def test_roll_suppressed_within_2h(agent):
    """Gaps on old contract suppressed within 2h of roll detection."""
    agent._post_roll_suppression = {"ESH6": datetime.now(UTC) - timedelta(hours=1)}
    assert agent._is_roll_suppressed("ESH6") is True


def test_roll_suppression_expires_after_2h(agent):
    """Suppression expires after 2h."""
    agent._post_roll_suppression = {"ESH6": datetime.now(UTC) - timedelta(hours=3)}
    assert agent._is_roll_suppressed("ESH6") is False


def test_roll_suppression_cleans_up_stale_entries(agent):
    """_cleanup_roll_suppression removes entries older than 2h."""
    agent._post_roll_suppression = {
        "ESH6": datetime.now(UTC) - timedelta(hours=3),  # stale
        "CLJ6": datetime.now(UTC) - timedelta(hours=1),  # active
    }
    agent._cleanup_roll_suppression()
    assert "ESH6" not in agent._post_roll_suppression
    assert "CLJ6" in agent._post_roll_suppression
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/test_bar_auditor_retry.py::test_roll_suppressed_within_2h -v
```

Expected: `AttributeError: 'BarAuditorAgent' object has no attribute '_post_roll_suppression'`

- [ ] **Step 3: Add roll suppression to `bar_auditor_agent.py`**

Add import at top (alongside existing stream_keys imports):

```python
from src.core.stream_keys import (
    topic_contract_updates,
    topic_gap_fill_dlq,
    topic_gap_requests,
    topic_roll_events,
)
from src.core.schemas.market_events import RollEvent
```

Add to `__init__`:

```python
# old_contract -> roll_detection_ts: suppress gap requests for 2h post-roll
self._post_roll_suppression: dict[str, datetime] = {}
self._roll_consumer: KafkaConsumerClient | None = None
```

Update `topics_consumed` property:

```python
@property
def topics_consumed(self) -> list[str]:
    return [
        topic_contract_updates(self.env_name),
        topic_roll_events(self.env_name),
    ]
```

Add `_roll_consumer` setup inside `_setup()`, after `_contract_consumer` setup:

```python
self._roll_consumer = KafkaConsumerClient(
    topic_roll_events(self.env_name),
    bootstrap_servers=self.settings.kafka_bootstrap_servers,
    group_id="bar_auditor_roll_events_consumer",
    auto_offset_reset="latest",
)
await self._roll_consumer.start()
```

Add teardown for `_roll_consumer` in `_teardown()`:

```python
if self._roll_consumer is not None:
    await self._roll_consumer.stop()
```

Add three new methods:

```python
_POST_ROLL_SUPPRESS_SECS: int = 7200  # 2 hours

def _is_roll_suppressed(self, old_contract: str) -> bool:
    """True if old_contract is within 2h post-roll suppression window."""
    roll_time = self._post_roll_suppression.get(old_contract)
    if roll_time is None:
        return False
    return (datetime.now(UTC) - roll_time).total_seconds() < _POST_ROLL_SUPPRESS_SECS

def _cleanup_roll_suppression(self) -> None:
    """Remove stale suppression entries (> 2h old) to prevent unbounded growth."""
    cutoff = datetime.now(UTC) - timedelta(seconds=_POST_ROLL_SUPPRESS_SECS)
    stale = [k for k, v in self._post_roll_suppression.items() if v < cutoff]
    for k in stale:
        del self._post_roll_suppression[k]

async def _drain_roll_events(self) -> None:
    """Drain topic_roll_events and register old contracts for suppression."""
    if self._roll_consumer is None:
        return
    try:
        records = await self._roll_consumer.getmany(timeout_ms=0, max_records=50)
        for msgs in records.values():
            for _topic, _key, payload in msgs:
                try:
                    event = RollEvent.model_validate(payload)
                    self._post_roll_suppression[event.old_contract] = event.detection_ts
                    self.logger.info(
                        "bar_auditor_agent.roll_suppression_registered",
                        old_contract=event.old_contract,
                        new_contract=event.new_contract,
                    )
                except Exception as exc:
                    self.logger.debug(
                        "bar_auditor_agent.roll_event_parse_error", error=str(exc)
                    )
    except Exception as exc:
        self.logger.debug("bar_auditor_agent.roll_drain_error", error=str(exc))
    self._cleanup_roll_suppression()
```

Call `_drain_roll_events()` in `_run()` alongside `_drain_contract_updates()`:

```python
await self._drain_contract_updates()
await self._drain_roll_events()
```

In `_detect_gaps`, add suppression check inside the per-window loop, right after `sym = w.instrument.symbol`:

```python
# Suppress gap requests on old contracts within 2h of a roll
if self._is_roll_suppressed(sym):
    self.logger.debug(
        "bar_auditor_agent.gap_suppressed_post_roll",
        symbol=sym,
        date=str(w.target_date),
    )
    continue
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_bar_auditor_retry.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Lint**

```bash
.venv/bin/ruff check services/bar_auditor_agent.py --fix
```

- [ ] **Step 6: Commit**

```bash
git add services/bar_auditor_agent.py tests/unit/test_bar_auditor_retry.py
git commit -m "fix(bar-auditor): subscribe to roll events, suppress false gaps 2h post-roll"
```

---

## Task 4: Provider — DB Pre-Check Before IBKR Fetch

Before calling `_adapter.fetch_historical`, check if the bars already exist in `market_data_ohlcv`. Skip the IBKR fetch if they do (idempotency, quota protection).

**Files:**
- Modify: `src/providers/base_provider_agent.py`

- [ ] **Step 1: Read the file to understand `_gap_requests_loop` context**

Confirm `_gap_requests_loop` is at approximately line 304 in `src/providers/base_provider_agent.py`.

- [ ] **Step 2: Add DB pool to provider agent**

In `base_provider_agent.py`, add asyncpg import if not already present:

```python
import asyncpg
```

Add pool creation in the provider's setup/start method (wherever `_kafka_producer` is initialized). Find the `__init__` or `_setup` equivalent and add:

```python
self._db_pool: asyncpg.Pool | None = None
```

In `start()` or wherever the agent initializes connections, add:

```python
self._db_pool = await asyncpg.create_pool(self.settings.database_url, min_size=1, max_size=2)
```

And in teardown/cleanup:

```python
if self._db_pool is not None:
    await self._db_pool.close()
```

- [ ] **Step 3: Add `_gap_already_filled` helper**

Add this method to `BaseProviderAgent`:

```python
async def _gap_already_filled(
    self,
    symbol: str,
    tf: str,
    start_ts: datetime,
    end_ts: datetime,
    expected_bars: int,
) -> bool:
    """Return True if market_data_ohlcv already has >= expected_bars for this window.

    Prevents redundant IBKR historical fetches on restart or duplicate gap requests.
    expected_bars is derived from the window duration; 0 disables the check.
    """
    if self._db_pool is None or expected_bars <= 0:
        return False
    async with self._db_pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM market_data_ohlcv
            WHERE symbol = $1 AND timeframe = $2
              AND timestamp >= $3 AND timestamp < $4
            """,
            symbol,
            tf,
            start_ts,
            end_ts,
        )
    return (count or 0) >= expected_bars
```

- [ ] **Step 4: Wire pre-check into `_gap_requests_loop`**

In `_gap_requests_loop`, after parsing `req = BarGapRequest.model_validate(payload)` and before `async with self._gap_fetch_sem:`, add:

```python
# Compute expected bar count from window duration
window_minutes = int((req.end_ts - req.start_ts).total_seconds() / 60)
expected_bars = window_minutes  # 1 bar per minute for tf="1m"

if await self._gap_already_filled(req.symbol, req.tf, req.start_ts, req.end_ts, expected_bars):
    self.logger.info(
        "provider_agent.gap_request_skipped_already_filled",
        agent=self.name,
        request_id=str(req.request_id),
        symbol=req.symbol,
        expected_bars=expected_bars,
    )
    continue
```

- [ ] **Step 5: Run lint**

```bash
.venv/bin/ruff check src/providers/base_provider_agent.py --fix
```

- [ ] **Step 6: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short --ignore=tests/unit/config/test_settings_equity.py
```

Expected: same pass count — no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/providers/base_provider_agent.py
git commit -m "fix(provider): pre-check market_data_ohlcv before IBKR historical fetch

Skip redundant gap fill fetches when bars already exist in DB.
Prevents quota waste on provider restart or duplicate gap requests."
```

---

## Task 5: Parity Auditor — Match Rate Alert Threshold

Publish to `topic_alert_requests` when `parity_match_rate < 0.95` for any `(symbol, tf)` pair. Uses the existing topic — no new infrastructure.

**Files:**
- Modify: `services/parity_auditor_agent.py`
- Create: `tests/unit/test_parity_auditor_alert.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_parity_auditor_alert.py`:

```python
"""Test parity_match_rate alert threshold in ParityAuditorAgent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.parity_auditor_agent import PARITY_ALERT_THRESHOLD, ParityAuditorAgent


@pytest.fixture
def agent():
    with patch("services.parity_auditor_agent.asyncpg"), \
         patch("services.parity_auditor_agent.AIOKafkaProducer"):
        a = ParityAuditorAgent.__new__(ParityAuditorAgent)
        a.name = "ParityAuditorAgent"
        a.settings = MagicMock(
            env_name="test",
            kafka_bootstrap_servers="localhost:9092",
        )
        a.logger = MagicMock()
        a._producer = AsyncMock()
        return a


@pytest.mark.asyncio
async def test_alert_published_when_match_rate_below_threshold(agent):
    """Alert is published to topic_alert_requests when match_rate < 0.95."""
    agent._producer.send_and_wait = AsyncMock()
    await agent._maybe_alert_parity("ES", "1m", match_rate=0.80)
    agent._producer.send_and_wait.assert_awaited_once()
    call_kwargs = agent._producer.send_and_wait.call_args
    assert b"parity_alert" in call_kwargs[1]["key"]


@pytest.mark.asyncio
async def test_no_alert_when_match_rate_above_threshold(agent):
    """No alert when match_rate >= PARITY_ALERT_THRESHOLD."""
    agent._producer.send_and_wait = AsyncMock()
    await agent._maybe_alert_parity("ES", "1m", match_rate=0.97)
    agent._producer.send_and_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_alert_at_exact_threshold_suppressed(agent):
    """No alert when match_rate == PARITY_ALERT_THRESHOLD (boundary: exclusive)."""
    agent._producer.send_and_wait = AsyncMock()
    await agent._maybe_alert_parity("ES", "1m", match_rate=PARITY_ALERT_THRESHOLD)
    agent._producer.send_and_wait.assert_not_awaited()
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/test_parity_auditor_alert.py -v
```

Expected: `ImportError: cannot import name 'PARITY_ALERT_THRESHOLD'`

- [ ] **Step 3: Add threshold constant and `_maybe_alert_parity` to `parity_auditor_agent.py`**

Add constant after existing module constants:

```python
PARITY_ALERT_THRESHOLD: float = 0.95
```

Add import at top (alongside existing stream_keys imports):

```python
from src.core.stream_keys import topic_alert_requests, topic_system_events
```

Add method to `ParityAuditorAgent`:

```python
async def _maybe_alert_parity(self, symbol: str, tf: str, match_rate: float) -> None:
    """Publish HIGH alert to topic_alert_requests when match_rate < PARITY_ALERT_THRESHOLD."""
    if match_rate >= PARITY_ALERT_THRESHOLD:
        return
    if self._producer is None:
        return
    payload = {
        "severity": "HIGH",
        "source": "parity_auditor",
        "symbol": symbol,
        "tf": tf,
        "match_rate": match_rate,
        "threshold": PARITY_ALERT_THRESHOLD,
        "message": f"Parity match rate {match_rate:.3f} below threshold {PARITY_ALERT_THRESHOLD} for ({symbol}, {tf})",
        "fired_at": datetime.now(UTC).isoformat(),
    }
    topic = topic_alert_requests(self.settings.env_name)
    await self._producer.send_and_wait(
        topic,
        key=f"parity_alert:{symbol}:{tf}".encode(),
        value=json.dumps(payload).encode(),
    )
    self.logger.warning(
        "parity_match_rate_alert",
        symbol=symbol,
        tf=tf,
        match_rate=match_rate,
        threshold=PARITY_ALERT_THRESHOLD,
    )
```

- [ ] **Step 4: Call `_maybe_alert_parity` in `_compare_cycle`**

In `_compare_cycle`, after `PARITY_MATCH_RATE.labels(symbol=sym, tf=tf).set(match_rate)`, add:

```python
await self._maybe_alert_parity(sym, tf, match_rate)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/unit/test_parity_auditor_alert.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 6: Lint**

```bash
.venv/bin/ruff check services/parity_auditor_agent.py --fix
```

- [ ] **Step 7: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short --ignore=tests/unit/config/test_settings_equity.py
```

Expected: same pass count.

- [ ] **Step 8: Commit**

```bash
git add services/parity_auditor_agent.py tests/unit/test_parity_auditor_alert.py
git commit -m "fix(parity-auditor): alert to topic_alert_requests when match_rate < 0.95"
```

---

## Self-Review

**Spec coverage:**
- H-1 (no verification): ✓ Task 2 — DLQ escalation after MAX_GAP_RETRIES; existing `_resolve_market_data_gap` handles resolution when audit sees completeness >= 1.0
- H-2 (set-based dedup): ✓ Task 2 — replaced with DB retry columns + backoff
- H-3 (feature backfill): ✓ Out of scope by design — gap bars already flow through `market.bars → intelligence_pipeline_agent`
- M-2 (roll suppression): ✓ Task 3
- M-3 (parity alerting): ✓ Task 5
- M-4 (provider pre-check): ✓ Task 4
- L-1 (DLQ never called): ✓ Task 2 wires `_publish_gap_fill_dlq()`

**Placeholder scan:** No TBDs or "similar to" references. All methods fully specified.

**Type consistency:** `_check_gap_retry` returns `bool`, called where `should_emit` bool was used. `_maybe_alert_parity` takes `float`, called with `match_rate` float. `_gap_already_filled` returns `bool`. All consistent.
