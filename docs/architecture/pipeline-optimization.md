# Pipeline Optimization Strategy

**Last Updated:** 2026-04-21
**Related:** `docs/ideas/pipeline-throughput-bottleneck-analysis.md` · `docs/architecture/current-state.md`

---

## Performance Challenge

IndicAgent processes **~4.5 bars/sec** against a theoretical target of **530 bars/sec** — a 118x gap. The bottleneck is **sequential tier execution** (I2-I6), compounded by Python's GIL preventing threading benefits.

---

## Architecture: Parallel vs Sequential

### Current Parallelization

```
I1: [Plugin1, Plugin2, ... Plugin28] → asyncio.gather (parallel)
 ↓
I2: [Plugin1] → [Plugin2] → ... (sequential, 11 plugins)
 ↓
I3: [Plugin1] → [Plugin2] → ... → [Plugin9] (sequential)
 ↓
I4: [Plugin1] → [Plugin2] → ... → [Plugin13] (sequential)
 ↓
I5 (16) → SMC (13) → I6 (1): (sequential)
 ↓
I7: [Plugin1, Plugin2, ... Plugin37] → asyncio.gather (parallel)
```

**Latency Impact:**
- I1 (parallel): 30ms
- I2-I6 (sequential): 160ms (73% of total)
- I7 (parallel): 20ms

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
Bar1: I1 → I2 → I3 → I4 → I5 → I6 → I7 (220ms)
Bar2: I1 → I2 → I3 → I4 → I5 → I6 → I7 (220ms)
Bar3: I1 → I2 → I3 → I4 → I5 → I6 → I7 (220ms)
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
2. **Identify biggest lever** — fix what dominates (73% of latency in I2-I6)
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
# Flamegraph
docker exec indicagent-intelligence-pipeline python -m py-spy record --output flamegraph.svg --pid <pid>

# Latency breakdown
curl -s http://localhost:9125/metrics | grep pipeline_latency_seconds
```

**Throughput:**
```bash
# Bars processed per second
curl -s http://localhost:9125/metrics | grep pipeline_bars_processed_total
# Rate = (value_now - value_60s_ago) / 60
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

Rewrite hot plugins (I1 indicators, I4 context) in Rust.

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

- **Analysis:** `docs/ideas/pipeline-throughput-bottleneck-analysis.md`
- **Current State:** `docs/architecture/current-state.md`
- **Evolution:** `docs/architecture/renaissance-pipeline-evolution.md`

---

*Focus: Concepts and architecture, not implementation timelines*
