# IndicAgent Hot/Warm/Cold Storage Resilience Architecture Plan

**Date:** 2026-03-01
**Status:** Shipped — circuit breaker metrics in src/observability/metrics.py
**Goal:** Design production-grade resilience for hot/warm/cold storage architecture to achieve 99.9% uptime, data completeness, and institutional sophistication.

---

## Executive Summary

IndicAgent implements a well-designed three-tier streaming architecture:
- **Hot Tier (Redis Streams):** Sub-millisecond persistence for real-time event streaming
- **Warm Tier (In-Memory Caches):** Service-local deques/OrderedDicts for plugin computation
- **Cold Tier (TimescaleDB):** Batch-persisted feature vectors for ML training and historical analysis

**Current Status:** Production-ready foundation with **4 critical gaps** that prevent institutional-grade reliability:
1. No IBKR auto-reconnection (manual intervention required)
2. Feature writer drops data when DB unavailable (no backpressure)
3. No consumer lag monitoring (visibility gaps)
4. No gap detection (silent data loss in ML training dataset)
5. At-most-once delivery semantics (no replay on restart)

**Target Outcome:** 99.9% uptime, at-least-once delivery, automatic gap detection and recovery, Grafana observability.

---

## Part 1: Current Architecture Deep Dive

### 1.1 Hot Tier: DragonflyDB Streams

**Location:** `/home/bg/dev/indicagent/src/core/stream_keys.py`

**Stream Types and MaxLen Policies:**

| Stream Pattern | Maxlen | Purpose | Consumer |
|---------------|---------|---------|-----------|
| `ticks:{symbol}:live` | 20,000 | Raw tick display | Dashboard (SSE) |
| `market:{symbol}:{tf}` | 2,000 (1m) / 1,000 (5m-15m-1h) | Authoritative OHLCV | Indicator Service |
| `indicators:{symbol}:{tf}` | 1,000 | I1 technical indicators | Market Analysis |
| `intelligence:{symbol}:{tf}` | 1,000 | I3-I6 intelligence | Signal Gen + Feature Writer |
| `signals:{symbol}:{tf}:aggregated` | 200 | Selected I7 signal | AI Narrative + Tracker |
| `narratives:{symbol}:{tf}` | 100 | I8 LLM synthesis | Dashboard (SSE) |
| `narratives:group:{group}` | 50 | Group synthesis | Dashboard (SSE) |

**Total Streams:** ~581 active streams (23 symbols × 4-6 timeframes + 6 groups)

**Key Pattern - BUSYGROUP Reset:**
```python
# src/core/stream_utils.py:11-50
async def ensure_consumer_group_with_reset(redis_client, stream_name, group_name, start_id="$"):
    try:
        await redis_client.xgroup_create(stream_name, group_name, start_id, mkstream=True)
        return True  # Freshly created
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            # Reset to current tail to skip stale backlog
            await redis_client.xgroup_setid(stream_name, group_name, start_id)
            return False  # Already existed
```

**Critical Behavior:** Consumer groups start at `$` (current tail) on restart → **no replay of missed data** (at-most-once semantics).

---

### 1.2 Warm Tier: Service Caches

**Pattern:** All services maintain in-memory history for plugin state and multi-TF injection.

**Cache Structure:**

| Service | Cache Type | Size | Purpose |
|----------|------------|------|---------|
| Indicator Service | `OrderedDict` (maxlen=200) | Deduplication, I1 plugin history |
| Market Analysis | `deque` (maxlen=200) + `dict` cache | Multi-TF bar injection, intelligence cache |
| Signal Generator | `deque` (maxlen=200) | I7 plugin state, bar history |
| AI Narrative | `dict` (latest signals) | Group synthesis fingerprinting |
| Feature Writer | `list` (buffer) | Batch aggregation before DB write |

**Design Strengths:**
- Fast access for plugin computation (<10μs)
- LRU eviction prevents unbounded growth
- Multi-TF cross-timeframe confluence (market_analysis_service injects higher-TF data)

---

### 1.3 Cold Tier: TimescaleDB

**Hypertables:**

| Table | Purpose | Retention | Compression |
|--------|---------|-----------|--------------|
| `market_data_ohlcv` | Raw OHLCV bars | 90 days, 7d compression |
| `intelligence_features` | Full feature vectors (ML dataset) | Indefinite, 7d compression |
| `signal_ledger` | Signal lifecycle + outcomes | 365 days, 7d compression |

**Compression Settings:**
- Segment by: `symbol,tf` or `symbol,setup_plugin`
- Order by: `ts ASC` (critical for forward-scan performance)
- Policy: 7-day compression (chunks older than 7 days)

**Connection Pooling:**
```python
# src/core/database_manager.py:37-38
self.pool = await asyncpg.create_pool(
    self.database_url,
    min_size=2,
    max_size=10,
    command_timeout=30,
    init=_setup_codecs  # JSONB codecs
)
```

**Design Principle:** Real-time pipeline **never writes directly to database**. Only `feature_writer_service` handles persistence.

---

### 1.4 Service Architecture

**Data Flow Pipeline:**

```
IBKR TWS (10.0.0.33:7497)
  ↓ [ticks:SYMBOL:live, market:SYMBOL:TF]
indicator_service (I1 indicators)
  ↓ [indicators:SYMBOL:TF]
market_analysis_service (I3-I6 intelligence)
  ↓ [intelligence:SYMBOL:TF]
  ├─→ signal_generator_service (I7 signals)
  │     ↓ [signals:SYMBOL:TF:aggregated]
  │     ├─→ ai_narrative_service (I8 narratives)
  │     │     ↓ [narratives:SYMBOL:TF, narratives:group:*]
  │     └─→ signal_tracker_service (signal lifecycle)
  │           ↓ [market:SYMBOL:1m → signal_ledger updates]
  └─→ feature_writer_service (batch persistence)
        ↓ [intelligence_features, signal_ledger]
TimescaleDB
```

**Systemd Services (9 units):**

| Service | Port | Dependencies | Restart Policy |
|---------|------|-------------|----------------|
| `indicagent-tws` | - | `network-online.target`, `Restart=always`, unlimited restarts |
| `indicagent-indicator` | 9109 | `After=tws`, `Wants=tws`, `Restart=always`, max 5 per 5 min |
| `indicant-market-analysis` | 9114 | `After=indicator`, `Wants=indicator`, same restart limits |
| `indicant-signal-generator` | 9112 | `After=market-analysis`, same restart limits |
| `indicant-signal-tracker` | 9115 | `After=signal-generator`, same restart limits |
| `indicant-ai-narrative` | 9113 | `After=market-analysis`, `TimeoutStopSec=75` |
| `indicant-feature-writer` | 9116 | `After=indicator`, same restart limits |
| `indicant-api` | 8000 | `After=network-online.target`, FastAPI + SSE |
| `indicant-weight-updater` | - | Timer daily at 02:00 |

**Startup Order:** TWS → Indicator → Market Analysis + Feature Writer → Signal Generator → AI Narrative + Signal Tracker

---

## Part 2: Critical Gaps Analysis

### Gap 1: IBKR Connection Reliability

**Current State:**
```python
# src/providers/ibkr.py:61-80
async def connect(self) -> bool:
    try:
        self._ib = IB()
        await self._ib.connectAsync(
            host=self._host, port=self._port, clientId=self._client_id,
            timeout=20, readonly=False
        )
        return self._ib.isConnected()  # True or False
    except Exception as e:
        logger.error("IBKRProvider connect failed", error=str(e))
        return False  # Returns False, NO RETRY
```

**Problem:**
- No retry loop
- No exponential backoff
- No automatic reconnection
- Disconnects require **manual intervention** (kill and restart TWS daemon)
- IBKR internal auto-reconnect takes ~1 minute (per MEMORY.md), but only if TCP connection stays alive

**Impact:** High - TWS outages cause cascading data gaps across the entire pipeline.

---

### Gap 2: Feature Writer Data Loss

**Current State:**
```python
# services/feature_writer_service.py:339-347
if not self.db_manager:
    # No database connection available
    self.logger.warning(
        "No database connection — dropping buffered events",
        count=len(self._buffer)
    )
    self._buffer.clear()  # Permanent data loss!
```

**Problem:**
- When TimescaleDB is down, ALL buffered `IntelligenceEvent`s are dropped
- No backpressure mechanism (consumer stops ACKing)
- No dead letter queue for failed messages
- Buffer is in-memory only (lost on crash)

**Impact:** Critical - Database outages cause permanent data loss in `intelligence_features` (ML training dataset).

---

### Gap 3: No Consumer Lag Monitoring

**Current State:**
```python
# src/observability/metrics.py:131-135
REDIS_STREAM_LAG_GAUGE = Gauge(
    "redis_stream_consumer_lag_messages",
    "Redis Stream consumer lag in messages",
    ["stream_name", "consumer_group"],
)
# Metric is defined but NEVER used by any service
```

**Problem:**
- No `xpending()` calls to measure consumer backlog
- No visibility into how far behind consumers are
- Cannot detect when a service is overwhelmed
- No alerting when lag exceeds thresholds

**Impact:** Medium - Silent processing delays, degraded system health without detection.

---

### Gap 4: No Gap Detection

**Current State:**
- `intelligence_features` table gaps are **silent**
- No service to detect missing bars
- Manual `historical_backfill.py --days N` required
- No audit trail of gaps

**Problem:**
- TWS disconnects cause gaps that accumulate indefinitely
- ML models trained on incomplete data
- Backtesting results are inaccurate
- Signal quality metrics are skewed

**Impact:** High - Silent data loss undermines platform reliability and ML model quality.

---

### Gap 5: At-Most-Once Delivery Semantics

**Current State:**
- Consumer groups start at `$` (current tail) on restart
- No replay of missed messages
- `ensure_consumer_group_with_reset()` prevents stale backlog replay

**Problem:**
- Service restart = permanent data loss for downtime period
- No recovery mechanism
- Acceptable for tick data (display only)
- **Unacceptable** for ML training data

**Impact:** Medium - Compromises data completeness, violates "data completeness is important" requirement.

---

### Gap 6: Limited Observability

**Current State:**
- Each service exposes Prometheus metrics on dedicated port
- **No Grafana dashboards** (manual Prometheus queries required)
- **No alerting rules** (no PagerDuty/OpsGenie/Email)
- Manual health checks only

**Problem:**
- No proactive monitoring
- No automated incident response
- No centralized view of system health
- Reactive troubleshooting only

**Impact:** Medium - Extended mean-time-to-detection (MTTD) and mean-time-to-resolution (MTTR).

---

## Part 3: Three Architecture Approaches

### Approach 1: Minimal-Impact Resilience

**Summary:** Add only the most critical fixes to address data loss without over-engineering.

**Components Added:**
1. **IBKR Auto-Reconnection Wrapper** (`src/providers/ibkr_reconnect.py`)
2. **Consumer Lag Metrics** (`src/core/consumer_lag.py`)
3. **Feature Writer Backpressure** (modified `services/feature_writer_service.py`)
4. **Basic Gap Detection** (`services/gap_detection_service.py` - scan + alert only)

**What It Addresses:**
- ✅ IBKR auto-reconnect with exponential backoff (1s → 2s → 4s → max 30s)
- ✅ Feature writer stops ACKing when buffer >= 1000 (configurable)
- ✅ Consumer lag metrics exposed to Prometheus (`REDIS_STREAM_CONSUMER_LAG`)
- ✅ Gap detection scans every 5 minutes, writes to `intelligence_gaps` table
- ✅ Grafana dashboard with 4 basic panels

**What It Does NOT Address:**
- ❌ No replay on service restart (still at-most-once)
- ❌ No automatic gap backfill (manual trigger only)
- ❌ No state persistence for distributed recovery

**Implementation:**
- **Phases:** 2 (Connection Resilience, Gap Detection & Monitoring)
- **Time Estimate:** ~8 hours
- **Lines of Code:** ~500 LOC
- **Files:** 7 new, 6 modified

**Complexity:** ⭐ (Low) - Minimal changes, preserves existing architecture

**Data Completeness:** ~95% (gaps detectable but not auto-filled)

**Suitable For:**
- Quick wins, limited development time
- Team without extensive operations experience
- Proof-of-concept for resilience patterns

---

### Approach 2: Balanced Production-Grade Resilience ⭐ **RECOMMENDED**

**Summary:** Full resilience with replay service, gap detection, and backpressure - production-ready.

**Components Added:**
1. **IBKR Auto-Reconnection with Health Monitoring** (`src/providers/connection_manager.py`)
2. **Replay Coordinator Service** (`services/replay_coordinator_service.py`)
3. **Gap Detection Service with Auto-Backfill** (`services/gap_detection_service.py`)
4. **Enhanced Feature Writer Backpressure** (modified with circuit breaker)
5. **Consumer Lag Monitoring** (integrated into all 6 services)
6. **Grafana Dashboard** (8 panels with alerting rules)

**What It Addresses:**
- ✅ IBKR auto-reconnect with exponential backoff + health monitoring
- ✅ Replay coordinator tracks checkpoints, intelligently rewinds on restart
- ✅ Gap detection automatically triggers `historical_backfill.py`
- ✅ Feature writer circuit breaker (zero data loss)
- ✅ Comprehensive Grafana dashboard with alerting
- ✅ Consumer lag monitoring with heatmap visualization

**What It Does NOT Address:**
- ❌ No distributed state management (local Redis only)
- ❌ No multi-region DR plan
- ❌ No service mesh (hardcoded systemd dependencies)

**Implementation:**
- **Phases:** 5 (Foundation, IBKR Reconnect, Feature Writer Backpressure, Replay Coordinator, Gap Detection & Monitoring)
- **Time Estimate:** ~22 hours (3 days)
- **Lines of Code:** ~2200 LOC
- **Files:** 14 new, 10 modified

**Complexity:** ⭐⭐⭐ (Medium) - Professional patterns, clear separation of concerns

**Data Completeness:** ~98% (replay + auto-backfill)

**Suitable For:**
- Production environments requiring reliability
- Teams with moderate operations experience
- Platform with ML training needs
- Future scaling consideration

---

### Approach 3: Enterprise-Grade Architecture

**Summary:** Full production stack with state management, DR planning, and comprehensive observability.

**Everything in Approach 2, plus:**
1. **Distributed State Manager** (Redis-backed state with TTL)
2. **Multi-Region Disaster Recovery Plan**
3. **Service Discovery** (Consul/K8s patterns)
4. **Audit Logging for Compliance**
5. **Advanced Observability** (Loki logs, Tempo tracing)

**What It Addresses:**
- ✅ Everything in Approach 2
- ✅ Distributed replay (multi-host ready)
- ✅ DR plan with failover strategies
- ✅ Audit trail for compliance (SEC-style logging)
- ✅ Centralized logging (Loki) + distributed tracing (Tempo)

**What It Does NOT Address:**
- N/A - This is the most complete approach

**Implementation:**
- **Phases:** 9 (Foundation, IBKR, Feature Writer, Replay, Gap Detection, Monitoring, State Management, Service Discovery, DR Planning)
- **Time Estimate:** ~28 hours (4 days)
- **Lines of Code:** ~2200 LOC (similar to Approach 2, but with enterprise patterns)
- **Files:** 19 new, 10 modified

**Complexity:** ⭐⭐⭐⭐ (High) - Enterprise patterns, requires ops maturity

**Data Completeness:** ~99%

**Suitable For:**
- Regulated environments requiring audit compliance
- Multi-region deployments
- Organizations with dedicated ops teams
- Mission-critical trading platforms

---

## Part 4: Approach Comparison Matrix

| Feature | Approach 1 (Minimal) | Approach 2 (Balanced) ⭐ | Approach 3 (Enterprise) |
|----------|------------------------|-------------------------|-------------------|
| **IBKR Auto-Reconnect** | Basic backoff | + health monitoring | + health + state management |
| **Replay on Restart** | ❌ None | ✅ Replay coordinator | ✅ Distributed replay |
| **Gap Detection** | ✅ Alert only | ✅ Auto-trigger backfill | ✅ Auto-trigger + DR |
| **Auto-Backfill** | ❌ Manual only | ✅ Automatic via gap service | ✅ Automatic + DR |
| **Feature Writer Backpressure** | Stop ACKing | Circuit breaker (zero loss) | Circuit + DB lag metrics |
| **Consumer Lag Metrics** | ✅ Basic | ✅ Comprehensive + heatmap | ✅ Full + distributed |
| **Grafana Dashboard** | 4 basic panels | 8 panels + alerting | 8 panels + full alerting |
| **State Persistence** | ❌ None | ✅ Local Redis | ✅ Distributed + TTL |
| **Multi-Host Ready** | ⚠️ Manual changes | ✅ Service discovery ready | ✅ K8s/Consul ready |
| **DR Planning** | ❌ None | ❌ Basic plan | ✅ Full DR plan |
| **Audit Logging** | ❌ None | ❌ None | ✅ Compliance-ready |
| **Implementation Time** | ~8 hours | ~22 hours | ~28 hours |
| **Lines of Code** | ~500 LOC | ~2200 LOC | ~2200 LOC |
| **Complexity** | ⭐ Low | ⭐⭐⭐ Medium | ⭐⭐⭐⭐ High |
| **Data Completeness** | ~95% | ~98% | ~99% |
| **Ops Overhead** | Low | Low-Medium | High |
| **Learning Curve** | Shallow | Moderate | Steep |
| **Future-Proof** | Limited | Good | Excellent |

---

## Part 5: Recommendation: Approach 2 (Balanced)

### Why Approach 2?

Based on your stated goals:

> "99.9% uptime is fine" ✅
> "IBKR needs to restart" ✅ (with auto-reconnect)
> "Data completeness is important" ✅ (replay service)
> "Auto detect and fill gaps" ✅ (gap detection + auto-backfill)
> "Single machine now but we want to plan for robust" ✅ (future-proof)
> "Providing for robust monitoring" ✅ (Grafana dashboard)
> "Eventually multi-tenant" ✅ (service discovery ready)
> "Balanced and leaning towards professional" ✅

**Approach 2 is the optimal choice because:**

1. **Addresses All Critical Gaps:**
   - IBKR reliability (auto-reconnect + health monitoring)
   - Feature writer data loss (circuit breaker + backpressure)
   - No consumer lag visibility (comprehensive metrics)
   - Gap detection (automatic scans + backfill triggers)
   - Data completeness (replay service for at-least-once delivery)

2. **Reasonable Complexity:**
   - ~22 hours implementation (3 days) - manageable sprint
   - Clean separation of concerns (replay, gap detection, monitoring are independent)
   - Builds on existing infrastructure (historical_backfill.py, consumer groups)
   - No breaking changes to delivery semantics (replay is opt-in)

3. **Professional-Grade Features:**
   - Grafana dashboard with 8 panels
   - Prometheus alerting rules (lag > threshold, buffer > 80%, etc.)
   - Circuit breaker pattern (3-state machine)
   - Comprehensive observability (service health, consumer lag, buffer sizes)
   - Documentation and operations playbooks

4. **Future-Proof:**
   - Service discovery patterns in place (can extend to multi-host)
   - State management ready for distributed deployment
   - Monitoring foundation scalable (can add Loki/Tempo later)

5. **Low Risk:**
   - Builds on existing, battle-tested patterns
   - All new services follow established service template
   - Can implement incrementally (phases can be shipped separately)
   - Rollback possible (each phase is atomic)

### When to Consider Approach 3

**Switch to Approach 3 when:**
- Multi-region deployment is planned (active-active DR)
- Regulatory compliance requires audit logging (SEC, FINRA)
- Dedicated ops team is available to manage DR, monitoring stack
- Platform is mission-critical for regulated trading

**Transition Path:** Approach 2 → Approach 3 is additive. You can upgrade to enterprise features without discarding balanced approach work.

---

## Part 6: Implementation Strategy for Approach 2

### Phase 1: Foundation (2-3 hours)

**Goals:** Add resilience infrastructure without touching data path.

**Tasks:**
1. Create generic `CircuitBreaker` class in `src/resilience/circuit_breaker.py`
2. Create `consumer_lag.py` metrics helper
3. Add Prometheus service to `docker-compose.yml`
4. Write unit tests for circuit breaker and lag metrics

**Verification:**
- Prometheus service scrapes all existing services
- New metrics exposed on `/metrics` endpoints
- Unit tests pass

---

### Phase 2: IBKR Auto-Reconnection (4-5 hours)

**Goals:** Reliable TWS connection with exponential backoff and health monitoring.

**Tasks:**
1. Create `ConnectionManager` class in `src/providers/connection_manager.py`
2. Integrate `ConnectionManager` into `IBKRProvider` in `src/providers/ibkr.py`
3. Add health monitoring loop to TWS daemon
4. Add Prometheus metrics (`ibkr_connection_state`, `ibkr_reconnect_attempts_total`)

**Key Design:**
```python
class ConnectionManager:
    async def ensure_connected(self) -> bool:
        """Loop until connected with exponential backoff."""
        while not self.is_connected:
            try:
                await self._ib.connectAsync(...)
                self.backoff_sec = 1  # Reset on success
            except Exception:
                self.backoff_sec = min(self.backoff_sec * 1.5, self.max_backoff)
                await asyncio.sleep(self.backoff_sec)
```

**Verification:**
- Kill TWS daemon, verify auto-reconnect happens
- Verify exponential backoff in logs
- Check Prometheus metrics update

---

### Phase 3: Feature Writer Backpressure (4-5 hours)

**Goals:** Zero data loss during database outages.

**Tasks:**
1. Add `CircuitBreaker` to `feature_writer_service`
2. Add backpressure logic (stop consuming when circuit OPEN)
3. Add buffer metrics (`feature_writer_buffer_size`, `feature_writer_circuit_state`)
4. Remove drop-when-db-unavailable logic

**Key Changes:**
```python
# NEW: Circuit breaker state management
self.circuit_breaker = CircuitBreaker(self.config)

# NEW: Backpressure check in _process_loop
if self.circuit_breaker.is_open("feature_writer_db"):
    await asyncio.sleep(0.1)  # Don't consume from streams
    continue  # Skip xreadgroup

# NEW: Buffer never drops, only drains on flush
# REMOVED: self._buffer.clear() when db_manager is None
```

**Verification:**
- Stop TimescaleDB, verify buffer grows but stops ACKing
- Check Prometheus `feature_writer_buffer_high_watermark_total` counter
- Restart DB, verify buffer drains and resumes

---

### Phase 4: Replay Coordinator (5-6 hours)

**Goals:** Track consumer positions and intelligently rewind on restart to recover missed data.

**Tasks:**
1. Create `replay_coordinator_service.py`
2. Add `replay_checkpoints` table (migration 013)
3. Add checkpoint saving to all 6 services
4. Implement gap detection logic (XINFO vs checkpoint comparison)
5. Implement rewind to last safe position
6. Coordinate with `historical_backfill.py` for targeted backfill

**Key Design:**
```python
class ReplayCoordinator:
    async def save_checkpoint(self, stream: str, group: str, last_id: str):
        await redis.hset(f"checkpoints:{stream}:{group}", "last_id", last_id)

    async def get_checkpoint(self, stream: str, group: str) -> str | None:
        return await redis.hget(f"checkpoints:{stream}:{group}", "last_id")

    async def detect_gap(self, stream: str, group: str) -> bool:
        xinfo = await redis.xinfo_stream(stream, group_name=group)
        last_delivered_id = xinfo['groups'][group]['last-delivered-id']
        checkpoint_id = await self.get_checkpoint(stream, group)
        # Gap if checkpoint_id != last_delivered_id and difference > threshold
```

**Verification:**
- Stop `signal_generator_service`, verify replay coordinator detects gap
- Verify rewind happens (consumer position moves back)
- Verify backfill is triggered for large gaps

---

### Phase 5: Gap Detection Service (4-5 hours)

**Goals:** Automatic gap detection with backfill triggering.

**Tasks:**
1. Create `gap_detection_service.py`
2. Implement SQL gap scan query
3. Add `intelligence_gaps` table (migration 013)
4. Implement `historical_backfill.py` coordination
5. Add Prometheus metrics (`intelligence_gaps_detected_total`)
6. Create systemd unit

**Key Design:**
```python
async def scan_for_gaps(self) -> None:
    for symbol in symbols:
        for tf in timeframes:
            expected = generate_expected_ts(symbol, tf, hours=24)
            actual = await db.fetch(
                "SELECT ts FROM intelligence_features "
                "WHERE symbol=$1 AND tf=$2 AND ts >= NOW() - INTERVAL '1 day' "
                "ORDER BY ts",
                symbol, tf
            )
            gaps = compare_timestamps(expected, actual)
            for gap in gaps:
                await insert_gap_record(gap)
                await emit_gap_metric(symbol, tf, len(gap.missing_bars))
```

**Verification:**
- Manually delete 1h of `intelligence_features`, verify gap detected
- Verify gap record written to `intelligence_gaps` table
- Check Prometheus metric increments
- Test backfill triggering

---

### Phase 6: Monitoring & Dashboard (3-4 hours)

**Goals:** Professional observability with Grafana dashboards and alerting.

**Tasks:**
1. Create `production/grafana/indicagent-resilience-dashboard.json`
2. Configure Prometheus datasource
3. Add alerting rules (Prometheus AlertManager format)
4. Integrate consumer lag metrics into all 6 services
5. Test dashboard panels render correctly

**Dashboard Panels:**
1. **Service Health** - Uptime, restart counts, error rates
2. **Consumer Lag Heatmap** - 23 symbols × 4 timeframes matrix, color-coded by lag
3. **Feature Writer Buffer** - Buffer size, backpressure state, DB lag
4. **IBKR Connection** - Connection state, uptime, reconnection attempts
5. **Intelligence Gaps** - Missing bar counts per symbol/TF (heatmap)
6. **Database Health** - Connection pool stats, query latency
7. **Stream Retention** - Current length vs maxlen (memory pressure)
8. **Replay Coordinator Status** - Checkpoints, rewinds, backfill jobs

**Alerting Rules:**
- Critical: Consumer lag > 1000 messages OR gap > 50 bars
- Warning: Buffer > 80% capacity OR circuit open > 5 min
- Info: Circuit state changes

**Verification:**
- Import dashboard into Grafana
- Verify all panels populate with data
- Test alert rules (simulate condition, verify alert fires)

---

### Phase 7: Systemd & Deployment (1-2 hours)

**Goals:** Orchestrate service startup with proper dependencies.

**Tasks:**
1. Create `indicagent-replay-coordinator.service`
2. Create `indicagent-gap-detection.service`
3. Add `After=redis.service` dependencies
4. Update existing services for checkpoint calls
5. Reload systemd: `daemon-reload`
6. Test full stack restart

**Systemd Unit Example:**
```ini
[Unit]
Description=IndicAgent Replay Coordinator Service
After=network-online.target redis.service
Wants=redis.service
Requires=redis.service

[Service]
Type=notify
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/replay_coordinator_service.py
Restart=always
RestartSec=10
StartLimitBurst=5
StartLimitIntervalSec=300
User=bg
Environment=INDICAGENT_ENV=production
```

**Verification:**
- Stop all services, start Redis
- Verify services start in correct order
- Check systemd journal for errors
- Verify metrics endpoints accessible

---

### Phase 8: Documentation (2-3 hours)

**Goals:** Update documentation and create operations playbooks.

**Tasks:**
1. Update `CLAUDE.md` with new services and architecture
2. Create `docs/operations/gap-fill-playbook.md` (troubleshooting guide)
3. Update `docs/cheatsheet.md` with new commands
4. Document Grafana dashboard URL and access
5. Create architecture diagram (Mermaid or similar)

**Operations Playbook Sections:**
- Gap interpretation (false positives, market hours)
- Running manual backfill (`historical_backfill.py --replay-only`)
- Gap verification queries
- Common failure scenarios and resolution steps

**Verification:**
- Review documentation for clarity
- Test procedures documented in playbook
- Verify docs links work

---

### Phase 9: Testing & QA (4-6 hours)

**Goals:** Comprehensive testing before production deployment.

**Tasks:**
1. Unit tests for all new components (~500 lines of test code)
2. Integration tests for IBKR reconnection, replay coordinator, gap detection
3. Failure simulation tests (DB down, TWS disconnect, network partition)
4. Load testing (24h tick stream, verify no memory leaks)
5. End-to-end gap detection and backfill verification
6. Ruff lint check: `.venv/bin/ruff check . --fix`

**Test Scenarios:**
- **IBKR Reconnection:** Kill TWS, verify auto-reconnect with backoff
- **DB Outage:** Stop PostgreSQL, verify backpressure, verify recovery
- **Service Restart:** Kill `signal_generator_service`, verify replay happens
- **Gap Detection:** Manually delete bars, verify gap detected within 5 min
- **Consumer Lag:** Stop `indicator_service`, verify lag metric increases
- **Full Outage:** Stop TWS + DB, verify graceful degradation

**Success Criteria:**
- All unit tests pass (target: 80% coverage)
- All integration tests pass
- Ruff: 0 errors
- Grafana dashboard renders correctly
- No regressions in existing functionality

---

## Part 7: Files Reference

### New Files to Create (14)

**Core Infrastructure:**
```
src/resilience/circuit_breaker.py              # Generic circuit breaker
src/core/consumer_lag.py                    # Lag metrics helper
production/docker-compose.yml                     # Prometheus service
production/grafana/indicagent-resilience-dashboard.json
```

**Services:**
```
services/replay_coordinator_service.py         # Replay checkpoint management
services/gap_detection_service.py             # Gap scan + backfill
src/providers/connection_manager.py             # IBKR auto-reconnect
```

**Database:**
```
production/migrations/013_replay_checkpoints.sql         # Checkpoints table
production/migrations/014_intelligence_gaps.sql         # Gap audit table
```

**Systemd:**
```
production/systemd/indicagent-replay-coordinator.service
production/systemd/indicagent-gap-detection.service
```

**Documentation:**
```
docs/operations/gap-fill-playbook.md
docs/architecture/resilience-improvements.md
CLAUDE.md (update)
```

### Files to Modify (10)

**Services with checkpoint calls:**
```
services/indicator_service.py
services/market_analysis_service.py
services/signal_generator_service.py
services/feature_writer_service.py
services/ai_narrative_service.py
services/signal_tracker_service.py
```

**Feature writer:**
```
services/feature_writer_service.py  # Add circuit breaker, backpressure
```

**Metrics:**
```
src/observability/metrics.py  # Add lag gauges, backpressure counters
```

---

## Part 8: Success Criteria

### Before Deployment

- [ ] All 9 phases completed
- [ ] All unit tests pass (80% coverage)
- [ ] All integration tests pass
- [ ] Ruff: 0 errors
- [ ] Grafana dashboard deployed and verified
- [ ] Documentation updated
- [ ] Operations playbook reviewed

### Production Deployment

- [ ] Deployed to staging environment
- [ ] Monitored for 24 hours
- [ ] All metrics within normal ranges
- [ ] No critical alerts
- [ ] Performance benchmarks met

### Post-Deployment

- [ ] Ops team trained on new dashboards
- [ ] Incident response procedures documented
- [ ] Weekly review of gap detection effectiveness

---

## Appendix: Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL DATA SOURCES                            │
└──────────────────────┬──────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                   HOT TIER: DragonflyDB Streams                           │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ ticks:*:live│  │ market:*:*   │  │ indicators:*:*   │  │ intelligence:*:*│  │
│  │ maxlen:20k  │  │ maxlen:500-2k│  │ maxlen:1k        │  │ maxlen:1k       │  │
│  └──────┬──────┘  └──────┬───────┘  └────────┬─────────┘  └───────┬────────┘  │
│         │                 │                   │                    │              │
│         │         ┌───────▼──────────────────▼────────────────────▼───────┐    │
│         │         │    NEW: Replay Coordinator (strategic replay)   │    │
│         │         │  - Tracks consumer group positions                     │    │
│         │         │  - Intelligent rewind on service restarts              │    │
│         │         └───────┬──────────────────┬────────────────────┬────────┘    │
│         │                 │                  │                    │              │
│         ▼                 ▼                  ▼                    ▼              │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ indicator   │  │ market       │  │ signal_gen       │  │ feature_writer │  │
│  │ service     │  │ analysis     │  │ service          │  │ service        │  │
│  │ (+backpres) │  │ (+backpres)  │  │ (+backpres)      │  │ (+circuit)    │  │
│  └──────┬──────┘  └──────┬───────┘  └────────┬─────────┘  └───────┬────────┘  │
│         │                 │                  │                    │              │
│         ▼                 ▼                  ▼                    ▼              │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                  WARM TIER: Service Caches (in-memory)                  │   │
│  │  - bar_history (deque maxlen=200)                                      │   │
│  │  - intelligence_cache (cross-TF context)                                │   │
│  │  - Local checkpointing for replay offsets                              │   │
│  └────────────────────────┬────────────────────────────────────────────────────────┘   │
└───────────────────────────┼────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                   COLD TIER: TimescaleDB Hypertables                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────────┐  │
│  │market_data_ohlcv│  │intelligence_feat │  │signal_ledger                 │  │
│  │90d retention    │  │indefinite       │  │365d retention               │  │
│  │(named/continuous)│  │7d compression   │  │outcome tracking              │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────────┬───────────────────┘  │
│           │                     │                       │                        │
│           │         ┌───────────▼──────────────────────▼───────┐              │
│           │         │   NEW: Gap Detection & Backfill Service   │              │
│           │         │  - Periodic gap scans (intelligence_feat) │              │
│           │         │  - Auto-trigger IBKR backfill             │              │
│           │         │  - Integrity verification                 │              │
│           │         └───────────────────────────────────────────┘              │
└───────────┼───────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      OBSERVABILITY: Prometheus + Grafana                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ NEW: Comprehensive Metrics Dashboard                                     │ │
│  │  - Consumer lag per stream (REDIS_STREAM_CONSUMER_LAG)                  │ │
│  │  - Backpressure buffer sizes (SERVICE_BUFFER_SIZE)                       │ │
│  │  - Circuit breaker states (CIRCUIT_BREAKER_STATE)                       │ │
│  │  - Gap detection alerts (DATA_GAPS_TOTAL)                                │ │
│  │  - Replay coordinator status (REPLAY_CHECKPOINTS)                       │ │
│  │  - IBKR connection health (IBKR_CONNECTION_STATE)                       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Next Steps

This plan document is complete. When you're ready to proceed with **Approach 2 (Balanced)**, I recommend using the **superpowers:executing-plans** skill to:

1. Review this plan document
2. Ask clarifying questions if any
3. Begin phase-by-phase implementation
4. Use code-reviewer skill after each phase
5. Run verification-before-completion before claiming done

**Estimated Timeline:**
- Planning: ✅ Complete (this document)
- Implementation: ~22 hours (3 days) across 5 phases
- Testing: ~6 hours
- Deployment & Documentation: ~4 hours
- **Total: ~32 hours** (4-5 days)

---

**Document Status:** ✅ Analysis Complete
**Recommended Approach:** Approach 2 (Balanced Production-Grade Resilience)
**Next Action:** Review plan and begin implementation when ready
