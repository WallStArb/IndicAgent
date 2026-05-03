# BaseWriterAgent Renaissance Refactor: Ship-Ready Design

**Last Updated:** 2026-05-02

**Status:** Ready | **Created:** 2026-04-13 | **Author:** Claude (Senior Engineer Review)
**Phase:** 69 | **Priority:** CRITICAL | **Effort:** 2-3 days (single wave)

## Executive Summary

Current BaseWriterAgent implementation violates core Renaissance principles:
- **Two patterns** for consumer creation (simplicity violation)
- **Duplication** in `_run()` loops across 6 writers (modularity violation)
- **Silent data loss** on buffer overflow (data quality violation)
- **Insufficient observability** — only buffer depth + overflow (instrumentation violation)

**Jim Simons' verdict:** *"It's not in prod? Build it RIGHT. Ship clean. Instrument everything from day one. No technical debt. No process overhead."*

**Impact:** This refactor eliminates duplication, prevents data loss, adds 7 critical Prometheus metrics, and ships Renaissance-compliant architecture from day one. Pre-production context enables aggressive refactoring without canary/gradual rollout overhead.

---

## Renaissance Principles Alignment

| Principle | Current State | Target State |
|-----------|---------------|--------------|
| **Simplicity** | 2 patterns for consumer creation | 1 pattern enforced by base class |
| **Modularity** | 6 duplicated `_run()` loops | 1 loop in base class (feature_writer exception) |
| **Data Quality** | Silent buffer overflow = data loss | Critical alerts + backpressure |
| **Instrument Everything** | Only buffer depth + overflow | 7 metrics (e2e, flush, commit, DB, parse, errors, lag) |
| **No Process Overhead** | N/A | Single-wave execution, ship when tests pass |

---

## Current Architecture Problems

### Problem 1: Dual Consumer Creation Patterns

**Pattern A** (3 writers): Direct assignment
```python
# signal_writer, swarm_writer, lifecycle_writer
self._consumer = KafkaConsumerClient(topic, ...)
```

**Pattern B** (2 writers): Wire after creation
```python
# bar_writer, feature_writer
self._kafka_consumer = KafkaConsumerClient(topic, ...)
self._consumer = self._kafka_consumer  # Easy to forget!
```

**Violation:** Subclasses can forget the wiring → silent offset commit failure → consumer lag → reprocessing waste

---

### Problem 2: Duplicated Consume Loops

Every writer implements this loop:
```python
async for _topic, _key, payload in self._consumer.messages():
    if not self.running: break
    rows = self._parse_payload(payload)
    if rows is not None:
        self._buffer_rows(rows)
    await self.maybe_flush()
```

**Present in:** `bar_writer`, `feature_writer`, `lifecycle_writer`, `signal_writer`, `swarm_writer`

**Violation:** 6 copies = 6 places for bugs. No consistency in error handling, DLQ routing, or instrumentation.

---

### Problem 3: Silent Data Loss on Buffer Overflow

Current behavior:
```python
if len(self._buffer) > MAX_BUFFER_SIZE:
    dropped = len(self._buffer) - MAX_BUFFER_SIZE
    del self._buffer[:-MAX_BUFFER_SIZE]  # Drops data!
    self.logger.warning(...)  # Warning only!
```

**Violation:** `logger.warning()` is not an alert. No pager. No backpressure. Data drops silently in production.

---

### Problem 4: Insufficient Observability

**Current metrics:**
- `buffer_depth` gauge
- `buffer_overflow_total` counter

**Missing metrics:**
- End-to-end latency (consume → commit)
- Flush latency (DB write only)
- Offset commit latency (Kafka operation)
- DB write latency (per-batch)
- Parse failures (DLQ rate)
- Flush errors (retryable failures)
- Commit errors (commit failures)
- Consumer lag (messages behind head)

**Gap:** Cannot diagnose tail latency, reprocessing, or data quality issues without comprehensive metrics.

### Problem 5: No Offset Commit Verification

**What we test:** `await agent._flush_batch(batch)` succeeds

**What we DON'T test:** `await self._consumer.commit()` actually happens

**Gap:** If `_consumer` is None or lacks `commit()` method, tests pass but offsets don't commit → reprocessing on restart.

---

## Target Architecture

### Principle: One True Pattern

```python
# Subclass provides configuration ONLY
class BarWriterAgent(BaseWriterAgent):
    def _topic_name(self) -> str: ...
    @property
    def _consumer_group(self) -> str: ...
    def _parse_payload(self, payload: dict) -> list | None: ...
    async def _flush_batch(self, batch: list) -> None: ...

# Base class handles EVERYTHING else:
# - Consumer creation from abstract properties
# - Consume loop with DLQ routing (standard writers)
# - Buffer management with overflow alerts
# - Offset commits with verification
# - 7 Prometheus metrics (e2e, flush, commit, DB, parse, errors, lag)
```

### Key Improvements

1. **Base class creates consumer** — Subclasses provide config via properties
2. **Base class provides `_run()`** — Subclasses override only for special routing (feature_writer keeps 3-loop)
3. **Buffer overflow = critical alert** — Triggers critical log + backpressure pause
4. **Comprehensive observability** — 7 Prometheus metrics ship from day one
5. **Integration tests verify offsets** — Prove commits happen after flush

---

## Implementation Plan

### Plan 01: Base Class Creates Consumer (2h)

**Goal:** Eliminate dual consumer creation patterns

**Implementation:**
- Add abstract property to BaseWriterAgent: `_bootstrap_servers() -> str`
- Implement `BaseWriterAgent._setup_consumer()` called from `__init__`
- Subclasses remove all `self._consumer =` assignments
- Subclasses implement properties: `_topic_name()`, `_consumer_group`, `_bootstrap_servers()`

**Files:** `src/core/agent/base_writer.py` + 6 writer agents

**Acceptance:**
- ✅ All writers use identical consumer creation pattern
- ✅ No dual patterns remain

---

### Plan 02: Base Class Provides Consume Loop (3h)

**Goal:** Eliminate 6 duplicated `_run()` loops

**Implementation:**
- Implement `BaseWriterAgent._run()` with standard loop
- Add `BaseWriterAgent._route_to_dlq(payload)` method
- Subclasses remove their `_run()` implementations
- **Exception:** `feature_writer` keeps 3-loop pattern (process/flush/health monitor)

**Files:** `src/core/agent/base_writer.py` + 5 writer agents

**Acceptance:**
- ✅ 5/6 writers use base class `_run()`
- ✅ feature_writer keeps 3-loop pattern (proven high-throughput pattern)

---

### Plan 03: Buffer Overflow Critical Alert (1h)

**Goal:** Prevent silent data loss

**Implementation:**
- Change `logger.warning()` → `logger.error()` with `severity="critical"`
- Add backpressure: `await asyncio.sleep(1.0)` after overflow
- Update existing `buffer_overflow_total` counter (already exists)

**Files:** `src/core/agent/base_writer.py`

**Acceptance:**
- ✅ Buffer overflow triggers critical log
- ✅ Backpressure pause prevents cascade failures

---

### Plan 04: Comprehensive Observability (3h)

**Goal:** Add 7 Prometheus metrics for full observability

**Implementation:**
```python
# Add to BaseWriterAgent.__init__:
agent_snake = name.lower().replace(" ", "_")

# End-to-end latency (consume → commit)
self._e2e_latency_seconds = _get_or_create_histogram(
    f"{agent_snake}_e2e_latency_seconds",
    "End-to-end message processing (consume → commit)",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0]
)

# Flush latency (DB write only)
self._flush_latency_seconds = _get_or_create_histogram(
    f"{agent_snake}_flush_latency_seconds",
    "Batch flush latency (DB write only)",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
)

# Commit latency (Kafka operation)
self._commit_latency_seconds = _get_or_create_histogram(
    f"{agent_snake}_offset_commit_seconds",
    "Kafka offset commit latency",
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1]
)

# DB write latency (per-batch)
self._db_write_latency_seconds = _get_or_create_histogram(
    f"{agent_snake}_db_write_latency_seconds",
    "Database write latency per batch",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
)

# Parse failures (DLQ rate)
self._parse_failures_total = _get_or_create_counter(
    f"{agent_snake}_parse_failures_total",
    "Payload parse failures (routed to DLQ)"
)

# Flush errors (retryable failures)
self._flush_errors_total = _get_or_create_counter(
    f"{agent_snake}_flush_errors_total",
    "Batch flush failures (retried)"
)

# Commit errors (commit failures)
self._commit_errors_total = _get_or_create_counter(
    f"{agent_snake}_commit_errors_total",
    "Offset commit failures"
)

# Consumer lag (messages behind head)
self._consumer_lag = _get_or_create_gauge(
    f"{agent_snake}_consumer_lag",
    "Kafka consumer lag (messages behind head)"
)
```

**Instrument `_do_flush()`:**
```python
async def _do_flush(self) -> None:
    if not self._buffer:
        return

    batch = self._buffer[:]
    e2e_start = time.monotonic()

    try:
        # Measure DB write latency
        flush_start = time.monotonic()
        await self._flush_batch(batch)
        flush_duration = time.monotonic() - flush_start
        self._flush_latency_seconds.observe(flush_duration)

        self._buffer.clear()
        self._buffer_depth_gauge.set(0)

        # Measure commit latency
        if self._consumer and hasattr(self._consumer, "commit"):
            commit_start = time.monotonic()
            await self._consumer.commit()
            commit_duration = time.monotonic() - commit_start
            self._commit_latency_seconds.observe(commit_duration)

        # Measure end-to-end latency
        e2e_duration = time.monotonic() - e2e_start
        self._e2e_latency_seconds.observe(e2e_duration)

    except Exception:
        self._flush_errors_total.inc()
        self.logger.exception("flush_failed", batch_size=len(batch))
```

**Instrument `_run()`:**
```python
async def _run(self) -> None:
    async for _topic, _key, payload in self._consumer.messages():
        if not self.running:
            break

        self._record_message_consumed()

        # Parse + track failures
        rows = self._parse_payload(payload)
        if rows is not None:
            self._buffer_rows(rows)
        else:
            self._parse_failures_total.inc()
            await self._route_to_dlq(payload)

        # Update lag gauge
        lag = await self._consumer.get_watermark_offsets()
        if lag:
            self._consumer_lag.set(lag.high - lag.current)

        await self.maybe_flush()
```

**Files:** `src/core/agent/base_writer.py`

**Acceptance:**
- ✅ All 7 metrics defined and instrumented
- ✅ Histograms have appropriate buckets for tail latency
- ✅ Counters track error rates accurately
- ✅ Gauge reflects real-time consumer lag

---

### Plan 05: Offset Commit Integration Tests (2h)

**Goal:** Prove offset commits work correctly

**Implementation:**
```python
# tests/integration/test_offset_commit.py
async def test_offset_commit_after_flush():
    """Verify offset IS committed after successful flush."""
    agent = BarWriterAgent()
    await agent._setup()

    # Consume message
    # Verify offset NOT committed
    assert await get_committed_offset() == 0

    # Trigger flush
    await agent._do_flush()

    # Verify offset IS committed
    assert await get_committed_offset() == 1

async def test_offset_not_commit_on_flush_error():
    """Verify offset NOT committed when flush fails."""
    # Mock _flush_batch to raise exception
    # Trigger flush
    # Verify offset NOT committed
```

**Files:** `tests/integration/test_offset_commit.py`

**Acceptance:**
- ✅ Integration test proves offset commits after flush
- ✅ Integration test proves offset NOT committed on error

---

### Plan 06: Comprehensive Test Coverage (3h)

**Goal:** Extend existing 115 unit tests + add load tests

**Implementation:**
- Extend buffer overflow test to verify backpressure
- Extend DLQ routing test to verify base class method
- Add load test: 1000 msg/sec, 10K messages, zero data loss
- Add load test: Verify p95 e2e latency < 500ms

**Files:** `tests/unit/service_tests/`, `tests/load/`

**Acceptance:**
- ✅ All 115 unit tests passing
- ✅ New integration tests passing
- ✅ Load tests pass (throughput + latency + zero data loss)

---

### Plan 07: Update All 6 Writers (4h)

**Goal:** Migrate all writers to use base class patterns

**Implementation:**
- Remove consumer creation from all 6 writers
- Remove `_run()` from 5 writers (feature_writer keeps 3-loop)
- Verify all writers pass tests

**Files:** `services/*_writer_agent.py`

**Acceptance:**
- ✅ All writers use base class consumer creation
- ✅ 5/6 writers use base class `_run()`
- ✅ All writers pass tests

---

## Testing Strategy

### Unit Tests (Already Passing: 115)
- ✅ Buffer accumulation
- ✅ Flush batch behavior
- ✅ Overflow guard (extend to test backpressure)
- ✅ DLQ routing (extend to test base class method)

### Integration Tests (New)
```python
# tests/integration/test_offset_commit.py
async def test_offset_commit_after_flush():
    """Verify offset IS committed after successful flush."""
    agent = BarWriterAgent()
    await agent._setup()
    
    # Consume message
    # Verify offset NOT committed
    assert await get_committed_offset() == 0
    
    # Trigger flush
    await agent._do_flush()
    
    # Verify offset IS committed
    assert await get_committed_offset() == 1

async def test_offset_not_commit_on_flush_error():
    """Verify offset NOT committed when flush fails."""
    # Mock _flush_batch to raise exception
    # Trigger flush
    # Verify offset NOT committed
```

### Load Tests (New)
```python
# tests/load/test_writer_throughput.py
async def test_1000_msgs_sec_no_data_loss():
    """Verify no data loss at peak throughput."""
    agent = BarWriterAgent()
    await agent._setup()
    
    # Send 10000 messages at 1000/sec
    # Verify all 10000 persisted
    # Verify no buffer overflows
    # Verify offset lag < 100
```

---

## Success Criteria

### Functional Requirements
- ✅ All 6 writers use single consumer creation pattern
- ✅ 5/6 writers use base class `_run()` loop (feature_writer keeps 3-loop)
- ✅ Buffer overflow triggers critical alert
- ✅ Offset commits verified by integration test

### Observability Requirements
- ✅ `e2e_latency_seconds` histogram (10 buckets: 1ms-5s)
- ✅ `flush_latency_seconds` histogram (7 buckets: 1ms-5s)
- ✅ `commit_latency_seconds` histogram (7 buckets: 0.1ms-100ms)
- ✅ `db_write_latency_seconds` histogram (7 buckets: 1ms-1s)
- ✅ `parse_failures_total` counter
- ✅ `flush_errors_total` counter
- ✅ `commit_errors_total` counter
- ✅ `consumer_lag` gauge

### Non-Functional Requirements
- ✅ Throughput > 1000 msg/sec per writer (load test)
- ✅ p95 e2e latency < 500ms (load test)
- ✅ Zero data loss in load test (1000 msg/sec, 10K messages)
- ✅ All tests passing (115 unit + integration + load)

### Renaissance Principles Compliance
- ✅ **Simplicity:** One pattern for consumer creation
- ✅ **Modularity:** Base class owns consume loop
- ✅ **Data Quality:** Buffer overflow alerts + backpressure
- ✅ **Instrument Everything:** 7 metrics ship from day one
- ✅ **No Process Overhead:** Single-wave execution

---

## Risk Mitigation

### Risk 1: Breaking Changes to Writers
**Mitigation:** Extensive test coverage (115 passing) + load tests before deployment

### Risk 2: Performance Regression
**Mitigation:** Load tests verify throughput + latency; pre-production context = no prod impact

### Risk 3: Kafka Consumer Complexity
**Mitigation:** Keep current `KafkaConsumerClient` wrapper, just move instantiation to base class

### Risk 4: Feature Writer 3-Loop Pattern
**Mitigation:** Recognize this as the CORRECT pattern for high-throughput writers; don't force into base class `_run()`

---

## Rollback Plan

Pre-production context: Simple revert if tests fail during development.

If issues detected after deployment:
1. `git revert <commit-hash>` — Revert refactor
2. `sudo systemctl restart indicagent-*` — Restart all writers
3. Verify: Tests passing, no errors

**No canary, no gradual rollout — ship when tests pass.**

---

## Execution Timeline

**Day 1: Foundation (6 hours)**
- Plans 01-03: Base class consumer creation + consume loop + critical alerts

**Day 2: Observability + Tests (8 hours)**
- Plan 04: Comprehensive observability (7 Prometheus metrics)
- Plan 05: Offset commit integration tests
- Plan 06: Comprehensive test coverage

**Day 3: Migration + Ship (4 hours)**
- Plan 07: Update all 6 writers
- Run full test suite (unit + integration + load)
- Ship it

**Total:** 18 hours (2-3 days)

---

## Open Questions

1. **Q:** Should we add background flush?
   **A:** Not in Phase 69. Add only if load tests show p95 > 500ms AND lag > 10000. Measure first.

2. **Q:** Should we add auto-tuning batch sizes?
   **A:** Not in Phase 69. Add only if batch size correlates with latency (R² > 0.7). Measure first.

3. **Q:** What about feature_writer's custom _run() for roll events?
   **A:** Keep 3-loop pattern — it's the correct pattern for high-throughput writers.

4. **Q:** Should we make DLQ mandatory?
   **A:** Yes. Change `_dlq_topic()` from `def _dlq_topic() -> str | None` to `@abc.abstractmethod` in future phase.

5. **Q:** Why no Grafana dashboard?
   **A:** Metrics ship first, dashboard can wait. Prometheus scraping is sufficient for observability.

---

## Next Steps

1. **Execute Plan 01** — Base class creates consumer (2h)
2. **Execute Plan 02** — Base class provides consume loop (3h)
3. **Execute Plan 03** — Buffer overflow critical alert (1h)
4. **Execute Plan 04** — Comprehensive observability (3h)
5. **Execute Plan 05** — Offset commit integration tests (2h)
6. **Execute Plan 06** — Comprehensive test coverage (3h)
7. **Execute Plan 07** — Update all 6 writers (4h)
8. **Run full test suite** — Unit + integration + load
9. **Ship it** — Update ROADMAP.md with Phase 69 complete

**Total:** 18 hours (2-3 days, single wave)

---

**Jim Simons would ask:** *"It's not in prod? Then build it RIGHT. Ship clean. Instrument everything from day one. No technical debt. No process overhead."*

**Verdict:** Do it. Ship Renaissance-compliant architecture from day one. 7 metrics, zero data loss, single-pattern, test-driven. No canary, no baseline, no gradual rollout — ship when tests pass.
