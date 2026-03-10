# Phase 5: Live Pipeline - Research

**Researched:** 2026-02-24
**Domain:** Service orchestration, TWS connectivity, Redis stream pipeline validation
**Confidence:** HIGH

## Summary

All 8 services are already installed as systemd units (installed Feb 23) and all process imports succeed cleanly. The pipeline is functionally intact: every service starts, connects to Redis and PostgreSQL, and its in-memory and stream infrastructure is correctly wired. However, the intelligence stream (`intelligence:SYMBOL:TF`) is not producing messages because two conditions are unmet: (1) the TWS daemon has lost its IBKR connection and is stuck in a false-connected state, blocking all live market data, and (2) the in-memory bar history has not accumulated enough bars to trigger market_analysis_service calculations. During RTH with a live TWS connection, both conditions resolve naturally within ~20 minutes.

Phase 5 requires fixing the TWS reconnection bug, correcting two configuration bugs (feature_writer hardcoded symbols; market_analysis consuming 5m/15m/1h with zero source data), then verifying the full pipeline during an RTH session. The core services, schemas, and routing are all correct — this is a bring-up and stabilization phase, not a build phase.

**Primary recommendation:** Fix the TWS connection bug first (the root blocker), then run the pipeline during RTH and verify each tier's stream shows live data. No new architecture is needed.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| systemd | native | Service supervision | All 8 units installed; Restart=always configured |
| redis.asyncio | 5.x | Async Redis streams | All services use xreadgroup consumer groups |
| ib_insync | via IBKRProvider | TWS data feed | Isolated in `src/providers/ibkr.py` |
| asyncpg | via DatabaseManager | PostgreSQL connection pool | Feature writer, market analysis use it |
| structlog | — | Structured logging | All services use it; logs to `logs/*.log` |
| prometheus_client | — | Metrics exposition | Ports 9109, 9112–9116 already assigned |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pandas 3.0.1 | installed | DataFrame ops in plugins | Already used; note rolling() API change |
| pydantic v2 | installed | IntelligenceEvent schema | Already used in all stream consumers |

## Architecture Patterns

### Current Service Topology (all running)

```
IBKR TWS (10.0.0.33:7497)
  ↓ (disconnected — root blocker)
high_frequency_tws_daemon.py
  → development:ticks:SYMBOL:live  (10k+ messages, stale since Feb 23 19:59 UTC)
  → development:market:SYMBOL:1m   (2007 msgs for ESH6, up to Feb 24 10:00)

indicator_service.py  (reads market:SYMBOL:1m via consumer group)
  → development:indicators:SYMBOL:1m  (69 msgs for ESH6, maxlen=1000 trims old)

market_analysis_service.py  (reads indicators:SYMBOL:TF via consumer group)
  bars_processed=1040, calculations=0  ← stuck below min_history_bars=120
  → development:intelligence:SYMBOL:TF  (0 messages — NOT flowing yet)

signal_generator_service.py  (reads intelligence:SYMBOL:TF)
  bars_processed=0, signals_generated=0  ← waiting for intelligence events

feature_writer_service.py  (reads intelligence:SYMBOL:TF via separate consumer group)
  events_consumed=0  ← waiting + has wrong symbols in config

ai_narrative_service.py  (reads signals:SYMBOL:TF:aggregated)
  waiting for signal events

signal_tracker_service.py  (reads market:SYMBOL:1m directly)
  working correctly, evaluating lifecycle on incoming bars

FastAPI / uvicorn  (SSE + REST)
  running, accepting connections, returning 200 OK for SSE endpoints
```

### Pattern: Consumer Group Per Service Per Stream

Each service creates a uniquely-named consumer group (timestamp-based) at startup:
```python
self.consumer_group = f"market_analysis_{int(time.time())}"
```

This means every restart creates a new group starting from message ID `"0"` (oldest available). Old groups accumulate in Redis as tombstones — harmless but noisy. On Phase 5 verification, multiple stale groups will be visible per stream; this is expected.

### Pattern: min_history_bars Warm-Up Gate

Both `indicator_service` and `market_analysis_service` require 120 bars in their in-memory `deque(maxlen=200)` before publishing output. On cold start this means:
- **During RTH (ES/NQ/etc):** ~400+ bars/hour → gate clears in ~18 minutes
- **Overnight:** ~3 bars/hour → never clears for current overnight session
- **After market_analysis restart:** it re-reads all available indicator stream messages (but stream is trimmed to maxlen=1000), fills history, then publishes

This is the expected behavior. The pipeline will NOT produce intelligence events until TWS reconnects and RTH bars flow at sufficient rate.

### Pattern: feature_writer Consumer Group (Separate from signal_generator)

`feature_writer_service` uses the static constant `CONSUMER_GROUP = "feature_writer:persist"` — unlike other services that use timestamp-based group names. This means:
- It always connects to the same group across restarts (correct)
- But the group must exist on the intelligence stream for each symbol/TF

## Bugs Found — Must Fix in Phase 5

### Bug 1: TWS Daemon False-Connected State (ROOT BLOCKER)

**What goes wrong:** TWS connection drops (e.g., overnight TWS reset at 10:00 ET / 15:00 UTC) without firing the `_on_disconnected` callback. `self.connected` remains `True`. The reconnect logic at line 394–408 never runs because it checks `if not self.connected`. All `poll_1m_bars()` calls log "Not connected" warnings but no reconnection occurs.

**Evidence:** TWS daemon has been running for 906 minutes (as of research time) with bars_processed=165831 frozen, tick age 19+ hours. All 23 symbols report "Not connected" warnings every 60 seconds.

**Location:** `/home/bg/dev/indicagent/production/daemons/high_frequency_tws_daemon.py`, main loop around line 395.

**Fix:** Add a secondary check in the main loop using `provider.is_connected()`. If `self.connected == True` but `self.provider.is_connected() == False`, set `self.connected = False` to trigger the existing reconnect path:
```python
# In the main loop, before the poll_1m_bars call:
if self.connected and self.provider and not self.provider.is_connected():
    logger.warning("Provider reports disconnected — triggering reconnect")
    self.connected = False
    self._on_disconnected()
```

### Bug 2: feature_writer Hardcoded Stale Symbols

**What goes wrong:** `feature_writer_service._load_config()` hardcodes symbols `['ESH6', 'NQH6', 'RTYH6', 'CLK6', 'GCM6', 'NGK6']`. CLK6 and GCM6 are wrong (April expiry for CL is J6, not K6; GC April is J6 not M6). The service subscribes to `intelligence:CLK6:TF` streams which will never receive messages, and misses 17 of 23 active contracts.

**Location:** `/home/bg/dev/indicagent/services/feature_writer_service.py`, line 179.

**Fix:** Replace hardcoded list with `get_active_contracts()` from `src.config.settings`, same as `market_analysis_service`:
```python
from src.config.settings import Settings, get_active_contracts
# ...
"symbols": get_active_contracts(Settings()),
```

### Bug 3: qualify_instrument Errors on 5 Contracts

**What goes wrong:** On TWS reconnect, `_qualify_all_instruments()` is called. Four symbols fail with "Unknown symbol 'X'. Call qualify_instrument() first." — SR1H6, 6EH6, 6JH6, BTCH6. BZJ6 and NGJ6 also had no tick data historically. These contracts never produce market bars.

**Evidence:** Logs show consistent "Unknown symbol" errors for these contracts since initial startup.

**Investigation needed:** These are SOFR, FX, and crypto futures — they may require different contract qualification parameters (e.g., `secType`, `currency`, `multiplier`) that are not matching IBKR's expected format. The `Instrument` model in `settings.py` needs `qualify_instrument()` verification against live IBKR for these 5 contracts.

**Impact:** Reduced to 17/23 symbols flowing through the pipeline. Not blocking for Phase 5 success criteria (ESH6 is the test symbol), but reduces coverage.

### Non-Blocking Issues (log noise, not blocking)

- **VWAP plugin "Cannot mix tz-aware with tz-naive" warnings:** Pandas 3.0.1 is stricter about timezone mixing. Plugin uses `pd.to_datetime(df['timestamp'])` then `.dt.date`. This fails in some bar history scenarios. Plugin skips gracefully (returns `{}`). Non-fatal.

- **Stochastic "No numeric types to aggregate" warnings:** Pandas 3.0.1 `rolling().min()` on non-numeric columns raises this error. Plugin handles it with exception catch. Non-fatal.

- **CMF "invalid value encountered in divide" RuntimeWarnings:** numpy division by zero warnings suppressed by `np.where` guard. Non-fatal.

- **Stale consumer groups:** Multiple timestamp-based groups accumulate per stream on restart. Harmless; can clean up manually if desired.

## Phase 5 Plan — What Must Happen

### Plan 05-01: Audit and Fix Services

**Scope:** Fix the three bugs above, then verify each service starts cleanly.

1. Fix TWS daemon reconnection bug (add `provider.is_connected()` check in main loop)
2. Fix feature_writer symbol config (use `get_active_contracts()`)
3. Verify 5m/15m/1h timeframe data source — the indicator_service and market_analysis_service both configure `["1m", "5m", "15m", "1h", "4h", "1d"]` timeframes but TWS daemon only publishes 1m bars. The `timeframes_builder_service.py` exists but has NO systemd unit file and is NOT running. Either:
   - Start the timeframes_builder_service (needs a systemd unit, needs symbol update to H6 contracts)
   - OR accept that only 1m intelligence events flow for now (defer 5m/15m for Phase 6)
4. Reload systemd units if .service files changed: `sudo systemctl daemon-reload`
5. Restart TWS daemon to trigger fresh reconnect: `sudo systemctl restart indicagent-tws`

### Plan 05-02: End-to-End Pipeline Smoke Test (RTH Required)

**Must run during RTH (Mon-Fri 09:30–16:00 ET = 14:30–21:00 UTC)**

Verification sequence:
1. Confirm TWS connected: latest `development:ticks:ESH6:live` message age < 5 minutes
2. Confirm indicator flow: `development:indicators:ESH6:1m` gaining messages at ~1/min
3. Wait for market_analysis to accumulate 120 bars (~20 min after RTH open)
4. Confirm intelligence flow: `development:intelligence:ESH6:1m` has messages
5. Confirm signal flow: `development:signals:ESH6:1m:aggregated` has messages
6. Confirm feature_writer persisting: `SELECT count(*) FROM intelligence_features WHERE ts > now() - interval '30 min'` count growing
7. Confirm narrative flow: `development:narratives:ESH6:1m` has messages (Ollama must be running)

**Redis inspection commands:**
```bash
# Check stream activity (requires .venv/bin/python):
.venv/bin/python -c "
import redis, datetime
r = redis.Redis(decode_responses=True)
streams = [
    'development:ticks:ESH6:live',
    'development:indicators:ESH6:1m',
    'development:intelligence:ESH6:1m',
    'development:signals:ESH6:1m:aggregated',
    'development:narratives:ESH6:1m',
]
for s in streams:
    msgs = r.xrevrange(s, count=1)
    if msgs:
        mid, _ = msgs[0]
        age = datetime.datetime.utcnow() - datetime.datetime.fromtimestamp(int(mid.split('-')[0])/1000)
        print(f'{s}: {r.xlen(s)} msgs, age={age.total_seconds():.0f}s')
    else:
        print(f'{s}: EMPTY')
"
```

### Plan 05-03: Stability Verification (30+ Minutes)

- Run all 8 services for 30+ minutes during RTH without crash-loops
- Check journalctl for each service for unhandled exceptions
- Check Prometheus metrics endpoints respond:
  ```bash
  curl -s http://localhost:9109/metrics | head -5  # indicator
  curl -s http://localhost:9112/metrics | head -5  # signal-generator
  curl -s http://localhost:9113/metrics | head -5  # ai-narrative
  curl -s http://localhost:9114/metrics | head -5  # market-analysis
  curl -s http://localhost:9115/metrics | head -5  # signal-tracker
  curl -s http://localhost:9116/metrics | head -5  # feature-writer
  ```
- Check no service has restarted unexpectedly:
  ```bash
  journalctl -u indicagent-market-analysis --since "2 hours ago" | grep "Started\|Failed"
  ```
- Check feature_writer row insertion:
  ```bash
  psql -U postgres -d indicagent -c "SELECT count(*), max(ts) FROM intelligence_features WHERE source='live';"
  ```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Service process management | Custom daemon manager | systemd | Already installed and configured |
| Redis stream retry/ack | Custom retry logic | xreadgroup + XACK pattern | Already in all services |
| Consumer group fanout | Custom pub/sub | Redis XREADGROUP with separate groups | feature_writer + signal_generator already use separate groups |
| IBKR reconnection | New connection manager | Fix the self.connected check bug | Provider already has is_connected() |
| Higher-TF aggregation | New aggregation service | timeframes_builder_service.py already exists | Add systemd unit + update symbols |

## Common Pitfalls

### Pitfall 1: Testing Outside RTH
**What goes wrong:** Overnight bar rate (~3/hr) never fills the 120-bar minimum history. Pipeline appears broken when it's actually waiting for market activity.
**How to avoid:** All end-to-end smoke tests MUST run during RTH (Mon–Fri, 09:30–16:00 ET). Plan 05-02 should explicitly note this prerequisite.
**Warning signs:** `calculations=0` in market_analysis logs, empty intelligence streams.

### Pitfall 2: False-Connected TWS State
**What goes wrong:** TWS daemon reports "Not connected" in poll_1m_bars() but systemd shows the service as `active (running)`. No automatic recovery.
**How to avoid:** Add `provider.is_connected()` check as described in Bug 1. After fix, a restart should be enough to reconnect.
**Warning signs:** All 23 symbols show "Not connected" in TWS daemon logs. Latest tick age > 30 minutes. `bars_processed` counter frozen in health check.

### Pitfall 3: feature_writer Missing Intelligence Events
**What goes wrong:** Even when intelligence events flow, feature_writer subscribes to wrong streams (CLK6, GCM6 etc.) and misses all messages.
**How to avoid:** Fix Bug 2 before running smoke tests.
**Warning signs:** `events_consumed=0` in feature_writer health log despite intelligence stream having messages.

### Pitfall 4: Multiple Consumer Groups on Same Stream
**What goes wrong:** Each service restart creates a new timestamp-named consumer group. Old groups don't auto-delete. After many restarts, `XINFO GROUPS development:indicators:ESH6:1m` shows dozens of groups.
**How to avoid:** This is expected behavior and harmless for correctness. If it becomes a problem, clean up with `XGROUP DESTROY`. Don't suppress the group creation.

### Pitfall 5: systemd Unit Files Out of Sync
**What goes wrong:** `.service` files in `services/` repo directory but `/etc/systemd/system/` has older versions. `systemctl restart` uses the installed (old) version.
**How to avoid:** After any `.service` file change, run `sudo cp services/indicagent-*.service /etc/systemd/system/ && sudo systemctl daemon-reload`.
**Current state:** All 8 installed units MATCH repo versions (verified Feb 24, 2026).

### Pitfall 6: Ollama Required for ai-narrative
**What goes wrong:** ai_narrative_service needs Ollama running with qwen3:8b. If Ollama is stopped, the service logs errors but doesn't crash.
**How to avoid:** Verify Ollama is running before smoke test: `curl -s http://localhost:11434/api/tags | python3 -m json.tool | grep name`.
**Known gotcha:** Qwen3 uses thinking mode by default — `content` may be empty if `num_predict < 500`. Use `/no_think` prefix in prompts or ensure `num_predict >= 500`.

## Code Examples

### Check All Service Health in One Command
```bash
.venv/bin/python -c "
import redis, datetime
r = redis.Redis(decode_responses=True)
streams = {
    'ticks:ESH6:live': 'TWS → Redis',
    'indicators:ESH6:1m': 'I1 output',
    'intelligence:ESH6:1m': 'I3-I6 output',
    'signals:ESH6:1m:aggregated': 'I7 output',
    'narratives:ESH6:1m': 'I8 output',
}
print('Stream health:')
for s, label in streams.items():
    key = f'development:{s}'
    cnt = r.xlen(key)
    msgs = r.xrevrange(key, count=1)
    if msgs:
        mid, _ = msgs[0]
        ts = datetime.datetime.fromtimestamp(int(mid.split('-')[0])/1000)
        age = (datetime.datetime.utcnow() - ts).total_seconds()
        print(f'  {label}: {cnt} msgs, latest {age:.0f}s ago')
    else:
        print(f'  {label}: EMPTY')
"
```

### Verify feature_writer Consumer Groups Exist
```bash
.venv/bin/python -c "
import redis
r = redis.Redis(decode_responses=True)
key = 'development:intelligence:ESH6:1m'
try:
    groups = r.xinfo_groups(key)
    for g in groups:
        print(f'{g[\"name\"]}: pending={g[\"pending\"]}')
except:
    print('Stream does not exist yet')
"
```

### Check DB Row Count Growing Live
```bash
psql -U postgres -d indicagent -c "
SELECT source, count(*), max(ts)
FROM intelligence_features
GROUP BY source
ORDER BY max(ts) DESC;
"
```

### Verify Metrics Endpoints
```bash
for port in 9109 9112 9113 9114 9115 9116; do
  status=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/metrics)
  echo "Port $port: HTTP $status"
done
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Multiple indicator services per TF | Single indicator_service.py reads all TFs from market: stream | Eliminates triple I1 computation |
| Flat string k/v in intelligence: stream | Single `{"event": "<IntelligenceEvent JSON>"}` field | Type-safe, versioned, schema-validated |
| intelligence_processor_service.py | Deleted; market_analysis_service.py is canonical | Eliminates redundant service |
| Timestamp-based consumer group names | Static `"feature_writer:persist"` for feature_writer | Ensures correct stream position across restarts |

**Deprecated/outdated:**
- `intelligence_processor_service.py`: Deleted in Phase 1 (01-03). Do not resurrect.
- `timeframes_builder_service.py`: Exists but has NO systemd unit. Should be added as `indicagent-timeframes.service` if 5m/15m/1h flow is needed. Needs symbol update from ESU5/NQU5 to H6 contracts.

## Open Questions

1. **Should timeframes_builder_service.py be activated in Phase 5?**
   - What we know: TWS daemon only publishes 1m bars. 5m/15m/1h indicator and intelligence streams have 0 messages.
   - What's unclear: Does the success criteria "intelligence:ESH6:1m has live messages" require 1m-only, or do higher TF streams matter?
   - Recommendation: Phase 5 success criteria explicitly says `intelligence:ESH6:1m` (1m only). Defer timeframes builder to Phase 6 dashboard work. This reduces Phase 5 scope to verifiable items.

2. **What's the qualify_instrument failure root cause for SR1H6, 6EH6, 6JH6, BTCH6?**
   - What we know: Error "Unknown symbol 'X'. Call qualify_instrument() first." means the contract object is missing a field IBKR requires (exchange, multiplier, secType). This is logged as a warning, not a crash.
   - What's unclear: Whether the Instrument model fields in settings.py match IBKR's contract spec for these specific instruments.
   - Recommendation: Investigate during Phase 5 05-01 after TWS reconnects. Try calling qualify_instrument manually in a Python shell to see the IBKR response.

3. **Is the VWAP tz-aware bug related to a real data issue or pandas 3.0 compatibility?**
   - What we know: All market bars have tz-naive timestamps (`2026-02-24T09:59:00`). VWAP error happens at `ts.dt.date == last_date` comparison.
   - What's unclear: Under what conditions does the bar_history deque contain mixed tz types.
   - Recommendation: Low priority for Phase 5. Indicator skips gracefully. Log noise only.

## Validation Architecture

> nyquist_validation is NOT set in `.planning/config.json` — skipping this section.

## Sources

### Primary (HIGH confidence)
- Direct Redis inspection of all stream keys, message counts, consumer groups (2026-02-24)
- Direct log inspection: `journalctl -u indicagent-*`, `logs/*.log` files (2026-02-24)
- Source code read: all 8 service files, TWS daemon, settings, stream_keys (2026-02-24)
- Process table inspection confirming all 8 services running (2026-02-24)
- systemd unit file comparison: installed units match repo (2026-02-24)

### Secondary (MEDIUM confidence)
- Inference about RTH bar rates based on market:ESH6:1m timestamps (2007 messages over 23 hours with clear RTH bursts)
- Inference about "false connected" state from correlation between service logs and Redis state

### Tertiary (LOW confidence)
- Root cause of qualify_instrument failures for SR1H6/6EH6/6JH6/BTCH6: not verified against live IBKR response

## Metadata

**Confidence breakdown:**
- Current system state: HIGH — directly observed from Redis, logs, processes
- Bug identification: HIGH — traced through code paths, confirmed against log evidence
- Fix correctness: MEDIUM — provider.is_connected() fix is straightforward; symbol config fix is definitive
- RTH timing predictions: MEDIUM — based on observed bar rate patterns

**Research date:** 2026-02-24
**Valid until:** 2026-03-15 (stable infrastructure; expires if contract roll to J6/M6 changes symbols)
