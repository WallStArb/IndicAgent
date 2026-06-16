# Performance Profiling Guide

**Version:** 2.8
**Last Updated:** 2026-05-28

---

## Overview

This guide covers performance profiling techniques for IndicAgent services. Use these methods to identify bottlenecks before optimizing.

**Key principle:** Measure first, optimize second. The Renaissance approach — profile → identify bottleneck → design fix → implement → measure again.

---

## Profiling Tools

### py-spy (Python Profiler)

**Purpose:** Flamegraph generation for running Python processes

**Installation:**
```bash
pip install py-spy
```

**Usage:**
```bash
# Profile running process (requires sudo)
sudo py-spy record --pid <pid> --output flamegraph.svg --duration 30

# Profile service startup
sudo py-spy record -- python services/intelligence_pipeline_agent.py

# Top-like live view
sudo py-spy top --pid <pid>
```

**Output:** SVG flamegraph showing call stacks and time spent per function.

**Common IndicAgent PIDs:**
```bash
# Find intelligence pipeline PID
pgrep -f intelligence_pipeline_agent

# Find feature writer PID
pgrep -f feature_writer_agent
```

---

### cProfile (Built-in Profiler)

**Purpose:** Function-level profiling with call counts

**Usage:**
```python
import cProfile
import pstats

# Profile specific function
pr = cProfile.Profile()
pr.enable()

# ... code to profile ...

pr.disable()
stats = pstats.Stats(pr)
stats.sort_stats('cumulative').print_stats(20)
```

**Output:** Function call count, cumulative time, per-call time.

---

### Python Profiling Module

**Purpose:** Quick ad-hoc profiling

**Usage:**
```bash
python -m cProfile -s cumulative services/intelligence_pipeline_agent.py
```

---

## Service-Level Profiling

### Intelligence Pipeline

**Metrics to watch:**
- `intelligence_pipeline_pipeline_latency_ms` — End-to-end latency per bar
- `intelligence_pipeline_bars_processed_total` — Throughput counter
- `plugin_execution_seconds` — Per-plugin execution time

**Grafana dashboard:** Pipeline Health

**Profiling steps:**
```bash
# 1. Check baseline latency
curl -s 'http://localhost:9090/api/v1/query?query=intelligence_pipeline_pipeline_latency_ms' | jq

# 2. Generate flamegraph
sudo py-spy record --pid $(pgrep -f intelligence_pipeline_agent) \
  --output /tmp/intelligence-flamegraph.svg --duration 30

# 3. Open flamegraph
firefox /tmp/intelligence-flamegraph.svg

# 4. Identify hot functions (wide boxes = more time)

# 5. Drill into plugin execution times
curl -s 'http://localhost:9090/api/v1/query?query=plugin_execution_seconds' | jq
```

---

### Writer Services (Feature/Signal)

**Metrics to watch:**
- `persistence_batch_latency_seconds` — DB write time per batch
- `persistence_consumer_lag_records` — Consumer backlog

**Grafana dashboard:** Operations

**Profiling steps:**
```bash
# 1. Check consumer lag
docker exec redpanda rpk group describe feature_writer_group

# 2. Profile writer process
sudo py-spy record --pid $(pgrep -f feature_writer_agent) \
  --output /tmp/feature-writer-flamegraph.svg --duration 30

# 3. Check batch size and latency
journalctl -u indicant-feature-writer --since "2 minutes ago" | grep "batch written"
```

---

### LLM Services (Narrative/Swarm)

**Metrics to watch:**
- `llm_call_duration_seconds` — LLM request latency
- `llm_tokens_used_total` — Token consumption rate

**Grafana dashboard:** Signals & I8

**Profiling steps:**
```bash
# 1. Check LLM latency by provider
curl -s 'http://localhost:9090/api/v1/query?query=llm_call_duration_seconds' | jq

# 2. Profile narrative service
sudo py-spy record --pid $(pgrep -f narrative_group_compute_agent) \
  --output /tmp/narrative-flamegraph.svg --duration 60

# 3. Check token usage rate
curl -s 'http://localhost:9090/api/v1/query?query=rate(llm_tokens_used_total[5m])' | jq
```

---

## Database Profiling

### Query Performance

**Identify slow queries:**
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT pid, now() - query_start as duration, query \
   FROM pg_stat_activity WHERE state = 'active' \
   ORDER BY duration DESC LIMIT 10"
```

**Query statistics:**
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT schemaname, tablename, idx_scan, seq_scan, \
   idx_scan / seq_scan as ratio \
   FROM pg_stat_user_tables WHERE seq_scan > 0 \
   ORDER BY seq_scan DESC"
```

**High ratio (>10) means indexes are being used effectively. Low ratio suggests missing indexes.**

---

### TimescaleDB Compression

**Check compression status:**
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT show_chunks('market_data_ohlcv'::regclass)"
```

**Compress old chunks:**
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT compress_chunk(show_chunks('market_data_ohlcv'::regclass));"
```

---

## Kafka Profiling

### Consumer Lag

**Check all consumer groups:**
```bash
docker exec redpanda rpk group list
```

**Check specific group:**
```bash
docker exec redpanda rpk group describe feature_writer_group
```

**High lag indicates consumer can't keep up.**

---

### Topic Throughput

**Topic stats:**
```bash
docker exec redpanda rpk topic stats intelligence.journal
```

**Check partition usage:**
```bash
docker exec redpanda rpk topic describe intelligence.journal
```

---

## OTel Profiling

### Metrics Query

**Query Prometheus for metrics:**
```bash
# Service-level metrics
curl -s 'http://localhost:9090/api/v1/query?query=up' | jq

# Agent-specific metrics
curl -s 'http://localhost:9090/api/v1/query?query=agent_last_message_timestamp_seconds' | jq

# Plugin execution time (p95 by tier)
curl -s 'http://localhost:9090/api/v1/query?query=histogram_quantile(0.95, rate(plugin_execution_seconds_bucket{intelligence_tier="I1"}[5m]))' | jq
```

---

### Custom Metrics

**Add histogram for custom profiling:**
```python
from src.observability.metrics import histogram

MY_CUSTOM_HISTOGRAM = histogram(
    "my_custom_operation_seconds",
    "Custom operation duration"
)

# In code
start = time.time()
# ... operation ...
MY_CUSTOM_HISTOGRAM.record((time.time() - start), {"label": "value"})
```

---

## Common Bottlenecks

### Plugin Execution

**Symptom:** High `plugin_execution_seconds` for specific plugin

**Diagnosis:**
```bash
# Profile plugin
sudo py-spy top --pid $(pgrep -f intelligence_pipeline_agent)

# Look for plugin compute_next() function in output
```

**Fix:** Vectorize computation (numpy), cache results, or reduce state size.

---

### DB Writes

**Symptom:** High `persistence_batch_latency_seconds`

**Diagnosis:**
```bash
# Check for long-running queries
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT pid, now() - query_start as duration, query \
   FROM pg_stat_activity WHERE state = 'active' \
   ORDER BY duration DESC LIMIT 5"
```

**Fix:** Add indexes, compress old data, increase batch size.

---

### GIL Contention

**Symptom:** Multi-threaded service not faster than single-threaded

**Diagnosis:**
```bash
# Profile with py-spy
sudo py-spy record --pid <pid> --output gil-flamegraph.svg

# Look for time spent in threading/synchronization
```

**Fix:** Batch processing (amortizes sequential cost), process-level parallelism.

---

### Memory Leaks

**Symptom:** Service memory growing over time

**Diagnosis:**
```bash
# Check memory usage
ps aux | grep <service-name>

# Profile memory
pip install memory_profiler
python -m memory_profiler services/<service>.py
```

**Fix:** Clear old state, limit cache size, restart service periodically.

---

## Optimization Workflow

### 1. Baseline Measurement

```bash
# Record baseline metrics
curl -s 'http://localhost:9090/api/v1/query?query=intelligence_pipeline_pipeline_latency_ms' | jq > baseline-latency.json
```

### 2. Profile

```bash
# Generate flamegraph
sudo py-spy record --pid <pid> --output before-flamegraph.svg --duration 60
```

### 3. Identify Bottleneck

**Review flamegraph:**
- Wide boxes = more time spent
- Deep stacks = many function calls
- Self time = time in function (not children)

### 4. Design Fix

**Consider:**
- Algorithm improvement (O(n²) → O(n))
- Vectorization (numpy/pandas)
- Caching (memoization)
- Batching (amortize cost)

### 5. Implement

**Make targeted changes.**

### 6. Verify

```bash
# Generate new flamegraph
sudo py-spy record --pid <pid> --output after-flamegraph.svg --duration 60

# Compare metrics
curl -s 'http://localhost:9090/api/v1/query?query=intelligence_pipeline_pipeline_latency_ms' | jq > after-latency.json

# Compare flamegraphs visually
diff before-flamegraph.svg after-flamegraph.svg
```

### 7. Iterate

**Repeat until satisfied or bottleneck moves elsewhere.**

---

## Profiling Checklist

Before optimizing:

- [ ] Baseline metrics recorded
- [ ] Flamegraph generated
- [ ] Bottleneck identified (top 3 functions)
- [ ] Fix designed and implemented
- [ ] Metrics improved
- [ ] Flamegraph compared

---

## See Also

- **Pipeline optimization:** `docs/architecture/pipeline-optimization.md`
- **Observability:** `docs/platform/platform-observability.md`
- **Grafana dashboards:** `docs/operations/operations-observability.md`
- **Performance characteristics:** `docs/architecture/current-state.md`
