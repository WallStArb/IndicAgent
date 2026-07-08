# Pipeline Optimization Strategy

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-04-21
**Tags:** performance, pipeline-throughput, parallelization, bottleneck, optimization, latency
**Related:** `docs/research/pipeline-throughput-bottleneck-analysis.md` · `docs/architecture/current-state.md`

---

## Performance Challenge

IndicAgent processes **~4.5 bars/sec** against a theoretical target of **530 bars/sec** — a 118x gap. The bottleneck is **sequential tier execution** (composite events through confluence, I2-I6), compounded by Python's GIL preventing threading benefits.

**Tier glossary:** I1 = indicators, I2 = composite_events, I3 = structure, I4 = context, I5 = patterns, SMC = smart_money, I6 = confluence, I7 = signals. See `docs/foundation/naming-system.md` for full reference.

---

## Architecture: Parallel vs Sequential

### Current Parallelization

```
Indicators (I1): [Plugin1, Plugin2, ... Plugin28] → asyncio.gather (parallel)
 ↓
Composite events (I2): [Plugin1] → [Plugin2] → ... (sequential, 11 plugins)
 ↓
Structure (I3): [Plugin1] → [Plugin2] → ... → [Plugin9] (sequential)
 ↓
Context (I4): [Plugin1] → [Plugin2] → ... → [Plugin13] (sequential)
 ↓
Patterns (I5, 16 plugins) → Smart money (SMC, 13 plugins) → Confluence (I6, 1 plugin): (sequential)
 ↓
I7: [Plugin1, Plugin2, ... Plugin37] → asyncio.gather (parallel)
```

**Latency Impact:**
- Indicators (I1, parallel): 30ms
- Composite events through confluence (I2-I6, sequential): 160ms (73% of total)
- Signals (I7, parallel): 20ms

**Why Threading Doesn't Help:**
Python's Global Interpreter Lock (GIL) allows only one thread to execute Python bytecode at a time. ThreadPoolExecutor workers contend for the GIL, causing context switching overhead. CPU-bound work (plugin compute) cannot utilize multiple cores regardless of worker count.

### Why Vectorization Fails

**Test Case:** OBVMomentum plugin
- Vectorized speedup: 8057ms → 177ms (46x faster)
- Overall throughput: **No improvement** (still ~4.5 bars/sec)

**Reason:** Bottleneck is sequential tier execution order, not individual plugin speed. Making one plugin 46x faster when it waits 160ms for sequential tiers doesn't improve overall throughput.

---

## Solution: Batch Processing

### Concept

Instead of processing 1 bar through all tiers sequentially, process N bars through each tier in parallel:

**Current (Per-Bar Sequential):**
```
Bar1: I1 → I2 → I3 → I4 → I5 → SMC → I6 → I7 (220ms)
Bar2: I1 → I2 → I3 → I4 → I5 → SMC → I6 → I7 (220ms)
Bar3: I1 → I2 → I3 → I4 → I5 → SMC → I6 → I7 (220ms)
Total: 660ms for 3 bars
```

**Batch (Per-Tier Parallel):**
```
Accumulate: [Bar1, Bar2, Bar3] (wait up to 5s for 100 bars)
I1:  Process all 3 bars in parallel (30ms)
I2:  Process all 3 bars in parallel (40ms)
I3:  Process all 3 bars in parallel (50ms)
I4:  Process all 3 bars in parallel (40ms)
I5-I6: Process all 3 bars in parallel (30ms)
I7:  Process all 3 bars in parallel (20ms)
Total: 210ms for 3 bars (amortized)
```

**For 100 bars:** 210ms total vs 22,000ms sequential — **105x speedup** (theoretical)

### Trade-offs

| Aspect | Real-Time Mode | Batch Mode |
|--------|----------------|------------|
| **Latency** | ~220ms per bar | 5s max wait + 200ms processing |
| **Throughput** | 4.5 bars/sec | 45-225 bars/sec (10-50x) |
| **Use case** | Low-volume, high-volatility | High-volume, normal regime |
| **Complexity** | Current implementation | Dual-path logic required |

### Adaptive Mode Selection

**Heuristics:**
- High volatility → real-time (fast response)
- Stale data (>5s since last batch) → batch (prevent staleness)
- Buffer full (≥100 bars) → batch (maximum efficiency)
- Otherwise → accumulate (wait for more bars)

---

## Optimization Principles

### Renaissance Approach: Measure First

1. **Profile** — identify actual hotspots (flamegraph, latency breakdown)
2. **Identify biggest lever** — fix what dominates (73% of latency in composite events through confluence, I2-I6)
3. **Design fix** — batch processing parallelizes across bars, not plugins
4. **Implement** — dual-mode architecture
5. **Measure again** — confirm improvement before next optimization

**Anti-patterns to avoid:**
- Optimizing individual plugins when tier execution is bottleneck
- Adding more threading workers when GIL blocks them
- Rewriting in Rust/Go when architecture is the issue

### Measurement Protocol

**Profiling:**
```bash
# Flamegraph (attach to running process)
docker exec indicagent-intelligence-pipeline python -m py-spy record --output flamegraph.svg --pid <pid>
```

**Throughput/Latency:** Query via Prometheus (`:9090`) or Grafana (`:3001`) — services push metrics via OTLP to the OTel Collector, no per-service `/metrics` endpoint:
```promql
# End-to-end latency p95
histogram_quantile(0.95, rate(indic_bar_to_signal_latency_seconds_bucket[5m]))

# Pipeline latency gauge (direct from intelligence pipeline)
intelligence_pipeline_pipeline_latency_ms
```

---

## Alternative Approaches (Not Pursued)

### Process-Level Parallelism

Use `multiprocessing` to bypass GIL — each tier in separate process.

**Challenges:**
- High overhead (process spawn ~100ms, IPC serialization)
- Complex state management (shared memory vs message passing)
- Diminishing returns if batch processing succeeds

### Native Extensions (Rust/C++)

Rewrite hot plugins (indicators I1, context I4) in Rust.

**Trade-offs:**
- Development cost (~3-5 days per plugin)
- Deployment complexity (native binaries, Python bindings)
- Only helps if plugin itself is bottleneck (not true today)

### JIT Compilation (Numba, PyPy)

JIT-compile numpy operations for native speed.

**Challenges:**
- Numba requires type annotations (refactor all plugins)
- PyPy incompatible with some libraries (asyncpg, kafka-python)
- Debugging complexity (JIT errors vs runtime errors)

**Recommendation:** Pursue only if batch processing achieves <20x improvement.

---

## Expected Performance

| Metric | Current | Batch (Expected) | Target |
|--------|---------|------------------|--------|
| **Throughput** | 4.5 bars/sec | 45-225 bars/sec (10-50x) | 530 bars/sec |
| **Latency (real-time)** | 220ms | 220ms (unchanged) | <10ms |
| **Latency (batch)** | N/A | 5s max wait + 200ms | <2s |
| **Memory** | ~10MB | ~50MB (100-bar buffer) | <100MB |

---

## References

- **Analysis:** `docs/research/pipeline-throughput-bottleneck-analysis.md`
- **Current State:** `docs/architecture/current-state.md`

---

*Focus: Concepts and architecture, not implementation timelines*
