# Intelligence Operations — Services & Monitoring

**Version:** 1.0.0
**Last Updated:** 2026-05-28
**Status:** Operational
**Milestone:** v2.8 — AI Platform + Evolvable Agents

---

## Purpose

OPS for intelligence services: Service DAG, health endpoints, metrics, debugging scenarios, performance tuning, and common operational issues.

---

## Service DAG

### Canonical Registry

**File:** `services/service_auditor_agent.py:_DAG_ORDER`

### Layer Structure

```
L0  Infrastructure sentinels
    indicagent-redpanda-ready, redpanda-watchdog, timescaledb-ready

L1  Data ingestion
    indicagent-ibkr-provider, indicagent-bar-replay

L2  Stream routing
    indicagent-provider-merger

L3  Bar processing
    indicagent-bar-aggregator, indicant-bar-auditor

L4  Bar persistence
    indicant-bar-writer

L5  Intelligence pipeline
    indicant-cross-asset, indicant-macro-compute, indicant-intelligence-pipeline

L6  Persistence writers (parallel)
    indicant-feature-writer, indicant-signal-writer, indicant-lifecycle-writer,
    indicant-lineage-writer, indicant-ctx-writer, indicant-signal-tracker-compute

L7  AI/LLM layer
    indicant-alpha-swarm, indicant-narrative-compute, indicant-llm-writer,
    indicant-swarm-ledger-writer

L8  Analytics (oneshot timers)
    indicant-signal-metrics-compute, indicant-graduation-compute,
    indicant-ml-training, indicant-ml-orchestrator, etc.

L9  Audit, parity, alerting
    indicant-signal-auditor, indicant-signal-replay, indicant-alerting-agent,
    indicant-dlq-drain

L10 Top-level (always-on)
    indicant-api, indicant-dashboard

L11 Meta
    indicant-service-auditor
```

**Priority:** Lower number = restarts first during graduated response.

### Lag Thresholds

**File:** `services/service_auditor_agent.py:_LAG_THRESHOLDS`

| Service | Threshold (ms) | Purpose |
|---------|----------------|---------|
| intelligence-pipeline | 500 | Hot path latency |
| feature-writer | 1000 | Batch write tolerance |
| signal-writer | 500 | Batch write tolerance |
| alpha-swarm | 200 | Async swarm evaluation |
| narrative-compute | 200 | LLM narrative generation |

**Health check:** `systemctl status indicant-<service>` or Grafana dashboard `:3001`

---

## Intelligence Pipeline Service

### Service Details

| Property | Value |
|----------|-------|
| **Unit name** | `indicagent-intelligence-pipeline` |
| **Class** | `IntelligencePipelineComputeAgent` |
| **File** | `services/intelligence_pipeline_agent.py` |
| **Metrics port** | `:9125` |
| **Consumer topics** | `market.bars`, `market.bars.htf` |
| **Producer topics** | `intelligence.journal`, `intelligence.i7.signals`, `lifecycle.transitions` |
| **Agent ID** | `intelligence_pipeline_agent` |

### Startup Sequence

1. Load active contracts via `get_active_contracts(settings)`
2. Initialize checkpoint state (per symbol/timeframe/plugin)
3. Register all plugins via `register_all_plugins()`
4. Enroll I7 plugins in `shadow_registry` via `enroll_all_plugins()`
5. Subscribe to Kafka topics
6. Begin bar processing loop

### Checkpoint State

State checkpointed to local file (per symbol/timeframe/plugin):
- I1-I7 plugin outputs where applicable
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
persistence_consumer_lag{agent_id="intelligence_pipeline_agent"}
```

**Agent liveness:**
```promql
agent_last_message_timestamp_seconds{agent_id="intelligence_pipeline_agent"}
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

### Current Latency Breakdown

Per bar (single symbol, all timeframes):

| Stage | Latency | Percentage |
|-------|--------|------------|
| I1 (parallel, 28 plugins) | 30ms | 14% |
| I2-I6 (sequential, 74 plugins) | 160ms | 73% |
| I7 (parallel, 36 plugins) | 20ms | 9% |
| **Total** | **~220ms** | **100%** |

### Bottleneck

**I2-I6 sequential execution** is the bottleneck (73% of total latency).

The GIL prevents threading from achieving true parallelism. CPU-bound work cannot utilize multiple cores.

### Throughput

- **Current:** ~4.5 bars/sec (limited by sequential I2-I6)
- **Target:** 530 bars/sec (118x gap)
- **Optimization:** Batch processing expected 10-50x improvement (see `docs/architecture/pipeline-optimization.md`)

### Plugin Performance Characteristics

| Metric | Value |
|--------|-------|
| Sequential bar processing | `await _process_bar` — one bar at a time |
| Per-bar latency (production) | Measured by `intelligence_pipeline_pipeline_latency_ms` gauge at `:8000/metrics` |
| Plugin count | 132 plugins + 2 aggregation components across I1-I7 |
| Thread-pool workers | 12 (GIL cap for CPU-bound plugins) |
| Backfill replay throttle | 10 bars/sec (`BAR_REPLAY_BARS_PER_SEC`) — not representative of pipeline ceiling |

**Bottleneck:** The sequential `_process_bar` await is the primary throughput limit. Each bar must complete all 132 plugins before the next bar begins. I1-I4 run in waves; I5-I7 run after I4 completes.

**GIL note:** Python GIL limits true parallelism for CPU-bound plugins. The 12 thread-pool workers help I/O-bound operations but CPU-bound indicator math is effectively single-threaded per bar.

---

## Common Issues

### Issue: Service Fails to Start

**Symptoms:** `systemctl status` shows `failed` or `StartLimitHit`

**Diagnosis:**
```bash
journalctl -u indicant-intelligence-pipeline --since "5 minutes ago"
```

**Common causes:**
- Database connection refused (check TimescaleDB is running)
- Kafka connection refused (check Redpanda is running)
- Contract metadata missing (run `production/scripts/ensure_contracts.py`)

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
journalctl -u indicant-narrative-compute --since "10 minutes ago"
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
systemctl status indicant-intelligence-pipeline

# Service logs
journalctl -u indicant-intelligence-pipeline -f
tail -f logs/intelligence_pipeline_agent.log
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
- **Service Auditor:** `services/service_auditor_agent.py` — DAG order, lag thresholds
