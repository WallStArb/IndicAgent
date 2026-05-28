# Phase 109: Config Foundation & Self-Healing Engine - Research

**Researched:** 2026-05-28
**Domain:** Configuration management, time-series state, control theory, self-healing systems
**Confidence:** HIGH

## Summary

Phase 109 implements a unified configuration system with time-series audit trail and a control-theory-based self-healing engine. The design follows Renaissance principles: config as time-series data (same database, same patterns as signals), transactional outbox pattern for safe DB-Kafka propagation, and self-healing as a control system (sensor -> setpoint -> actuator -> feedback).

**Primary recommendation:** Implement in 5 sub-phases starting with config foundation (DB tables, ConfigService, OutboxDispatcher), then BaseAgent hot-reload pattern, then self-healing engine, then Alertmanager integration, finally migrate runtime params from settings.py.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Three Semantic Config Layers:**
- **INFRASTRUCTURE** - DB URLs, secrets, Kafka brokers (restart required, stays in .env)
- **STRUCTURE** - Plugin tiers, DAG order, service definitions (deploy required, stays in code/YAML)
- **OPERATIONAL** - Feature flags, thresholds, windows (hot-reload via DB + Kafka)

**Architecture Decisions:**
- Config as time-series state (TimescaleDB hypertables, same patterns as signals)
- Kafka as sink not pipe (ConfigService writes DB + outbox, OutboxDispatcher publishes)
- Transactional outbox pattern (DB commit before Kafka publish)
- Optimistic concurrency control (expected_version prevents silent overwrites)
- Zero-downtime tuning for OPERATIONAL layer (hot-reload on all services)

**Self-Healing Engine:**
- Control theory approach (sensor -> setpoint -> error -> actuator -> process -> feedback)
- Every remediation must measure pre-state, execute action, measure post-state, record outcome
- Conservative Phase 1 strategies only (static mapping, low-risk actions)
- Auto-disable strategies with <80% success rate

**Default State:**
- All alerts OFF by default
- Runtime params seeded from current settings.py values
- Everything OFF by default (Renaissance principle)

### Claude's Discretion

**Implementation Phases:**
- 109.1: Config foundation (DB tables, ConfigService, OutboxDispatcher, Kafka propagation)
- 109.2: BaseAgent config reload pattern integration
- 109.3: SelfHealingEngine (webhook, remediation engine, ledger)
- 109.4: Alertmanager webhook configuration
- 109.5: Migration of runtime params from settings.py

**Technical Debt Cleanup (post-implementation):**
- Delete ~15 runtime params from settings.py
- Delete _LAG_THRESHOLDS dict from service_auditor_agent.py (~25 entries)
- Delete hardcoded shadow_only=True from 8 AI agents

### Deferred Ideas (OUT OF SCOPE)

- Per-category permissions (who can change INFRA vs STRUCT vs OPS)
- Approval workflows for high-risk keys
- Complex rule engine for remediation (current: static mapping)
- Rich dashboard for config history visualization
- A/B testing framework for config values
- Automated config optimization based on signal quality
- Multi-region config replication
- Config validation dry-run mode
- Full Prometheus Alertmanager rule set (only webhook integration)
- Complete settings.py cleanup (technical debt section, not execution)
- Production tuning of thresholds (baseline only)

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | (latest in project) | PostgreSQL/TimescaleDB async driver | Already used throughout project, 2-5x faster than psycopg2, native async |
| TimescaleDB | (existing) | Time-series config storage | Already in project, hypertables with compression/retention policies |
| aiokafka | (existing) | Kafka producer/consumer | Already used throughout project for event streaming |
| FastAPI | (existing) | ConfigService + SelfHealingEngine API | Already used in src/api/, async/await native, OpenAPI auto-docs |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | (existing) | Structured logging | Already used throughout project |
| sdnotify | (existing) | systemd watchdog integration | Already used in BaseAgent |
| aiohttp | (existing) | HTTP client for webhook validation | Already used in alerting_agent.py |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncpg | psycopg2 (sync) | asyncpg is 2-5x faster, native async - already in project |
| Custom outbox | Debezium CDC | Debezium is external dependency, adds complexity for simple pattern |
| FastAPI | Flask | FastAPI async/await native, already in project, better performance |
| TimescaleDB hypertables | Plain SQL tables | Loses compression, retention policies, time-series query optimization |

**Installation:**
```bash
# No new packages required - all dependencies already in project
# Existing: asyncpg, aiokafka, fastapi, structlog, sdnotify, aiohttp
```

## Architecture Patterns

### Recommended Project Structure

```
src/
├── config/
│   ├── __init__.py
│   ├── settings.py              # Existing (INFRASTRUCTURE layer only, post-migration)
│   ├── config_service.py        # NEW: ConfigService (DB + outbox write)
│   ├── config_schema.py         # NEW: Config validation schemas
│   └── outbox_dispatcher.py     # NEW: Kafka outbox reader (separate process)
├── self_healing/
│   ├── __init__.py
│   ├── engine.py                # NEW: SelfHealingEngine (webhook + remediation)
│   ├── strategies.py           # NEW: Remediation strategies (static mapping)
│   └── ledger.py                # NEW: Remediation ledger persistence
├── core/
│   ├── agent/
│   │   └── base.py              # MODIFY: Add config reload pattern
└── observability/
    └── metrics.py               # MODIFY: Add config + self-healing metrics

services/
├── config_service_agent.py     # NEW: ConfigService FastAPI server
├── outbox_dispatcher_agent.py   # NEW: Outbox dispatcher daemon
└── self_healing_agent.py        # NEW: Self-healing webhook + remediation

production/migrations/
└── 109_config_foundation.sql   # NEW: Config tables, remediation ledger
```

### Pattern 1: Transactional Outbox Pattern

**What:** Write config changes to DB + outbox in same transaction, separate process publishes to Kafka.

**When to use:** When you need guaranteed DB-Kafka consistency (no lost config updates).

**Example:**
```python
# Source: Context7 + design doc docs/plans/2026-05-28-config-foundation-and-alerting-system.md
async def set(self, key: str, value: Any, changed_by: str = "system",
              expected_version: int | None = None, reason: str | None = None) -> ConfigChange:
    """Set config with validation, version check, transactional outbox."""
    # 1. Validate against config_schema
    schema = await self._validate_schema(key, value)
    
    # 2. Optimistic concurrency check
    current = await self._get_current(key)
    if expected_version and current.version != expected_version:
        raise ConfigVersionConflict(...)
    
    # 3. Transactional write: config_history + config_state + config_outbox
    async with self._db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                datetime.now(UTC), key, current.version + 1, value, changed_by, reason
            )
            await conn.execute(
                "INSERT INTO config_state (config_key, config_value, version) "
                "VALUES ($1, $2, $3) ON CONFLICT (config_key) DO UPDATE SET config_value=$2, version=$3",
                key, value, current.version + 1
            )
            await conn.execute(
                "INSERT INTO config_outbox (config_key, config_value, version, status) "
                "VALUES ($1, $2, $3, 'pending')",
                key, value, current.version + 1
            )
    
    return ConfigChange(key=key, value=value, version=current.version + 1)
```

### Pattern 2: Config Consumer Pattern (BaseAgent)

**What:** Services subscribe to topic_config_updates, hot-reload in-memory cache on message.

**When to use:** All BaseAgent subclasses need OPERATIONAL layer config hot-reload.

**Example:**
```python
# Source: design doc docs/plans/2026-05-28-config-foundation-and-alerting-system.md
class BaseAgent:
    async def _setup(self) -> None:
        # Load DB snapshot on startup
        self._config_cache = await config_service.list()
        
        # Subscribe to config updates (only for OPERATIONAL layer)
        if self._config_layer == "OPS":
            self._config_consumer = KafkaConsumerClient("topic_config_updates", ...)
            asyncio.create_task(self._reload_config_loop())
    
    async def _reload_config_loop(self) -> None:
        """Hot-reload config on Kafka message."""
        async for _topic, _key, payload in self._config_consumer.messages():
            key = payload["config_key"]
            value = payload["config_value"]
            version = payload["version"]
            
            # Update cache
            self._config_cache[key] = value
            
            # Emit metric
            CONFIG_RELOAD_TOTAL.add(1, {"agent": self.name, "key": key})
            
            self.logger.info("config.reloaded", key=key, version=version)
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get config value from in-memory cache (hot path)."""
        return self._config_cache.get(key, default)
```

### Pattern 3: Control Loop Remediation

**What:** Sensor -> Setpoint -> Error -> Actuator -> Process -> Feedback loop.

**When to use:** Self-healing actions (disk cleanup, service restart, pool flush).

**Example:**
```python
# Source: design doc docs/plans/2026-05-28-config-foundation-and-alerting-system.md
async def execute_remediation(self, alert: AlertRequest) -> RemediationResult:
    """Execute remediation with control loop feedback."""
    # 1. Measure pre-state (sensor)
    pre_value = await self._measure_state(alert.state_variable)
    
    # 2. Compare to setpoint
    error = pre_value - alert.threshold
    if error <= 0:
        return RemediationResult(status="no_action", ...)
    
    # 3. Execute action (actuator)
    strategy = REMEDIATION_STRATEGIES.get(alert.alert_id)
    if not strategy:
        return RemediationResult(status="no_strategy", ...)
    
    start = time.monotonic()
    
    # 4. Execute action with timeout
    try:
        async with asyncio.timeout(strategy.timeout_seconds):
            await strategy.execute(alert)
    except Exception as exc:
        # Record failure, don't update post_value
        await self._record_ledger(alert, pre_value, None, "failed", str(exc))
        return RemediationResult(status="failed", error=str(exc))
    
    # 5. Measure post-state (feedback)
    post_value = await self._measure_state(alert.state_variable)
    duration_ms = (time.monotonic() - start) * 1000
    
    # 6. Record outcome
    outcome = "success" if post_value < alert.threshold else "partial"
    await self._record_ledger(alert, pre_value, post_value, outcome, duration_ms)
    
    return RemediationResult(status=outcome, pre_value=pre_value, post_value=post_value, duration_ms=duration_ms)
```

### Anti-Patterns to Avoid

- **Mixing config layers in same mechanism** - INFRA (restart-required) and OPS (hot-reload) must have different code paths
- **Direct Kafka publish from ConfigService** - Violates transactional outbox pattern, can lose updates
- **Measuring only post-state** - Control loop requires pre-state to calculate error and verify fix
- **Silent overwrite on concurrent writes** - Must use optimistic concurrency or explicit last-write-wins
- **Blocking config reload** - Hot-reload must be async, never block message processing

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DB connection pooling | Custom pool wrapper | DatabaseManager.create_pool() | Already in project, handles JSONB codecs, pool gauges |
| Kafka producer/consumer | Custom Kafka client | KafkaProducerClient/KafkaConsumerClient | Already in project, handles OTel trace propagation, metrics |
| Logging | Custom logger setup | structlog (existing) | Already used throughout project, bound contexts, JSON output |
| HTTP server | Custom async server | FastAPI (existing) | Already in project, OpenAPI auto-docs, async/await native |
| systemd integration | Custom sd-notify logic | sdnotify (existing) | Already used in BaseAgent watchdog |
| OTel metrics | Custom metrics registry | OTel SDK (existing) | Already used throughout project, prometheus_client removed |
| Schema validation | Custom validator | Pydantic (existing via Settings) | Already used in settings.py, type-safe, declarative |
| JSON serialization | Custom json handling | asyncpg JSONB codecs | Already configured in DatabaseManager |

**Key insight:** The project already has mature infrastructure for DB pooling, Kafka, logging, metrics, and HTTP. Reuse existing patterns instead of rebuilding.

## Common Pitfalls

### Pitfall 1: Config Reload Blocking Message Processing

**What goes wrong:** Hot-reload logic blocks the main message loop, causing consumer lag and stall detection.

**Why it happens:** Synchronous config reload in the message processing path.

**How to avoid:** Run config reload in separate asyncio task, only update in-memory cache (no I/O in hot path).

**Warning signs:** Consumer lag spikes after config changes, `config_reload_latency_seconds` histogram shows p99 > 100ms.

### Pitfall 2: Lost Config Updates Due to DB-Kafka Race

**What goes wrong:** Config update written to DB but Kafka publish fails silently.

**Why it happens:** Publishing to Kafka directly from ConfigService without outbox pattern.

**How to avoid:** Use transactional outbox (write DB + outbox in same transaction), separate OutboxDispatcher process publishes to Kafka.

**Warning signs:** `config_outbox_pending` gauge > 0, services report stale config despite DB updates.

### Pitfall 3: Concurrent Config Write Silent Overwrite

**What goes wrong:** Two concurrent writes to same key, last write wins silently, first write lost.

**Why it happens:** No optimistic concurrency check, or expected_version not enforced.

**How to avoid:** Require expected_version on set(), raise ConfigVersionConflict on mismatch, force client to re-read and retry.

**Warning signs:** Config changes "disappear", `config_version_conflict_total` counter increments.

### Pitfall 4: Remediation Success Rate Not Tracked

**What goes wrong:** Failing remediation strategies run indefinitely, no auto-disable.

**Why it happens:** Not tracking success rate per strategy, no circuit breaker.

**How to avoid:** Record every remediation outcome to remediation_ledger, materialized view calculates 30-day success rate, auto-disable < 80%.

**Warning signs:** Same alert repeatedly triggers but remediation never succeeds, `remediation_success_rate` gauge < 0.8.

### Pitfall 5: Mixing INFRA and OPS Config Layers

**What goes wrong:** Database URL change attempted via hot-reload, causing connection failures.

**Why it happens:** No category enforcement, all config keys routed through same hot-reload path.

**How to avoid:** Check config_schema.category before hot-reload, INFRA keys reject hot-reload, require explicit restart.

**Warning signs:** Service crashes after config change, connection pool errors after "hot-reload".

## Code Examples

### ConfigService.set() with Transactional Outbox

```python
# Source: design doc docs/plans/2026-05-28-config-foundation-and-alerting-system.md
async def set(self, key: str, value: Any, changed_by: str = "system",
              expected_version: int | None = None, reason: str | None = None) -> ConfigChange:
    """Set config with validation, version check, transactional outbox."""
    
    # 1. Validate against config_schema (type, range, allowed_values)
    schema = await self._get_schema(key)
    validation = self._validate_value(value, schema)
    if not validation.valid:
        CONFIG_VALIDATION_FAILED_TOTAL.add(1, {"key": key, "reason": validation.reason})
        raise ConfigValidationError(validation.reason)
    
    # 2. Optimistic concurrency check
    current = await self._get_current(key)
    if expected_version is not None and current.version != expected_version:
        CONFIG_VERSION_CONFLICT_TOTAL.add(1, {"key": key})
        raise ConfigVersionConflict(expected=expected_version, actual=current.version)
    
    # 3. Transactional write: config_history + config_state + config_outbox
    new_version = current.version + 1
    now = datetime.now(UTC)
    
    async with self._db_pool.acquire() as conn:
        async with conn.transaction():
            # Write to history (time-series audit trail)
            await conn.execute(
                "INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                now, key, new_version, value, changed_by, reason
            )
            # Update current state (fast lookup)
            await conn.execute(
                "INSERT INTO config_state (config_key, config_value, version, updated_at) "
                "VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (config_key) DO UPDATE SET config_value=$2, version=$3, updated_at=$4",
                key, value, new_version, now
            )
            # Write to outbox (Kafka propagation)
            await conn.execute(
                "INSERT INTO config_outbox (config_key, config_value, version, changed_at, status) "
                "VALUES ($1, $2, $3, $4, 'pending')",
                key, value, new_version, now
            )
    
    CONFIG_SET_TOTAL.add(1, {"key": key, "changed_by": changed_by, "outcome": "success"})
    
    return ConfigChange(key=key, value=value, version=new_version, changed_at=now)
```

### OutboxDispatcher Kafka Publisher

```python
# Source: design doc docs/plans/2026-05-28-config-foundation-and-alerting-system.md
class OutboxDispatcherAgent(BaseAgent):
    """Poll config_outbox for pending rows, publish to Kafka, update status."""
    
    async def _run(self) -> None:
        """Poll loop: read pending, publish, update status."""
        while self.running:
            # 1. Fetch pending outbox rows
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, config_key, config_value, version, changed_at "
                    "FROM config_outbox WHERE status = 'pending' "
                    "FOR UPDATE SKIP LOCKED LIMIT 100"
                )
            
            if not rows:
                await asyncio.sleep(1)
                continue
            
            # 2. Publish to Kafka
            for row in rows:
                start = time.monotonic()
                try:
                    payload = {
                        "config_key": row["config_key"],
                        "config_value": row["config_value"],
                        "version": row["version"],
                        "changed_by": "system",  # From config_history join
                        "changed_at": row["changed_at"].isoformat(),
                        "reason": None,
                        "redacted": False,
                        "correlation_id": str(uuid.uuid4()),
                    }
                    await self._producer.publish(
                        topic_config_updates(self.env_name),
                        payload,
                        key=row["config_key"]  # Partition by key for ordering
                    )
                    
                    # 3. Update status to published
                    async with self._db_pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE config_outbox SET status = 'published' WHERE id = $1",
                            row["id"]
                        )
                    
                    CONFIG_OUTBOX_PUBLISH_LATENCY.record(time.monotonic() - start)
                    CONFIG_OUTBOX_PENDING.add(-1)  # Decrement gauge
                    
                except Exception as exc:
                    # 4. Update status to failed (will retry)
                    async with self._db_pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE config_outbox SET status = 'failed' WHERE id = $1",
                            row["id"]
                        )
                    self.logger.error("outbox.publish_failed", id=row["id"], error=str(exc))
```

### Remediation Ledger Write

```python
# Source: design doc docs/plans/2026-05-28-config-foundation-and-alerting-system.md
async def _record_ledger(self, alert: AlertRequest, pre_value: float, post_value: float | None,
                         outcome: str, duration_ms: int, error: str | None = None) -> None:
    """Record remediation attempt to time-series ledger."""
    
    remediation_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    
    async with self._db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO remediation_ledger "
            "(timestamp, remediation_id, alert_id, state_variable, pre_value, post_value, "
            "target_value, action, outcome, duration_ms, error_message, changed_by, reason) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
            now, remediation_id, alert.alert_id, alert.state_variable, pre_value, post_value,
            alert.threshold, alert.action, outcome, duration_ms, error, "system", alert.reason
        )
    
    REMEDIATION_ATTEMPT_TOTAL.add(1, {
        "state_variable": alert.state_variable,
        "action": alert.action,
        "outcome": outcome
    })
    REMEDIATION_DURATION_SECONDS.record(duration_ms / 1000, {
        "state_variable": alert.state_variable,
        "action": alert.action
    })
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded config in settings.py | DB-backed time-series config | Phase 109 | Zero-downtime tuning, full audit trail |
| Direct Kafka publish from services | Transactional outbox pattern | Phase 109 | Guaranteed DB-Kafka consistency |
| No self-healing (manual escalation) | Control-theory-based remediation | Phase 109 | Automated recovery, success rate tracking |
| Static systemd unit restart thresholds | DB-configured alert thresholds | Phase 109 | Runtime tuning without deploy |
| No config history (what changed when) | Time-series config_history | Phase 109 | Correlation analysis, rollback capability |

**Deprecated/outdated:**
- Hardcoded runtime params in settings.py (~40 tunable params to migrate)
- Hardcoded _LAG_THRESHOLDS dict in service_auditor_agent.py (~25 entries)
- Hardcoded shadow_only=True in AI agent classes (~8 agents)

## Open Questions

1. **Config API authentication mechanism**
   - What we know: Design specifies Bearer token for API, shared secret for webhook
   - What's unclear: Token storage (ENV vs DB), token rotation strategy
   - Recommendation: Use ENV for initial phase (shared secret in .env), add DB-backed token rotation post-109

2. **OutboxDispatcher polling frequency**
   - What we know: Need sub-second latency for config updates, but polling too frequently wastes resources
   - What's unclear: Optimal poll interval (100ms? 1s?), adaptive polling based on pending count
   - Recommendation: Start with 100ms poll, adaptive backoff to 1s when no pending rows, metric-based tuning

3. **Remediation strategy rate limiting**
   - What we know: Design specifies max_attempts_per_hour per strategy
   - What's unclear: Sliding window vs fixed window, state storage (in-memory vs DB)
   - Recommendation: Sliding window with in-memory state (reset on restart), add DB-backed tracking post-109

## Sources

### Primary (HIGH confidence)

- **Existing codebase** - src/config/settings.py, services/service_auditor_agent.py, src/core/agent/base.py
- **Existing codebase** - src/core/kafka_utils.py, src/core/database_manager.py, src/observability/metrics.py
- **Design doc** - docs/plans/2026-05-28-config-foundation-and-alerting-system.md
- **CONTEXT.md** - .planning/phases/109-config-foundation-self-healing-engine/109-CONTEXT.md
- **Migration patterns** - production/migrations/*.sql (003_timescaledb_enable_and_policies.sql, 008_5m_15m_caggs.sql)

### Secondary (MEDIUM confidence)

- [The Transactional Outbox Pattern: Reliable Event Publishing](https://james-carr.org/posts/2026-01-15-transactional-outbox-pattern/) - January 15, 2026
- [Outbox Pattern with Apache Kafka - Axual](https://axual.com/blog/transactional-outbox-pattern-kafka)
- [The Transactional Outbox Pattern - Confluent Developer](https://developer.confluent.io/courses/microservices/the-transactional-outbox-pattern/)
- [Processing Prometheus Alerts with Fastapi - Stack Overflow](https://stackoverflow.com/questions/76136163/processing-prometheus-alerts-with-fastapi)
- [How to use subprocess.call to restart a service in linux? - Stack Overflow](https://stackoverflow.com/questions/54103141/how-to-use-subprocess-call-to-restart-a-service-in-linux)
- [A Control-Theoretic Framework for the Self-Healing Enterprise](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6087866) - February 2026

### Tertiary (LOW confidence)

- [How to Configure Data Retention Policies in TimescaleDB](https://oneuptime.com/blog/post/2026-02-02-timescaledb-data-retention/view) - February 2, 2026
- [TimescaleDB vs QuestDB: 2026 Benchmark Results](https://questdb.com/blog/timescaledb-vs-questdb-comparison/) - 2026
- Various Chinese blog posts on asyncpg and systemd (via WebSearch - unverified)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in project, verified via codebase inspection
- Architecture: HIGH - Design document is comprehensive, verified against existing patterns
- Pitfalls: HIGH - Based on well-known distributed systems patterns (outbox, optimistic concurrency, control theory)
- Implementation details: MEDIUM - Some decisions (polling frequency, rate limiting) require runtime tuning

**Research date:** 2026-05-28
**Valid until:** 2026-07-28 (60 days - stable architectural patterns, but library versions may update)
