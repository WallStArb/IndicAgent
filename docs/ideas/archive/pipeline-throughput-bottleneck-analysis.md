# Pipeline Throughput Bottleneck Analysis

**Date:** 2026-04-07  
**Status:** Active investigation  
**Related:** Phase 58 (Pipeline Parallelization), Phase 62 (SSE cleanup)

## Problem Statement

Intelligence pipeline throughput is **4.5 bars/sec**, far below the Phase 58 benchmark target of 530 bars/sec (118x gap).

### Current Metrics

| Metric | Value | Target | Gap |
|--------|-------|--------|-----|
| Throughput | 4.5 bars/sec | 530 bars/sec | 118x slower |
| Per-bar latency | 140.78ms | ~2ms (benchmark) | 70x slower |
| I1 tier latency | 36ms | - | 25% of total |
| I7 tier latency | 13ms | - | 9% of total |
| I2-I6 latency | ~91ms | - | 65% of total |
| Thread pool workers | 48 (all idle at 0.9% CPU) | - | GIL-bound |
| Main thread CPU | 103% | - | Saturated |

## Root Cause: GIL Contention

### The Benchmark Fallacy

Phase 58 benchmark (`production/scripts/benchmark_thread_pool.py`) used:
```python
def _synthetic_plugin_work() -> dict:
    time.sleep(0.001)  # Releases GIL
    return {"value": 1.0}
```

**Problem:** `time.sleep()` releases the GIL, allowing threads to run in parallel. Real plugin computation is **CPU-bound Python code** which **cannot benefit from threading** due to the **Global Interpreter Lock (GIL)**.

### Why ThreadPoolExecutor Workers Are Idle

```
Main thread: 58.7% CPU (managing asyncio event loop)
Worker threads: 0.9% CPU each (waiting for GIL)
```

Even though plugins are offloaded via `loop.run_in_executor()`, the worker threads spend most of their time waiting for the GIL to execute Python bytecode. Only one thread can execute Python at a time.

### Pandas/NumPy GIL Behavior

**Good news:** Most I1 indicators use pandas/NumPy operations that DO release the GIL:
- 18/27 plugins use pandas
- 14/27 plugins use NumPy
- Operations like `.rolling()`, `.ewm()`, `.mean()` execute C code (GIL released)

**Bad news:** Python wrapper code is GIL-bound:
- Dataframe extraction/copying
- Result dict construction
- State serialization for incremental updates
- **Python loops** (66 found across I1 indicators)

## Identified Bottlenecks

### 1. OBVMomentum Plugin (I2 Tier)

**File:** `src/intelligence/composites/obv_momentum.py`  
**Timing:** 4.61ms per call (8 seconds total per 1,748 bars)  
**Issue:** Pure Python loop for OBV calculation (lines 41-47)

```python
# CURRENT: GIL-bound loop
obv = np.zeros(len(close))
for i in range(1, len(close)):
    if close[i] > close[i - 1]:
        obv[i] = obv[i - 1] + volume[i]
    elif close[i] < close[i - 1]:
        obv[i] = obv[i - 1] - volume[i]
    else:
        obv[i] = obv[i - 1]
```

**Fix:** Vectorize with NumPy
```python
# PROPOSED: GIL-releasing vectorized
price_changes = np.sign(close[1:] - close[:-1])
obv_values = volume[1:] * price_changes
obv = np.concatenate([[0], obv_values]).cumsum()
```

### 2. I2 Tier Composite Plugins

**Top bottlenecks:**
- `OBVMomentum`: 4.61ms/call (Python loop)
- `MomentumAcceleration`: 1.34ms/call (needs investigation)
- Other I2 plugins: 0.02-0.06ms each

**Total I2 latency:** ~91ms (65% of pipeline)

### 3. I1 Indicator Python Loops

**Finding:** 66 Python loops across 27 I1 indicators (2.4 loops per plugin average)

**Example:** RSI plugin has GIL-bound smoothing loop (lines 106-111):
```python
for i in range(period + 1, len(close)):
    delta = deltas[i - 1]
    up_val = (up_val * (period - 1) + max(delta, 0)) / period
    down_val = (down_val * (period - 1) + max(-delta, 0)) / period
    # ...
```

**Impact:** Even though NumPy operations release the GIL, the Python loops around them do not.

## Architecture Constraints

### Why Threading Doesn't Help

The current Phase 58 parallelization uses:
```python
loop.run_in_executor(self._executor, _timed_plugin_call, plugin, frames)
```

**Problem:** ThreadPoolExecutor + CPU-bound Python code = GIL contention.

**What releases GIL:**
- NumPy/pandas C operations
- I/O operations (file, network, DB)
- `time.sleep()`

**What does NOT release GIL:**
- Pure Python computation
- Python loops
- Object attribute access
- Dict/list operations

### Why the Benchmark Was Misleading

The benchmark simulated plugins with `time.sleep(1ms)`, which:
1. Releases GIL immediately
2. Allows 48 threads to run in parallel
3. Achieves 530 bars/sec

Real plugins:
1. Use pandas/NumPy (GIL released for C code)
2. But have Python wrapper overhead (GIL-bound)
3. Have Python loops (GIL-bound)
4. Achieve 4.5 bars/sec

## Potential Solutions

### Option 1: Vectorize Python Loops (Quick Win)

**Impact:** 2-5x speedup  
**Effort:** Low-Medium  
**Risk:** Low

**Targets:**
1. OBVMomentum plugin (I2) → 4.6ms → ~0.5ms
2. RSI smoothing loop (I1) → Can use pandas EWMA
3. Other indicators with explicit loops

**Approach:** Replace Python loops with NumPy vectorized operations.

### Option 2: Multiprocessing (High Impact, High Cost)

**Impact:** 10-20x speedup (bypasses GIL)  
**Effort:** High  
**Risk:** Medium

**Approach:** Replace `ThreadPoolExecutor` with `ProcessPoolExecutor`.

**Challenges:**
- Higher process spawn overhead
- Data serialization (pickling) cost
- State management complexity
- Memory usage (each process needs copy of data)

**Best for:** Batch processing, not real-time streaming.

### Option 3: Native Extensions (Maximum Impact)

**Impact:** 50-100x speedup  
**Effort:** Very High  
**Risk:** High

**Approach:** Rewrite compute-heavy plugins in Rust/C++ with Python bindings.

**Examples:**
- PyO3 (Rust) or pybind11 (C++)
- Compile indicators to native shared libraries
- Zero-copy data access via NumPy C API

**Trade-off:** Development speed vs runtime speed.

### Option 4: Batch Processing (Architectural Change)

**Impact:** 10-50x speedup  
**Effort:** High  
**Risk:** Medium

**Approach:** Process bars in batches (e.g., 100 bars at once) instead of one-by-one.

**Benefits:**
- Amortize Python overhead over larger datasets
- Better NumPy vectorization opportunities
- Reduce serialization overhead

**Challenges:**
- Increased latency (wait for batch to fill)
- State management complexity
- Real-time responsiveness trade-off

## Recommended Action Plan

### Phase 1: Low-Hanging Fruit (1-2 days)

1. **Vectorize OBVMomentum** → Expected 2-3ms/bar savings
2. **Audit I1 loops** → Vectorize top 5 bottlenecks
3. **Profile I2-I6 tiers** → Identify remaining hotspots

**Target throughput:** 15-20 bars/sec (3-4x improvement)

### Phase 2: Batch Processing (1 week)

1. **Batch bar ingestion** → Process 50-100 bars at once
2. **Vectorize across batch dimension** → NumPy operations on (bars, features) arrays
3. **Incremental fallback** → Use singleton mode for real-time, batch for catch-up

**Target throughput:** 50-100 bars/sec (10-20x improvement)

### Phase 3: Native Extensions (Optional, TBD)

1. **Profile to find remaining bottlenecks**
2. **Prioritize top 10 compute-heavy plugins**
3. **Prototype Rust extension for one plugin**
4. **Measure actual speedup vs development cost**

**Target throughput:** 200-500 bars/sec (50-100x improvement)

## Related Files

- `production/scripts/benchmark_thread_pool.py` - Misleading benchmark
- `services/intelligence_pipeline_agent.py` - Pipeline implementation
- `src/intelligence/composites/obv_momentum.py` - Top bottleneck
- `src/intelligence/features/i1_indicators/*.py` - 27 I1 plugins
- `.planning/phases/58-pipeline-parallelization-renaissance-completion/` - Phase 58 plans

## Test Results: OBVMomentum Vectorization

**Date:** 2026-04-07 16:45

**Change:** Replaced Python loop with vectorized NumPy operations
```python
# BEFORE: 4.61ms per call (GIL-bound loop)
obv = np.zeros(len(close))
for i in range(1, len(close)):
    if close[i] > close[i - 1]:
        obv[i] = obv[i - 1] + volume[i]
    # ...

# AFTER: 0.1ms per call (vectorized, releases GIL)
price_changes = np.sign(close[1:] - close[:-1])
obv_changes = volume[1:] * price_changes
obv = np.concatenate([[0], obv_changes]).cumsum()
```

**Result:** OBVMomentum time decreased from 8057ms → 177ms (46x faster per 1748 bars)

**Impact on overall throughput:** NONE (still 4.6 bars/sec)

**Conclusion:** Vectorizing individual plugins helps locally but doesn't solve the fundamental GIL bottleneck. The ThreadPoolExecutor architecture cannot achieve 50+ bars/sec with CPU-bound Python work.

## Updated Recommendation

**Abandon threading approach.** Implement one of:
1. **Batch processing** (10-50x improvement, medium effort)
2. **Multiprocessing** (10-20x improvement, high complexity)
3. **Native extensions** (50-100x improvement, very high effort)

The threading parallelization from Phase 58 is fundamentally unsuited for this workload.

## Next Steps

1. ✅ Identify bottlenecks (completed)
2. ✅ Vectorize OBVMomentum plugin (proved ineffective for overall throughput)
3. ⏳ **DECISION REQUIRED:** Choose batch processing vs multiprocessing vs native extensions
4. ⏳ Design chosen architecture
5. ⏳ Implement and test

## References

- [Python GIL Documentation](https://docs.python.org/3/glossary.html#term-global-interpreter-lock)
- [NumPy Performance Tips](https://numpy.org/doc/stable/user/basics.performance.html)
- [Multiprocessing vs Threading](https://docs.python.org/3/library/multiprocessing.html)
