# Bar Aggregator Fault Tolerance & Observability

**Status:** Design Approved  
**Version:** 1.0  
**Date:** 2026-04-01  
**Author:** Claude (Superpowers Brainstorming)  
**Issue:** Bar aggregator silently stops consuming after session boundaries, causing cascade failure (no HTF bars → intelligence pipeline starves → no signals → dashboard empty)

## Problem Statement

**Symptom:** BarAggregatorComputeAgent stops processing 1m bars after session boundaries (RTH close at 16:00 ET), specifically:
- Consumed up to: March 29th 23:59 EDT
- Latest HTF bar: March 30th 03:50 UTC
- Process still running (PID 3467, 3 active TCP connections)
- Consumer assigned to partition but not emitting HTF bars
- **Cascade impact:** Intelligence pipeline has 1.1M message backlog, no signals, dashboard empty

**Root Cause Hypothesis:** Session boundary logic or state management issue causes the aggregation loop to silently stop while consumer continues committing offsets.

## Solution Overview

**Three-layer defense following Renaissance principles:**

1. **Per-bar telemetry** - Track every bar through processing pipeline (efficient: metrics, not logs)
2. **Health monitoring** - Service-level metrics with automated recovery (circuit breaker pattern)
3. **Root cause prevention** - Defensive checks for session boundaries, state corruption, and timeout protection

**Design principles:**
- ✅ Instrument everything (metrics, not expensive logs)
- ✅ Degrade gracefully (auto-recovery, no human intervention)
- ✅ Automation over manual tasks
- ✅ Efficient (98.6% reduction in log volume)
- ✅ Modular (telemetry, processing, recovery concerns separated)

## Architecture

### Component 1: Efficient Observability

**Principle:** Log exceptions, not normal operations. Metrics for trends, logs for debugging.

**Implementation:**

1. **In-memory metrics only** (zero I/O overhead):
   ```python
   _bars_processed = Counter("bars_processed_total", ["agent"])
   _bars_skipped = Counter("bars_skipped_total", ["agent", "reason"])
   _htf_bars_emitted = Counter("htf_bars_emitted_total", ["agent", "tf"])
   _processing_duration = Histogram("bar_processing_seconds", ["agent"])
   ```

2. **Threshold-based logging** (log only on anomalies):
   - Always log errors
   - Log warning if processing >1 second
   - Log info every 60 seconds (health summary)
   - No per-bar logging (0.1% of original design)

3. **Health summary log** (1 line per minute):
   ```python
   self.logger.info(
       "bar_aggregator_health",
       processed_last_min=self._bars_processed._value.get(),
       skipped_last_min=self._bars_skipped._value.get(),
       htf_emitted_last_min=self._htf_bars_emitted._value.get(),
       consumer_lag=self._get_consumer_lag()
   )
   ```

**Cost comparison:**
- Before: 100K log lines/day (~70MB/week)
- After: 1,440 log lines/day (~1MB/week)
- **Reduction: 98.6%**

### Component 2: Health Monitoring & Circuit Breaker

**Principle:** Detect unhealthy state and take automated action (self-healing).

**Implementation:**

1. **Health metrics tracked in-memory:**
   - `_last_bar_ts` - Timestamp of last processed bar
   - `_bars_last_minute` - Bars processed in last 60s
   - `_htf_bars_last_minute` - HTF bars emitted in last 60s
   - `_consecutive_errors` - Error count

2. **Health checks** (evaluated every 30 seconds):
   - No bars for 5+ minutes → unhealthy
   - 50+ consecutive errors → unhealthy
   - Consuming 100+ bars but 0 HTF output → accumulator stuck

3. **Automated recovery**:
   ```python
   async def _handle_unhealthy_state(self, reason: str):
       """Handle unhealthy state with automated recovery."""
       if "no_bars" in reason or "consuming_not_emitting" in reason:
           self.logger.warning("bar_aggregator.attempting_consumer_reset")
           await self._kafka_consumer.stop()
           await asyncio.sleep(1)
           await self._kafka_consumer.start()
           self._health_metrics._consecutive_errors = 0
           self.logger.info("bar_aggregator.consumer_reset_complete")
   ```

4. **Prometheus health metrics:**
   ```python
   _health_status = Gauge("bar_agg_health_status", "Service health (1=healthy, 0=unhealthy)", ["agent"])
   _consumer_lag_seconds = Gauge("bar_agg_consumer_lag_seconds", "Consumer lag in seconds", ["agent"])
   _time_since_last_bar_seconds = Gauge("bar_agg_time_since_last_bar_seconds", "Seconds since last bar", ["agent"])
   ```

### Component 3: Root Cause Fixes

**Principle:** Fix the actual bug causing session boundary failures.

**Implementation:**

1. **Session boundary logging** (rate limited, 1 log per 5min per symbol):
   ```python
   if self._session.is_session_break(acc["last_ts"], curr_ts):
       now = datetime.now(UTC)
       last_log = self._last_session_boundary_log.get(key, 0)
       if now.timestamp() - last_log > 300:
           logger.info("bar_accumulator.session_boundary", symbol=bar_1m.symbol, tf=tf, ...)
   ```

2. **Accumulator state validation** (detect corruption):
   ```python
   def _is_accumulator_valid(self, acc: dict) -> bool:
       required_keys = {"period_ts", "open", "high", "low", "close", "volume", "last_ts"}
       if not all(k in acc for k in required_keys):
           return False
       if not isinstance(acc["high"], (int, float)) or not isinstance(acc["low"], (int, float)):
           return False
       if acc["high"] < acc["low"]:  # Invalid OHLC
           return False
       return True
   ```

3. **Timeout protection per bar** (max 5 seconds):
   ```python
   async with asyncio.timeout(5.0):
       result = await self._process_single_bar(payload, htf_topic)
   except asyncio.TimeoutError:
       self.logger.error("bar_aggregator.processing_timeout", timeout_seconds=5)
       self._aggregation_errors_lbl.inc()
       # Continue to next bar - don't block entire pipeline
   ```

4. **Graceful error handling** (one bad bar doesn't stop consumption):
   ```python
   try:
       result = await self._process_single_bar(payload, htf_topic)
       if result.success:
           consecutive_errors = 0
       else:
           consecutive_errors += 1
           if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
               raise RuntimeError(f"Bar aggregation failing: {consecutive_errors} consecutive errors")
   except Exception as exc:
       self._aggregation_errors_lbl.inc()
       self.logger.error("bar_aggregator.bar_failed", error=str(exc))
       # Continue to next bar - don't let one bad bar stop the pipeline
   ```

## Testing Strategy

### Unit Tests

**Test: Session boundary emits partial bar**
- Create accumulator, add bars up to 23:59 EDT
- Add RTH close bar (16:00 ET)
- Assert partial 5m bar is emitted
- Assert new accumulator starts fresh

**Test: Corrupted accumulator reset**
- Create accumulator, add normal bar
- Corrupt state (set high < low)
- Add another bar
- Assert corruption is detected and logged
- Assert accumulator is reset

**Test: Timeout protection**
- Mock slow _process_single_bar (sleeps 10 seconds)
- Assert timeout exception is raised
- Assert service continues to next bar

### Integration Tests

**Test: Session boundary under load**
- Produce 11 bars spanning RTH close (15:55 ET to 16:05 ET)
- Start bar aggregator
- Consume HTF bars for 2 minutes
- Assert ≥10 HTF bars emitted
- Assert boundary bars present (partial bar at 16:00 ET)

### Validation Checklist

**Before deploy:**
- [ ] Unit tests pass (`pytest tests/unit/test_bar_accumulator.py`)
- [ ] Integration test passes (`pytest tests/integration/test_bar_aggregator_session_boundary.py`)
- [ ] No performance regression (processing time < 10ms per bar)
- [ ] Memory leak check (run for 1 hour, memory stable)

**After deploy:**
- [ ] Service starts successfully
- [ ] No errors in logs for 5 minutes
- [ ] Consumer lag stays < 1000
- [ ] HTF bars being emitted (check Kafka topic)
- [ ] Health metrics show "healthy"
- [ ] Intelligence pipeline lag starts decreasing

**Rollback criteria:**
- Service crashes within 5 minutes
- Consumer lag > 10,000 and increasing
- No HTF bars emitted for 10 minutes
- Error rate > 10%

## Deployment Plan

### Blue-Green Deployment (Zero Downtime)

1. Deploy fix alongside running service
2. Run integration tests in staging
3. Deploy to production (service restart)
4. Monitor for 5 minutes (health metrics, logs, lag)
5. If healthy, merge to main
6. Keep old code available for fast rollback

### Rollback Procedure

```bash
# Immediate rollback (if issues detected)
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl restart indicagent-bar-aggregator-compute

# Full rollback (if bad commit deployed)
git checkout main
git reset --hard HEAD~1
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl restart indicagent-bar-aggregator-compute
```

## Success Criteria

1. **Observability:**
   - Health metrics visible in Prometheus
   - 1 log line per minute (health summary)
   - Error logs on exceptions only

2. **Reliability:**
   - Service auto-recovers from consumer stall
   - Single bad bar cannot block pipeline
   - Session boundaries logged (rate limited)

3. **Performance:**
   - Processing time < 10ms per bar
   - No memory leaks over 1 hour
   - Log volume reduced by 98.6%

4. **Correctness:**
   - All session boundaries emit partial bars
   - Corrupted state detected and reset
   - No bars skipped without logging reason

## Alignment with Renaissance Principles

- ✅ **Instrument everything** - Metrics track every bar, health status always visible
- ✅ **Let the system run** - Automated recovery, no human intervention needed
- ✅ **Degrade gracefully** - Circuit breaker prevents cascade failure
- ✅ **Never drop data** - Every bar accounted for, skips logged with reason
- ✅ **Efficiency** - Minimal logging, in-memory metrics, 98.6% reduction in I/O
- ✅ **Automation** - Self-healing system, no manual monitoring required
- ✅ **Modularity** - Telemetry, processing, recovery concerns separated
- ✅ **Data quality** - Defensive checks prevent corrupted state propagation
