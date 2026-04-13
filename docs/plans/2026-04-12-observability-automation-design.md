# Observability, Alerting & Automation Design — Renaissance Refactor

**Date:** 2026-04-13  
**Status:** Refactored for Renaissance compliance  
**Scope:** Single phase covering CRITICAL + HIGH gaps with modular, reusable architecture  
**Renaissance principles:** Instrument everything. Single responsibility. Reuse everywhere. Earn the right.

---

## Problem Statement

The system produces data it cannot trust, and when it breaks nobody knows. Three incidents from the live system illustrate the gap:

1. `bar-replay` crash-looped 1,346 times — discovered manually hours later
2. `ibkr-provider` watchdog-killed 195 times (hours of missed bars) — no alert fired
3. `signal-tracker-compute` + `lifecycle-writer` installed but never enabled — silently doing nothing

Every undetected downtime window is a training sample that looks like "no signal" but actually means "no data." That poisons models downstream.

**Original design violated Renaissance principles:**
- ❌ Separation of concerns: Webhook dispatch in service_auditor_agent (audit + alerting mixed)
- ❌ Modularity: Bootstrap retry agent-specific, not reusable
- ❌ Instrument Everything: Alerting system had no internal metrics
- ❌ Earn the Right: Auto-restart without verification

**Jim Simons' verdict:** *"You're adding observability but not observing the observability layer? You're mixing audit and alerting responsibilities? You're making agent-specific patterns that should be general? Rewrite it. Single responsibility. Reuse everywhere. Instrument everything."*

---

## Architecture: Right Tool for Each Job (Renaissance-Compliant)

Three failure modes require different alerting paths:

```
BaseAgent (all agents) ──→ Crash/setup metrics → Prometheus
                         ├──→ _setup_with_retry() (opt-in bootstrap resilience)
                         └──→ _send_alert() → Kafka topic_alert_requests()
                                                        ↓
                                         alerting_agent (NEW service)
                                                        ↓
                                  ┌─────────────────┴─────────────────┐
                                  ↓                                   ↓
                          _dispatch_telegram()                 _dispatch_discord()
                                  ↓                                   ↓
                            Telegram (CRITICAL)                 Discord (HIGH/MEDIUM)

service_auditor_agent ──→ audit services (existing)
                       ──→ consume roll_events → auto-restart WITH verification

bar_auditor_agent ──→ market_data_gaps (new table)
                  └──→ topic_gap_fill_dlq() (new topic, on retry exhaustion)
```

**BaseAgent** provides universal observability (crash/setup metrics), reusable bootstrap retry, AND alert publishing capability for ALL agents.

**`alerting_agent`** (NEW) handles alert dispatch — single responsibility, separated from audit. Any agent can send alerts via Kafka using `BaseAgent._send_alert()`.

**`service_auditor_agent`** continues auditing services + roll automation, now with post-restart verification and uses `BaseAgent._send_alert()` for escalation/roll events.

**Grafana** handles metric-based thresholds (lag, latency, completeness).

**Renaissance improvements:**
- ✅ **Single responsibility:** AlertingAgent separates dispatch from audit
- ✅ **Modularity:** Bootstrap retry + alert publishing in BaseAgent, reusable by any agent
- ✅ **Reuse:** All agents get crash/setup observability + alert capability automatically
- ✅ **Instrument Everything:** AlertingAgent has internal metrics
- ✅ **Earn the Right:** Roll automation with post-restart verification
- ✅ **Separation of Concerns:** BaseAgent provides alert INTERFACE, AlertingAgent provides alert DISPATCH

---

## Component 0: BaseAgent Observability Foundation (NEW — First)

**Renaissance principle:** Modularity + reuse — crash/setup observability belongs in the base class, not duplicated across agents.

### Problem

Current observability is agent-specific and incomplete:
- Crash detection scattered across agents
- No universal setup success/failure tracking
- No setup latency measurement
- Bootstrap retry logic duplicated in signal_tracker_compute_agent (should be general pattern)

### Solution: Add to BaseAgent

```python
# src/core/agent/base.py additions:
from prometheus_client import Counter, Histogram

AGENT_CRASH_TOTAL = Counter(
    "agent_crash_total",
    "Agent crashes (uncaught exceptions)",
    ["agent"]
)

AGENT_SETUP_SUCCESS_TOTAL = Counter(
    "agent_setup_success_total",
    "Successful _setup() completions",
    ["agent"]
)

AGENT_SETUP_FAILURE_TOTAL = Counter(
    "agent_setup_failure_total",
    "Failed _setup() completions (retried if applicable)",
    ["agent", "error_type"]
)

AGENT_SETUP_LATENCY_SECONDS = Histogram(
    "agent_setup_latency_seconds",
    "_setup() execution time",
    ["agent"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0]
)

class BaseAgent(abc.ABC):
    BOOTSTRAP_RETRY_ATTEMPTS: int = 3
    BOOTSTRAP_RETRY_BACKOFF_BASE: float = 2.0  # seconds
    
    def __init__(self, name: str, metrics_port: int | None = None, max_idle_seconds: int = 0) -> None:
        # ... existing init ...
        
        # NEW: Crash/setup observability (cached at init, minimal runtime overhead)
        agent_label = name.lower().replace(" ", "_")
        self._crash_total = AGENT_CRASH_TOTAL.labels(agent=agent_label)
        self._setup_success_total = AGENT_SETUP_SUCCESS_TOTAL.labels(agent=agent_label)
        self._setup_failure_total = AGENT_SETUP_FAILURE_TOTAL.labels(agent=agent_label)
        self._setup_latency = AGENT_SETUP_LATENCY_SECONDS.labels(agent=agent_label)
    
    async def _setup_with_retry(self) -> None:
        """Wrap _setup() with exponential backoff retry.
        
        Subclasses call this from start() instead of _setup() directly
        if they need bootstrap resilience. Default behavior is no retry.
        """
        for attempt in range(self.BOOTSTRAP_RETRY_ATTEMPTS):
            try:
                await self._setup()
                return
            except Exception as exc:
                if attempt == self.BOOTSTRAP_RETRY_ATTEMPTS - 1:
                    raise
                backoff = self.BOOTSTRAP_RETRY_BACKOFF_BASE ** attempt
                self.logger.warning(
                    "agent.setup_retry",
                    attempt=attempt + 1,
                    max_attempts=self.BOOTSTRAP_RETRY_ATTEMPTS,
                    backoff_seconds=backoff,
                    error=str(exc),
                )
                await asyncio.sleep(backoff)
```

### Integration: Wrap start() Method

```python
# In BaseAgent.start():
async def start(self) -> None:
    self._register_signal_handlers()
    if self._metrics_port is not None:
        start_metrics_server(port=self._metrics_port)
    self.logger.info("agent.starting", agent=self.name)

    # NEW: Track setup latency + success/failure
    try:
        setup_start = time.monotonic()
        await self._setup()
        setup_duration = time.monotonic() - setup_start
        self._setup_latency.observe(setup_duration)
        self._setup_success_total.inc()
    except Exception as exc:
        self._setup_failure_total.labels(error_type=type(exc).__name__).inc()
        raise

    # NEW: Track crashes in _run()
    lag_task = asyncio.create_task(self._report_consumer_lag())
    watchdog_task = asyncio.create_task(self._watchdog_notify())
    stall_task = asyncio.create_task(self._stall_watchdog())
    try:
        await self._run()
    except Exception as exc:
        self._crash_total.inc()
        raise
    finally:
        # ... teardown ...
```

### Alert Publishing: `_send_alert()` Method

```python
# In BaseAgent (NEW):
async def _send_alert(self, severity: str, message: str, context: dict | None = None) -> None:
    """Send alert to AlertingAgent via Kafka.

    Args:
        severity: "CRITICAL" | "HIGH" | "MEDIUM"
        message: Human-readable alert message
        context: Optional structured context (symbol, tf, error details, etc.)

    No-op if producer not configured (agents without Kafka output).
    AlertingAgent routes: CRITICAL → Telegram, HIGH/MEDIUM → Discord.
    """
    if not hasattr(self, "_producer") or self._producer is None:
        return

    from src.core.stream_keys import topic_alert_requests
    from datetime import datetime, UTC

    payload = {
        "severity": severity,
        "message": message,
        "source": self.name,
        "timestamp": datetime.now(UTC).isoformat(),
        **(context or {}),
    }

    try:
        await self._producer.produce(topic_alert_requests(self._settings.env_name), payload)
        self.logger.info("alert_published", severity=severity, message=message[:100])
    except Exception as exc:
        self.logger.error("alert_publish_failed", error=str(exc))
```

### Benefits

**Reuse:** EVERY agent gets crash/setup observability + alert capability automatically
**Modularity:** Bootstrap retry + alert publishing in BaseAgent, reusable by any agent
**Efficiency:** Metrics cached at init, minimal runtime overhead
**Simplicity:** Single pattern, no code duplication
**Decoupling:** Agents publish alerts to Kafka, don't know about Telegram/Discord

### Migration

**Bootstrap resilience:**
```python
# OLD:
await self._setup()

# NEW:
await self._setup_with_retry()
```

**Alert publishing:**
```python
# OLD (direct webhook — mixed concerns):
await self._dispatch_webhook("CRITICAL", "title", "body")

# NEW (Kafka-based — separation of concerns):
await self._send_alert("CRITICAL", "title: body", {"context": "data"})
```

---

## Component 1: Grafana Alerting

### Contact Points

| Name | Channel | Severity |
|------|---------|---------|
| `telegram-critical` | Telegram bot DM | CRITICAL only |
| `discord-ops` | Discord `#indicagent-ops` webhook | HIGH + MEDIUM |

### Alert Rules (`production/grafana/provisioning/alerting/alert-rules.yml`)

| Severity | Name | Expression | Threshold |
|----------|------|-----------|-----------|
| CRITICAL | Provider dead | `rate(provider_bars_produced_total[5m])` | `== 0` during market hours |
| CRITICAL | Service crash-looping | `rate(service_auditor_service_restarts_total[10m])` | `> 3` — requires new counter in `service_auditor_agent` (see Component 4c) |
| CRITICAL | Signals being dropped | `increase(signal_writer_buffer_dropped_total[5m])` | `> 0` |
| CRITICAL | Signal DLQ growing | `increase(intelligence_pipeline_signal_dlq_total[5m])` | `> 0` |
| CRITICAL | Data completeness critical | `bar_auditor_canonical_completeness_pct` | `< 90` |
| HIGH | Consumer lag — any writer | writer consumer lag metrics | `> 1000` messages |
| HIGH | Bar flow stale | `bar_agg_time_since_last_bar_seconds` | `> 300` |
| HIGH | Output buffer pressure | `intelligence_pipeline_output_buffer_depth` | `> 400` |
| HIGH | Gap fill DLQ growing | `gap_fill_dlq_depth` counter | `> 0` |
| MEDIUM | Data completeness soft | `bar_auditor_canonical_completeness_pct` | `< 95` |

### Provisioning Structure

```
production/grafana/
  provisioning/
    alerting/
      contact-points.yml        ← gitignored (real credentials)
      contact-points.example.yml ← committed (placeholder values)
      alert-rules.yml           ← committed (all rule definitions)
    dashboards/
      dashboards.yml            ← existing, unchanged
  dashboards/
    operations.json             ← new (replaces service-overview.json)
    pipeline-health.json        ← rebuilt in place
    signals-i8.json             ← rebuilt in place
```

`contact-points.yml` added to `.gitignore`. Bot token and webhook URL never committed.

### Naming Conventions

- Provisioning files: kebab-case YAML
- Alert rule names: `snake_case` matching the metric domain
- Dashboard files: kebab-case JSON

---

## Component 2: Data Completeness

### Migration: `market_data_gaps` Table

```sql
-- 062_market_data_gaps.sql
CREATE TABLE market_data_gaps (
    id            BIGSERIAL    PRIMARY KEY,
    symbol        TEXT         NOT NULL,
    tf            TEXT         NOT NULL,
    gap_start_ts  TIMESTAMPTZ  NOT NULL,
    gap_end_ts    TIMESTAMPTZ,           -- NULL while gap is ongoing
    bars_expected INT          NOT NULL,
    bars_missing  INT          NOT NULL,
    detected_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at   TIMESTAMPTZ,           -- set when bar_auditor confirms filled
    UNIQUE (symbol, tf, gap_start_ts)
);
CREATE INDEX ON market_data_gaps (symbol, tf, gap_start_ts);
```

### `bar_auditor_agent` Changes

**Write path (on each audit cycle):**
- When `completeness_pct < 100%` for a (symbol, tf): UPSERT into `market_data_gaps`
  - If gap already exists for `gap_start_ts`: update `bars_missing`
  - If new gap: INSERT with `gap_end_ts = NULL`
- When `completeness_pct == 100%` and an open gap row exists: set `resolved_at = NOW()`, `gap_end_ts = NOW()`

**Consumer offset fix:**
- Change `auto_offset_reset="latest"` → `"earliest"` on the gap requests consumer
- Add in-memory dedup: `_seen_gap_requests: set[tuple[str, str, datetime]]` cleared every 24h
- Prevents re-processing the same gap request on consumer restart

**Gap fill DLQ:**
- When `_gap_requests_loop()` in `base_provider_agent` fails after 3 retries: publish to `topic_gap_fill_dlq()`
- Payload: `{symbol, tf, start_ts, end_ts, retry_count, error}`
- `bar_auditor_agent` exposes a `gap_fill_dlq_depth` Prometheus counter
- Grafana HIGH alert fires when counter grows

**Downstream value:**
- ML training JOINs `market_data_gaps` to exclude contaminated windows
- Backfill scripts query it for what to fill
- Signal ledger rows where `feature_ts` falls within a known gap can be flagged

### Naming

- Table: `market_data_gaps` (snake_case plural noun ✓)
- New Kafka topic: `topic_gap_fill_dlq()` in `stream_keys.py` → `{env}.gap_fill.dlq`
- New Prometheus counter: `bar_auditor_gap_fill_dlq_depth` (follows `bar_auditor_*` prefix)

---

## Component 3: Roll Automation

### Design (Renaissance-Compliant: Earn the Right)

`service_auditor_agent` adds a second Kafka consumer for `topic_roll_events` alongside its existing health event consumer. Both run as concurrent asyncio tasks within the same process — no new service.

**On `RollEvent` with `event_type = "roll_complete"`:**
1. **BEFORE restart:** Snapshot current provider lag
2. Log: `roll_automation.triggered {symbol} {old_expiry} → {new_expiry}`
3. Publish HIGH alert via Kafka (AlertingAgent dispatches to Discord)
4. Execute restart: `subprocess.run(["sudo", "systemctl", "restart", "indicagent-ibkr-provider"], check=True)`
5. **AFTER restart:** Wait 30s for warmup, then verify lag decreased
6. **Verification:** If lag did NOT decrease, escalate to CRITICAL alert

```python
async def _handle_roll_event(self, event: RollEvent) -> None:
    """Handle roll_complete event with verification."""
    if event.event_type != "roll_complete":
        return
    
    dedup_key = (event.symbol, event.new_expiry)
    if dedup_key in self._handled_rolls:
        return
    self._handled_rolls.add(dedup_key)
    
    # BEFORE restart: Snapshot state
    pre_restart_lag = await self._get_provider_lag()
    
    # Publish alert (via AlertingAgent)
    await self._publish_alert_event(
        severity="HIGH",
        title=f"Futures Roll: {event.symbol} {event.old_expiry}→{event.new_expiry}",
        body=f"Restarting indicagent-ibkr-provider",
    )
    
    # Restart
    await self._restart_ibkr_provider()
    
    # AFTER restart: Verify health (wait 30s for warmup)
    await asyncio.sleep(30)
    post_restart_lag = await self._get_provider_lag()
    
    # Verification: Did lag decrease?
    if post_restart_lag >= pre_restart_lag:
        # Restart failed — escalate to CRITICAL
        await self._publish_alert_event(
            severity="CRITICAL",
            title=f"Roll Restart Failed: {event.symbol}",
            body=f"Provider lag did not decrease after restart: {post_restart_lag}",
        )
```

**Dedup guard:** `_handled_rolls: set[tuple[str, str]]` tracking `(symbol, new_expiry)` — Kafka at-least-once delivery cannot trigger a double restart.

**Gate:** Only fires on `roll_complete`, not `roll_imminent` or `roll_detected` — prevents premature restarts before the old contract actually expires.

**Sudoers entry** (scoped to exactly one command):
```
bg ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart indicagent-ibkr-provider
```

**Renaissance improvement:** Verification loop ensures automation earns the right to run autonomously.

### Naming

- New consumer group: `service_auditor_roll_consumer` (follows `<concept>_consumer` pattern)
- New methods: `_handle_roll_event()`, `_restart_ibkr_provider()` — private snake_case ✓

---

## Component 1: AlertingAgent (NEW — Separation of Concerns)

**Renaissance principle:** Single responsibility — alert dispatch is separate from service auditing.

### Problem

Original design mixed audit and alerting in service_auditor_agent:
- Violates single responsibility principle
- Alerting not reusable by other agents
- No internal observability (alert dispatch success/failure not measured)

### Solution: New Dedicated Agent

```python
# services/alerting_agent.py (NEW FILE)
class AlertingAgent(BaseAgent):
    """Centralized alert dispatcher for all agents.
    
    Separation of concerns: service_auditor_agent audits services,
    AlertingAgent dispatches notifications. Reuse pattern: any agent
    can send alerts via Kafka → AlertingAgent → Telegram/Discord.
    """
    
    def __init__(self) -> None:
        settings = Settings()
        super().__init__(name="alerting_agent", metrics_port=9132)
        self._settings = settings
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._http_session: aiohttp.ClientSession | None = None
    
    # Internal observability (Instrument Everything):
    self._alert_dispatch_total = Counter(
        "alerting_dispatch_total",
        "Alerts dispatched by channel",
        ["channel", "severity", "status"]  # status=success/failure
    )
    
    self._alert_latency_seconds = Histogram(
        "alert_latency_seconds",
        "Alert dispatch latency",
        ["channel"],
        buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0]
    )
    
    async def _setup(self) -> None:
        """Initialize Kafka consumer and HTTP session."""
        self._kafka_consumer = KafkaConsumerClient(
            topic_alert_requests(self._settings.env_name),
            group_id="alerting_consumer",
        )
        self._http_session = aiohttp.ClientSession()
    
    async def _teardown(self) -> None:
        """Close HTTP session."""
        if self._http_session:
            await self._http_session.close()
    
    async def _dispatch_telegram(self, title: str, body: str) -> bool:
        """Dispatch CRITICAL alert to Telegram. Returns True on success."""
        token = self._settings.telegram_bot_token
        chat_id = self._settings.telegram_chat_id
        if not token or not chat_id:
            return False
        
        start = time.monotonic()
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            text = f"*[CRITICAL]* {title}\n{body}"
            assert self._http_session is not None
            async with self._http_session.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    self._alert_dispatch_total.labels(
                        channel="telegram", severity="CRITICAL", status="success"
                    ).inc()
                    self._alert_latency_seconds.labels(channel="telegram").observe(
                        time.monotonic() - start
                    )
                    return True
                else:
                    self._alert_dispatch_total.labels(
                        channel="telegram", severity="CRITICAL", status="failure"
                    ).inc()
                    self.logger.warning("telegram.notify_failed", status=resp.status, title=title)
                    return False
        except Exception as exc:
            self._alert_dispatch_total.labels(
                channel="telegram", severity="CRITICAL", status="failure"
            ).inc()
            self.logger.error("telegram.notify_error", error=str(exc))
            return False
    
    async def _dispatch_discord(self, title: str, body: str, severity: str) -> bool:
        """Dispatch HIGH/MEDIUM alert to Discord. Returns True on success."""
        url = self._settings.discord_webhook_url
        if not url:
            return False
        
        start = time.monotonic()
        try:
            content = f"**[{severity}]** {title}\n{body}"
            assert self._http_session is not None
            async with self._http_session.post(
                url,
                json={"content": content},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 204):
                    self._alert_dispatch_total.labels(
                        channel="discord", severity=severity, status="success"
                    ).inc()
                    self._alert_latency_seconds.labels(channel="discord").observe(
                        time.monotonic() - start
                    )
                    return True
                else:
                    self._alert_dispatch_total.labels(
                        channel="discord", severity=severity, status="failure"
                    ).inc()
                    self.logger.warning("discord.notify_failed", status=resp.status, title=title)
                    return False
        except Exception as exc:
            self._alert_dispatch_total.labels(
                channel="discord", severity=severity, status="failure"
            ).inc()
            self.logger.error("discord.notify_error", error=str(exc))
            return False
    
    async def _run(self) -> None:
        """Consume alert requests from Kafka and dispatch."""
        async for _topic, _key, payload in self._kafka_consumer.messages():
            if not self.running:
                break
            
            severity = payload.get("severity", "MEDIUM")
            title = payload.get("title", "")
            body = payload.get("body", "")
            
            if severity == "CRITICAL":
                await self._dispatch_telegram(title, body)
            elif severity in ("HIGH", "MEDIUM"):
                await self._dispatch_discord(title, body, severity)
```

### New Kafka Topic

```python
# src/core/stream_keys.py:
def topic_alert_requests(env_name: str) -> str:
    """Alert requests from any agent.
    
    Any agent can publish alert requests here.
    AlertingAgent consumes and dispatches to Telegram/Discord.
    """
    return f"{env_prefix(env_name)}alert.requests"
```

### Systemd Unit

```ini
# /etc/systemd/system/indicagent-alerting-agent.service
[Unit]
Description=IndicAgent Alerting Dispatcher
After=network.target redpanda.service

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment="PATH=/home/bg/dev/indicagent/.venv/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/home/bg/dev/indicagent/.venv/bin/python -m services.alerting_agent
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Benefits

**Single responsibility:** AlertingAgent ONLY dispatches alerts
**Reuse:** ANY agent can send alerts via Kafka
**Observability:** 4 internal metrics track alerting system health
**Modularity:** Decoupled from service_auditor_agent

---

## Component 2: Code Fixes

### 2a. Bootstrap Retry Usage (SIMPLIFIED)

**Problem:** Slow DB → zero signals loaded → silent logic failure.

**Fix:** Use BaseAgent._setup_with_retry() (see Component 0)

**signal_tracker_compute_agent migration:**
```python
# OLD:
await self._setup()

# NEW:
await self._setup_with_retry()
```

**Success condition:** `len(active_signals) > 0` OR COUNT query returns 0
**Failure condition:** 0 signals loaded when ledger has rows → retry
**`sd_notify(READY=1)`** moves to after successful bootstrap

### 2b. SwarmOrchestratorComputeAgent Context Cache Seeding

**Problem:** `SwarmContextCache` starts empty — first N bars processed without historical regime context.

**Fix:** In `_setup()`, before the consume loop:
- Query last 200 rows per (symbol, tf) from `intelligence_features`
- Load into `SwarmContextCache`
- One startup DB read, amortized cost is negligible

### 2c. Remove Webhook from ServiceAuditorAgent (REFACTORED)

**OLD:** Webhook dispatcher in service_auditor_agent
**NEW:** Send alert requests to Kafka, AlertingAgent dispatches

```python
# service_auditor_agent.py changes:
async def _publish_alert_event(self, severity: str, title: str, body: str) -> None:
    """Publish alert request to Kafka for AlertingAgent to dispatch."""
    await self._kafka_producer.publish(
        topic_alert_requests(self._env_name),
        {"severity": severity, "title": title, "body": body},
    )

# In _handle_escalation():
await self._publish_alert_event(
    "CRITICAL",
    f"Service escalated: {spec.unit}",
    f"{len(state.restart_times)} restarts in 10 min — stopped retrying.",
)

# In _handle_roll_event():
await self._publish_alert_event(
    "HIGH",
    f"Futures Roll: {event.symbol} {event.old_expiry}→{event.new_expiry}",
    f"Restarting indicagent-ibkr-provider",
)
```

---

## Component 5: Dashboard Rebuild

Three Grafana dashboards covering the Golden Signals (Traffic, Latency, Errors, Saturation):

### Operations (`operations.json`) — Always-Open View

| Row | Panels |
|-----|--------|
| Service Health | Services running count · restart rate by service · data completeness % · active signals |
| Traffic | Bars produced rate · bars processed rate · time since last bar |
| Errors | Restart heatmap · signal DLQ · gap-fill DLQ · buffer drops rate |
| Saturation | Consumer lag per writer · output buffer depth · thread pool workers |
| Data Quality | Completeness % by (symbol, tf) · gap windows from `market_data_gaps` |

### Pipeline (`pipeline-health.json`) — Latency and Throughput

| Row | Panels |
|-----|--------|
| Latency | I1 p95 · I7 p95 · DB write p95 · merger bar p95 |
| Throughput | Bars/min · HTF bars emitted · signals generated vs selected vs written |
| Health | Plugin skips · state checkpoint failures · checkpoint fallback rate |

### Signals (`signals-i8.json`) — Rebuilt in Place

| Row | Panels |
|-----|--------|
| Signal Funnel | Generated vs selected vs written · active signals · lifecycle transitions/hr |
| Routing | Merger bars routed vs dropped · provider merger lag |
| AI Narrative | Narrative rate · LLM latency · LLM circuit breaker state |

---

## Naming Convention Audit

| Layer | New Name | Follows Rule |
|-------|---------|-------------|
| DB table | `market_data_gaps` | snake_case plural noun ✓ |
| Kafka topic fn | `topic_gap_fill_dlq()` | `topic_<output_domain>()` ✓ |
| Kafka topic string | `{env}.gap_fill.dlq` | dots only, env prefix ✓ |
| Consumer group | `service_auditor_roll_consumer` | `<concept>_consumer` ✓ |
| Prometheus counter | `bar_auditor_gap_fill_dlq_depth` | `<agent>_<metric>` prefix ✓ |
| Private methods | `_dispatch_webhook`, `_notify_telegram`, `_notify_discord`, `_handle_roll_event`, `_restart_ibkr_provider` | private snake_case ✓ |
| Grafana files | `contact-points.yml`, `alert-rules.yml`, `operations.json` | kebab-case ✓ |
| Migration | `062_market_data_gaps.sql` | sequential NNN ✓ |

---

## What Is NOT in Scope

- AlertManager (Grafana native alerting is sufficient)
- Changes to I1–I7 plugin logic
- `market_data_gaps` backfill for historical outages (separate script, future work)

**NEW in Renaissance refactor:**
- ✅ **NEW agent service:** AlertingAgent (separation of concerns, reusability)
- ✅ **NEW systemd unit:** indicagent-alerting-agent.service
- ✅ **NEW Kafka topic:** topic_alert_requests()
- ✅ **NEW BaseAgent features:** 4 crash/setup metrics, bootstrap retry method

---

## Success Criteria

### Functional
1. ✅ A service crash-looping triggers a Telegram message within 60 seconds
2. ✅ Provider downtime > 5 min triggers a Telegram message
3. ✅ Every gap window is recorded in `market_data_gaps` with correct `bars_expected` / `bars_missing`
4. ✅ Futures roll triggers automatic `ibkr-provider` restart with verification
5. ✅ `signal-tracker-compute` starts with valid state even when DB responds slowly
6. ✅ `swarm_orchestrator` processes first bar with seeded context, not empty cache
7. ✅ All three Grafana dashboards load with current service names and live data
8. ✅ No Prometheus queries reference archived service names

### Observability (NEW — Instrument Everything)
9. ✅ ALL agents have crash metrics (agent_crash_total)
10. ✅ ALL agents have setup metrics (success_total, failure_total, latency_seconds)
11. ✅ Bootstrap retry available to ALL agents via BaseAgent._setup_with_retry()
12. ✅ AlertingAgent has internal metrics (dispatch_total, latency_seconds)
13. ✅ Roll automation verification (pre/post lag comparison)

### Renaissance Principles Compliance
- ✅ **Simplicity:** Single pattern for bootstrap retry (BaseAgent)
- ✅ **Modularity:** AlertingAgent separates dispatch from audit
- ✅ **Reuse:** Crash/setup metrics in ALL agents automatically
- ✅ **Instrument Everything:** Alerting system has internal metrics
- ✅ **Earn the Right:** Roll automation verified before trusted
