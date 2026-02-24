# Pipeline Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent the data pipeline from silently dying — fix the TWS daemon reconnect hang and put all 8 services under systemd supervision with auto-restart.

**Architecture:** Two parts: (1) fix `_tick_loop` in the daemon so it cancels itself on disconnect and restarts cleanly; (2) write correct systemd unit files for all 8 services and install them at system level.

**Tech Stack:** Python asyncio, systemd, `/etc/systemd/system/`, `INDICAGENT_ENV=development`

---

## Context

**Current path:** `/home/bg/dev/indicagent`
**Python:** `/home/bg/dev/indicagent/.venv/bin/python`
**User:** `bg` (has sudo)
**Env:** `INDICAGENT_ENV=development` (loaded from `.env` by pydantic-settings — no need to set in unit files)

**The 8 services:**
| Unit name | Script |
|---|---|
| `indicagent-tws` | `production/daemons/high_frequency_tws_daemon.py --client-id 35` |
| `indicagent-indicator` | `services/indicator_service.py` |
| `indicagent-market-analysis` | `services/market_analysis_service.py` |
| `indicagent-signal-generator` | `services/signal_generator_service.py` |
| `indicagent-signal-tracker` | `services/signal_tracker_service.py` |
| `indicagent-ai-narrative` | `services/ai_narrative_service.py` |
| `indicagent-feature-writer` | `services/feature_writer_service.py` |
| `indicagent-api` | `uvicorn src.api.main:app --host 0.0.0.0 --port 8000` |

**Stale service files to delete:** The old `.service` files in `services/` reference `/home/bg/projects/indicagent` and non-existent scripts. They will be replaced.

---

## Task 1: Fix `_tick_loop` reconnect hang

**Files:**
- Modify: `production/daemons/high_frequency_tws_daemon.py`

### What's broken

`_tick_loop` calls `async for tick in self.provider.stream_ticks(symbols)`. Internally `stream_ticks` does `while True: tick = await self._tick_queue.get()`. When TWS drops, the queue stops receiving items and `get()` blocks forever. The main loop sets `connected = False` and tries to reconnect, but the old hung coroutine still owns the event loop — the new `_tick_loop` task is never actually reached.

### The fix

Store the `Future` from `asyncio.run_coroutine_threadsafe` on `self`. Cancel it from `_on_disconnected`. Restart it after successful reconnect.

**Step 1: Add `_tick_task` attribute to `__init__`**

In `__init__`, after `self._reconnect_delay = 1.0`, add:
```python
self._tick_task: "asyncio.Future | None" = None
```

**Step 2: Store future when starting tick loop**

Find the two places `_tick_loop` is scheduled (startup and reconnect). Both currently look like:
```python
asyncio.run_coroutine_threadsafe(self._tick_loop(), self.loop)
```
Change **both** to:
```python
self._tick_task = asyncio.run_coroutine_threadsafe(self._tick_loop(), self.loop)
```

Locations:
- `production/daemons/high_frequency_tws_daemon.py:376` (startup)
- `production/daemons/high_frequency_tws_daemon.py:393` (reconnect block)

**Step 3: Cancel the task in `_on_disconnected`**

Current code at line ~439:
```python
def _on_disconnected(self, *args):
    """IBKR disconnected event handler."""
    logger.warning("TWS disconnected event received")
    self.connected = False
    self.g_connected.set(0)
```

Replace with:
```python
def _on_disconnected(self, *args):
    """IBKR disconnected event handler."""
    logger.warning("TWS disconnected event received")
    self.connected = False
    self.g_connected.set(0)
    if self._tick_task is not None and not self._tick_task.done():
        self._tick_task.cancel()
        logger.info("Tick loop task cancelled for reconnect")
```

**Step 4: Handle CancelledError cleanly in `_tick_loop`**

Current `_tick_loop` (line ~231):
```python
async def _tick_loop(self) -> None:
    """Consume ticks from IBKRProvider and publish to Redis."""
    if not self.provider:
        return
    symbols = [c["symbol"] for c in self.contracts]
    async for tick in self.provider.stream_ticks(symbols):
        if not self.running:
            break
        try:
            ...
        except Exception as e:
            ...
```

Replace with:
```python
async def _tick_loop(self) -> None:
    """Consume ticks from IBKRProvider and publish to Redis."""
    if not self.provider:
        return
    symbols = [c["symbol"] for c in self.contracts]
    try:
        async for tick in self.provider.stream_ticks(symbols):
            if not self.running:
                break
            try:
                stream_name = sk_live_tick(self.env_prefix, tick.symbol)
                if self.async_redis:
                    tick_fields = {k: str(v) for k, v in tick.model_dump(mode="json").items() if v is not None}
                    await self.async_redis.xadd(
                        stream_name,
                        tick_fields,
                        maxlen=10000,
                        approximate=True,
                    )
                tick_data = {"last": tick.price, "volume": tick.size or 0}
                self._update_tick_accumulator(tick.symbol, tick_data, datetime.now())
                self.ticks_processed += 1
                self.m_ticks.inc()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.dropped_ticks += 1
                self.m_dropped.inc()
                self.m_dropped_by_reason.labels(reason="tick_loop_error").inc()
                logger.warning("Tick loop error", error=str(e))
    except asyncio.CancelledError:
        logger.info("Tick loop cancelled (disconnect or shutdown)")
```

**Step 5: Verify reconnect loop restarts `_tick_task`**

Read lines 386–402 of the daemon. The reconnect block calls `connect_tws()` then schedules `_tick_loop`. Confirm the schedule line now assigns `self._tick_task`. It should read:
```python
self._tick_task = asyncio.run_coroutine_threadsafe(self._tick_loop(), self.loop)
```

**Step 6: Manual test**

Kill the running daemon, start it fresh:
```bash
kill $(pgrep -f "high_frequency_tws_daemon") 2>/dev/null
source .venv/bin/activate && PYTHONPATH=/home/bg/dev/indicagent python production/daemons/high_frequency_tws_daemon.py --client-id 35 > /tmp/hf_tws_test.log 2>&1 &
sleep 8 && tail -5 /tmp/hf_tws_test.log
```
Expected: `Connected to TWS via IBKRProvider` + `⚡ Real-time tick processing active...` with no `Tick loop error` lines.

Verify ticks flowing:
```bash
.venv/bin/python -c "
import redis; r = redis.Redis(decode_responses=True)
import time; time.sleep(5)
e = r.xrevrange('development:ticks:ESH6:live', count=1)
print('ESH6 tick:', e[0][1] if e else 'EMPTY')
"
```
Expected: a tick with `price`, `bid`, `ask`.

**Step 7: Commit**
```bash
git add production/daemons/high_frequency_tws_daemon.py
git commit -m "fix(tws): cancel tick loop task on disconnect to enable clean reconnect"
```

---

## Task 2: Write new systemd service files

**Files:**
- Create: `services/indicagent-tws.service`
- Create: `services/indicagent-indicator.service`
- Create: `services/indicagent-market-analysis.service`
- Create: `services/indicagent-signal-generator.service`
- Create: `services/indicagent-signal-tracker.service`
- Create: `services/indicagent-ai-narrative.service`
- Create: `services/indicagent-feature-writer.service`
- Create: `services/indicagent-api.service`
- Delete: `services/indicagent-hf-tws.service` (stale, wrong path)
- Delete: `services/indicagent-enhanced-indicator.service` (stale)
- Delete: `services/indicagent-indicator-processor.service` (stale)
- Delete: `services/indicagent-parallel.service` (stale)
- Delete: `services/indicagent-timeframe-builder.service` (stale)
- Delete: `services/indicagent-backend-api.service` (stale)

### Step 1: Create `services/indicagent-tws.service`

```ini
[Unit]
Description=IndicAgent TWS Daemon — IBKR ticks to Redis
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python production/daemons/high_frequency_tws_daemon.py --client-id 35
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-tws

[Install]
WantedBy=multi-user.target
```

### Step 2: Create `services/indicagent-indicator.service`

```ini
[Unit]
Description=IndicAgent Indicator Service — bars to I1 indicators
After=network-online.target indicagent-tws.service
Wants=indicagent-tws.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/indicator_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-indicator

[Install]
WantedBy=multi-user.target
```

### Step 3: Create `services/indicagent-market-analysis.service`

```ini
[Unit]
Description=IndicAgent Market Analysis Service — I1 to I3-I7 intelligence
After=network-online.target indicagent-indicator.service
Wants=indicagent-indicator.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/market_analysis_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-market-analysis

[Install]
WantedBy=multi-user.target
```

### Step 4: Create `services/indicagent-signal-generator.service`

```ini
[Unit]
Description=IndicAgent Signal Generator Service — I7 signals
After=network-online.target indicagent-market-analysis.service
Wants=indicagent-market-analysis.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/signal_generator_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-signal-generator

[Install]
WantedBy=multi-user.target
```

### Step 5: Create `services/indicagent-signal-tracker.service`

```ini
[Unit]
Description=IndicAgent Signal Tracker Service
After=network-online.target indicagent-signal-generator.service
Wants=indicagent-signal-generator.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/signal_tracker_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-signal-tracker

[Install]
WantedBy=multi-user.target
```

### Step 6: Create `services/indicagent-ai-narrative.service`

```ini
[Unit]
Description=IndicAgent AI Narrative Service — I8 narratives
After=network-online.target indicagent-market-analysis.service
Wants=indicagent-market-analysis.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/ai_narrative_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-ai-narrative

[Install]
WantedBy=multi-user.target
```

### Step 7: Create `services/indicagent-feature-writer.service`

```ini
[Unit]
Description=IndicAgent Feature Writer Service — Redis to TimescaleDB
After=network-online.target indicagent-indicator.service
Wants=indicagent-indicator.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/feature_writer_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-feature-writer

[Install]
WantedBy=multi-user.target
```

### Step 8: Create `services/indicagent-api.service`

```ini
[Unit]
Description=IndicAgent FastAPI — SSE bridge and REST API
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-api

[Install]
WantedBy=multi-user.target
```

### Step 9: Delete stale service files
```bash
rm services/indicagent-hf-tws.service \
   services/indicagent-enhanced-indicator.service \
   services/indicagent-indicator-processor.service \
   services/indicagent-parallel.service \
   services/indicagent-timeframe-builder.service \
   services/indicagent-backend-api.service
```

### Step 10: Commit
```bash
git add services/
git commit -m "feat(ops): replace stale systemd units with correct service files for current pipeline"
```

---

## Task 3: Stop manually-started services and install systemd units

> **Note:** This task requires sudo. Password when prompted.

### Step 1: Stop all currently running services
```bash
kill $(pgrep -f "high_frequency_tws_daemon") 2>/dev/null
kill $(pgrep -f "indicator_service") 2>/dev/null
kill $(pgrep -f "market_analysis_service") 2>/dev/null
kill $(pgrep -f "signal_generator_service") 2>/dev/null
kill $(pgrep -f "signal_tracker_service") 2>/dev/null
kill $(pgrep -f "ai_narrative_service") 2>/dev/null
kill $(pgrep -f "feature_writer_service") 2>/dev/null
kill $(pgrep -f "uvicorn") 2>/dev/null
sleep 2
echo "Remaining processes:"
ps aux | grep -E "tws_daemon|indicator_service|market_analysis|signal_generator|signal_tracker|ai_narrative|feature_writer|uvicorn" | grep -v grep
```
Expected: empty output (all processes stopped).

### Step 2: Copy unit files to systemd
```bash
sudo cp services/indicagent-tws.service \
        services/indicagent-indicator.service \
        services/indicagent-market-analysis.service \
        services/indicagent-signal-generator.service \
        services/indicagent-signal-tracker.service \
        services/indicagent-ai-narrative.service \
        services/indicagent-feature-writer.service \
        services/indicagent-api.service \
        /etc/systemd/system/
```

### Step 3: Reload systemd and enable all units
```bash
sudo systemctl daemon-reload
sudo systemctl enable \
  indicagent-tws \
  indicagent-indicator \
  indicagent-market-analysis \
  indicagent-signal-generator \
  indicagent-signal-tracker \
  indicagent-ai-narrative \
  indicagent-feature-writer \
  indicagent-api
```
Expected: 8 symlink created lines.

### Step 4: Start all services
```bash
sudo systemctl start \
  indicagent-tws \
  indicagent-indicator \
  indicagent-market-analysis \
  indicagent-signal-generator \
  indicagent-signal-tracker \
  indicagent-ai-narrative \
  indicagent-feature-writer \
  indicagent-api
```

### Step 5: Verify all running
```bash
sudo systemctl status indicagent-tws indicagent-indicator indicagent-market-analysis indicagent-signal-generator indicagent-signal-tracker indicagent-ai-narrative indicagent-feature-writer indicagent-api --no-pager | grep -E "●|Active:"
```
Expected: all 8 show `Active: active (running)`.

---

## Task 4: Verify data is flowing end-to-end

### Step 1: Wait 30 seconds for pipeline to warm up
```bash
sleep 30
```

### Step 2: Check ticks and market bars in Redis
```bash
.venv/bin/python -c "
import redis, datetime
r = redis.Redis(decode_responses=True)
checks = [
    ('development:ticks:ESH6:live', 'ESH6 ticks'),
    ('development:market:ESH6:1m', 'ESH6 1m bars'),
    ('development:indicators:ESH6:1m', 'ESH6 indicators'),
    ('development:intelligence:ESH6:5m', 'ESH6 intelligence'),
]
for key, label in checks:
    e = r.xrevrange(key, count=1)
    if e:
        ts = e[0][1].get('timestamp', 'unknown')
        print(f'✓ {label}: {ts}')
    else:
        print(f'✗ {label}: EMPTY')
"
```
Expected: all 4 showing recent timestamps (within last few minutes).

### Step 3: Check SSE endpoint is live
```bash
curl -s "http://localhost:8000/api/sse/events?symbols=ES&timeframe=1m" --max-time 5 | head -10
```
Expected: SSE frames with `event: tick_data` or `event: market_data`.

### Step 4: Check service logs
```bash
journalctl -u indicagent-tws --since "5 minutes ago" --no-pager | tail -5
journalctl -u indicagent-indicator --since "5 minutes ago" --no-pager | tail -5
journalctl -u indicagent-market-analysis --since "5 minutes ago" --no-pager | tail -5
```

### Step 5: Commit verification note
```bash
git add -A
git commit -m "ops: systemd pipeline supervision active — auto-restart on crash and boot"
```

---

## Quick reference after setup

```bash
# Status of all services
sudo systemctl status 'indicagent-*'

# Restart a specific service
sudo systemctl restart indicagent-tws

# View live logs
journalctl -u indicagent-tws -f
journalctl -u indicagent-market-analysis -f

# Stop everything
sudo systemctl stop 'indicagent-*'

# Start everything
sudo systemctl start indicagent-tws indicagent-indicator indicagent-market-analysis indicagent-signal-generator indicagent-signal-tracker indicagent-ai-narrative indicagent-feature-writer indicagent-api
```
