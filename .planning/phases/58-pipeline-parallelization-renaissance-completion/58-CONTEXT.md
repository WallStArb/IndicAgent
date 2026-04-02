# Phase 58: Pipeline Parallelization — Renaissance Completion - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning
**Source:** PRD Express Path (docs/superpowers/specs/2026-04-02-pipeline-parallelization-renaissance-completion-design.md)

<domain>
## Phase Boundary

Close the four Renaissance gaps left after initial I1/I7 parallelization (already merged to main):

1. **Per-plugin observability** — per-plugin latency histograms and error counters (only I1 total latency exists today)
2. **Thread pool empirical sizing** — `cpu_count * 2` was never benchmarked; must become a configurable parameter backed by empirical data
3. **Correctness proofs** — no determinism test, no exception isolation test for the parallel implementation
4. **Horizontal scaling readiness** — current systemd unit is a single-instance unit; must become a template unit

This is not a performance crisis phase. With Kafka cleared and 75 symbols at ~3 bars/sec steady state, the pipeline has headroom. This phase makes the implementation provably correct, fully observable, and operationally ready to scale.

**Not in scope:**
- I2-I6 parallelization (sequential is correct — each tier depends on prior tier's output)
- Delta filtering / caching (drops signal, violates Renaissance data preservation)
- Repartitioning Kafka topics (deferred — backlog 999.1)
- Multiple pipeline instances / auto-scaler (deferred — 100-symbol IBKR constraint)
- Plugin alpha attribution (requires 30+ days signal outcomes — data not available)
- GIL release audit (deferred — needs per-plugin metrics from this phase first; todo captured)

</domain>

<decisions>
## Implementation Decisions

### 1. Per-Plugin Metrics (PIPE-01, PIPE-02)

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

### 2. Thread Pool: Empirical Sizing → Config Parameter (PIPE-03)

- Add `INTELLIGENCE_THREAD_POOL_WORKERS: int` field to `src/config/settings.py`
- Default: `cpu_count * 2` (preserve current behavior if unset)
- New benchmark script `production/scripts/benchmark_thread_pool.py` runs throughput at pool sizes [28, 48, 64, 96, 128] against real bars
- Plot throughput curve, identify knee, set optimal value in `.env`
- Document results in `production/scripts/README_PROFILING.md`
- **No adaptive auto-tuning** — at ≤100 symbols, a stable configured value is simpler and sufficient

### 3. Correctness Validation (PIPE-04, PIPE-05)

**Determinism test** (`tests/unit/test_pipeline_determinism.py`):
- Replay 100 bars through reference sequential + current parallel implementations using deterministic mock plugins
- Assert identical: `i1` dict keys/values, `i7` signal list, `winner_plugin`, `winner_confidence`, `winner_direction`
- If floating point differences appear: tolerance `abs(a - b) < 1e-10` and document
- Note: `asyncio.gather` preserves submission order; state mutations locked per `(plugin_name, symbol, tf)` — no non-determinism expected

**Exception isolation test** (`tests/unit/test_pipeline_exception_isolation.py`):
- Plugin N in I1 raises → remaining I1 plugins complete → I2 receives valid (partial) I1 output
- All I1 plugins raise → I2 receives empty dict → pipeline logs error and continues (no crash)
- Plugin N in I7 raises → remaining I7 plugins complete → signal ranking proceeds normally
- Assert: pipeline never crashes on plugin exception; error counter increments; downstream tiers receive available (not corrupted) output

### 4. Systemd Template Unit (PIPE-06)

- Rename installed unit from `indicagent-intelligence-pipeline.service` to template `indicagent-intelligence-pipeline@.service`
- `%i` instance parameter: `@1` = current instance, `@2` = future second instance
- Template unit env changes:
  ```ini
  Environment=METRICS_PORT=9125
  Environment=INSTANCE_ID=%i
  Environment=LOG_FILE=logs/intelligence_pipeline_%i.log
  ```
- Instance 1 uses port `9125` (current port — no change)
- Port is **never auto-computed from `%i`** — always explicit env var in unit file (prevent silent conflicts)
- Consumer group ID stays `intelligence_pipeline_consumer` for all instances (Kafka distributes partitions)
- `services/intelligence_pipeline_agent.py` reads `METRICS_PORT` from settings (not hardcoded)

### Claude's Discretion

- Test mocking strategy: mock plugins should return deterministic fixed outputs — focus on verifying gather/collect/state-lock machinery, not real compute correctness
- Benchmark script format: CSV output for throughput curve; matplotlib optional
- README_PROFILING.md update: append benchmark results section alongside existing profiling docs

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Pipeline Agent (primary target)
- `services/intelligence_pipeline_agent.py` — `_collect_plugin_results`, thread pool creation, `METRICS_PORT` usage, I1/I7 parallel execution pattern
- `src/intelligence/register_plugins.py` — `TIER_I1`, `TIER_I7` plugin lists (source of truth for plugin names)

### Metrics Infrastructure
- `src/observability/metrics.py` — existing metric registrations, label conventions, `PLUGIN_METRICS_SAMPLE_RATE`
- `src/core/service_utils.py` — `setup_service_logging()`, `PLUGIN_METRICS_SAMPLE_RATE`

### Settings
- `src/config/settings.py` — `Settings` class, existing env var patterns, how to add new configurable fields

### Systemd / Infrastructure
- `production/systemd/indicagent-intelligence-pipeline.service` — current unit file (reference only — NOT what's installed; installed is `/etc/systemd/system/`)
- `CLAUDE.md` active services table — for port assignments before any new port allocation

### Correctness Testing
- `tests/unit/` — existing test patterns; follow same conventions
- `docs/superpowers/specs/2026-04-02-pipeline-parallelization-renaissance-completion-design.md` — full spec including Correctness Validation section and Horizontal Scaling Readiness checklist

### Design Docs
- `docs/superpowers/specs/2026-04-01-pipeline-parallelization-design.md` — original parallelization design (superseded by this spec but useful for implementation history)
- `production/scripts/README_PROFILING.md` — existing profiling docs to append to

</canonical_refs>

<specifics>
## Specific Ideas

### Files Changed (from spec)
| File | Change |
|------|--------|
| `src/observability/metrics.py` | Add `PLUGIN_DURATION_MS`, `PLUGIN_ERRORS_TOTAL`, `THREAD_POOL_WORKERS` |
| `src/config/settings.py` | Add `INTELLIGENCE_THREAD_POOL_WORKERS: int` field |
| `services/intelligence_pipeline_agent.py` | Read pool size from settings; record per-plugin metrics in `_collect_plugin_results`; read `METRICS_PORT` from settings |
| `production/systemd/indicagent-intelligence-pipeline@.service` | Template unit with `%i` parameterization |
| `tests/unit/test_pipeline_determinism.py` | New — sequential vs parallel output equivalence |
| `tests/unit/test_pipeline_exception_isolation.py` | New — plugin failure graceful degradation |
| `production/scripts/benchmark_thread_pool.py` | New — throughput curve at 5 pool sizes |
| `production/scripts/README_PROFILING.md` | Append benchmark results |

### Success Criteria (from spec)
- `PLUGIN_DURATION_MS` visible in Grafana per plugin after one RTH session
- `PLUGIN_ERRORS_TOTAL` increments on injected failures (test passes)
- Determinism test passes: 100 bars, sequential == parallel outputs
- Exception isolation test passes: pipeline never crashes on plugin error
- Thread pool benchmark run, optimal size documented, `INTELLIGENCE_THREAD_POOL_WORKERS` set in `.env`
- `indicagent-intelligence-pipeline@1.service` installed and running
- Full test suite green

### Horizontal Scaling Readiness Checklist (from spec)
- No process-level globals that would conflict across instances
- Consumer group ID is not instance-specific
- Metrics port configurable via env var (not hardcoded)
- Log file path uses instance ID: `logs/intelligence_pipeline_%i.log`
- Systemd template unit installed and verified with `systemctl start indicagent-intelligence-pipeline@1`

</specifics>

<deferred>
## Deferred Ideas

- GIL release audit — identify I1/I7 plugins that don't release GIL, move off `asyncio.to_thread` → `.planning/todos/pending/` (todo captured in spec)
- Repartition topics + multiple instances + auto-scaler → ROADMAP backlog 999.1
- Plugin alpha attribution → ROADMAP backlog Phase 55-56 (requires 30+ days signal outcomes)

</deferred>

---

*Phase: 58-pipeline-parallelization-renaissance-completion*
*Context gathered: 2026-04-01 via PRD Express Path*
