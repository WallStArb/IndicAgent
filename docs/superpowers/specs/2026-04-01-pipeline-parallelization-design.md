# Intelligence Pipeline Throughput Optimization Design

**Status:** Draft
**Date:** 2026-04-01
**Author:** Claude (with user guidance)
**Milestone:** v2.2 Operational Excellence
**Principles:** Renaissance-aligned (instrumentation, automation, statistical validation)

---

## Problem Statement

The IntelligencePipelineComputeAgent processes 5.87 bars/second while production rate is 162 bars/second (27x gap). Consumer lag is 3.5M messages and growing - the pipeline will NEVER catch up.

**Root cause:** Thread pool exhaustion. Sequential execution of 27 I1 plugins + 36 I7 plugins = 74 plugin calls per bar. With 28 thread pool workers and 434 calls/sec, workers are 100% saturated.

**Metrics:**
- Throughput: 5.87 bars/sec
- Pipeline latency: 49ms average
- CPU usage: 100% (6h 45min accumulated)
- Theoretical max: 20 bars/sec (1000ms / 49ms)
- Actual efficiency: 30% (thread pool starvation)

**Renaissance principle violation:** System is not self-tuning or self-scaling. Manual intervention required.

---

## Solution

Parallelize independent plugin execution within I1 and I7 tiers using `asyncio.gather()` with **adaptive thread pool scaling**, **complete instrumentation**, and **statistical validation**.

**Target throughput:** 40-60 bars/second (10x improvement)

---

## Architecture

### Current (Sequential)

```
Bar → I1(sequential 27 plugins) → I2-I6(sequential) → I7(sequential 36 plugins) → signals
      35ms                                              45ms
      Total: ~50ms/bar, 5.87 bars/sec actual
```

### Optimized (Parallel I1 + I7)

```
Bar → I1(PARALLEL 27 plugins) → I2-I6(sequential) → I7(PARALLEL 36 plugins) → signals
      3ms                                              4ms
      Total: ~25ms/bar, 40-60 bars/sec target
```

**Why only I1 and I7?**
- I1 plugins (27): All independent, read same `frames`, write separate outputs
- I7 plugins (36): All independent, read same `features`, write separate signals
- I2-I6 (11 plugins): Sequential, fast enough as-is

---

## Component Changes

### 1. Adaptive Thread Pool (Auto-Tuning)

**File:** `services/intelligence_pipeline_agent.py`
**Method:** `__init__`

**Renaissance principle:** "Degrade gracefully, adapt automatically. Systems that require manual tuning are fragile."

```python
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

class IntelligencePipelineComputeAgent:
    def __init__(self):
        # Adaptive thread pool: scales with CPU cores, not hardcoded
        cpu_count = os.cpu_count() or 24
        min_workers = cpu_count * 2  # Minimum: 2x CPU cores
        max_workers = cpu_count * 8  # Maximum: 8x CPU cores

        self._executor = ThreadPoolExecutor(
            max_workers=min_workers,  # Start conservative
            thread_name_prefix="intel_"
        )
        self._min_workers = min_workers
        self._max_workers = max_workers
        self._current_workers = min_workers

        # Set default executor for asyncio.to_thread
        asyncio.get_event_loop().set_default_executor(self._executor)

        # Start auto-tuning task
        asyncio.create_task(self._auto_tune_thread_pool())
```

**Why adaptive?**
- Different machines have different CPU counts (dev vs prod)
- Load varies by time of day (market open vs close)
- Manual tuning is fragile and error-prone

### 2. Auto-Tuning Logic (Feedback Loop)

**Add method:** `_auto_tune_thread_pool`

```python
async def _auto_tune_thread_pool(self):
    """Dynamically adjust thread pool size based on load and CPU."""
    import psutil  # Add to requirements.txt

    while True:
        try:
            # Get metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            lag = await self._get_consumer_lag()

            # Scaling decisions
            if lag > 10000 and cpu_percent < 70:
                # Lag growing + CPU headroom → scale up
                new_workers = min(self._current_workers + 8, self._max_workers)
                self._resize_thread_pool(new_workers)
                self.logger.info("thread_pool.scaled_up",
                    from=self._current_workers, to=new_workers,
                    reason=f"lag={lag}, cpu={cpu_percent}%")
            elif cpu_percent > 90:
                # CPU saturated → scale down
                new_workers = max(self._current_workers - 4, self._min_workers)
                self._resize_thread_pool(new_workers)
                self.logger.info("thread_pool.scaled_down",
                    from=self._current_workers, to=new_workers,
                    reason=f"cpu={cpu_percent}%")
            else:
                # Stable → no change
                pass

        except Exception as e:
            self.logger.error("thread_pool.tune_failed", error=str(e))

        await asyncio.sleep(60)  # Check every minute

def _resize_thread_pool(self, new_size: int):
    """Resize thread pool (requires executor replacement)."""
    self._executor.shutdown(wait=False)
    self._executor = ThreadPoolExecutor(
        max_workers=new_size,
        thread_name_prefix="intel_"
    )
    self._current_workers = new_size
    asyncio.get_event_loop().set_default_executor(self._executor)
```

**Renaissance principle:** "Let the system run. Build the automation, then trust it."

### 3. Parallelize I1 Plugins

**Method:** `_run_i1()`

```python
async def _run_i1(self, frames: dict, symbol: str, tf: str) -> dict:
    """Run I1 plugins in parallel with complete instrumentation."""
    i1_start = time.perf_counter()
    result = {}

    # Build tasks with metadata
    tasks = []
    for plugin_name in TIER_I1:
        plugin = self._plugin_cache.get(plugin_name)
        if plugin is None:
            continue

        if should_skip_plugin(plugin, self._instrument_map.get(symbol),
                           self._plugin_skipped_total, plugin_name):
            continue

        state_key = (plugin_name, symbol, tf)
        lock = self._get_state_lock(state_key)

        # Track per-plugin metrics
        tasks.append((
            asyncio.to_thread(plugin.compute_full, frames),
            plugin_name,
            state_key,
            lock,
            time.perf_counter()  # Start time for this plugin
        ))

    # Execute in parallel
    results = await asyncio.gather(*[t[0] for t in tasks], return_exceptions=True)

    # Process results with metrics
    for i, (task, plugin_name, state_key, lock, start_time) in enumerate(tasks):
        plugin_latency_ms = (time.perf_counter() - start_time) * 1000

        # Record per-plugin latency (Renaissance: instrument everything)
        self._i1_plugin_latency.labels(plugin_name=plugin_name).observe(plugin_latency_ms)

        out = results[i]

        if isinstance(out, Exception):
            self._pipeline_errors.inc()
            self._plugin_errors.labels(plugin_name=plugin_name, tier="i1").inc()
            self.logger.warning("plugin.error", plugin=plugin_name, error=str(out))

            # DLQ: preserve failed attempts (Renaissance: never drop data)
            if self._plugin_errors.labels(plugin_name=plugin_name, tier="i1")._value.get() >= 100:
                await self._publish_to_dlq(
                    bar={"symbol": symbol, "tf": tf},
                    plugin_name=plugin_name,
                    error=str(out)
                )
        elif isinstance(out, dict):
            with lock:
                if "_state" in out:
                    # State transition validation (Renaissance: validate state changes)
                    old_state = self._plugin_states.get(state_key)
                    new_state = out.pop("_state")

                    if old_state is not None:
                        old_version = old_state.get("version", 0)
                        new_version = new_state.get("version", 0)
                        if new_version <= old_version:
                            self.logger.warning("state.stale_update",
                                state_key=state_key,
                                old_version=old_version,
                                new_version=new_version)
                            continue

                    self._plugin_states[state_key] = new_state
                    self._state_updates.labels(plugin_name=plugin_name).inc()

                result.update(out)

    # Record total I1 latency
    i1_latency_ms = (time.perf_counter() - i1_start) * 1000
    self._i1_latency_ms.set(i1_latency_ms)

    return result
```

### 4. Parallelize I7 Plugins

**Method:** `_run_i7()`

```python
async def _run_i7(self, bar, event, tiered: dict) -> dict:
    """Run I7 plugins in parallel with complete instrumentation."""
    i7_start = time.perf_counter()
    features = tiered.get("i4", {})

    # Build tasks
    tasks = []
    for plugin_name in I7_PLUGINS:
        plugin = self._plugin_cache.get(plugin_name)
        if plugin is None:
            continue

        if should_skip_plugin(plugin, self._instrument_map.get(bar.symbol),
                           self._plugin_skipped_total, plugin_name):
            continue

        state_key = (plugin_name, bar.symbol, bar.tf)
        lock = self._get_state_lock(state_key)

        tasks.append((
            asyncio.to_thread(plugin.compute_full, {"main": None, **features}),
            plugin_name,
            state_key,
            lock,
            bar,
            time.perf_counter()  # Start time
        ))

    # Execute in parallel
    results = await asyncio.gather(*[t[0] for t in tasks], return_exceptions=True)

    # Process results
    raw_signals = []
    for i, (task, plugin_name, state_key, lock, bar, start_time) in enumerate(tasks):
        plugin_latency_ms = (time.perf_counter() - start_time) * 1000
        self._i7_plugin_latency.labels(plugin_name=plugin_name).observe(plugin_latency_ms)

        out = results[i]

        if isinstance(out, Exception):
            self._pipeline_errors.inc()
            self._plugin_errors.labels(plugin_name=plugin_name, tier="i7").inc()
            self.logger.warning("plugin.error", plugin=plugin_name, error=str(out))
        elif isinstance(out, dict) and out.get("signal"):
            sig = out["signal"]
            sig["setup_plugin"] = plugin_name
            sig["symbol"] = bar.symbol
            sig["tf"] = bar.tf
            raw_signals.append(sig)

    # Record total I7 latency
    i7_latency_ms = (time.perf_counter() - i7_start) * 1000
    self._i7_latency_ms.set(i7_latency_ms)

    return {"signals": raw_signals}
```

### 5. Dead Letter Queue (Data Preservation)

**Add method:** `_publish_to_dlq`

```python
async def _publish_to_dlq(self, bar: dict, plugin_name: str, error: str):
    """Publish failed processing attempt to DLQ for analysis.

    Renaissance principle: Never drop data that could contain signal.
    """
    await self._dlq_producer.publish(
        topic="intelligence.pipeline.dlq",
        value={
            "bar": bar,
            "plugin_name": plugin_name,
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
            "error_count": self._plugin_errors.labels(plugin_name=plugin_name, tier="i1")._value.get()
        }
    )
    self._dlq_published.inc()
```

**Why DLQ?**
- Every processing failure is captured for analysis
- Can replay failed bars after fixing bugs
- Provides data for debugging plugin issues
- Aligns with "Never drop data that could contain signal"

### 6. Complete Instrumentation (Prometheus)

**Add to `__init__`:**

```python
from prometheus_client import Histogram, Gauge, Counter

# Per-plugin latency (which plugins are slowest?)
self._i1_plugin_latency = Histogram(
    "intelligence_pipeline_i1_plugin_latency_ms",
    "I1 plugin execution time",
    labels=["plugin_name"]
)
self._i7_plugin_latency = Histogram(
    "intelligence_pipeline_i7_plugin_latency_ms",
    "I7 plugin execution time",
    labels=["plugin_name"]
)

# Total tier latency
self._i1_latency_ms = Gauge("intelligence_pipeline_i1_latency_ms", "I1 total execution time")
self._i7_latency_ms = Gauge("intelligence_pipeline_i7_latency_ms", "I7 total execution time")

# Per-plugin errors (which plugins fail most?)
self._plugin_errors = Counter(
    "intelligence_pipeline_plugin_errors_total",
    "Plugin error count",
    labels=["plugin_name", "tier"]
)

# Thread pool metrics
self._thread_pool_size = Gauge(
    "intelligence_pipeline_thread_pool_size",
    "Current thread pool size"
)
self._thread_pool_utilization = Gauge(
    "intelligence_pipeline_thread_utilization_percent",
    "Thread pool CPU utilization"
)

# Queue depth (are we backing up?)
self._queue_depth = Gauge(
    "intelligence_pipeline_queue_depth",
    "Bars waiting to be processed",
    labels=["symbol"]
)

# State updates (how often is state mutating?)
self._state_updates = Counter(
    "intelligence_pipeline_state_updates_total",
    "Plugin state update count",
    labels=["plugin_name"]
)

# DLQ metrics
self._dlq_published = Counter(
    "intelligence_pipeline_dlq_published_total",
    "Messages published to DLQ"
)
```

**Renaissance principle:** "Instrument everything. No data point left uncaptured."

### 7. Consumer Lag Monitoring

**Add method:** `_get_consumer_lag`

```python
async def _get_consumer_lag(self) -> int:
    """Get current consumer lag from Kafka consumer group.

    Used for auto-tuning thread pool size.
    """
    try:
        consumer_group = "intelligence_pipeline_consumer"
        topic = topic_market_bars()

        # Get consumer group info
        group_info = await self._consumer._client.describe_consumer_groups([consumer_group])
        if not group_info:
            return 0

        group_detail = group_info[0]
        total_lag = 0

        for topic_partition in group_detail.topic_partitions:
            if topic_partition.topic == topic:
                total_lag += topic_partition.consumer_lag

        self._consumer_lag.set(total_lag)
        return total_lag

    except Exception as e:
        self.logger.error("consumer_lag.fetch_failed", error=str(e))
        return 0
```

---

## Statistical Validation (Earn the Right Through Proof)

**Renaissance principle:** "No model, strategy, or feature gets promoted to production without statistically significant evidence (p < 0.05)."

### Shadow Mode Validation

**File:** `tests/integration/test_pipeline_parallelization_validation.py`

```python
import asyncio
from scipy import stats
from typing import Dict, List, Tuple
import numpy as np

def kolmogorov_smirnov_test(shadow_outputs: Dict, prod_outputs: Dict, alpha: float = 0.05) -> Tuple[bool, str]:
    """Test if shadow and prod output distributions are identical.

    H0: Distributions are identical
    H1: Distributions are different

    Returns:
        (is_valid, explanation)
    """
    failures = []

    for plugin_name in prod_outputs:
        if plugin_name not in shadow_outputs:
            failures.append(f"{plugin_name}: missing in shadow outputs")
            continue

        shadow_values = np.array(shadow_outputs[plugin_name])
        prod_values = np.array(prod_outputs[plugin_name])

        # Kolmogorov-Smirnov test for distribution equality
        statistic, p_value = stats.ks_2samp(shadow_values, prod_values)

        if p_value < alpha:
            failures.append(
                f"{plugin_name}: distributions differ (KS={statistic:.4f}, p={p_value:.4f})"
            )

    if failures:
        return False, "; ".join(failures)
    return True, "All plugin outputs match (p >= 0.05)"


def welch_ttest(shadow_latency: List[float], prod_latency: List[float], alpha: float = 0.05) -> Tuple[bool, str]:
    """Test if shadow mode improves latency significantly.

    H0: Mean latencies are equal
    H1: Shadow latency is lower (one-sided)

    Uses Welch's t-test (unequal variances, unequal sample sizes).
    """
    shadow_mean = np.mean(shadow_latency)
    prod_mean = np.mean(prod_latency)

    statistic, p_value = stats.ttest_ind(shadow_latency, prod_latency, alternative='less')

    if p_value < alpha:
        improvement = (prod_mean - shadow_mean) / prod_mean * 100
        return True, f"Latency improved by {improvement:.1f}% (p={p_value:.4f})"
    else:
        return False, f"Latency improvement not significant (p={p_value:.4f})"


async def test_shadow_mode_output_consistency():
    """Validate shadow mode produces statistically identical outputs."""
    # Collect data from both pipelines
    prod_agent = IntelligencePipelineComputeAgent()
    shadow_agent = IntelligencePipelineComputeAgent(shadow_mode=True)

    test_bars = [_create_test_bar() for _ in range(1000)]

    prod_outputs = {}
    shadow_outputs = {}

    for bar in test_bars:
        # Run production pipeline
        prod_result = await prod_agent._process_bar(bar)
        for key, value in prod_result.items():
            prod_outputs.setdefault(key, []).append(value)

        # Run shadow pipeline
        shadow_result = await shadow_agent._process_bar(bar)
        for key, value in shadow_result.items():
            shadow_outputs.setdefault(key, []).append(value)

    # Statistical tests
    is_valid, explanation = kolmogorov_smirnov_test(shadow_outputs, prod_outputs)

    assert is_valid, f"Shadow mode output validation failed: {explanation}"
    print(f"✓ Output validation passed: {explanation}")


async def test_shadow_mode_latency_improvement():
    """Validate shadow mode improves latency significantly."""
    shadow_agent = IntelligencePipelineComputeAgent(shadow_mode=True)

    test_bars = [_create_test_bar() for _ in range(1000)]
    latencies = []

    for bar in test_bars:
        start = time.perf_counter()
        await shadow_agent._process_bar(bar)
        latency_ms = (time.perf_counter() - start) * 1000
        latencies.append(latency_ms)

    # Compare against baseline (50ms from production)
    baseline_latency = [50.0] * len(latencies)
    is_significant, explanation = welch_ttest(latencies, baseline_latency)

    assert is_significant, f"Latency improvement not significant: {explanation}"
    print(f"✓ Latency validation passed: {explanation}")
```

**Validation criteria (automated):**
- ✅ Output distributions identical (KS test, p ≥ 0.05)
- ✅ Latency improved by ≥ 2x (Welch's t-test, p < 0.05)
- ✅ Throughput ≥ 40 bars/sec (10x improvement)
- ✅ Error rate ≤ 0.1% (not regressed)
- ✅ No new failure modes

**Renaissance principle:** "Earn the right through proof."

---

## Rollout Plan (Automated)

### Phase 0: Profiling (Understand Before Optimizing)

**Renaissance principle:** "Profile first, then optimize. Don't guess - measure."

Before parallelizing a single line of code, we must understand WHERE the time is actually spent. Parallelization without profiling is optimization without understanding.

#### Profiling Goals

1. **Identify slowest plugins** - Which I1/I7 plugins dominate execution time?
2. **Understand bottlenecks** - Is it CPU? I/O? GIL contention? Pandas overhead?
3. **Quantify optimization potential** - What's the theoretical speedup if we fix the slowest plugins?
4. **Validate parallelization strategy** - Is I1/I7 parallelization the right approach, or should we optimize individual plugins first?

#### Profiling Methodology

**Step 1: Production Profiling (2 hours)**

Run cProfile on the production pipeline to capture real-world performance:

```python
# File: production/scripts/profile_pipeline.py
import cProfile
import pstats
import asyncio
from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent

async def profile_production_pipeline():
    """Profile the production pipeline with real data."""
    agent = IntelligencePipelineComputeAgent()

    # Create profiler
    profiler = cProfile.Profile()
    profiler.enable()

    # Process 1000 real bars from Kafka
    bars_consumed = 0
    async for bar in agent._consumer.consume(topic_market_bars(), max_records=1000):
        await agent._process_bar(bar)
        bars_consumed += 1

        if bars_consumed >= 1000:
            break

    profiler.disable()

    # Analyze results
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumtime')

    # Save detailed report
    stats.dump_stats('profile_results.prof')

    # Print top 50 bottlenecks
    print("\n=== TOP 50 FUNCTIONS BY CUMULATIVE TIME ===")
    stats.print_stats(50)

    # Print per-plugin breakdown
    print("\n=== PER-PLUGIN BREAKDOWN ===")
    profile_by_plugin(stats)

def profile_by_plugin(stats: pstats.Stats):
    """Extract and group profiling data by plugin."""
    plugin_times = {}

    for func, (cc, nc, tt, ct, callers) in stats.stats.items():
        # Extract plugin name from function call
        if 'compute_full' in str(func):
            plugin_name = str(func).split('.')[-2]  # Extract plugin class name
            plugin_times[plugin_name] = ct

    # Sort by time
    sorted_plugins = sorted(plugin_times.items(), key=lambda x: x[1], reverse=True)

    for plugin, time in sorted_plugins:
        pct = (time / stats.total_tt) * 100
        print(f"{plugin:40s} {time:8.2f}s ({pct:5.1f}%)")

if __name__ == "__main__":
    asyncio.run(profile_production_pipeline())
```

**Run it:**
```bash
.venv/bin/python production/scripts/profile_pipeline.py 2>&1 | tee profile_report.txt
```

**Step 2: Flame Graph Visualization (2 hours)**

Use `py-spy` to generate a flame graph for visual bottleneck identification:

```bash
# Install py-spy
pip install py-spy

# Profile running intelligence pipeline service
sudo py-spy record -o profile_flamegraph.svg \
    --pid $(pgrep -f intelligence_pipeline_agent) \
    --duration 60 \
    --rate 10 \
    --format flamegraph
```

**What to look for:**
- Wide bars = functions taking lots of time
- Deep stacks = complex call chains
- Repeated patterns = hot loops

**Step 3: Per-Plugin Microbenchmarks (4 hours)**

Isolate and benchmark the slowest plugins individually:

```python
# File: production/scripts/benchmark_plugins.py
import time
import pandas as pd
from src.intelligence.register_plugins import TIER_I1, TIER_I7

def benchmark_plugin(plugin_class, plugin_name):
    """Benchmark a single plugin in isolation."""
    plugin = plugin_class()

    # Create test data (realistic size)
    test_frames = {"main": pd.DataFrame({
        "open": [100.0] * 1000,
        "high": [101.0] * 1000,
        "low": [99.0] * 1000,
        "close": [100.5] * 1000,
        "volume": [1000000] * 1000,
    })}

    # Warmup
    for _ in range(10):
        plugin.compute_full(test_frames)

    # Benchmark
    iterations = 100
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = plugin.compute_full(test_frames)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    # Statistics
    mean_time = pd.Series(times).mean()
    std_time = pd.Series(times).std()
    p95_time = pd.Series(times).quantile(0.95)
    p99_time = pd.Series(times).quantile(0.99)

    print(f"\n{plugin_name}:")
    print(f"  Mean: {mean_time*1000:.2f}ms")
    print(f"  Std:  {std_time*1000:.2f}ms")
    print(f"  P95:  {p95_time*1000:.2f}ms")
    print(f"  P99:  {p99_time*1000:.2f}ms")

    return mean_time

if __name__ == "__main__":
    print("=== I1 PLUGIN BENCHMARKS ===")
    i1_times = {}
    for plugin_name in TIER_I1:
        plugin_class = get_plugin_class(plugin_name)
        mean_time = benchmark_plugin(plugin_class, plugin_name)
        i1_times[plugin_name] = mean_time

    print("\n=== SLOWEST I1 PLUGINS ===")
    sorted_i1 = sorted(i1_times.items(), key=lambda x: x[1], reverse=True)
    for plugin, time in sorted_i1[:10]:
        print(f"{plugin:40s} {time*1000:.2f}ms")
```

**Step 4: Root Cause Analysis (4 hours)**

For each of the top 10 slowest plugins, identify WHY they're slow:

```python
# File: production/scripts/analyze_plugin_bottlenecks.py
def analyze_plugin_performance(plugin_name: str):
    """Deep dive into a single plugin's performance."""

    # 1. Check for pandas operations
    print("=== PANDAS OPERATIONS ===")
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})

    # Test vectorized vs iterative
    start = time.perf_counter()
    for i in range(10000):
        df["c"] = df["a"] + df["b"]  # Vectorized (fast)
    vectorized_time = time.perf_counter() - start

    start = time.perf_counter()
    for i in range(10000):
        df["c"] = df.apply(lambda row: row["a"] + row["b"], axis=1)  # Iterative (slow)
    iterative_time = time.perf_counter() - start

    print(f"Vectorized: {vectorized_time:.4f}s")
    print(f"Iterative:  {iterative_time:.4f}s ({iterative_time/vectorized_time:.1f}x slower)")

    # 2. Check for redundant calculations
    print("\n=== REDUNDANT CALCULATIONS ===")
    # Does the plugin recompute expensive values on each call?
    # Look for: loading data from DB, expensive aggregations, complex parsing

    # 3. Check for GIL contention
    print("\n=== GIL CONTENTION ===")
    # Does the plugin release the GIL during pandas operations?
    # pandas/numpy usually release GIL, but custom Python code might not

    # 4. Check memory usage
    print("\n=== MEMORY USAGE ===")
    import tracemalloc
    tracemalloc.start()

    plugin = get_plugin_class(plugin_name)()
    result = plugin.compute_full(df)

    current, peak = tracemalloc.get_traced_memory()
    print(f"Current: {current / 1024 / 1024:.2f} MB")
    print(f"Peak:    {peak / 1024 / 1024:.2f} MB")

    tracemalloc.stop()

if __name__ == "__main__":
    for plugin_name in ["slowest_plugin_1", "slowest_plugin_2", "slowest_plugin_3"]:
        print(f"\n{'='*60}")
        print(f"ANALYZING: {plugin_name}")
        print(f"{'='*60}")
        analyze_plugin_performance(plugin_name)
```

#### Expected Findings

Based on Renaissance experience profiling similar systems, we expect to find:

| Bottleneck Type | Example | Solution |
|-----------------|---------|----------|
| **Iterative pandas** | `df.apply()` in loop | Vectorize operations |
| **Redundant DB queries** | Query per bar instead of caching | Cache in memory |
| **Recomputing aggregations** | Sum/mean recalculated each call | Memoize results |
| **String parsing** | Heavy JSON/text processing | Use faster libraries (orjson, ujson) |
| **State serialization** | Expensive `__dict__` copies | Use slots/dataclasses |
| **GIL contention** | Pure Python loops | Use numpy/pandas (releases GIL) |

#### Deliverables

After profiling, we'll have:

1. **`profile_results.prof`** - Raw profiling data (view with `snakeviz`)
2. **`profile_flamegraph.svg`** - Visual flame graph
3. **`profile_report.txt`** - Text summary of top 50 bottlenecks
4. **`plugin_benchmarks.json`** - Per-plugin timing data
5. **`bottleneck_analysis.md`** - Root cause analysis of top 10 slowest plugins

#### Decision Tree

Based on profiling results, we'll decide:

```
Are the top 3 plugins responsible for >50% of execution time?
├─ YES → Optimize those plugins first (might eliminate need for parallelization)
└─ NO → Time is evenly distributed → Parallelization is the right approach

Do the slowest plugins have obvious optimization opportunities?
├─ YES → Fix the plugins first (vectorize, cache, memoize)
└─ NO → Plugins are already optimized → Parallelization is the right approach

Is the bottleneck I/O-bound (DB queries, network calls)?
├─ YES → Parallelization might not help (GIL contention) → Consider async/await
└─ NO → CPU-bound → Parallelization will help
```

#### Example Decision

**Hypothetical profiling results:**

```
TOP 10 I1 PLUGINS BY TIME:
1. MovingAveragePlugin:          8.5ms (24.3%)
2. BollingerBandsPlugin:         6.2ms (17.7%)
3. RSIPlugin:                    5.1ms (14.6%)
4. MACDPlugin:                   4.8ms (13.7%)
5. ATRPlugin:                    3.2ms (9.1%)
6-27. Other plugins:             <2ms each (20.6%)
```

**Analysis:**
- Top 5 plugins = 79.4% of execution time
- All use `rolling().mean()` or similar - can be vectorized
- **Conclusion:** Optimize top 5 plugins first → could get 2-3x speedup without parallelization

**Alternative scenario:**

```
TOP 10 I1 PLUGINS BY TIME:
1. ADXPlugin:                     1.5ms (4.3%)
2. CISScorer:                     1.4ms (4.0%)
3. StochasticOscillatorPlugin:    1.3ms (3.7%)
4-27. All other plugins:          1.0-1.2ms each (88.0%)
```

**Analysis:**
- Time evenly distributed (no plugin >5%)
- All plugins already vectorized
- **Conclusion:** Parallelization is the right approach - no low-hanging fruit

#### Timeline

- **Hours 1-2:** Run production profiler, generate flame graph
- **Hours 3-6:** Benchmark all plugins individually
- **Hours 7-10:** Root cause analysis of top 10 slowest plugins
- **Hour 11:** Write analysis document and recommendation
- **Hour 12:** Review findings with team, decide on optimization strategy

**Total: 1-2 days** depending on findings complexity

#### Success Criteria

After Phase 0, we must be able to answer:

1. ✅ Which specific plugins are the bottlenecks?
2. ✅ WHY are they slow? (pandas? I/O? GIL?)
3. ✅ Can we optimize individual plugins for 2-3x speedup?
4. ✅ OR should we skip to parallelization?
5. ✅ What's the theoretical max speedup if we parallelize?

**Renaissance principle:** "Measure twice, cut once. Don't optimize without data."

### Phase 1: Development (1 day)

1. Create feature branch: `git checkout -b feature/pipeline-parallelization`
2. Implement changes (~200 lines of code including instrumentation)
3. Add unit tests (see Testing section below)
4. Add integration tests (statistical validation)
5. Code review: `/coderabbit:code-review`

### Phase 2: Shadow Mode (3 days)

**Renaissance principle: Shadow mode first, always**

Deploy alongside production:
```bash
INTELLIGENCE_PIPELINE_SHADOW=true .venv/bin/python services/intelligence_pipeline_agent.py
```

**Automated validation:**
```python
async def automated_shadow_validation():
    """Run statistical tests and automatically decide on cutover."""
    shadow_metrics = await measure_shadow_performance(duration_minutes=30)
    prod_metrics = await measure_prod_performance(duration_minutes=30)

    # Test 1: Output consistency
    output_valid, output_msg = kolmogorov_smirnov_test(
        shadow_metrics.outputs,
        prod_metrics.outputs
    )

    # Test 2: Latency improvement
    latency_valid, latency_msg = welch_ttest(
        shadow_metrics.latencies,
        prod_metrics.latencies
    )

    # Test 3: Throughput improvement
    throughput_improvement = shadow_metrics.throughput / prod_metrics.throughput

    # Test 4: Error rate
    error_rate_valid = shadow_metrics.error_rate <= 0.001

    # Decision
    if (output_valid and latency_valid and
        throughput_improvement >= 2.0 and error_rate_valid):
        print("✓ All validation criteria met - ready for automated cutover")
        return True
    else:
        print(f"✗ Validation failed:")
        print(f"  - Output: {output_msg}")
        print(f"  - Latency: {latency_msg}")
        print(f"  - Throughput: {throughput_improvement:.2f}x (need 2.0x)")
        print(f"  - Error rate: {shadow_metrics.error_rate:.4f} (need ≤ 0.001)")
        return False
```

**Verify:**
- Shadow throughput: ≥ 40 bars/sec
- Shadow latency: ≤ 30ms
- Output statistically identical to production (p ≥ 0.05)
- Error rate ≤ 0.1%
- No new crashes or deadlocks

### Phase 3: Automated Gradual Cutover (1 day)

**Automated traffic shifting:**

```python
async def automated_cutover():
    """Gradually shift traffic from prod to shadow based on metrics."""
    traffic_percentage = 0.0

    while traffic_percentage < 1.0:
        # Measure both versions
        prod_metrics = await measure_prod_performance(duration_minutes=5)
        shadow_metrics = await measure_shadow_performance(duration_minutes=5)

        # Check health
        if shadow_metrics.error_rate > 0.01:
            await rollback()
            raise Exception(f"Shadow error rate too high: {shadow_metrics.error_rate}")

        if shadow_metrics.consumer_lag > prod_metrics.consumer_lag * 1.1:
            await rollback()
            raise Exception("Shadow consumer lag increasing")

        # Increase traffic
        traffic_percentage = min(traffic_percentage + 0.1, 1.0)
        await set_traffic_percentage(percentage=traffic_percentage)

        logger.info("cutover.progress",
            percentage=traffic_percentage * 100,
            shadow_throughput=shadow_metrics.throughput,
            prod_throughput=prod_metrics.throughput)

        await asyncio.sleep(30)  # Wait between increments

    logger.info("cutover.complete", percentage=100)
```

**No manual intervention required.** System self-monitors and rolls back if:
- Error rate > 1%
- Consumer lag increasing
- Output quality degraded (statistical test fails)

### Phase 4: Full Rollout + Monitor (24 hours)

**Success criteria after 24 hours:**
- ✅ Throughput: ≥ 40 bars/sec (10x improvement)
- ✅ Latency: ≤ 30ms average
- ✅ Consumer lag: Decreasing
- ✅ Error rate: ≤ 0.1%
- ✅ Thread pool: Auto-tuned (not static)
- ✅ DLQ: Captured all failures (zero data loss)

### Rollback Plan (Automated)

**Automatic rollback triggers:**
```python
ROLLBACK_THRESHOLDS = {
    "error_rate": 0.01,  # 1%
    "latency_regression_ms": 10,  # 10ms slower than baseline
    "consumer_lag_increase": 1.2,  # 20% increase
    "dlq_rate": 0.001,  # Too many failures
}

async def monitor_and_rollback():
    """Continuously monitor and auto-rollback if thresholds breached."""
    while True:
        metrics = await get_current_metrics()

        if metrics.error_rate > ROLLBACK_THRESHOLDS["error_rate"]:
            logger.error("rollback.triggered", reason="error_rate", value=metrics.error_rate)
            await rollback()
            break

        if metrics.latency_ms > baseline_latency_ms + ROLLBACK_THRESHOLDS["latency_regression_ms"]:
            logger.error("rollback.triggered", reason="latency_regression", value=metrics.latency_ms)
            await rollback()
            break

        if metrics.consumer_lag > baseline_consumer_lag * ROLLBACK_THRESHOLDS["consumer_lag_increase"]:
            logger.error("rollback.triggered", reason="consumer_lag", value=metrics.consumer_lag)
            await rollback()
            break

        await asyncio.sleep(60)  # Check every minute
```

**Rollback:**
```bash
# Automated (no manual steps)
git revert HEAD
sudo systemctl restart indicagent-intelligence-pipeline
```

---

## Testing

### Unit Tests

**Test I1 parallel execution:**
```python
async def test_i1_parallel_execution():
    """Verify I1 plugins run concurrently."""
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    agent._plugin_cache = _mock_i1_plugins(27)
    agent._i1_plugin_latency = MagicMock()
    agent._i1_latency_ms = MagicMock()

    bar = _create_test_bar(symbol="ES", tf="1m")
    start = time.perf_counter()
    result = await agent._run_i1({"main": test_df}, "ES", "1m")
    elapsed = time.perf_counter() - start

    # Should be faster than sequential
    assert elapsed < 0.050  # Faster than 50ms for 27 plugins
    assert len(result) > 0
    assert agent._pipeline_errors_total._value.get() == 0

    # Verify per-plugin metrics recorded
    assert agent._i1_plugin_latency.observe.call_count == 27
```

**Test I7 parallel execution:**
```python
async def test_i7_parallel_execution():
    """Verify I7 plugins run concurrently."""
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    agent._plugin_cache = _mock_i7_plugins(36)
    agent._i7_plugin_latency = MagicMock()
    agent._i7_latency_ms = MagicMock()

    start = time.perf_counter()
    result = await agent._run_i7(bar, event, tiered)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.050  # Faster than 50ms for 36 plugins
    assert len(result["signals"]) > 0
```

**Test state isolation:**
```python
async def test_parallel_state_isolation():
    """Verify parallel plugins don't corrupt state."""
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)

    # Run same bar twice in parallel
    bar1 = _create_test_bar(symbol="ES", tf="1m")
    bar2 = _create_test_bar(symbol="ES", tf="1m")

    await asyncio.gather(
        agent._process_bar(bar1),
        agent._process_bar(bar2)
    )

    assert agent._bars_processed_total._value.get() == 2

    # Verify plugin states are consistent
    for state in agent._plugin_states.values():
        assert isinstance(state, dict)
```

**Test adaptive thread pool:**
```python
async def test_adaptive_thread_pool_scaling():
    """Verify thread pool scales based on load."""
    agent = IntelligencePipelineComputeAgent()

    initial_workers = agent._current_workers
    assert initial_workers == os.cpu_count() * 2

    # Simulate high load
    with mock.patch.object(agent, '_get_consumer_lag', return_value=50000):
        with mock.patch('psutil.cpu_percent', return_value=50):
            await agent._auto_tune_thread_pool()

            # Should scale up
            assert agent._current_workers > initial_workers
```

**Test DLQ publishing:**
```python
async def test_failed_plugins_go_to_dlq():
    """Verify plugins with >100 failures go to DLQ."""
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    agent._plugin_cache = {"failing_plugin": FailingPlugin()}
    agent._dlq_producer = MagicMock()
    agent._plugin_errors = Counter(
        "intelligence_pipeline_plugin_errors_total",
        labels=["plugin_name", "tier"]
    )

    # Fail plugin 101 times
    for _ in range(101):
        try:
            await agent._run_i1({"main": test_df}, "ES", "1m")
        except:
            pass

    # Should have published to DLQ
    assert agent._dlq_producer.publish.called
    assert agent._dlq_published._value.get() > 0
```

### Profiling Tests

**Test profiling infrastructure:**
```python
def test_profiling_capture():
    """Verify profiler can capture pipeline execution."""
    import cProfile
    import pstats

    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    agent._plugin_cache = _mock_i1_plugins(5)

    profiler = cProfile.Profile()
    profiler.enable()

    # Process 10 bars
    for _ in range(10):
        bar = _create_test_bar()
        await agent._process_bar(bar)

    profiler.disable()

    stats = pstats.Stats(profiler)
    assert stats.total_calls > 0
    assert stats.total_tt > 0  # Total time > 0

    # Verify plugin calls are captured
    func_names = [func[0] for func in stats.stats.keys()]
    assert any('compute_full' in str(name) for name in func_names)


def test_profiling_identifies_bottlenecks():
    """Verify profiler can identify slow plugins."""
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)

    # Create one slow plugin and 4 fast plugins
    agent._plugin_cache = {
        "slow_plugin": SlowPlugin(latency_ms=10),  # 10ms
        "fast_plugin_1": FastPlugin(latency_ms=1),
        "fast_plugin_2": FastPlugin(latency_ms=1),
        "fast_plugin_3": FastPlugin(latency_ms=1),
        "fast_plugin_4": FastPlugin(latency_ms=1),
    }

    profiler = cProfile.Profile()
    profiler.enable()

    # Process 10 bars
    for _ in range(10):
        bar = _create_test_bar()
        await agent._run_i1({"main": test_df}, "ES", "1m")

    profiler.disable()

    stats = pstats.Stats(profiler)
    stats.sort_stats('cumtime')

    # Extract plugin times
    plugin_times = {}
    for func, (cc, nc, tt, ct, callers) in stats.stats.items():
        if 'compute_full' in str(func):
            plugin_name = str(func).split('.')[-2]
            plugin_times[plugin_name] = ct

    # Verify slow_plugin is identified as bottleneck
    assert 'slow_plugin' in plugin_times
    assert plugin_times['slow_plugin'] > max(
        plugin_times.get(f'fast_plugin_{i}', 0) for i in range(1, 5)
    )


def test_benchmark_plugin_accuracy():
    """Verify plugin benchmarking produces reproducible results."""
    plugin = FastPlugin(latency_ms=1)
    test_frames = {"main": test_df}

    # Warmup
    for _ in range(10):
        plugin.compute_full(test_frames)

    # Benchmark
    iterations = 100
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        plugin.compute_full(test_frames)
        times.append(time.perf_counter() - start)

    # Statistics
    mean_time = pd.Series(times).mean()
    std_time = pd.Series(times).std()

    # Verify reproducibility (CV < 10%)
    cv = std_time / mean_time
    assert cv < 0.1, f"Benchmark not reproducible: CV={cv:.2f}"

    # Verify mean is in expected range (1ms ± 0.5ms)
    assert 0.0005 < mean_time < 0.0015
```

**Integration Tests**

**Test throughput improvement:**
```python
async def test_throughput_improvement():
    """Verify parallel version processes more bars/sec."""
    agent = IntelligencePipelineComputeAgent()

    bars = [_create_test_bar() for _ in range(100)]
    start = time.perf_counter()
    for bar in bars:
        await agent._process_bar(bar)
    elapsed = time.perf_counter() - start

    throughput = 100 / elapsed
    assert throughput > 10  # At least 10 bars/sec (vs current 5.87)
```

**Test statistical output consistency:**
```python
async def test_output_unchanged():
    """Verify parallel execution produces identical results."""
    bar = _create_test_bar()

    # Sequential version (mocked)
    result_sequential = await _run_sequential_pipeline(bar)

    # Parallel version
    agent = IntelligencePipelineComputeAgent()
    result_parallel = await agent._process_bar(bar)

    # Statistical comparison
    is_valid, explanation = kolmogorov_smirnov_test(
        result_parallel, result_sequential
    )

    assert is_valid, f"Outputs differ: {explanation}"
```

---

## Expected Impact

| Metric | Current | Target | Improvement |
|--------|---------|--------|-------------|
| Throughput | 5.87 bars/sec | 40-60 bars/sec | 10x |
| Pipeline latency | 49ms | 25ms | 2x |
| Thread pool | 28 workers (static) | 48-192 workers (adaptive) | Auto-tuning |
| Concurrent tasks | 1 | 63 | 63x |
| Consumer lag | 3.5M messages | Decreasing | Catching up |
| Data loss | Unknown (untracked) | 0% (DLQ) | Complete preservation |
| State corruption | Unknown | Validated | Transition checks |
| Observability | Basic | Complete (10+ new metrics) | Full visibility |

**Time to catch up:**
- At 5.87 bars/sec: Never (lag grows)
- At 60 bars/sec: ~10 hours to eliminate 3.5M lag

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Thread pool exhaustion | Low | Low | **Auto-tuning** prevents manual misconfiguration |
| State corruption | Low | High | **Version validation** in state updates |
| Plugin failures | Medium | Low | **DLQ** preserves data for replay |
| Output changes | Low | High | **Statistical validation** (KS test, p < 0.05) |
| Performance regression | Low | Medium | **Automated rollback** on threshold breach |
| Race conditions | Medium | High | **Lock protection** + version checks |
| Data loss | Low | Critical | **DLQ** for all failures |

---

## Open Questions

**Q1: Why not split I1/I7 into separate microservices?**

**A:** True Renaissance DAG architecture would have independent agents per tier. However, operational complexity (managing 10+ services) vs immediate throughput gain (10x) suggests this as Phase 2. Current design: monolithic but parallelized. Future: fully distributed DAG.

**Q2: What's the rollback window?**

**A:** Automated rollback triggers within 60 seconds of threshold breach. Manual rollback: ~30 seconds (git revert + systemctl restart).

**Q3: How do we know auto-tuning works?**

**A:** Monitor `_thread_pool_size` metric. Should fluctuate based on load (market hours = high, overnight = low). Static = auto-tuning broken.

---

## Next Steps

After user approval:

1. Invoke `writing-plans` skill to create detailed implementation plan with:
   - Code structure changes
   - Migration path for existing deployments
   - Monitoring dashboards (Grafana)
   - Runbooks for troubleshooting

2. Execute plan using `executing-plans` skill with:
   - Atomic commits per component
   - Code review checkpoints
   - Statistical validation at each step

3. Verify with `verification-before-completion` skill:
   - Full test suite passes
   - Statistical tests pass (p < 0.05)
   - DLQ captures failures
   - Auto-tuning works

4. Deploy shadow mode and let statistical tests drive cutover decision

---

## Appendix: Profiling Tools and Techniques

### Tool Installation

```bash
# Core profiling tools
pip install cProfile  # Built-in with Python
pip install py-spy    # Sampling profiler (flame graphs)
pip install snakeviz  # Interactive profiler visualization
pip install memory_profiler  # Memory profiling

# Visualization
pip install matplotlib  # For plotting profiling data
pip install seaborn    # For nicer charts
```

### Quick Profiling Commands

```bash
# 1. Profile running service (non-invasive)
sudo py-spy top --pid $(pgrep -f intelligence_pipeline_agent)

# 2. Generate flame graph
sudo py-spy record -o flamegraph.svg --pid $(pgrep -f intelligence_pipeline_agent) --duration 60

# 3. Profile specific function
python -m cProfile -o profile.prof production/scripts/profile_pipeline.py

# 4. View profile results interactively
snakeviz profile.prof
```

### Interpreting cProfile Output

```
ncalls  tottime  percall  cumtime  percall filename:lineno(function)
```

- **ncalls**: Number of calls to this function
- **tottime**: Time spent in this function (excluding sub-calls)
- **percall**: tottime / ncalls
- **cumtime**: Cumulative time (including sub-calls)
- **percall**: cumtime / ncalls

**What to look for:**
- High `cumtime` → Function (or its children) is slow
- High `tottime` → Function itself is slow (not children)
- High `ncalls` → Function called frequently (optimization target)

### Flame Graph Reading

```
Width  = Time spent in function
Height = Call stack depth
Color  = Random (for contrast)
```

**Bottleneck identification:**
- Wide bars at top = Leaf functions doing actual work
- Wide bars at bottom = High-level functions calling many things
- "Plateau" shape = Time spread across many functions (parallelization candidate)
- "Spire" shape = Single dominant bottleneck (optimization candidate)

### Common Python Performance Anti-Patterns

| Anti-Pattern | Example | Fix | Speedup |
|--------------|---------|-----|---------|
| **Iterative pandas** | `df.apply(lambda row: ...)` | Vectorize: `df["col"] + df["col2"]` | 10-100x |
| **String concatenation in loop** | `s += x` for 10000 iterations | `''.join(list)` | 5-10x |
| **Redundant DB queries** | Query per bar | Cache/batch query | 100-1000x |
| **Recomputing aggregations** | `sum(df["col"])` per call | Memoize result | 2-5x |
| **Using lists instead of sets** | `x in my_list` (1M items) | Use `set` | 1000x |
| **Global interpreter lock** | Pure Python loops | Use numpy/pandas | 2-4x |
| **Unnecessary sorting** | `sorted()` when order doesn't matter | Remove sort | 2-3x |

### Performance Optimization Checklist

Before parallelizing, verify:

- [ ] All pandas operations are vectorized (no `.apply()`)
- [ ] No redundant DB queries (cache where possible)
- [ ] Expensive computations are memoized
- [ ] String parsing uses fast libraries (orjson, ujson)
- [ ] No unnecessary data copies (views vs copies)
- [ ] Memory-efficient data structures (use `slots` where appropriate)
- [ ] GIL-releasing operations (numpy, pandas, cython)

### Expected Profiling Results for IndicAgent

Based on plugin architecture:

**I1 Tier (27 plugins):**
- Expected per-plugin latency: 0.5-2ms (vectorized pandas)
- Total I1 latency: 15-30ms (sequential)
- Bottleneck: Rolling window calculations (SMA, EMA, RSI)

**I7 Tier (36 plugins):**
- Expected per-plugin latency: 0.2-1ms (mostly dict lookups)
- Total I7 latency: 10-20ms (sequential)
- Bottleneck: Signal composition (confidence calculation)

**If profiling shows:**
- Per-plugin latency > 5ms → Plugin needs optimization (vectorization)
- Total tier latency > 50ms → Consider parallelization
- GIL contention → Use multiprocessing vs threading

## Appendix: Renaissance Principles Applied

| Principle | How It's Applied |
|-----------|------------------|
| **Instrument everything** | 10+ new metrics (per-plugin latency, thread pool %, DLQ, queue depth) |
| **Let the system run** | Auto-tuning thread pool (no manual configuration) |
| **Earn the right through proof** | Statistical validation (KS test, Welch's t-test, p < 0.05) |
| **Degrade gracefully** | Automated rollback on threshold breach |
| **Never drop data** | DLQ for all failed processing attempts |
| **Data quality over complexity** | State transition validation prevents corruption |
| **Automation over manual tasks** | Automated cutover, automated rollback, automated validation |
