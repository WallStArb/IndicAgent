# Intelligence Pipeline Parallelization — Renaissance Completion

**Status:** Draft  
**Date:** 2026-04-02  
**Supersedes:** `docs/superpowers/specs/2026-04-01-pipeline-parallelization-design.md`  
**Milestone:** v2.2 Operational Excellence  
**Principles:** Renaissance-aligned (instrument everything, earn the right through proof, let the system run)

---

## Problem Statement

The intelligence pipeline was falling behind at 5.87 bars/sec against a 162 bars/sec replay rate — a 27x gap driven by sequential plugin execution (74 calls per bar at ~50ms each).

The core parallelization work is **already merged to main**:
- I1 (27 plugins): `asyncio.gather` via `loop.run_in_executor` ✅
- I7 (36 plugins): same pattern ✅
- Shared `_collect_plugin_results` helper ✅
- I1 total latency gauge ✅
- Thread pool: `cpu_count * 2` (48 workers on current hardware) ✅

**What this phase completes** — the Renaissance gaps left after the initial implementation:

1. Per-plugin observability (only I1 total latency exists today)
2. Thread pool size not empirically validated or configurable
3. Correctness never formally proven (no determinism test, no exception isolation test)
4. Systemd unit not template-ready for horizontal scaling

**This is not a performance crisis phase.** With Kafka cleared and 75 symbols at ~3 bars/sec steady state, the pipeline has headroom. This phase closes the Renaissance gaps so the implementation is provably correct, fully observable, and operationally ready to scale.

---

## Scope

### In scope
- Per-plugin latency histogram and error counter (labeled by `plugin_name`, `tier`)
- Thread pool utilization gauge
- Empirical thread pool benchmark at 5 sizes → configurable parameter
- Determinism test: sequential vs parallel outputs must be identical
- Exception isolation test: plugin failure → downstream tiers degrade gracefully
- Systemd template unit (`indicagent-intelligence-pipeline@.service`)
- Metrics port parameterization (`METRICS_PORT` env var)

### Explicitly out of scope
- I2-I6 parallelization — each tier depends on the prior tier's output; sequential is correct
- Delta filtering / caching — drops signal, violates Renaissance data preservation principle
- Repartitioning Kafka topics — deferred until second data source (see backlog 999.1)
- Multiple pipeline instances / auto-scaler — deferred (100-symbol IBKR constraint makes it unnecessary now)
- Plugin alpha attribution — requires 30+ days of signal outcomes; data not available
- GIL release audit — deferred; requires per-plugin metrics from this phase first (todo captured)

---

## Architecture

### What stays the same
- Single `IntelligencePipelineComputeAgent` — no service split
- In-process I1-I7 — no Kafka hops between tiers
- Per-`(plugin_name, symbol, tf)` state locking — already correct, no changes
- Sequential I2-I6 via `_run_analysis_pipeline()` — intentional, correct

### What changes

**1. Per-plugin metrics**

Add to `src/observability/metrics.py`:
```python
PLUGIN_DURATION_MS = Histogram(
    "intelligence_pipeline_plugin_duration_ms",
    "Per-plugin execution latency",
    ["plugin_name", "tier"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 50, 100]
)
PLUGIN_ERRORS_TOTAL = Counter(
    "intelligence_pipeline_plugin_errors_total",
    "Plugin execution errors",
    ["plugin_name", "tier"]
)
THREAD_POOL_WORKERS = Gauge(
    "intelligence_pipeline_thread_pool_workers",
    "Current thread pool worker count"
)
```

Record `PLUGIN_DURATION_MS` per plugin inside `_collect_plugin_results` — one place, both I1 and I7 covered. Record `PLUGIN_ERRORS_TOTAL` on exception. Record `THREAD_POOL_WORKERS` at startup.

**2. Thread pool: empirical sizing → config parameter**

Current: `max_workers=cpu_count * 2` (hardcoded formula, never benchmarked).

Approach:
1. Add `INTELLIGENCE_THREAD_POOL_WORKERS` env var (read via `Settings`)
2. Default: `cpu_count * 2` (preserve current behavior if unset)
3. Run benchmark script at pool sizes [28, 48, 64, 96, 128] against real bars
4. Plot throughput curve, identify knee, set `INTELLIGENCE_THREAD_POOL_WORKERS` to empirical optimum in `.env`
5. Document the curve in `production/scripts/README_PROFILING.md`

Why not adaptive auto-tuning? At ≤100 symbols, a stable configured value is simpler and sufficient. Adaptive tuning is complexity without benefit at this scale. Revisit when horizontal scaling is deployed (backlog 999.1).

**3. Systemd template unit**

Rename installed unit from `indicagent-intelligence-pipeline.service` to template `indicagent-intelligence-pipeline@.service`. The `%i` instance parameter enables:
```bash
systemctl start indicagent-intelligence-pipeline@1   # current instance
systemctl start indicagent-intelligence-pipeline@2   # future second instance
```

Template unit env changes:
```ini
Environment=METRICS_PORT=9125
Environment=INSTANCE_ID=%i
Environment=LOG_FILE=logs/intelligence_pipeline_%i.log
```

Instance 1 uses port `9125` (current port — no change). If a second instance is added, assign the next available port (audit `CLAUDE.md` active services table at that time). Port is never auto-computed from `%i` — it is always an explicit env var in the unit file to avoid silent conflicts.

Consumer group ID stays `intelligence_pipeline_consumer` for all instances — intentional; Kafka distributes partitions across group members automatically.

---

## Correctness Validation

No shadow mode — there is no production to protect. Ship when correctness is proven.

**Gate 1 — Determinism test** (`tests/unit/test_pipeline_determinism.py`)

Replay an identical sequence of 100 bars through:
- A reference sequential implementation: mock plugins that return deterministic, fixed outputs (no real compute) — used purely to verify the gather/collect/state-lock machinery produces the same result regardless of execution order
- The current parallel implementation with the same mock plugins

Assert outputs are identical: `i1` dict keys and values, `i7` signal list, `winner_plugin`, `winner_confidence`, `winner_direction`.

Note on floating point: `asyncio.gather` preserves submission order in results. State mutations are locked per `(plugin_name, symbol, tf)`. There should be no non-determinism. If floating point differences appear, document the specific operations and add a tolerance (e.g. `abs(a - b) < 1e-10`).

**Gate 2 — Exception isolation test** (`tests/unit/test_pipeline_exception_isolation.py`)

Inject failures at different points:
- Plugin N in I1 raises → remaining I1 plugins complete → I2 receives valid (partial) I1 output
- All I1 plugins raise → I2 receives empty dict → pipeline logs error and continues (no crash)
- Plugin N in I7 raises → remaining I7 plugins complete → signal ranking proceeds normally

Assert: pipeline never crashes on plugin exception. Assert: error counter increments. Assert: downstream tiers receive whatever is available, not a corrupted state.

**Gate 3 — Full test suite green**
```bash
.venv/bin/pytest tests/unit/ -v
.venv/bin/ruff check . --fix
.venv/bin/black .
```

---

## Horizontal Scaling Readiness

The code must make zero single-instance assumptions. Checklist:

- [ ] No process-level globals that would conflict across instances
- [ ] Consumer group ID is not instance-specific (shared group = Kafka distributes partitions)
- [ ] Metrics port is configurable via env var (not hardcoded)
- [ ] Log file path uses instance ID: `logs/intelligence_pipeline_%i.log`
- [ ] Systemd template unit installed and verified with `systemctl start indicagent-intelligence-pipeline@1`

When the second data source arrives, adding a second instance is:
1. `docker exec redpanda rpk topic alter-config market.bars --set num_partitions=50`
2. `systemctl start indicagent-intelligence-pipeline@2`

No code changes required.

---

## Files Changed

| File | Change |
|------|--------|
| `src/observability/metrics.py` | Add `PLUGIN_DURATION_MS`, `PLUGIN_ERRORS_TOTAL`, `THREAD_POOL_WORKERS` |
| `src/config/settings.py` | Add `INTELLIGENCE_THREAD_POOL_WORKERS: int` field |
| `services/intelligence_pipeline_agent.py` | Read pool size from settings; record per-plugin metrics in `_collect_plugin_results`; read `METRICS_PORT` from settings |
| `production/systemd/indicagent-intelligence-pipeline@.service` | Template unit with `%i` parameterization |
| `tests/unit/test_pipeline_determinism.py` | New — sequential vs parallel output equivalence |
| `tests/unit/test_pipeline_exception_isolation.py` | New — plugin failure graceful degradation |
| `production/scripts/benchmark_thread_pool.py` | New — throughput curve at 5 pool sizes |
| `production/scripts/README_PROFILING.md` | Document benchmark results |

---

## Deferred Items

| Item | Where captured |
|------|---------------|
| GIL release audit — identify plugins that don't release GIL, move off `asyncio.to_thread` | `.planning/todos/pending/2026-04-02-audit-i1-i7-plugins-for-gil-release...md` |
| Repartition topics + multiple instances + auto-scaler | ROADMAP backlog 999.1 |
| Plugin alpha attribution | ROADMAP backlog Phase 55-56 (requires 30+ days signal outcomes) |

---

## Success Criteria

- [ ] `PLUGIN_DURATION_MS` visible in Grafana per plugin after one RTH session
- [ ] `PLUGIN_ERRORS_TOTAL` increments on injected failures (test passes)
- [ ] Determinism test passes: 100 bars, sequential == parallel outputs
- [ ] Exception isolation test passes: pipeline never crashes on plugin error
- [ ] Thread pool benchmark run, optimal size documented, `INTELLIGENCE_THREAD_POOL_WORKERS` set in `.env`
- [ ] `indicagent-intelligence-pipeline@1.service` installed and running
- [ ] Full test suite green
