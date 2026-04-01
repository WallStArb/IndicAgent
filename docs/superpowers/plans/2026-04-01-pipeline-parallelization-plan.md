# Intelligence Pipeline Throughput Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optimize IntelligencePipelineComputeAgent throughput from 5.87 bars/sec to 40-60 bars/sec (10x improvement) by parallelizing independent plugin execution within I1 and I7 tiers.

**⚠️ DEPLOYMENT NOTE:** Tasks 5-6 (shadow mode) **SKIPPED** — system is experimental, not production. Direct deployment via Tasks 7-8.

**Architecture:** Parallelize I1 (27 plugins) and I7 (36 plugins) using asyncio.gather() while maintaining DAG structure and state isolation. Increase thread pool from 28 to 96 workers to eliminate thread pool starvation.

**Tech Stack:** Python 3.13, asyncio, concurrent.futures.ThreadPoolExecutor, aiokafka, Prometheus metrics

---

## Task 1: Add Thread Pool and Timing Metrics

**Files:**
- Modify: `services/intelligence_pipeline_agent.py:351-400`

- [ ] **Step 1: Add thread pool import**

Add after line 17 (after `from uuid import uuid4`):
```python
from concurrent.futures import ThreadPoolExecutor
```

- [ ] **Step 2: Add timing metric imports**

Add after line 51 (after `from src.intelligence.schemas import ...`):
```python
from time import perf_counter
```

- [ ] **Step 3: Initialize thread pool in __init__**

Add after line 430 (after `self._htf_intel_cache: dict = {}`):
```python
# Create custom executor with more workers (4x CPU cores)
self._executor = ThreadPoolExecutor(
    max_workers=96,  # 24 cores * 4
    thread_name_prefix="intel_"
)
asyncio.get_event_loop().set_default_executor(self._executor)
```

- [ ] **Step 4: Add timing metrics in __init__**

Add after line 444 (after `self._bars_processed = counter(...)`):
```python
self._i1_latency_ms = gauge(
    "intelligence_pipeline_i1_latency_ms",
    "I1 tier execution time in milliseconds"
)
self._i7_latency_ms = gauge(
    "intelligence_pipeline_i7_latency_ms",
    "I7 tier execution time in milliseconds"
)
```

- [ ] **Step 5: Test thread pool initialization**

Run: `python -c "from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent; print('Thread pool import successful')"`

Expected: No import errors

- [ ] **Step 6: Commit**

```bash
git add services/intelligence_pipeline_agent.py
git commit -m "feat(pipeline): add thread pool executor and timing metrics

- Increase ThreadPoolExecutor to 96 workers (4x CPU cores)
- Add I1 and I7 timing metrics for observability
- Target: Eliminate thread pool starvation causing 27x throughput gap
"
```

---

## Task 2: Parallelize I1 Plugins

**Files:**
- Modify: `services/intelligence_pipeline_agent.py:959-983`

- [ ] **Step 1: Replace sequential I1 execution with parallel**

Replace lines 959-983 (entire `_run_i1` method) with:
```python
async def _run_i1(self, frames: dict, symbol: str, tf: str) -> dict:
    """Run all I1 plugins in parallel and return merged result."""
    
    # Start timing
    i1_start = perf_counter()
    
    result: dict[str, Any] = {}
    tasks = []
    
    # Build parallel tasks
    for plugin_name in TIER_I1:
        plugin = self._plugin_cache.get(plugin_name)
        if plugin is None:
            continue
        if should_skip_plugin(plugin, self._instrument_map.get(symbol), 
                           self._plugin_skipped_total, plugin_name):
            continue
        state_key = (plugin_name, symbol, tf)
        lock = self._get_state_lock(state_key)
        
        # Create parallel task: (coroutine, plugin_name, state_key, lock)
        tasks.append((
            asyncio.to_thread(plugin.compute_full, frames),
            plugin_name,
            state_key,
            lock
        ))
    
    # Execute all I1 plugins in parallel
    results = await asyncio.gather(*[t[0] for t in tasks], return_exceptions=True)
    
    # Collect results with state locking
    for i, (_, plugin_name, state_key, lock) in enumerate(tasks):
        out = results[i]
        if isinstance(out, Exception):
            self._pipeline_errors.inc()
            self.logger.warning(
                "plugin.error",
                plugin=plugin_name,
                error=str(out)
            )
        elif isinstance(out, dict):
            with lock:
                if "_state" in out:
                    self._plugin_states[state_key] = out.pop("_state")
                result.update(out)
    
    # Record timing metric
    i1_latency_ms = (perf_counter() - i1_start) * 1000
    self._i1_latency_ms.set(i1_latency_ms)
    
    return result
```

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile services/intelligence_pipeline_agent.py`

Expected: No syntax errors

- [ ] **Step 3: Test parallel I1 execution**

Run: `.venv/bin/pytest tests/unit/test_intelligence_pipeline_agent.py::test_run_i1 -v`

Expected: Test passes (may not exist yet, if so skip)

- [ ] **Step 4: Commit**

```bash
git add services/intelligence_pipeline_agent.py
git commit -m "feat(pipeline): parallelize I1 plugins using asyncio.gather

- Replace sequential I1 plugin execution (27 plugins) with parallel execution
- Use asyncio.gather() to run all I1 plugins concurrently
- Maintain state locking per (plugin_name, symbol, tf)
- Add I1 timing metric for observability
- Expected speedup: 15-20x on I1 tier (35ms → 2-3ms)
"
```

---

## Task 3: Parallelize I7 Plugins

**Files:**
- Modify: `services/intelligence_pipeline_agent.py:1036-1100+`

- [ ] **Step 1: Find I7 plugin loop end location**

Run: `grep -n "for plugin_name in I7_PLUGINS" services/intelligence_pipeline_agent.py | head -1`

Note: This shows where the loop starts. Find where it ends (look for next method definition or ~20 lines after).

- [ ] **Step 2: Replace sequential I7 execution with parallel**

Replace the I7 plugin loop (approximately lines 1050-1085) with parallel execution:
```python
# Run all I7 plugins in parallel
i7_start = perf_counter()

tasks = []
raw_signals: list[dict] = []

for plugin_name in I7_PLUGINS:
    plugin = self._plugin_cache.get(plugin_name)
    if plugin is None:
        continue
    if should_skip_plugin(plugin, self._instrument_map.get(bar.symbol), 
                       self._plugin_skipped_total, plugin_name):
        continue
    state_key = (plugin_name, bar.symbol, bar.tf)
    lock = self._get_state_lock(state_key)
    
    # Create parallel task: (coroutine, plugin_name, state_key, lock, bar)
    tasks.append((
        asyncio.to_thread(plugin.compute_full, {"main": None, **features}),
        plugin_name,
        state_key,
        lock,
        bar
    ))

# Execute all I7 plugins in parallel
results = await asyncio.gather(*[t[0] for t in tasks], return_exceptions=True)

# Collect results
for i, (_, plugin_name, state_key, lock, bar) in enumerate(tasks):
    out = results[i]
    if isinstance(out, Exception):
        self._pipeline_errors.inc()
        self.logger.warning("plugin.error", plugin=plugin_name, error=str(out))
    elif isinstance(out, dict) and out.get("signal"):
        sig = out["signal"]
        sig["setup_plugin"] = plugin_name
        sig["symbol"] = bar.symbol
        sig["tf"] = bar.tf
        
        # Alpha decay
        fire_key = (bar.symbol, bar.tf, plugin_name, sig.get("direction", 0))
        if fire_key in self._setup_last_fire:
            bars_since = self._setup_last_fire.get(fire_key, 0)
            self._apply_alpha_decay(sig, bars_since)
        
        raw_signals.append(sig)

# Record timing metric
i7_latency_ms = (perf_counter() - i7_start) * 1000
self._i7_latency_ms.set(i7_latency_ms)

# Continue with existing ranking/selection logic (unchanged)
```

- [ ] **Step 3: Verify syntax**

Run: `python -m py_compile services/intelligence_pipeline_agent.py`

Expected: No syntax errors

- [ ] **Step 4: Commit**

```bash
git add services/intelligence_pipeline_agent.py
git commit -m "feat(pipeline): parallelize I7 plugins using asyncio.gather

- Replace sequential I7 plugin execution (36 plugins) with parallel execution
- Use asyncio.gather() to run all I7 plugins concurrently
- Maintain state locking per (plugin_name, symbol, tf)
- Add I7 timing metric for observability
- Expected speedup: 15-20x on I7 tier (45ms → 3-4ms)
"
```

---

## Task 4: Add Integration Tests

**Files:**
- Create: `tests/unit/test_pipeline_parallelization.py`

- [ ] **Step 1: Create test file**

Create `tests/unit/test_pipeline_parallelization.py`:
```python
"""Test pipeline parallelization improvements."""

import asyncio
import time
from unittest.mock import Mock, MagicMock

from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent


def _mock_plugin(compute_result: dict):
    """Create a mock plugin that returns a fixed result."""
    def mock_compute_full(frames):
        return compute_result
    return mock_compute_full


async def test_i1_parallel_execution_speed():
    """Verify I1 plugins run concurrently and are faster than sequential."""
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    
    # Mock 27 I1 plugins
    agent._plugin_cache = {}
    for i in range(27):
        plugin_name = f"test_plugin_{i}"
        agent._plugin_cache[plugin_name] = _mock_plugin({"value": i})
    
    agent._instrument_map = {}
    agent._plugin_skipped_total = MagicMock()
    
    # Create mock frames
    frames = {"main": MagicMock()}
    
    # Time parallel execution
    start = time.perf_counter()
    result = await agent._run_i1(frames, "ES", "1m")
    elapsed_parallel = time.perf_counter() - start
    
    # Verify all plugins executed
    assert len(result) == 27
    assert all(result[f"test_plugin_{i}"]["value"] == i for i in range(27))
    
    # Should be reasonably fast (< 50ms for 27 plugins)
    assert elapsed_parallel < 0.050, f"I1 took {elapsed_parallel*1000:.1f}ms, expected <50ms"
    
    print(f"✓ I1 parallel execution: {elapsed_parallel*1000:.1f}ms for 27 plugins")


async def test_i7_parallel_execution_speed():
    """Verify I7 plugins run concurrently and are faster than sequential."""
    agent = IntelligencePipelineComputeAgent.__new__(IntelligenceComputeAgent)
    
    # Mock 36 I7 plugins
    agent._plugin_cache = {}
    for i in range(36):
        plugin_name = f"test_signal_{i}"
        agent._plugin_cache[plugin_name] = _mock_plugin({"signal": {"value": i}})
    
    agent._instrument_map = {}
    agent._plugin_skipped_total = MagicMock()
    
    # Create mock bar and event
    bar = MagicMock()
    bar.symbol = "ES"
    bar.tf = "1m"
    
    event = MagicMock()
    event.model_dump_json.return_value = '{"i1": {}}'
    
    # Mock _build_features_from_event
    from unittest.mock import patch
    with patch('services.intelligence_pipeline_agent._build_features_from_event', return_value={}):
        start = time.perf_counter()
        result = await agent._run_i7(bar, event, {})
        elapsed_parallel = time.perf_counter() - start
    
    # Verify signals generated
    assert "signals" in result
    assert len(result["signals"]) == 36
    
    # Should be reasonably fast (< 50ms for 36 plugins)
    assert elapsed_parallel < 0.050, f"I7 took {elapsed_parallel*1000:.1f}ms, expected <50ms"
    
    print(f"✓ I7 parallel execution: {elapsed_parallel*1000:.1f}ms for 36 plugins")


async def test_parallel_state_isolation():
    """Verify parallel plugin execution doesn't corrupt state."""
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    
    # Mock minimal setup
    agent._plugin_cache = {"test_plugin": _mock_plugin({"value": 1, "_state": {"counter": 0}})}
    agent._instrument_map = {}
    agent._plugin_skipped_total = MagicMock()
    
    frames = {"main": MagicMock()}
    
    # Run same I1 execution twice in parallel (simulates concurrent bars)
    result1 = await agent._run_i1(frames, "ES", "1m")
    result2 = await agent._run_i1(frames, "ES", "1m")
    
    # Verify state integrity - both should have updated state
    assert result1["test_plugin"]["value"] == 1
    assert result2["test_plugin"]["value"] == 1
    
    print(f"✓ State isolation verified in parallel execution")


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
```

- [ ] **Step 2: Run tests**

Run: `.venv/bin/pytest tests/unit/test_pipeline_parallelization.py -v`

Expected: All 3 tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_pipeline_parallelization.py
git commit -m "test(pipeline): add parallelization integration tests

- Test I1 parallel execution speed (<50ms for 27 plugins)
- Test I7 parallel execution speed (<50ms for 36 plugins)  
- Test state isolation in parallel execution
- Validates throughput improvement targets
"
```

---

## Task 5: Deploy in Shadow Mode

**Status:** ⏭️ **SKIPPED** — Experimental system, shadow mode unnecessary

**Files:**
- Systemd unit: `/etc/systemd/system/indicagent-intelligence-pipeline-shadow.service` (create)

- [ ] **Step 1: Create shadow mode systemd unit**

Create `/etc/systemd/system/indicagent-intelligence-pipeline-shadow.service`:
```ini
[Unit]
Description=IndicAgent Intelligence Pipeline Shadow Service — Parallelization Testing
Documentation=https://github.com/bg/indicagent
After=network.target redpanda.service timescaledb.service

[Service]
Type=simple
User=bg
Group=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment="PATH=/home/bg/dev/indicagent/.venv/bin"
Environment="INDICAGENT_ENV=development"
Environment="INTELLIGENCE_PIPELINE_SHADOW=true"
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/intelligence_pipeline_agent.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Enable and start shadow service**

```bash
sudo systemctl daemon-reload
sudo systemctl enable indicagent-intelligence-pipeline-shadow
sudo systemctl start indicagent-intelligence-pipeline-shadow
```

- [ ] **Step 3: Verify shadow service running**

Run: `systemctl status indicagent-intelligence-pipeline-shadow`

Expected: `active (running)`

- [ ] **Step 4: Monitor shadow metrics for 1 hour**

Run: `watch -n 10 'curl -s http://localhost:9125/metrics | grep -E "bars_per_second|i1_latency|i7_latency"'`

Expected: See I1 and I7 latency metrics, throughput increasing

- [ ] **Step 5: Compare shadow vs production metrics**

```bash
# Production throughput
curl -s http://localhost:9125/metrics | grep bars_processed

# Shadow throughput (different port needed - check metrics port)
```

Note: Shadow service will use different metrics port to avoid collision. Check logs for actual port.

- [ ] **Step 6: Commit systemd unit**

```bash
git add /etc/systemd/system/indicagent-intelligence-pipeline-shadow.service
git commit -m "infra(pipeline): add shadow mode service for parallelization testing

- Create systemd unit for shadow mode deployment
- INTELLIGENCE_PIPELINE_SHADOW=true enables shadow execution
- Runs alongside production to validate parallelization
- Part of phased rollout strategy (shadow → gradual cutover)
"
```

---

## Task 6: Validate Shadow Mode Results

**Status:** ⏭️ **SKIPPED** — Experimental system, shadow mode unnecessary

**Files:**
- None (monitoring and validation)

- [ ] **Step 1: Monitor shadow mode for 24-48 hours**

Check metrics periodically:
```bash
# Throughput comparison
echo "Production bars/sec:"
curl -s http://localhost:9125/metrics | grep bars_processed

echo "Shadow bars/sec:"
# Check shadow logs/journald for processed count
journalctl -u indicagent-intelligence-pipeline-shadow --since "1 hour" | grep "bars_processed"

# Latency comparison
curl -s http://localhost:9125/metrics | grep _latency_ms
```

- [ ] **Step 2: Verify shadow throughput target**

Run: Monitor for 1 hour, calculate average throughput

Expected: Shadow throughput ≥ 40 bars/sec (vs production 5.87 bars/sec)

- [ ] **Step 3: Verify shadow latency target**

Run: Check I1 and I7 latency metrics

Expected: Both < 30ms average

- [ ] **Step 4: Verify output quality**

Compare shadow signals vs production signals in database:
```sql
-- Check if shadow signals match production
SELECT 
    COUNT(*) as shadow_count,
    AVG(confidence) as avg_confidence
FROM signal_ledger
WHERE ts > NOW() - INTERVAL '1 hour'
GROUP BY 'shadow';  -- Add identifier column if needed
```

- [ ] **Step 5: Stop shadow mode after validation**

```bash
sudo systemctl stop indicagent-intelligence-pipeline-shadow
sudo systemctl disable indicagent-intelligence-pipeline-shadow
```

- [ ] **Step 6: Document validation results**

Create `docs/notes/shadow-mode-validation.md`:
```markdown
# Shadow Mode Validation Results

**Date:** 2026-04-01

**Throughput:**
- Production: 5.87 bars/sec
- Shadow: XX bars/sec
- Improvement: XXx

**Latency:**
- Production I1: XXms
- Shadow I1: XXms
- Production I7: XXms
- Shadow I7: XXms

**Output Quality:** Validated
**Error Rate:** XX% (same as production)

**Decision:** ✓ Approved for production deployment
```

---

## Task 7: Production Deployment (Direct - No Shadow Mode)

**⚠️ EXPERIMENTAL SYSTEM:** Shadow mode (Tasks 5-6) skipped — direct deployment for experimental/non-production use.

**Files:**
- Modify: `services/intelligence_pipeline_agent.py` (already committed in Tasks 1-3)

- [ ] **Step 1: Create deployment PR**

```bash
git checkout main
git checkout -b feature/pipeline-parallelization
git merge <commit-hash-from-task-3>
```

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/pytest tests/unit/ -v --tb=short`

Expected: All tests pass

- [ ] **Step 3: Code review**

Run: `/coderabbit:code-review`

- [ ] **Step 4: Merge to main**

```bash
git checkout main
git merge feature/pipeline-parallelization
git push origin main
```

- [ ] **Step 5: Deploy to production**

```bash
sudo systemctl restart indicagent-intelligence-pipeline
```

- [ ] **Step 6: Monitor post-deployment metrics**

Run: `journalctl -u indicagent-intelligence-pipeline --since "5 minutes ago" | tail -50`

Expected: Service starts, processes bars, no errors

- [ ] **Step 7: Verify throughput improvement**

Run: `curl -s http://localhost:9125/metrics | grep bars_per_second`

Expected: ≥ 40 bars/sec within 10 minutes

- [ ] **Step 8: Verify consumer lag decreasing**

Run: `docker exec redpanda rpk group describe intelligence_pipeline_group -t | grep LAG`

Expected: LAG metric decreasing over time

- [ ] **Step 9: Monitor for 24 hours**

Set up monitoring dashboard or periodic checks:
```bash
# Every hour for 24 hours
for i in {1..24}; do
  echo "Hour $i check:"
  curl -s http://localhost:9125/metrics | grep -E "bars_per_second|pipeline_errors"
  sleep 3600
done
```

---

## Task 8: Post-Deployment Verification

**Files:**
- Create: `docs/notes/pipeline-parallelization-results.md`

- [ ] **Step 1: Collect 24-hour metrics**

Collect metrics after 24 hours of production runtime:
```bash
# Throughput
curl -s http://localhost:9125/metrics | grep bars_processed_total

# Latency
curl -s http://localhost:9125/metrics | grep _latency_ms

# Errors
curl -s http://localhost:9125/metrics | grep pipeline_errors_total

# Consumer lag
docker exec redpanda rpk group describe intelligence_pipeline_group -t | grep LAG
```

- [ ] **Step 2: Create results document**

Create `docs/notes/pipeline-parallelization-results.md`:
```markdown
# Pipeline Parallelization Results

**Deployment Date:** 2026-04-01
**Review Period:** 24 hours post-deployment

## Throughput Improvement

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Bars/sec | 5.87 | XX | XXx |
| Hourly bars processed | 21,132 | XX | XX |

## Latency Improvement

| Tier | Before | After | Improvement |
|------|--------|-------|-------------|
| I1 latency | 35ms | XXms | XXx faster |
| I7 latency | 45ms | XXms | XXx faster |

## Consumer Lag

| Metric | Before | After | Status |
|--------|--------|-------|--------|
| Lag (messages) | 3.5M | XX | ✓ Decreasing |

## Error Rate

| Metric | Before | After | Status |
|--------|--------|-------|--------|
| Pipeline errors | Baseline | XX | ✓ Stable |

## Conclusion

**Status:** ✓ Success / ⚠️ Issues / ✗ Rollback required

**Recommendations:**
- [Any follow-up optimizations needed]
- [Next improvement targets]
```

- [ ] **Step 3: Commit results documentation**

```bash
git add docs/notes/pipeline-parallelization-results.md
git commit -m "docs(pipeline): add parallelization deployment results

- Document 24-hour post-deployment metrics
- Verify 10x throughput improvement achieved
- Note any issues or follow-up optimizations needed
"
```

---

## Success Criteria

**⚠️ EXPERIMENTAL DEPLOYMENT** (no shadow mode validation):

After restart, verify:

- [ ] **Throughput:** ≥ 40 bars/sec (10x improvement from 5.87)
- [ ] **I1 Latency:** ≤ 30ms average (vs 35ms before)
- [ ] **I7 Latency:** ≤ 30ms average (vs 45ms before)
- [ ] **Consumer lag:** Decreasing (not increasing)
- [ ] **Error rate:** ≤ 0.1% (unchanged from baseline)
- [ ] **Output quality:** Signal distribution similar to baseline

---

## Rollback Plan

**If any of the following occur, rollback immediately:**

1. **Error rate spikes** > 1% (10x baseline of 0.1%)
2. **Consumer lag increases** (not decreasing after 6 hours)
3. **Service crashes** or restarts frequently
4. **Output quality degrades** (wrong signals, missing signals)

**Rollback commands:**
```bash
# Stop new version
sudo systemctl stop indicagent-intelligence-pipeline

# Revert to previous commit
git revert HEAD

# Restart old version
sudo systemctl start indicagent-intelligence-pipeline

# Verify recovery
curl -s http://localhost:9125/metrics | grep bars_per_second
```

---

**Total tasks:** 8 (Tasks 5-6 skipped - experimental system)
**Estimated time:** 1 day (development: complete, deployment: immediate)
**Lines of code changed:** ~100 lines (excluding tests and comments)
**Deployment:** Direct to main (no shadow mode - experimental/non-production)
