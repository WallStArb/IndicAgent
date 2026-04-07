# Service Watchdog + SSE Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 crash-looping services (watchdog timeouts + OOM), fix SSE signal scorecard event routing, and remove dead Kafka topic subscriptions.

**Architecture:** Three independent problem areas: (1) systemd watchdog misconfiguration causes 60s crash loops; (2) 837K stale pending signals accumulate because signal_tracker never runs long enough to expire them, causing OOM on startup; (3) SSE event name mismatch routes `intelligence.journal` to `intelligence_data` instead of `signal_scorecard`, so the scorecard tab is always empty.

**Tech Stack:** Python asyncio, systemd sd_notify, PostgreSQL/TimescaleDB, Kafka/Redpanda, FastAPI SSE

---

## Files Modified

| File | Change |
|------|--------|
| `/etc/systemd/system/indicagent-ai-narrative.service` | Remove `WatchdogSec=60` + `NotifyAccess=main` |
| `/etc/systemd/system/indicagent-cross-asset.service` | Remove `WatchdogSec=60` + `NotifyAccess=main` |
| `/etc/systemd/system/indicagent-llm-writer.service` | Remove `WatchdogSec=60` + `NotifyAccess=main` |
| `services/signal_tracker_agent.py` | Add `_watchdog_notify()` task in `start()` |
| `src/api/routes/sse.py` | Fix `_event_name_for_topic()` + remove dead topics from `_build_topic_list()` |
| `src/api/main.py` | Remove dead topic subscriptions from lifespan |
| `tests/unit/test_sse_routing.py` | New: event name mapping + topic list tests |

---

## Task 1: Bulk-Expire Stale Pending Signals

**Background:** 837,570 "pending" signals (2026-04-01 to 2026-04-06) never expired because signal_tracker was crash-looping. signal_tracker's `_seed_active_index()` loads all of them → 3.1GB OOM. Must clear this before signal_tracker can start.

**Files:** DB only (no Python changes)

- [ ] **Step 1: Verify count before**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT status, COUNT(*) 
FROM signal_ledger 
WHERE status IN ('pending','active','regime_suppressed') AND exit_at IS NULL
GROUP BY status;"
```
Expected: ~837,570 pending, ~3,304 active.

- [ ] **Step 2: Dry-run — count rows the UPDATE will affect**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT COUNT(*) 
FROM signal_ledger
WHERE status = 'pending' AND exit_at IS NULL
  AND timestamp < NOW() - INTERVAL '6 hours';"
```
Expected: ~837,570 rows.

- [ ] **Step 3: Execute bulk expire**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
UPDATE signal_ledger
SET status     = 'expired',
    exit_at    = NOW(),
    exit_reason= 'bulk_startup_expire',
    outcome    = 'expired'
WHERE status = 'pending' AND exit_at IS NULL
  AND timestamp < NOW() - INTERVAL '6 hours';"
```
Expected: `UPDATE 837570` (approximately).

- [ ] **Step 4: Verify residual is small**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT status, COUNT(*) 
FROM signal_ledger 
WHERE status IN ('pending','active','regime_suppressed') AND exit_at IS NULL
GROUP BY status;"
```
Expected: pending ~0, active ~3,304 (only last 6 hours of real signals remain).

---

## Task 2: Fix signal_tracker_agent Watchdog

**Background:** `signal_tracker_agent.py` inherits `BaseAgent` but overrides `start()` entirely. `BaseAgent.start()` creates the `_watchdog_notify()` task — the override never does. Result: systemd fires watchdog at 60s, kills the process.

**Files:**
- Modify: `services/signal_tracker_agent.py:1002-1052`
- Test: `tests/unit/service_tests/test_signal_tracker_agent.py` (if exists, else skip — no simple mock-free path for this)

- [ ] **Step 1: Read the current start() to understand the structure**

Lines 1002–1052 in `services/signal_tracker_agent.py`. Key: it calls `_register_signal_handlers()` but never creates `_watchdog_notify()` task. The `finally` block only handles `reseed_task` and `lag_task`.

- [ ] **Step 2: Add watchdog task**

In `services/signal_tracker_agent.py`, replace the `start()` method:

```python
async def start(self) -> None:
    """Full agent lifecycle: connect, seed, run, drain."""
    self._register_signal_handlers()
    self.logger.info("Starting SignalTrackerAgent")
    reseed_task: asyncio.Task | None = None
    watchdog_task: asyncio.Task | None = None
    lag_task: asyncio.Task | None = None
    try:
        await self._connect_database()
        start_metrics_server(port=self.config.get("metrics_port", 9115))
        await self._setup_kafka_clients()
        await self._reseed_chandelier_state()
        await self._seed_active_index()
        reseed_task = asyncio.create_task(self._active_index_reseed_loop())
        lag_task = asyncio.create_task(self._report_consumer_lag())
        watchdog_task = asyncio.create_task(self._watchdog_notify())
        tasks = [
            asyncio.create_task(self._process_loop()),
            asyncio.create_task(self._health_monitor_loop()),
        ]
        self.logger.info("SignalTrackerAgent started")
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        self.logger.error("Failed to start", error=str(e))
        raise
    finally:
        for t in (reseed_task, lag_task, watchdog_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        await self.stop()
```

- [ ] **Step 3: Verify no other watchdog-related imports are needed**

```bash
grep -n "sdnotify\|WATCHDOG_USEC\|NOTIFY_SOCKET" services/signal_tracker_agent.py
```
Expected: no matches (BaseAgent handles all of this in `_watchdog_notify()`).

- [ ] **Step 4: Lint**

```bash
cd /home/bg/dev/indicagent && .venv/bin/ruff check services/signal_tracker_agent.py --fix
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add services/signal_tracker_agent.py
git commit -m "fix(signal-tracker): add _watchdog_notify() task to overridden start()"
```

---

## Task 3: Remove WatchdogSec from 3 Non-BaseAgent Unit Files

**Background:** `ai_narrative_service`, `cross_asset_service`, `llm_writer_service` are plain service classes — they do not inherit BaseAgent and never call `sd_notify("WATCHDOG=1")`. Their unit files have `WatchdogSec=60` + `NotifyAccess=main`, which kills them every 60s.

**Fix:** Remove the watchdog directives from the unit files. These services don't implement the watchdog protocol; removing the directives lets them run indefinitely.

**Files:**
- Modify: `/etc/systemd/system/indicagent-ai-narrative.service`
- Modify: `/etc/systemd/system/indicagent-cross-asset.service`
- Modify: `/etc/systemd/system/indicagent-llm-writer.service`

- [ ] **Step 1: Write corrected unit files to /tmp (use sudo to install)**

```bash
# ai-narrative
sudo sed -i '/^WatchdogSec=/d; /^NotifyAccess=/d' \
    /etc/systemd/system/indicagent-ai-narrative.service

# cross-asset
sudo sed -i '/^WatchdogSec=/d; /^NotifyAccess=/d' \
    /etc/systemd/system/indicagent-cross-asset.service

# llm-writer
sudo sed -i '/^WatchdogSec=/d; /^NotifyAccess=/d' \
    /etc/systemd/system/indicagent-llm-writer.service
```

- [ ] **Step 2: Verify the lines are gone**

```bash
grep -n "WatchdogSec\|NotifyAccess" \
    /etc/systemd/system/indicagent-ai-narrative.service \
    /etc/systemd/system/indicagent-cross-asset.service \
    /etc/systemd/system/indicagent-llm-writer.service
```
Expected: no output.

- [ ] **Step 3: Also update production/systemd reference templates**

```bash
grep -rn "WatchdogSec\|NotifyAccess" production/systemd/ | grep -v "intelligence-pipeline\|signal-tracker\|bar-"
```
Update any matching reference templates to match. These are not installed but should stay consistent.

- [ ] **Step 4: Reload systemd**

```bash
sudo systemctl daemon-reload
```

---

## Task 4: Fix SSE Event Name for intelligence.journal

**Background:** `_event_name_for_topic()` in `sse.py` has a generic `startswith("intelligence")` catch-all that maps `intelligence.journal` → `intelligence_data`. The SSE broadcaster transforms `intelligence.journal` payloads into scorecard shape via `_extract_signal_scorecard_payload()`, but the wrong event name means the dashboard's `signal_scorecard` listener never fires.

**Files:**
- Modify: `src/api/routes/sse.py` — `_event_name_for_topic()` function

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sse_routing.py`:

```python
"""Tests for SSE event name routing and topic list construction."""
import pytest
from unittest.mock import patch

# Patch settings before import to avoid DB/kafka connections
with patch("src.api.utils.get_settings") as _mock:
    from src.api.routes.sse import _event_name_for_topic, _build_topic_list


class TestEventNameForTopic:
    def test_intelligence_journal_maps_to_signal_scorecard(self):
        assert _event_name_for_topic("intelligence.journal") == "signal_scorecard"

    def test_intelligence_journal_with_env_prefix(self):
        assert _event_name_for_topic("dev.intelligence.journal") == "signal_scorecard"

    def test_intelligence_maps_to_intelligence_data(self):
        assert _event_name_for_topic("intelligence") == "intelligence_data"

    def test_intelligence_i8_maps_to_narrative_data(self):
        assert _event_name_for_topic("intelligence.i8") == "narrative_data"

    def test_signals_aggregated_maps_to_signal_data(self):
        assert _event_name_for_topic("signals.aggregated") == "signal_data"

    def test_market_bars_maps_to_market_data(self):
        assert _event_name_for_topic("market.bars") == "market_data"

    def test_market_bars_htf_maps_to_market_data(self):
        assert _event_name_for_topic("market.bars.htf") == "market_data"

    def test_narratives_maps_to_narrative_data(self):
        assert _event_name_for_topic("narratives") == "narrative_data"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/bg/dev/indicagent && .venv/bin/pytest tests/unit/test_sse_routing.py::TestEventNameForTopic::test_intelligence_journal_maps_to_signal_scorecard -v
```
Expected: FAIL — `assert 'intelligence_data' == 'signal_scorecard'`

- [ ] **Step 3: Fix `_event_name_for_topic()` in `src/api/routes/sse.py`**

Find the block starting at line ~207 and add the `intelligence.journal` check BEFORE the generic `intelligence` check:

```python
@functools.lru_cache(maxsize=256)
def _event_name_for_topic(topic: str) -> str:
    """Map a Kafka topic name (period-separated) to an SSE event name.

    Strips optional env prefix (e.g. 'dev.') before matching.
    """
    known_prefixes = {
        "market.ticks",
        "market.bars",
        "indicators",
        "intelligence.record",
        "intelligence.journal",
        "intelligence.i7",
        "intelligence.i8",
        "intelligence",
        "signals.aggregated",
        "signals",
        "narratives.group",
        "narratives",
        "llm.calls",
        "llm.outcomes",
        "system.events",
    }
    dot_idx = topic.find(".")
    if dot_idx > 0:
        rest = topic[dot_idx + 1 :]
        matches = any(
            rest == p or rest.startswith(p + ".") or rest.startswith(p) for p in known_prefixes
        )
        if matches:
            candidate = rest
        else:
            candidate = topic
    else:
        candidate = topic

    if candidate == "market.ticks" or candidate.startswith("market.ticks"):
        return "tick_data"
    if candidate == "market.bars" or candidate.startswith("market.bars"):
        return "market_data"
    if candidate == "indicators" or candidate.startswith("indicators"):
        return "indicator_data"
    # intelligence.journal — BarIntelligenceRecord transformed to scorecard shape by broadcaster
    if candidate == "intelligence.journal" or candidate.startswith("intelligence.journal"):
        return "signal_scorecard"
    if candidate == "intelligence.record" or candidate.startswith("intelligence.record"):
        return "signal_scorecard"
    if candidate == "intelligence.i8" or candidate.startswith("intelligence.i8"):
        return "narrative_data"
    if candidate == "intelligence" or candidate.startswith("intelligence"):
        return "intelligence_data"
    if candidate == "signals.aggregated" or candidate.startswith("signals.aggregated"):
        return "signal_data"
    if candidate == "signals" or candidate.startswith("signals"):
        return "signal_data"
    if candidate == "narratives.group" or candidate.startswith("narratives.group"):
        return "narrative_data"
    if candidate == "narratives" or candidate.startswith("narratives"):
        return "narrative_data"
    return "message"
```

Note: must clear the lru_cache before re-running tests (`_event_name_for_topic.cache_clear()`).

- [ ] **Step 4: Run all SSE routing tests**

```bash
.venv/bin/pytest tests/unit/test_sse_routing.py -v
```
Expected: all PASS.

---

## Task 5: Remove Dead Topic Subscriptions from SSE + API

**Background:** `indicators` (no active producer — only archived services published to it) and `market.ticks` (no IBKR tick publisher) both have offset=0. SSE and API still subscribe to them, wasting consumer group memberships and Kafka polling.

**Files:**
- Modify: `src/api/routes/sse.py` — `_build_topic_list()`
- Modify: `src/api/main.py` — lifespan consumer

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_sse_routing.py`:

```python
class TestBuildTopicList:
    def test_no_dead_indicators_topic(self):
        """indicators topic has no active producer — must not be in SSE subscription list."""
        from unittest.mock import MagicMock
        mock_settings = MagicMock()
        mock_settings.env_name = ""
        with patch("src.api.routes.sse._get_settings", return_value=mock_settings):
            topics = _build_topic_list(["ES"], "1m")
        assert "indicators" not in topics, "indicators topic has no active producer"

    def test_no_dead_market_ticks_topic(self):
        """market.ticks has no active publisher in SSE path — must not be in list."""
        from unittest.mock import MagicMock
        mock_settings = MagicMock()
        mock_settings.env_name = ""
        with patch("src.api.routes.sse._get_settings", return_value=mock_settings):
            topics = _build_topic_list(["ES"], "1m")
        assert "market.ticks" not in topics, "market.ticks has no publisher for SSE"

    def test_active_topics_present(self):
        """Core active topics must be in SSE subscription list."""
        from unittest.mock import MagicMock
        mock_settings = MagicMock()
        mock_settings.env_name = ""
        with patch("src.api.routes.sse._get_settings", return_value=mock_settings):
            topics = _build_topic_list(["ES"], "1m")
        for expected in [
            "market.bars",
            "market.bars.htf",
            "intelligence",
            "intelligence.journal",
            "intelligence.i8",
            "signals.aggregated",
            "narratives",
            "narratives.group",
        ]:
            assert expected in topics, f"{expected} missing from topic list"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_sse_routing.py::TestBuildTopicList -v
```
Expected: FAIL on `test_no_dead_indicators_topic` and `test_no_dead_market_ticks_topic`.

- [ ] **Step 3: Remove dead topics from `_build_topic_list()` in `sse.py`**

Find `_build_topic_list()` (around line 155) and remove the two dead lines:

```python
def _build_topic_list(symbols: list[str], timeframe: str) -> list[str]:
    settings = _get_settings()
    env_name = settings.env_name or ""
    topics: list[str] = []
    # market.ticks removed — no active publisher; intelligence_pipeline caches it internally
    topics.append(topic_market_bars(env_name))
    topics.append(topic_market_bars_htf(env_name))
    # indicators removed — only archived services published to this topic
    topics.append(topic_intelligence(env_name))
    topics.append(topic_intelligence_journal(env_name))
    topics.append(topic_intelligence_i8(env_name))
    topics.append(topic_signals_aggregated(env_name))
    topics.append(topic_narratives(env_name))
    topics.append(topic_narratives_group(env_name))
    seen: set[str] = set()
    result: list[str] = []
    for t in topics:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result
```

Also remove the unused `topic_indicators` and `topic_market_ticks` imports at the top of `sse.py` (leave them in `main.py` step below).

- [ ] **Step 4: Remove dead topics from `main.py` lifespan**

In `src/api/main.py`, find the lifespan KafkaConsumerClient instantiation and remove `topic_indicators` and `topic_market_ticks`:

```python
_sse_consumer = KafkaConsumerClient(
    topic_market_bars(env_name),
    topic_market_bars_htf(env_name),
    topic_intelligence(env_name),
    topic_intelligence_journal(env_name),
    topic_intelligence_i8(env_name),
    topic_signals_aggregated(env_name),
    topic_narratives(env_name),
    topic_narratives_group(env_name),
    bootstrap_servers=kafka_bootstrap,
    group_id="sse_broadcaster",
    auto_offset_reset="latest",
)
```

Remove the now-unused imports from `main.py`:
```python
# Remove these two lines from the import block:
#   topic_indicators,
#   topic_market_ticks,
```

- [ ] **Step 5: Run all SSE tests**

```bash
.venv/bin/pytest tests/unit/test_sse_routing.py -v
```
Expected: all PASS.

- [ ] **Step 6: Lint both files**

```bash
.venv/bin/ruff check src/api/routes/sse.py src/api/main.py --fix
```
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/api/routes/sse.py src/api/main.py tests/unit/test_sse_routing.py
git commit -m "fix(sse): intelligence.journal→signal_scorecard; remove dead indicators+ticks topic subscriptions"
```

---

## Task 6: Restart All Fixed Services

- [ ] **Step 1: Reload systemd and restart the 4 crash-looping services**

```bash
sudo systemctl daemon-reload
sudo systemctl restart \
    indicagent-signal-tracker \
    indicagent-ai-narrative \
    indicagent-cross-asset \
    indicagent-llm-writer
```

- [ ] **Step 2: Restart API to pick up SSE routing fix**

```bash
sudo systemctl restart indicagent-api
```

- [ ] **Step 3: Verify all 4 services are running (not activating/crashed)**

Wait 90 seconds (past the 60s watchdog window), then:

```bash
systemctl status indicagent-signal-tracker indicagent-ai-narrative indicagent-cross-asset indicagent-llm-writer --no-pager | grep -E "Active:|Main PID:"
```
Expected: all show `active (running)`.

- [ ] **Step 4: Verify no more watchdog kills in journal**

```bash
journalctl -u indicagent-signal-tracker -u indicagent-ai-narrative -u indicagent-cross-asset -u indicagent-llm-writer --since "3 minutes ago" --no-pager | grep -i "watchdog\|failed\|ABRT"
```
Expected: no output.

- [ ] **Step 5: Verify consumer lag is draining for signal_tracker**

```bash
docker exec redpanda rpk group describe signal_lifecycle 2>/dev/null | grep -E "TOTAL-LAG|LAG"
```
Expected: LAG is non-zero but decreasing (service consuming).

- [ ] **Step 6: Verify SSE signal scorecard reaches dashboard**

```bash
# Quick smoke test: consume 5 messages from intelligence.journal and check payload shape
docker exec redpanda rpk topic consume intelligence.journal --num 2 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        msg = json.loads(line)
        val = json.loads(msg.get('value','{}'))
        print('keys:', list(val.keys())[:5])
    except: pass
"
```
Expected: keys include `ranked_signals` and `intelligence` — confirms broadcaster has data to transform.

---

## Verification Checklist

- [ ] `systemctl list-units --all | grep indicagent` — 0 services in `activating` state
- [ ] `journalctl -u indicagent-signal-tracker --since "5 min ago" | grep -c "watchdog"` → 0
- [ ] `docker exec redpanda rpk group describe signal_lifecycle | grep TOTAL-LAG` → number is decreasing
- [ ] `docker exec redpanda rpk group describe sse_broadcaster | grep indicators` → no `indicators` or `market.ticks` row
- [ ] Dashboard signal scorecard tab shows ranked signals (requires live market or replay data)
