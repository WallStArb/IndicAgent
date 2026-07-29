# Intelligence Operations — Services & Monitoring

**Version:** 1.0.0
**Last Updated:** 2026-05-28
**Status:** current
**Milestone:** v2.8 — AI Platform + Evolvable Agents

---

## Purpose

OPS for intelligence services: Service DAG, health endpoints, metrics, debugging scenarios, performance tuning, and common operational issues.

---

## Service DAG

### Canonical Registry

**File:** `services/service_auditor.py:_DAG_ORDER`

### Layer Structure

```
L0  Infrastructure sentinels
    indicagent-redpanda-ready, redpanda-watchdog, timescaledb-ready

L1  Data ingestion
    indicagent-ibkr-provider, indicagent-bar-replay

L2  Stream routing
    indicagent-provider-merger

L3  Bar processing
    indicagent-bar-aggregator, indicagent-bar-auditor

L4  Bar persistence
    indicagent-bar-writer

L5  Intelligence pipeline
    indicagent-cross-asset, indicagent-macro-compute, indicagent-intelligence-pipeline

L6  Persistence writers (parallel)
    indicagent-feature-writer, indicagent-signal-writer, indicagent-lifecycle-writer,
    indicagent-lineage-writer, indicagent-ctx-writer, indicagent-signal-tracker-compute

L7  AI/LLM layer
    indicagent-alpha-swarm, indicagent-narrative-compute, indicagent-llm-writer,
    indicagent-swarm-ledger-writer

L8  Analytics (oneshot timers)
    indicagent-signal-metrics-compute, indicagent-graduation-compute,
    indicagent-ml-training, indicagent-ml-orchestrator, etc.

L9  Audit, parity, alerting
    indicagent-signal-auditor, indicagent-signal-replay, indicagent-alerting-agent,
    indicagent-dlq-drain

L10 Top-level (always-on)
    indicagent-api, indicagent-dashboard

L11 Meta
    indicagent-service-auditor
```

**Priority:** Lower number = restarts first during graduated response.

### Lag Thresholds

**File:** `services/service_auditor.py:_LAG_THRESHOLDS`

| Service | Threshold (ms) | Purpose |
|---------|----------------|---------|
| intelligence-pipeline | 500 | Hot path latency |
| feature-writer | 1000 | Batch write tolerance |
| signal-writer | 500 | Batch write tolerance |
| alpha-swarm | 200 | Async swarm evaluation |
| narrative-compute | 200 | LLM narrative generation |

**Health check:** `systemctl status indicagent-<service>` or Grafana dashboard `:3001`

---

## Intelligence Pipeline Service

### Service Details

| Property | Value |
|----------|-------|
| **Unit name** | `indicagent-intelligence-pipeline` |
| **Class** | `IntelligencePipeline` |
| **File** | `services/intelligence_pipeline.py` |
| **Metrics port** | `:9125` |
| **Consumer topics** | `market.bars`, `market.bars.htf` |
| **Producer topics** | `intelligence.journal`, `intelligence.i7.signals`, `lifecycle.transitions` |
| **Service name** | `intelligence_pipeline` |

### Startup Sequence

1. Load active contracts via `get_active_contracts(settings)`
2. Initialize checkpoint state (per symbol/timeframe/plugin)
3. Register all plugins via `register_all_plugins()`
4. Enroll signal (I7) plugins in `shadow_registry` via `enroll_all_plugins()`
5. Subscribe to Kafka topics
6. Begin bar processing loop

### Checkpoint State

State checkpointed to local file (per symbol/timeframe/plugin):
- indicator through signal (I1-I7) plugin outputs where applicable
- No warmup on restart
- Enables deterministic replay

---

## Metrics

### Prometheus Endpoints

Each service exposes metrics on its assigned port:

| Service | Port | Path |
|---------|------|------|
| intelligence-pipeline | :9125 | `/metrics` |
| feature-writer | :9116 | `/metrics` |
| signal-writer | :9119 | `/metrics` |
| alpha-swarm | — | Via pipeline |
| narrative-compute | :9113 | `/metrics` |

### Key Metrics

**Pipeline latency:**
```promql
rate(intelligence_pipeline_plugin_duration_ms_sum{plugin_name=~".+"}[5m])
/
rate(intelligence_pipeline_plugin_duration_ms_count{plugin_name=~".+"}[5m])
```

**Plugin duration:**
```promql
histogram_quantile(0.50, intelligence_pipeline_plugin_duration_ms_bucket)
histogram_quantile(0.95, intelligence_pipeline_plugin_duration_ms_bucket)
```

**Consumer lag:**
```promql
persistence_consumer_lag{agent_id="intelligence_pipeline"}
```

**Agent liveness:**
```promql
agent_last_message_timestamp_seconds{agent_id="intelligence_pipeline"}
```

### OTel Spans

Use `observed_span()` from `src/observability/spans.py` — auto-records ERROR status + exception on raise.

```python
from src.observability.spans import observed_span, ATTR_PLUGIN_NAME

with observed_span("plugin_compute", attributes={ATTR_PLUGIN_NAME: plugin.name}):
    result = plugin.compute(bar, features)
```

---

## Performance

**Tier reference:** I1 = indicators, I2 = composite_events, I3 = structure, I4 = context, I5 = patterns, I6 = confluence, I7 = signals. See `docs/foundation/naming-system.md` for full glossary.

### Current Latency Breakdown

Per bar (single symbol, all timeframes):

| Stage | Latency | Percentage |
|-------|--------|------------|
| Indicators (I1, parallel, 28 plugins) | 30ms | 14% |
| Composite events through confluence (I2-I6, sequential, 74 plugins) | 160ms | 73% |
| Signals (I7, parallel, 36 plugins) | 20ms | 9% |
| **Total** | **~220ms** | **100%** |

### Bottleneck

**Composite events through confluence (I2-I6) sequential execution** is the bottleneck (73% of total latency).

The GIL prevents threading from achieving true parallelism. CPU-bound work cannot utilize multiple cores.

### Throughput

- **Current:** ~4.5 bars/sec (limited by sequential I2-I6 composite events through confluence)
- **Target:** 530 bars/sec (118x gap)
- **Optimization:** Batch processing expected 10-50x improvement (see `docs/architecture/pipeline-optimization.md`)

### Plugin Performance Characteristics

| Metric | Value |
|--------|-------|
| Sequential bar processing | `await _process_bar` — one bar at a time |
| Per-bar latency (production) | Measured by `intelligence_pipeline_pipeline_latency_ms` gauge at `:8000/metrics` |
| Plugin count | 132 plugins + 2 aggregation components across indicators through signals (I1-I7) |
| Thread-pool workers | 12 (GIL cap for CPU-bound plugins) |
| Backfill replay throttle | 10 bars/sec (`BAR_REPLAY_BARS_PER_SEC`) — not representative of pipeline ceiling |

**Bottleneck:** The sequential `_process_bar` await is the primary throughput limit. Each bar must complete all 132 plugins before the next bar begins. Indicators through context (I1-I4) run in waves; patterns through signals (I5-I7) run after I4 completes.

**GIL note:** Python GIL limits true parallelism for CPU-bound plugins. The 12 thread-pool workers help I/O-bound operations but CPU-bound indicator math is effectively single-threaded per bar.

### Current Parallelization Architecture

```
I1: [P1, P2, ... P28] → asyncio.gather (parallel)
 ↓
I2: [P1] → [P2] → ... (sequential, 10 plugins)
 ↓
I3: [P1] → [P2] → ... → [P8] (sequential)
 ↓
I4: [P1] → [P2] → ... → [P12] (sequential)
 ↓
I5 (16) → SMC (16) → I6 (6): (sequential)
 ↓
I7: [P1, P2, ... P36] → asyncio.gather (parallel)
```

I1 and I7 are parallelized; I2–I6 are sequential because GIL prevents true CPU parallelism.

### Optimization: Batch Processing

The path to 10–50x throughput improvement is batch processing — accumulating N bars and processing them tier-by-tier in parallel instead of processing each bar through all tiers sequentially.

**Current (per-bar sequential):**
```
Bar1: I1 → I2 → I3 → I4 → I5 → I6 → I7  (220ms)
Bar2: I1 → I2 → I3 → I4 → I5 → I6 → I7  (220ms)
Bar3: I1 → I2 → I3 → I4 → I5 → I6 → I7  (220ms)
Total: 660ms for 3 bars
```

**Batch (per-tier parallel across bars):**
```
Accumulate: [Bar1, Bar2, Bar3]
I1:  Process all 3 bars in parallel (30ms)
I2:  Process all 3 bars in parallel (40ms)
I3:  Process all 3 bars in parallel (50ms)
I4:  Process all 3 bars in parallel (40ms)
I5–I6: Process all 3 bars in parallel (30ms)
I7:  Process all 3 bars in parallel (20ms)
Total: 210ms for 3 bars — 3x reduction, scales to 105x at 100 bars
```

**Trade-offs:**

| Aspect | Real-time mode | Batch mode |
|--------|----------------|------------|
| Latency | ~220ms per bar | 5s max wait + ~200ms processing |
| Throughput | ~4.5 bars/sec | 45–225 bars/sec (10–50x) |
| Use case | Low-volume, high-volatility | High-volume, normal regime |

**Adaptive mode selection heuristics:**
- High volatility → real-time (fast response)
- Stale data (>5s since last batch) → batch (prevent staleness)
- Buffer full (≥100 bars) → batch (maximum efficiency)
- Otherwise → accumulate

**Full analysis:** `docs/architecture/pipeline-optimization.md`

---

## Common Issues

### Issue: Service Fails to Start

**Symptoms:** `systemctl status` shows `failed` or `StartLimitHit`

**Diagnosis:**
```bash
journalctl -u indicagent-intelligence-pipeline --since "5 minutes ago"
```

**Common causes:**
- Database connection refused (check TimescaleDB is running)
- Kafka connection refused (check Redpanda is running)
- Contract metadata missing (check contract_metadata table and verify get_active_contracts() returns data)

### Issue: High Consumer Lag

**Symptoms:** Grafana shows `persistence_consumer_lag > 5000`

**Diagnosis:**
```bash
docker exec redpanda rpk group describe intelligence_pipeline -t
```

**Common causes:**
- Backfill running (temporary, expected)
- Service deadlock (check `agent_crash_total` counter)
- Database write slowdown (check TimescaleDB metrics)

### Issue: Plugin Schema Validation Error

**Symptoms:** Service crashes on startup with `Schema coverage gaps detected`

**Diagnosis:** Error message shows which plugin and which fields are missing

**Fix:** Add missing fields to the tier schema in `src/intelligence/schemas.py`

### Issue: LLM Timeout

**Symptoms:** `alpha_swarm` or `narrative_compute` shows timeout errors

**Diagnosis:**
```bash
docker logs ollama  | tail -50
journalctl -u indicagent-narrative-compute --since "10 minutes ago"
```

**Common causes:**
- Ollama container not running
- Model not pulled (run `docker exec ollama ollama pull gemma4:e4b`)
- GPU resource exhaustion (check `docker stats`)

### Issue: Shadow Registry Promotion Failure

**Symptoms:** Agent remains shadow-only despite n >= 100

**Diagnosis:**
```sql
SELECT * FROM shadow_registry WHERE component_name = 'my_agent_v1';
SELECT * FROM signal_lineage WHERE source = 'my_agent_v1' LIMIT 10;
```

**Common causes:**
- `bootstrap_ci_lower(pnl_r) <= 0` (no statistical edge)
- `n < 100` (insufficient sample size)
- Graduation loop not running (check `graduation-compute` service)

---

## Debugging

### Service Health

```bash
# All services
systemctl list-units --all | grep indicant

# Specific service
systemctl status indicagent-intelligence-pipeline

# Service logs
journalctl -u indicagent-intelligence-pipeline -f
tail -f logs/intelligence_pipeline.log
```

### Kafka Topics

```bash
# List topics
docker exec redpanda rpk topic list

# Consume topic (from end)
docker exec redpanda rpk topic consume intelligence --from-end

# Consumer lag
docker exec redpanda rpk group describe intelligence_pipeline -t
```

### Database Queries

```bash
# Check freshness
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT symbol, tf, MAX(ts) FROM intelligence_features
  GROUP BY symbol, tf ORDER BY MAX(ts) DESC LIMIT 5;
"

# Check shadow registry
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT component_name, component_type, shadow_only, n
  FROM shadow_registry ORDER BY component_name;
"
```

### Traces

**Tempo UI:** `http://localhost:9411`

Query by trace ID or `agent_id` tag to see full request flow through the pipeline.

---

## Tuning

### Batch Size

**Feature writer:** `feature_writer` batch size tuned via env var. Increase for higher throughput, decrease for lower latency.

**Signal writer:** `signal_writer` batch size tuned via env var.

### Consumer Poll Interval

Most services use default `poll_ms=100`. Increase for lower CPU usage, decrease for lower latency.

### Checkpoint Interval

State checkpointed every N bars. Tune via service-specific env var.

### Ollama Context Window

Default: 16384 tokens. Increase via `OLLAMA_NUM_CTX` for longer prompts (reduces throughput).

---

## Maintenance

### Daily

- Check Grafana dashboard for anomalies
- Verify consumer lag < threshold
- Review DLQ topics (should be empty)

### Weekly

- Review signal metrics tables for setup performance
- Check shadow registry for graduation candidates
- Review `agent_crash_total` counters

### Monthly

- Review and compact TimescaleDB partitions if needed
- Review and rotate logs
- Update Ollama models if new versions available

---

## See Also

- **Foundation:** `intelligence-foundation.md` — I1-I8 definitions, data flow
- **Plugins:** `intelligence-plugins.md` — Plugin protocol, tier lists
- **AI Agents:** `intelligence-ai.md` — Swarm agents, LLM chain
- **Observability:** `src/observability/` — Metrics, spans, tracing
- **Service Auditor:** `services/service_auditor.py` — DAG order, lag thresholds
