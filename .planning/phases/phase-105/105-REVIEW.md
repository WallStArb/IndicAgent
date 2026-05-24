---
phase: phase-105
reviewed: 2026-05-24T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - services/bar_writer_agent.py
  - services/ctx_writer_agent.py
  - services/feature_writer_agent.py
  - services/intelligence_pipeline_agent.py
  - services/llm_writer_service.py
  - services/shadow_auditor_agent.py
  - services/swarm_ledger_writer_agent.py
  - src/intelligence/pipeline/executor.py
  - src/intelligence/pipeline/signal_processor.py
  - src/observability/metrics.py
  - tests/unit/observability/test_metrics.py
  - tests/unit/pipeline/test_signal_processor.py
  - tests/unit/services/test_bar_writer_agent.py
  - tests/unit/services/test_ctx_writer_agent.py
  - tests/unit/services/test_feature_writer_agent.py
  - tests/unit/services/test_llm_writer_service.py
  - tests/unit/services/test_shadow_auditor_agent.py
  - tests/unit/services/test_swarm_ledger_writer_agent.py
findings:
  critical: 3
  warning: 6
  info: 3
  total: 12
status: issues_found
---

# Phase 105: Code Review Report

**Reviewed:** 2026-05-24T00:00:00Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Phase 105 refactored and hardened several writer agents and the I7 signal pipeline. The code quality is generally strong: the shadow auditor filter direction is correct, OTel counter call-sites use `.add()` correctly in the main flush paths, and several tests accurately pin architectural invariants. However, three serious correctness bugs were found: a misaligned `zip` that assigns wrong plugin identities to signals, a ghost-run pattern in `LLMWriterAgent._connect_database` that allows silent data loss, and a monotonically-growing metric counter that reports garbage for consumer lag. Several weaker issues complete the picture.

---

## Critical Issues

### CR-01: `run_i7_complete` zip misalignment corrupts signal plugin identity

**File:** `src/intelligence/pipeline/executor.py:698`
**Issue:** `run_i7_plugins` returns a `(tasks, outputs, state_updates)` triple where `tasks` contains ALL dispatched `PluginTask` objects and `outputs` contains only the SUCCESSFUL dict results (exceptions are filtered in `_collect_plugin_results`). When any plugin raises an exception, `len(outputs) < len(tasks)`. The subsequent `zip(tasks, outputs, strict=False)` pairs `task[N]` with the result that actually belongs to `task[M]` (where M > N). This means `sig["setup_plugin"]`, `sig["regime_type"]`, and `sig["is_shadow"]` are stamped with the wrong plugin's identity. A shadow plugin's signal can incorrectly receive a live plugin's identity and be traded live; a live plugin's signal can be suppressed as shadow. This is a signal identity corruption bug affecting every bar where any I7 plugin fails.

**Fix:** Change the return type of `run_i7_plugins` from a filtered `outputs` list to a parallel list of `dict | None` (one entry per task, `None` for failed tasks), or zip over `(tasks, gather_results)` before filtering:

```python
# In run_i7_complete — after run_i7_plugins returns (tasks, outputs, state_updates):
# Replace:
for task, output in zip(tasks, outputs, strict=False):
    ...

# With: iterate over tasks and their gather_results directly (pre-filter).
# Simplest fix: collect task->output pairs inside _collect_plugin_results and return
# them as a list of (PluginTask, dict) tuples instead of two separate lists.
# Alternatively, build the mapping inside run_i7_plugins before returning:
task_outputs: list[tuple[PluginTask, dict]] = []
for task, raw in zip(tasks, gather_results):
    if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[0], dict):
        task_outputs.append((task, raw[0]))
for task, output in task_outputs:
    output.pop("_tier_key", None)
    if output.get("direction", 0) != 0:
        sig = output
        sig["setup_plugin"] = task.plugin_name
        ...
```

---

### CR-02: `LLMWriterAgent._connect_database` ghost-run pattern silently drops all data

**File:** `services/llm_writer_service.py:544`
**Issue:** When the database is unreachable at startup, `_connect_database` catches the exception and sets `self.db_manager = None` while logging only a warning. The service then continues running: it consumes messages from Kafka, advances offsets (via the process loop), and silently drops every LLM call without persisting it. This is the same ghost-run pattern that was explicitly fixed in `FeatureWriterAgent._connect_database` (which re-raises after logging, and has a dedicated test `test_connect_database_raises_on_db_failure` enforcing this). `LLMWriterAgent` diverges from the established project pattern and has no equivalent protection.

**Fix:**
```python
async def _connect_database(self) -> None:
    dsn = self.config["database"].get("dsn") or self.config["database"].get("url")
    try:
        self.db_manager = DatabaseManager(dsn)
        await self.db_manager.initialize()
        self.logger.info("Connected to database")
    except Exception as e:
        self.logger.error("llm_writer.db_connect_failed", error=str(e))
        raise  # let BaseAgent restart cycle handle reconnect; do not ghost-run
```

---

### CR-03: `_CONSUMER_LAG` and `_CONTRACT_CACHE_SIZE` up-down-counters accumulate garbage

**File:** `services/bar_writer_agent.py:271` and `:299`, `:334`
**Issue:** `_CONSUMER_LAG` is created as `create_up_down_counter` and every bar calls `.add(len(self._buffer), ...)`. An up-down counter accumulates its delta values — it is never decremented after a flush. After 100 bars the counter reads the sum of all buffer depths seen, not the current depth. This metric is labeled "proxy for consumer lag" in the description but it silently reports cumulative garbage instead of a point-in-time value. Similarly, `_CONTRACT_CACHE_SIZE` is an up-down counter whose `.add(cache_size, ...)` is called on every reload and every cache update, causing it to grow by `cache_size` each time rather than tracking the actual size.

Both instruments should either be OTel gauges (`create_gauge` / `point_gauge`) using `.set()`, or the up-down counter pattern must include a corresponding negative delta before each positive one.

**Fix:**
```python
# In module-level metrics block — change both instruments:
_CONSUMER_LAG = _bw_meter.create_gauge(
    "bar_writer_persistence_consumer_lag",
    description="Current unwritten buffer depth (proxy for consumer lag)",
)
_CONTRACT_CACHE_SIZE = _bw_meter.create_gauge(
    "bar_writer_contract_cache_size",
    description="Number of entries in the contract->base symbol cache",
)

# At call sites, change .add() to .set():
_CONSUMER_LAG.set(len(self._buffer), self._consumer_lag_attrs)   # line 271
_CONTRACT_CACHE_SIZE.set(cache_size, self._contract_cache_size_attrs)  # line 299
_CONTRACT_CACHE_SIZE.set(len(self._contract_cache), self._contract_cache_size_attrs)  # line 334
```

---

## Warnings

### WR-01: `LLMWriterAgent.service_uptime_seconds` and `buffer_size_gauge` use wrong instrument type

**File:** `services/llm_writer_service.py:439-444`, `:703`, `:989`
**Issue:** `buffer_size_gauge` and `service_uptime_seconds` are created with `gauge()`, which calls `create_up_down_counter`. Both are then used with `.add(value)` — `buffer_size_gauge.add(len(self._buffer))` and `service_uptime_seconds.add(uptime)`. An up-down counter accumulates deltas, so both metrics will grow unboundedly. `FeatureWriterAgent` makes the same metrics with `point_gauge()` (`create_gauge`) and correctly uses `.set()`. The `LLMWriterAgent` equivalent should use `point_gauge` + `.set()`.

**Fix:**
```python
# Change both to point_gauge:
from src.observability.metrics import counter, gauge, point_gauge

self.buffer_size_gauge = point_gauge(
    "llm_writer_buffer_size",
    "Current number of LLM call events in write buffer",
)
self.service_uptime_seconds = point_gauge(
    "llm_writer_service_uptime_seconds",
    "LLM writer agent uptime in seconds",
)
# At call sites, change .add() to .set():
self.buffer_size_gauge.set(len(self._buffer))   # line 703
self.service_uptime_seconds.set(uptime)          # line 989
```

---

### WR-02: `bar_writer_agent._run()` routes empty `rows=[]` to DLQ on `_parse_payload` returning `[]`

**File:** `services/bar_writer_agent.py:257-262`
**Issue:** `_parse_payload` can return `None` (for non-bar payloads / parse failure). The docstring says it returns an "empty list if parse fails (not DLQ)" but the actual code returns `None` when `_parse_bar` fails, and `None` is the only path that triggers `_maybe_route_to_dlq`. The `[]` return path documented in the docstring at line 170 is never reached (line 147 is the `topics_produced` property, not `_parse_payload`). However, the docstring creates a false contract: callers checking for the empty-list case will be confused, and the CLAUDE.md rule "`_parse_payload` return contract: returning `[]` for all-invalid prevents double-DLQ" is violated by always returning `None` for parse failures. The inconsistency between doc and code will cause maintainers to mis-implement future validation paths.

**Fix:** Either update the docstring to match reality (only `None` or `list[tuple]`), or implement the empty-list path for the case where `_parse_bar` returns `None`:
```python
def _parse_payload(self, payload: dict) -> list | None:
    bar = self._parse_bar(payload)
    if bar is None:
        return []  # per-signal validation fail -> empty list (not None/DLQ)
    ...
```
Then remove the explicit DLQ call at line 261 (base writer handles `None` → DLQ automatically).

---

### WR-03: `intelligence_pipeline_agent._run()` double-registers `drain_task`

**File:** `services/intelligence_pipeline_agent.py:342-351`
**Issue:** `drain_task` is added to both `self._background_tasks` (line 344) and the `tasks` list that is passed to `asyncio.gather` (line 346). If the task finishes early (e.g. `OutputQueue` drain loop exits), the done callback (`self._background_tasks.discard`) removes it from `_background_tasks`. But `asyncio.gather` holds its own reference, so the task is not cancelled and the gather continues waiting for it. When `gather` completes and logs any exception at line 359, the task has already been discarded from `_background_tasks`. This is harmless in practice today but means teardown code that iterates `_background_tasks` to cancel tasks will miss `drain_task` if it stopped early, potentially leaving the gather hanging until all other tasks complete. The design intent (background task management) and the gather (shutdown coordination) are working against each other.

**Fix:** Remove `drain_task` from `self._background_tasks` (or remove it from the `tasks` list passed to gather). Pick one owner, not both:
```python
async def _run(self) -> None:
    drain_task = asyncio.create_task(self._out_queue.drain_loop(lambda: self.running))
    # Only add to background_tasks for restart/discard callback:
    self._background_tasks.add(drain_task)
    drain_task.add_done_callback(self._background_tasks.discard)
    tasks = [
        asyncio.create_task(self._process_loop()),
        asyncio.create_task(self._health_monitor_loop()),
        asyncio.create_task(self._report_consumer_lag()),
    ]
    # drain_task is managed via _background_tasks; gather only the other three
    await asyncio.gather(*tasks, return_exceptions=True)
```

---

### WR-04: `feature_writer_agent._connect_database` sets `self.db_manager` before `initialize()` succeeds

**File:** `services/feature_writer_agent.py:409-414`
**Issue:** `self.db_manager = DatabaseManager(dsn)` is set at line 409 before `await self.db_manager.initialize()` at line 410. If `initialize()` raises, `self.db_manager` is left pointing to an uninitialized `DatabaseManager` instance. The test `test_connect_database_no_ghost_run_path` asserts that `"self.db_manager = None"` is absent, and the fix at line 414 (`raise`) is correct — but if another coroutine reads `self.db_manager` after the exception before the service exits (unlikely but possible during teardown), it will call methods on an uninitialized pool. This is a latent race, not a live bug today.

**Fix:**
```python
async def _connect_database(self) -> None:
    dsn = self.config["database"].get("dsn") or self.config["database"].get("url")
    db = DatabaseManager(dsn)
    await db.initialize()  # raises before assignment on failure
    self.db_manager = db
    self.logger.info("Connected to database")
```

---

### WR-05: `shadow_auditor._check_promotion` replaces the entire cache on DB reload but not on ContractUpdate-style single-entry invalidation

**File:** `services/shadow_auditor_agent.py:185-202`
**Issue:** The `days_to_gate` estimate uses `signal_computed_at` from `signal_ledger` rows. When `r["signal_computed_at"]` is not `None` but its `tzinfo` is `None` (naive datetime), the code does `r["signal_computed_at"].replace(tzinfo=UTC)` to make it timezone-aware before subtracting `now` (which is UTC-aware). However, asyncpg returns `timestamptz` columns as timezone-aware `datetime` objects (CLAUDE.md: "asyncpg returns datetime objects"). If the column is `timestamp` (no timezone) it would return a naive datetime. This only breaks if `signal_computed_at` is stored as `timestamp` instead of `timestamptz`. The conditional guard `if r["signal_computed_at"].tzinfo is None` suggests the author anticipated this, but if the column is actually `timestamptz` then the `.replace(tzinfo=UTC)` path is dead code and the subtraction path should work — no real bug. The code is defensive and correct IF the column type is consistent. However, the confusing conditional warrants a comment or removal of the dead branch.

**Fix:** Add a comment clarifying the invariant:
```python
# asyncpg always returns timestamptz as tz-aware; the .replace() branch
# is a defensive fallback for any future naive-datetime edge case.
```

---

### WR-06: `CtxWriterAgent._run()` calls `self._parse_failures_total.add(1)` but the counter may not exist if `_run` is reached without `__init__` running

**File:** `services/ctx_writer_agent.py:185`
**Issue:** `_parse_failures_total` is a BaseWriterAgent attribute set in `BaseWriterAgent.__init__`. `CtxWriterAgent._run()` calls `self._parse_failures_total.add(1)` on the parse failure path. If tests instantiate `CtxWriterAgent` via `__new__` without calling `__init__`, this attribute will not exist and raises `AttributeError`. The test fixture `_make_agent()` in `test_ctx_writer_agent.py` does explicitly set `agent._parse_failures_total = MagicMock()`, so tests pass. But the runtime path is sound because `_run()` is only called after `_setup()` which calls `super().__init__` via the normal constructor. The risk is in future tests that forget this attribute. Not a production bug, but a fragile test contract.

**Fix:** Document the attribute dependency in `_run()`:
```python
# _parse_failures_total is set by BaseWriterAgent.__init__
self._parse_failures_total.add(1)
```

---

## Info

### IN-01: `_build_score_insert_params` in `llm_writer_service.py` does not include `symbol` field

**File:** `services/llm_writer_service.py:281-330`
**Issue:** The `_build_score_insert_params` pure function (used in the unit test path) returns a dict without a `symbol` key (line 319 shows `n_calls`, `n_outcomes`, etc., but no `symbol`). The `_recompute_scores` method in the class does include `symbol` in its upsert tuple. However, the test `test_build_score_insert_params_below_min_n_not_significant` calls `_build_score_insert_params` and does not check for `symbol`, leaving the function's output mismatched with the full upsert SQL. If `_build_score_insert_params` is ever wired into the DB path directly, the missing `symbol` field would cause a positional parameter mismatch.

**Fix:** Add `symbol` to `_build_score_insert_params` return dict or mark the function as a test-only helper with a clear comment.

---

### IN-02: `intelligence_pipeline_agent._health_monitor_loop` is a no-op stub

**File:** `services/intelligence_pipeline_agent.py:615-617`
**Issue:** `_health_monitor_loop` sleeps 10 seconds and returns, forever. It logs nothing and performs no health checks. The method exists in the task list and gathers alongside `_process_loop`, consuming a task slot. This is dead code that would be better removed or replaced with an actual health check.

**Fix:** Either implement a health check or remove the task from `_run()`'s task list.

---

### IN-03: Deprecated `PLUGIN_FALLBACK_TOTAL` metric retained indefinitely

**File:** `src/observability/metrics.py:43-50`
**Issue:** The comment says "Remove old name in follow-on phase" (line 42) but no follow-on phase has been scheduled and the dual-emit pattern means every plugin fallback fires two OTel instruments. This adds cardinality overhead to the metrics backend. It is labeled `[DEPRECATED]` in its description, so Grafana dashboards should migrate to the new name.

**Fix:** Remove `PLUGIN_FALLBACK_TOTAL` and update the Grafana dashboard to use `intelligence_pipeline_plugin_fallback_total`.

---

_Reviewed: 2026-05-24T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
