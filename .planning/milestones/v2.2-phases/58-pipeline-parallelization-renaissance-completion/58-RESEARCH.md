# Phase 58: Pipeline Parallelization — Renaissance Completion - Research

**Researched:** 2026-04-01
**Domain:** Python observability (prometheus_client), systemd template units, async/concurrent testing, pydantic-settings
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Per-Plugin Metrics (PIPE-01, PIPE-02)**
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
Record `PLUGIN_DURATION_MS` per plugin inside `_collect_plugin_results`. Record `PLUGIN_ERRORS_TOTAL` on exception. Record `THREAD_POOL_WORKERS` at startup.

**Thread Pool: Empirical Sizing → Config Parameter (PIPE-03)**
- Add `INTELLIGENCE_THREAD_POOL_WORKERS: int` field to `src/config/settings.py`
- Default: `cpu_count * 2`
- Benchmark script `production/scripts/benchmark_thread_pool.py` runs at pool sizes [28, 48, 64, 96, 128]
- Document results in `production/scripts/README_PROFILING.md`
- No adaptive auto-tuning

**Correctness Validation (PIPE-04, PIPE-05)**
- `tests/unit/test_pipeline_determinism.py` — 100 bars, sequential == parallel outputs
- `tests/unit/test_pipeline_exception_isolation.py` — plugin failure graceful degradation
- Floating point tolerance: `abs(a - b) < 1e-10` if differences appear

**Systemd Template Unit (PIPE-06)**
- Rename to `indicagent-intelligence-pipeline@.service`
- Template env: `METRICS_PORT=9125`, `INSTANCE_ID=%i`, `LOG_FILE=logs/intelligence_pipeline_%i.log`
- Port never auto-computed from `%i` — always explicit
- Consumer group stays `intelligence_pipeline_consumer` for all instances
- `services/intelligence_pipeline_agent.py` reads `METRICS_PORT` from settings

### Claude's Discretion
- Test mocking strategy: mock plugins return deterministic fixed outputs — verify gather/collect/state-lock machinery
- Benchmark script format: CSV output for throughput curve; matplotlib optional
- README_PROFILING.md update: append benchmark results section

### Deferred Ideas (OUT OF SCOPE)
- GIL release audit
- Repartition topics + multiple instances + auto-scaler (backlog 999.1)
- Plugin alpha attribution (Phase 55-56)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PIPE-01 | Per-plugin latency histogram (`intelligence_pipeline_plugin_duration_ms` labeled by `plugin_name`, `tier`) visible in Prometheus after one RTH session | metrics.py already has labeled Histograms; same pattern used for `PLUGIN_EXECUTION_TIME`; add inside `_collect_plugin_results` which is the single collection point for both I1 and I7 |
| PIPE-02 | Per-plugin error counter (`intelligence_pipeline_plugin_errors_total`) increments on plugin exception | `_collect_plugin_results` already catches exceptions and increments `_pipeline_errors` (unlabeled); replace with labeled `PLUGIN_ERRORS_TOTAL` at that same exception branch |
| PIPE-03 | Thread pool size configurable via `INTELLIGENCE_THREAD_POOL_WORKERS` env var (defaults to `cpu_count * 2`); optimal value set in `.env` from benchmark | Settings uses pydantic-settings `Field(default=..., validation_alias="...")` pattern; cpu_count=24 on current hardware (48 default workers); benchmark covers [28, 48, 64, 96, 128] |
| PIPE-04 | Determinism test passes: 100 bars sequential vs parallel outputs identical (`i1` keys/values, `i7` signal list, `winner_plugin`, `winner_confidence`, `winner_direction`) | Existing `test_pipeline_parallelization.py` uses `__new__` pattern and mock plugins; same pattern applies to new test file; `asyncio.gather` preserves submission order — no expected non-determinism |
| PIPE-05 | Exception isolation test passes: plugin failure never crashes pipeline; downstream tiers receive partial output; `PLUGIN_ERRORS_TOTAL` increments | `_collect_plugin_results` already skips exceptions via `isinstance(out, Exception)` guard; test must confirm partial output propagates and error counter fires |
| PIPE-06 | Systemd template unit `indicagent-intelligence-pipeline@.service` installed and running as `@1` instance; metrics port configurable via `METRICS_PORT` env var | Installed unit at `/etc/systemd/system/indicagent-intelligence-pipeline.service` hardcodes `metrics_port=9125` in `__init__`; must add `METRICS_PORT` to Settings and read it in agent |
</phase_requirements>

---

## Summary

Phase 58 is a surgical close of four observability/correctness/ops gaps in the parallelized intelligence pipeline. The heavy lifting (I1/I7 `asyncio.gather` parallelization) is already on main and running in production. This phase adds: per-plugin Prometheus histograms and error counters, a configurable thread pool size backed by empirical benchmarking, two new correctness test files, and a systemd template unit.

All four work areas are well-bounded. The existing `_collect_plugin_results` method is the single hook point for both metrics additions (latency and errors) — no new architectural patterns needed. The Settings pattern for adding env vars is established and consistent across the codebase. The test infrastructure (`__new__` bypass, mock plugins, `asyncio.gather` patterns) already exists in `test_pipeline_parallelization.py` and can be directly extended. The systemd template conversion is a rename + 3-line env addition plus a `systemctl disable/enable` cycle.

The single subtlety is that `metrics_port=9125` is currently **hardcoded** in `IntelligencePipelineComputeAgent.__init__` as a direct `super().__init__()` argument, not read from Settings. This must be changed to `Settings().metrics_port` (using a new `METRICS_PORT`-aliased field) before the template unit's `Environment=METRICS_PORT=9125` will take effect.

**Primary recommendation:** Implement in sequence: (1) metrics.py additions, (2) Settings field + agent wiring, (3) two test files, (4) benchmark script, (5) systemd template. Each step is independently verifiable.

---

## Standard Stack

### Core (already in project — no new installs needed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| prometheus_client | installed | Histogram/Counter/Gauge metrics | Already used throughout `src/observability/metrics.py` |
| pydantic-settings | installed | Env var → Settings field mapping | Established pattern; all env vars go here |
| pytest + pytest-asyncio | installed | Unit test framework | `asyncio_mode=auto` in pytest.ini; `--asyncio-mode=auto` |
| concurrent.futures.ThreadPoolExecutor | stdlib | Thread pool for CPU-bound plugin execution | Already in `intelligence_pipeline_agent.py` |

### No New Dependencies Required
All libraries needed for Phase 58 are already installed. `pip install` is not needed.

---

## Architecture Patterns

### Pattern 1: Labeled Metric Registration in metrics.py

All module-level metrics use direct `prometheus_client` instantiation (not the `counter()`/`gauge()` helpers, which don't support labels). New metrics follow this same module-level pattern:

```python
# Source: src/observability/metrics.py (existing labeled metrics pattern)
PLUGIN_EXECUTION_TIME = Histogram(
    "plugin_execution_seconds", "Plugin execution time", ["plugin_name", "intelligence_tier"]
)
```

The new `PLUGIN_DURATION_MS`, `PLUGIN_ERRORS_TOTAL`, and `THREAD_POOL_WORKERS` must be module-level constants, not created inside functions, to avoid duplicate registration errors across tests.

**CRITICAL:** The existing `counter()` and `gauge()` helpers in `metrics.py` only accept `name` and `documentation` — they have NO label support. New labeled metrics must use `prometheus_client.Counter/Histogram/Gauge` directly at module level, exactly like `PLUGIN_EXECUTION_TIME`, `BAR_TO_I1_LATENCY`, etc.

### Pattern 2: Adding a Settings Field

```python
# Source: src/config/settings.py (established pattern)
intelligence_thread_pool_workers: int = Field(
    default=0,  # 0 = use cpu_count * 2 formula
    validation_alias="INTELLIGENCE_THREAD_POOL_WORKERS"
)
```

The `METRICS_PORT` field needs a different alias to avoid collision with the existing `metrics_port` field (which uses `INDICAGENT_METRICS_PORT`). The new field should use validation_alias `"METRICS_PORT"` so systemd `Environment=METRICS_PORT=9125` maps directly.

**CRITICAL:** Existing `metrics_port` field uses `validation_alias="INDICAGENT_METRICS_PORT"`, not `METRICS_PORT`. Adding a new field with `validation_alias="METRICS_PORT"` is non-conflicting. The agent's `super().__init__(metrics_port=9125)` hardcode must become `super().__init__(metrics_port=settings.metrics_port_override)` or similar.

### Pattern 3: _collect_plugin_results Instrumentation

The current `_collect_plugin_results` method (line 1000–1029) already handles both success and exception paths. The instrumentation hooks in cleanly:

```python
# Current exception branch (line 1019-1025):
if isinstance(out, Exception):
    self._pipeline_errors.inc()          # unlabeled — will be supplemented
    self.logger.warning(...)

# Current success branch (line 1026-1028):
elif isinstance(out, dict):
    self._update_plugin_state(task, out)
    outputs.append(out)
```

The `log_prefix` argument already carries tier context (`"plugin"` for I1, `"i7.plugin"` for I7). However, the tier must be passed as a separate string matching the Prometheus label values (e.g., `"I1"`, `"I7"`) — not derived from `log_prefix`. The method signature needs a `tier: str` parameter.

The `task.plugin_name` is already on `PluginTask` and available in the loop — no structural changes needed to access it.

**Timing for PLUGIN_DURATION_MS:** The method receives results already computed by `asyncio.gather`. Per-plugin timing must be recorded by wrapping the `run_in_executor` call (before gather), not inside `_collect_plugin_results`. Alternatively, timing can be captured inside the plugin wrapper callable passed to `run_in_executor`. The cleanest approach: wrap the plugin call in a timed closure before submitting to the executor.

### Pattern 4: Test File Structure (from existing test_pipeline_parallelization.py)

```python
# Established __new__ bypass pattern — MUST follow exactly
def _make_agent():
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    agent.name = "intelligence_pipeline_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent._plugin_cache = {}
    agent._plugin_states = {}
    agent._plugin_states_locks = {}
    agent._instrument_map = {}
    agent._plugin_skipped_total = MagicMock()
    agent._i1_latency_ms = MagicMock()
    agent._i7_latency_ms = MagicMock()
    agent._pipeline_errors = MagicMock()
    agent._setup_last_fire = {}
    agent._signals_generated = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "dev"
    agent._regime_cache = {}
    agent._tod_priors = {}
    agent._calibration_curves = {}
    agent._perf_weights = {}
    agent._output_queue = asyncio.Queue(maxsize=500)
    cpu_count = os.cpu_count() or 24
    agent._executor = ThreadPoolExecutor(max_workers=cpu_count * 2, thread_name_prefix="test_intel_")
    return agent
```

New test files for determinism and exception isolation must use this exact `_make_agent()` helper (copy and extend). **After adding `PLUGIN_DURATION_MS`, `PLUGIN_ERRORS_TOTAL`, `THREAD_POOL_WORKERS` to the agent, the `_make_agent()` in the new test files must also mock these new metrics attributes** (`agent._plugin_duration_ms = MagicMock()`, etc.) — otherwise tests fail mid-run with misleading AttributeError.

### Pattern 5: Systemd Template Unit

```ini
# Template unit filename: indicagent-intelligence-pipeline@.service
# Instance 1: indicagent-intelligence-pipeline@1.service

[Unit]
Description=IndicAgent Intelligence Pipeline — Unified I1-I7 compute agent (instance %i)
After=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
Environment=METRICS_PORT=9125
Environment=INSTANCE_ID=%i
Environment=LOG_FILE=logs/intelligence_pipeline_%i.log
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/intelligence_pipeline_agent.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-intelligence-pipeline@%i
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

**Transition sequence:**
1. `sudo systemctl stop indicagent-intelligence-pipeline`
2. `sudo systemctl disable indicagent-intelligence-pipeline`
3. Write new `@.service` file to `/etc/systemd/system/`
4. `sudo systemctl daemon-reload`
5. `sudo systemctl enable --now indicagent-intelligence-pipeline@1`
6. Verify: `systemctl status indicagent-intelligence-pipeline@1`

The reference file in `production/systemd/` also needs updating (the `@.service` file goes there as the new canonical reference template).

### Pattern 6: Benchmark Script Structure

```python
# production/scripts/benchmark_thread_pool.py
# Pattern: CSV output, pool_sizes = [28, 48, 64, 96, 128]
# Test against synthetic bars (no live infra needed)
# Measure: bars/sec throughput at each pool size
# Output: CSV to stdout + summary table
```

Uses synthetic mock plugin execution (real sleep-based or CPU-bound stub) to simulate realistic thread contention at each pool size. Does not require live Kafka or DB — purely measures `asyncio.gather` + `ThreadPoolExecutor` throughput.

### Anti-Patterns to Avoid

- **Deriving tier from `log_prefix`:** `log_prefix="plugin"` and `log_prefix="i7.plugin"` are logging strings, not Prometheus label values. Pass `tier="I1"` or `tier="I7"` as a separate explicit argument.
- **Creating metric objects inside functions:** Results in duplicate registration errors on second call. All Prometheus objects must be module-level.
- **Auto-computing port from `%i` in systemd:** Explicitly set `Environment=METRICS_PORT=9125` — never `Environment=METRICS_PORT=912%i`.
- **Using `counter()`/`gauge()` helpers for new labeled metrics:** Those helpers don't support labels. Use `prometheus_client.Counter/Histogram/Gauge` directly.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-plugin timing | Custom timing dict | `time.perf_counter()` + `PLUGIN_DURATION_MS.labels(...).observe()` | Already used for `_i1_latency_ms` / `_i7_latency_ms` |
| Settings env var | `os.environ.get(...)` | `Field(default=..., validation_alias="...")` in Settings | All env vars go through Settings; os.environ direct use is a CLAUDE.md violation |
| Systemd multi-instance | Custom PID management | Systemd template units (`@.service`) | Native systemd feature; handles lifecycle, restarts, journald correctly |
| Duplicate metric registration | try/except around registration | Module-level constants + `_server_started` guard already in metrics.py | Pattern established; adds no new mechanism |

---

## Common Pitfalls

### Pitfall 1: `_collect_plugin_results` Timing — Gather Already Happened
**What goes wrong:** Trying to record per-plugin duration inside `_collect_plugin_results` — but `asyncio.gather` has already completed by the time this method is called. Duration is unavailable at collection time.
**Why it happens:** The method receives `results: list` which are the outputs, not futures with timing info.
**How to avoid:** Wrap each plugin call in a timed closure *before* submitting to the executor. The closure records start/end time and stores in a per-task dict, OR the method signature is extended to also accept timing data. The simplest approach: modify `PluginTask` to carry a `duration_ms: float = 0.0` field, populated by the wrapper before returning the result.
**Warning signs:** `PLUGIN_DURATION_MS` always shows 0 in Grafana.

### Pitfall 2: `_make_agent()` Missing New Metric Attributes
**What goes wrong:** New test files copy `_make_agent()` without mocking `_plugin_duration_ms`, `_plugin_errors_total`, `_thread_pool_workers` — test crashes with `AttributeError` partway through.
**Why it happens:** The `__new__` bypass skips `__init__`, so any attributes set in `__init__` must be manually added to `_make_agent()`.
**How to avoid:** After adding metrics attributes to `__init__`, immediately add `agent._plugin_duration_ms = MagicMock()` etc. to `_make_agent()` in all test files that use it.
**Warning signs:** `AttributeError: 'IntelligencePipelineComputeAgent' object has no attribute '_plugin_duration_ms'` in tests.

### Pitfall 3: `METRICS_PORT` Field Conflicts with `INDICAGENT_METRICS_PORT`
**What goes wrong:** Adding `metrics_port_override: int = Field(validation_alias="METRICS_PORT")` to Settings collides with existing `metrics_port: int = Field(validation_alias="INDICAGENT_METRICS_PORT")`.
**Why it happens:** Two fields in pydantic-settings with different names but potentially confusable aliases. The existing field uses `INDICAGENT_METRICS_PORT`; the new one uses bare `METRICS_PORT`. No collision, but the agent currently calls `super().__init__(metrics_port=9125)` hardcoded — that line must be updated.
**How to avoid:** Name the new field something distinct, e.g. `pipeline_metrics_port: int = Field(default=9125, validation_alias="METRICS_PORT")`. Update `__init__` to read `settings.pipeline_metrics_port`.
**Warning signs:** Port still hardcoded to 9125 even after setting `METRICS_PORT=9126` in `.env`.

### Pitfall 4: Systemd Transition Leaves Old Unit Active
**What goes wrong:** Old `indicagent-intelligence-pipeline.service` not disabled; new `@1.service` also enabled; both try to run — port conflict on 9125.
**Why it happens:** `daemon-reload` alone doesn't stop old unit.
**How to avoid:** Explicit stop+disable sequence before enabling template. Verify with `systemctl list-units --all | grep indicagent-intelligence-pipeline`.
**Warning signs:** `Address already in use` on port 9125.

### Pitfall 5: `asyncio_mode=auto` vs STRICT Mode
**What goes wrong:** New test files don't include `@pytest.mark.asyncio` — fail with "no running event loop" or similar.
**Why it happens:** pytest.ini sets `asyncio_mode = auto` but phase 52.2 decision notes "pytest-asyncio 1.3.0 runs STRICT mode despite asyncio_mode=auto". Existing tests explicitly use `@pytest.mark.asyncio` for all async test functions.
**How to avoid:** Always add `@pytest.mark.asyncio` to all async test methods, even with `asyncio_mode=auto` in config.
**Warning signs:** Tests not collected or "coroutine was never awaited" warning.

---

## Code Examples

### Recording Per-Plugin Duration (timing wrapper approach)

```python
# Source: architecture decision — _collect_plugin_results receives completed results
# Solution: wrap plugin callable before submitting to executor

def _timed_plugin_call(plugin, frames):
    """Wrapper that returns (result, duration_ms) tuple."""
    t0 = time.perf_counter()
    result = plugin.compute_full(frames)
    duration_ms = (time.perf_counter() - t0) * 1000
    return result, duration_ms
```

Then in `_run_i1` / `_run_i7`, submit `_timed_plugin_call` instead of `plugin.compute_full`, and update `PluginTask` + `_collect_plugin_results` to unpack the tuple and record the histogram.

### Settings Field Addition

```python
# Source: src/config/settings.py (established Field pattern)
intelligence_thread_pool_workers: int = Field(
    default=0,
    validation_alias="INTELLIGENCE_THREAD_POOL_WORKERS",
    description="Thread pool worker count. 0 = cpu_count * 2 (auto)."
)
pipeline_metrics_port: int = Field(
    default=9125,
    validation_alias="METRICS_PORT",
    description="Prometheus metrics port for intelligence pipeline instances."
)
```

### Thread Pool Size Resolution

```python
# In IntelligencePipelineComputeAgent.__init__:
settings = Settings()
cpu_count = os.cpu_count() or 24
_configured = settings.intelligence_thread_pool_workers
_workers = _configured if _configured > 0 else cpu_count * 2
self._executor = ThreadPoolExecutor(max_workers=_workers, thread_name_prefix="intel_")
THREAD_POOL_WORKERS.set(_workers)
```

### Determinism Test Pattern

```python
# tests/unit/test_pipeline_determinism.py
class TestPipelineDeterminism:
    @pytest.mark.asyncio
    async def test_i1_sequential_equals_parallel(self):
        """100 bars: sequential mock execution == asyncio.gather execution."""
        agent = _make_agent()
        # Deterministic mock plugins — fixed outputs keyed by plugin name
        for i, name in enumerate(TIER_I1):
            agent._plugin_cache[name] = _deterministic_plugin({f"{name}_val": float(i)})
        frames = {"main": MagicMock()}
        results = [await agent._run_i1(frames, "ES", "1m") for _ in range(100)]
        # All 100 runs must produce identical dicts
        assert all(r == results[0] for r in results[1:])
```

### Exception Isolation Test Pattern

```python
# tests/unit/test_pipeline_exception_isolation.py
class TestExceptionIsolation:
    @pytest.mark.asyncio
    async def test_single_i1_plugin_raises_does_not_crash(self):
        agent = _make_agent()
        # Plugin 0 always raises
        class FailPlugin:
            def compute_full(self, frames):
                raise RuntimeError("injected failure")
        agent._plugin_cache[TIER_I1[0]] = FailPlugin()
        # Remaining plugins succeed
        for name in TIER_I1[1:]:
            agent._plugin_cache[name] = _deterministic_plugin({"val": 1.0})
        frames = {"main": MagicMock()}
        result = await agent._run_i1(frames, "ES", "1m")
        # Must not crash — partial result returned
        assert isinstance(result, dict)
        assert len(result) >= len(TIER_I1) - 1
        # Error counter must have fired
        agent._pipeline_errors.inc.assert_called()
```

---

## Runtime State Inventory

> Phase 58 renames/converts the systemd unit. Checking all 5 categories:

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | None — no DB schema changes, no string references to service name in TimescaleDB | None |
| Live service config | Installed unit: `/etc/systemd/system/indicagent-intelligence-pipeline.service` — currently active and running | Stop + disable old unit; install + enable `@1` template unit |
| OS-registered state | Old unit registered with systemd. `systemctl list-units --all \| grep indicagent-intelligence-pipeline` shows it as `active (running)` | `systemctl stop` + `systemctl disable` old unit; `daemon-reload`; `enable --now @1` |
| Secrets/env vars | `METRICS_PORT` not yet in `.env` (port currently hardcoded). `INTELLIGENCE_THREAD_POOL_WORKERS` not yet in `.env` | Add both to `.env` after benchmark; template unit provides `METRICS_PORT=9125` |
| Build artifacts | `.venv/` unaffected — no new packages. Log file `logs/intelligence_pipeline_agent.log` exists; template unit will write to `logs/intelligence_pipeline_1.log` | Old log file remains (harmless); new log path from `LOG_FILE` env var |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | All | ✓ | 3.13 | — |
| prometheus_client | PIPE-01/02 | ✓ | installed | — |
| pydantic-settings | PIPE-03/06 | ✓ | installed | — |
| pytest + pytest-asyncio | PIPE-04/05 | ✓ | installed | — |
| systemd | PIPE-06 | ✓ | active | — |
| ThreadPoolExecutor (stdlib) | PIPE-03 | ✓ | stdlib | — |

**Missing dependencies with no fallback:** None.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (asyncio_mode=auto, asyncio_default_fixture_loop_scope=function) |
| Config file | `pytest.ini` (project root) |
| Quick run command | `.venv/bin/pytest tests/unit/test_pipeline_determinism.py tests/unit/test_pipeline_exception_isolation.py -v` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PIPE-01 | `PLUGIN_DURATION_MS` histogram records per plugin | unit | `.venv/bin/pytest tests/unit/test_pipeline_exception_isolation.py -k "test_plugin_duration_recorded" -x` | Wave 0 |
| PIPE-02 | `PLUGIN_ERRORS_TOTAL` counter fires on exception | unit | `.venv/bin/pytest tests/unit/test_pipeline_exception_isolation.py -k "test_error_counter_increments" -x` | Wave 0 |
| PIPE-03 | Thread pool reads `INTELLIGENCE_THREAD_POOL_WORKERS` from Settings | unit | `.venv/bin/pytest tests/unit/test_pipeline_determinism.py -k "test_thread_pool_size_configurable" -x` | Wave 0 |
| PIPE-04 | 100 bars sequential == parallel outputs | unit | `.venv/bin/pytest tests/unit/test_pipeline_determinism.py -v -x` | Wave 0 |
| PIPE-05 | Plugin exception never crashes pipeline | unit | `.venv/bin/pytest tests/unit/test_pipeline_exception_isolation.py -v -x` | Wave 0 |
| PIPE-06 | Template unit installs and starts as `@1` | manual smoke | `systemctl status indicagent-intelligence-pipeline@1` | N/A |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/test_pipeline_determinism.py tests/unit/test_pipeline_exception_isolation.py -v -x`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green (2677+ passing, existing 2 pre-existing failures in `test_bar_writer_agent.py` are out of scope)

### Wave 0 Gaps
- [ ] `tests/unit/test_pipeline_determinism.py` — covers PIPE-04 (and PIPE-03 via configurable pool size subtest)
- [ ] `tests/unit/test_pipeline_exception_isolation.py` — covers PIPE-01, PIPE-02, PIPE-05
- [ ] `production/scripts/benchmark_thread_pool.py` — covers PIPE-03 empirical validation (not automated test, manual benchmark)

---

## Current State: What Exists vs What's Needed

### What Exists (confirmed by reading source)

| Item | Location | Status |
|------|----------|--------|
| `_collect_plugin_results` method | `services/intelligence_pipeline_agent.py:1000` | Exists — single hook point for both I1 and I7 |
| I1 + I7 parallel execution via `asyncio.gather` | `_run_i1` (line 1065), `_run_i7` (line 1170) | Exists and running in production |
| `_pipeline_errors` (unlabeled counter) | `intelligence_pipeline_agent.py:495` | Exists — fires on exception in `_collect_plugin_results` |
| `_i1_latency_ms` + `_i7_latency_ms` (gauges, tier-total only) | `intelligence_pipeline_agent.py:479,483` | Exists — no per-plugin granularity |
| `ThreadPoolExecutor(max_workers=cpu_count * 2)` | `intelligence_pipeline_agent.py:421` | Exists — hardcoded, not configurable |
| `metrics_port=9125` hardcoded in `__init__` | `intelligence_pipeline_agent.py:366` | Exists — not readable from env var |
| `PLUGIN_EXECUTION_TIME` histogram (symbol+tier labels) | `src/observability/metrics.py:59` | Exists — NOT per-plugin (uses `plugin_name` + `intelligence_tier` labels but is called from `record_plugin_execution()` helper, not from the pipeline hot path) |
| `__new__` test pattern + `_make_agent()` helper | `tests/unit/test_pipeline_parallelization.py:25` | Exists — copy for new test files |
| pytest.ini `asyncio_mode=auto` | `pytest.ini` | Exists — but use `@pytest.mark.asyncio` anyway per Phase 52.2 decision |

### What's Missing (Phase 58 adds)

| Item | Target File |
|------|-------------|
| `PLUGIN_DURATION_MS` Histogram (per-plugin, ms buckets) | `src/observability/metrics.py` |
| `PLUGIN_ERRORS_TOTAL` Counter (per-plugin labeled) | `src/observability/metrics.py` |
| `THREAD_POOL_WORKERS` Gauge | `src/observability/metrics.py` |
| `intelligence_thread_pool_workers` Settings field | `src/config/settings.py` |
| `pipeline_metrics_port` Settings field | `src/config/settings.py` |
| Wiring in `_collect_plugin_results` (timer + error label) | `services/intelligence_pipeline_agent.py` |
| `THREAD_POOL_WORKERS.set(n)` at startup | `services/intelligence_pipeline_agent.py` |
| Read pool size from settings (not hardcoded formula) | `services/intelligence_pipeline_agent.py` |
| Read `METRICS_PORT` from settings (not hardcoded 9125) | `services/intelligence_pipeline_agent.py` |
| `tests/unit/test_pipeline_determinism.py` | new file |
| `tests/unit/test_pipeline_exception_isolation.py` | new file |
| `production/scripts/benchmark_thread_pool.py` | new file |
| `production/systemd/indicagent-intelligence-pipeline@.service` | new file (rename/replace) |

---

## Project Constraints (from CLAUDE.md)

- **No `os.environ` direct reads** — all env vars through `src/config/settings.py` Settings class
- **No hardcoded Prometheus metric construction inside functions** — module-level constants only
- **Timestamps: always UTC** — not applicable for this phase (no new timestamps)
- **`setup_service_logging` requires full log path** — template unit sets `LOG_FILE=logs/intelligence_pipeline_%i.log`; agent must read this and pass it to `setup_service_logging()`
- **`PERSISTENCE_BATCH_LATENCY` label key is `agent_id`** — always verify label names in metrics.py before using; new metrics use `plugin_name` and `tier` per spec
- **Labeled metrics use direct `prometheus_client.Counter/Histogram/Gauge`** — NOT the `counter()`/`gauge()` helpers (which are label-less)
- **`@pytest.mark.asyncio` required** — despite `asyncio_mode=auto` in pytest.ini, per Phase 52.2 decision
- **Service test `__new__` pattern** — any new `__init__` attribute must be manually set in `_make_agent()`
- **Pre-commit mandatory: `/simplify` then `/coderabbit:code-review`** before committing
- **Ruff from project root only:** `.venv/bin/ruff check .` (not absolute paths)
- **Systemd units:** Installed in `/etc/systemd/system/`; `production/systemd/` is reference only

---

## Open Questions

1. **`PluginTask` timing wrapper vs method signature extension**
   - What we know: `_collect_plugin_results` receives results post-gather; timing unavailable there
   - What's unclear: Whether to add `(result, duration_ms)` tuple wrapping at the `run_in_executor` call site, or pass timing dict as an additional argument to `_collect_plugin_results`
   - Recommendation: Tuple wrapper is self-contained and doesn't change `_collect_plugin_results` signature — preferred. Add `_timed_plugin_call(plugin, frames)` wrapper function.

2. **`LOG_FILE` env var reading in agent**
   - What we know: Template unit sets `LOG_FILE=logs/intelligence_pipeline_%i.log`; current agent hardcodes `setup_service_logging("logs/intelligence_pipeline_agent.log")`
   - What's unclear: Whether to add `LOG_FILE` to Settings or read via `os.environ.get("LOG_FILE", ...)` as a special bootstrap case
   - Recommendation: Since `setup_service_logging` is called before Settings can be constructed, read `LOG_FILE` from `os.environ` directly for this single bootstrap case. This is a justified exception to the Settings rule (same pattern as Python logging before settings init).

3. **Benchmark script: synthetic vs real plugin execution**
   - What we know: Pool sizes [28, 48, 64, 96, 128] need a meaningful workload; real plugins require live data
   - What's unclear: Whether synthetic sleep-based stubs (simulate I/O wait) or CPU-spin stubs (simulate GIL-releasing compute) give more representative results
   - Recommendation: Use `time.sleep(0.001)` per plugin to simulate realistic 1ms latency; this is a fair ThreadPoolExecutor benchmark for I/O-like workloads. Document the assumption in the script header.

---

## Sources

### Primary (HIGH confidence)
- Direct code reading: `services/intelligence_pipeline_agent.py` — lines 363-424 (init, executor), 1000-1029 (`_collect_plugin_results`), 1035-1074 (`_run_i1`), 1150-1192 (`_run_i7`)
- Direct code reading: `src/observability/metrics.py` — all existing metric registrations, labeled vs unlabeled patterns
- Direct code reading: `src/config/settings.py` — Field pattern, existing aliases
- Direct code reading: `tests/unit/test_pipeline_parallelization.py` — `_make_agent()` pattern
- Direct reading: `/etc/systemd/system/indicagent-intelligence-pipeline.service` — current installed unit
- Direct reading: `docs/superpowers/specs/2026-04-02-pipeline-parallelization-renaissance-completion-design.md` — authoritative spec
- Direct reading: `.planning/phases/58-pipeline-parallelization-renaissance-completion/58-CONTEXT.md` — locked decisions

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` Phase 52.2 decision: "pytest-asyncio 1.3.0 runs STRICT mode despite asyncio_mode=auto — always use `@pytest.mark.asyncio`"
- `CLAUDE.md` service test `__new__` pattern and metric label conventions

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in project; no new dependencies
- Architecture patterns: HIGH — read directly from source code; no assumptions
- Pitfalls: HIGH — grounded in actual code structure (e.g., timing in `_collect_plugin_results` is a real constraint discovered by reading the method)
- Systemd template: HIGH — current installed unit confirmed by reading `/etc/systemd/system/`

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable domain; no fast-moving dependencies)
