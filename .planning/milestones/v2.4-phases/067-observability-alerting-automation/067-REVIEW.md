---
phase: 067-observability-alerting-automation
reviewed: 2026-04-14T00:00:00Z
depth: standard
files_reviewed: 23
files_reviewed_list:
  - production/grafana/dashboards/operations.json
  - production/grafana/dashboards/pipeline-health.json
  - production/grafana/dashboards/signals-i8.json
  - services/ai_narrative_agent.py
  - services/bar_aggregator_agent.py
  - services/bar_auditor_agent.py
  - services/contract_metadata_writer_agent.py
  - services/cross_asset_service.py
  - services/intelligence_pipeline_agent.py
  - services/lifecycle_writer_agent.py
  - services/llm_writer_service.py
  - services/ml_data_quality_agent.py
  - services/ml_discovery_agent.py
  - services/ml_orchestrator_agent.py
  - services/parity_auditor_agent.py
  - services/roll_compute_agent.py
  - services/service_auditor_agent.py
  - services/signal_auditor_agent.py
  - services/signal_metrics_compute_agent.py
  - services/signal_metrics_writer_agent.py
  - services/signal_writer_agent.py
  - services/swarm_orchestrator_agent.py
  - tests/unit/test_grafana_dashboards.py
findings:
  critical: 0
  warning: 6
  info: 5
  total: 11
status: issues_found
---

# Phase 067: Code Review Report

**Reviewed:** 2026-04-14T00:00:00Z
**Depth:** standard
**Files Reviewed:** 23
**Status:** issues_found

## Summary

This phase delivers observability infrastructure across the pipeline: BaseAgent crash/setup metrics, Grafana dashboards (operations, pipeline-health, signals-i8), service auditor with webhook alerting, signal/bar/parity auditors, ML pipeline orchestration (data quality, discovery, orchestrator), signal metrics compute/writer, lifecycle writer, swarm orchestrator, and companion unit tests.

The implementation is broadly solid. All agents follow the BaseAgent lifecycle contract, use `stream_keys.py` for topic names, use `datetime.now(UTC)` for timestamps, and handle graceful SIGTERM. The graduated restart policy in `service_auditor_agent.py` and the dedup/cooldown logic in `bar_auditor_agent.py` are well-constructed. None of the issues below are data-loss bugs, but IN-02 (roll automation never fires) and WR-01 (runtime crash in lag check) are worth fixing before production load.

---

## Warnings

### WR-01: Runtime TypeError in `_get_consumer_lag` — frozenset not subscriptable

**File:** `services/bar_aggregator_agent.py:459`
**Issue:** `aiokafka`'s `assignment()` method returns a `frozenset`, not a list. The code does `partitions[0]`, which raises `TypeError: 'frozenset' object is not subscriptable` at runtime. The guard at line 456 (`if not partitions`) never executes because the TypeError is raised one line before the guard. Additionally, line 454 accesses `self._kafka_consumer._consumer` (a private internal attribute) — during the consumer restart window (`_consumer_restart_needed` path), this may be `None`, causing `AttributeError` before even reaching the guard.
**Fix:** Use `next(iter(partitions))` instead of subscript, and guard `_consumer` for None:
```python
inner = getattr(self._kafka_consumer, "_consumer", None)
if inner is None:
    return 0
partitions = inner.assignment()
if not partitions:
    return 0
tp = next(iter(partitions))
```

---

### WR-02: Blocking `subprocess.run` inside async event loop in `_restart_ibkr_provider`

**File:** `services/service_auditor_agent.py:580`
**Issue:** `subprocess.run(cmd, check=True, capture_output=True)` is a synchronous blocking call. When called from `_handle_roll_event` (running inside an `asyncio.Task`), this blocks the entire event loop for the duration of `systemctl restart` (typically 1-5 seconds). During that window, the Prometheus check loop, heartbeat loop, and systemd check loop cannot make progress.
**Fix:** Replace with the async subprocess pattern already used in `ml_orchestrator_agent.py`:
```python
async def _restart_ibkr_provider(self) -> None:
    cmd = ["sudo", "systemctl", "restart", "indicagent-ibkr-provider"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            self.logger.error(
                "roll_automation.restart_failed",
                service="indicagent-ibkr-provider",
                returncode=proc.returncode,
                stderr=stderr.decode() if stderr else "",
            )
            return
        SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.labels(
            service_name="indicagent-ibkr-provider"
        ).inc()
        self.logger.info("roll_automation.restart_complete", service="indicagent-ibkr-provider")
    except Exception as exc:
        self.logger.error(
            "roll_automation.restart_failed",
            service="indicagent-ibkr-provider",
            error=str(exc),
        )
```

---

### WR-03: `asyncpg` not imported at top level but used in type annotation

**File:** `services/swarm_orchestrator_agent.py:210`
**Issue:** `_seed_context_cache` has the annotation `pool: asyncpg.Pool`. The file only imports asyncpg locally inside `_setup()` as `import asyncpg as _asyncpg`. The top-level name `asyncpg` is never bound. This file does not have `from __future__ import annotations`, so annotations are evaluated eagerly at class definition time — `asyncpg.Pool` raises `NameError: name 'asyncpg' is not defined`.
**Fix:** Add `from __future__ import annotations` at the top of the file (already present in most other service files):
```python
from __future__ import annotations
```

---

### WR-04: `_run` in `SwarmOrchestratorComputeAgent` cannot propagate stop signal — shutdown deadlock

**File:** `services/swarm_orchestrator_agent.py:104-113`
**Issue:** `_run` awaits `asyncio.gather(bar_task, signal_task)`. Neither inner task checks `self.running` or `self._stop_event`; both loop on `.messages()` indefinitely. On SIGTERM, BaseAgent sets `_stop_event` but `_run` remains blocked in `gather`. `_teardown` (which stops the consumers and would unblock `.messages()`) is only called after `_run` returns — a deadlock. In practice, systemd's `TimeoutStopSec` SIGKILL saves the process, but the drain is not clean.
**Fix:** Add a stop check inside each inner loop:
```python
async def _bar_loop(self) -> None:
    assert self._bar_consumer is not None
    async for _topic, _key, payload in self._bar_consumer.messages():
        if not self.running:
            break
        self._record_message_consumed()
        await self._handle_bar(payload)

async def _signal_loop(self) -> None:
    assert self._signal_consumer is not None
    async for _topic, _key, payload in self._signal_consumer.messages():
        if not self.running:
            break
        ...
```

---

### WR-05: `setup_service_logging` call in ML agent `__init__` is overwritten by BaseAgent

**File:** `services/ml_data_quality_agent.py:54`, `services/ml_discovery_agent.py:66`, `services/ml_orchestrator_agent.py:65`
**Issue:** All three ML one-shot agents call `setup_service_logging("logs/ml_*.log")` before `super().__init__()`, following the documented CLAUDE.md pattern. However, `BaseAgent.__init__` unconditionally re-calls `setup_service_logging` using a name-derived path (line 92 of `base.py`). For `MLDataQualityAuditorAgent`, the derived path is `logs/m_l_data_quality_auditor_agent.log` — not the intended `logs/ml_data_quality_agent.log`. The second call overwrites the first. Structured service logs will land in the wrong file.
**Fix:** The root cause is that BaseAgent does not respect a pre-existing logging configuration. Minimal fix: rename the classes so the auto-derived name matches the desired filename, e.g., rename `MLDataQualityAuditorAgent` to `MlDataQualityAgent` (derives `logs/ml_data_quality_agent.log`). Alternatively, make `setup_service_logging` idempotent (skip if already configured to the same path).

---

### WR-06: RSI outlier threshold is unreachable — `_check_outliers` score is always 1.0

**File:** `services/ml_data_quality_agent.py:166`
**Issue:** The SQL condition `ABS((i1->>'rsi_14')::float - 50) > 6 * 20` evaluates to `ABS(rsi - 50) > 120`. RSI is bounded in [0, 100], so the maximum deviation from 50 is 50 — the condition is mathematically impossible. `outlier_count` is always 0 and `outlier_score` is always 1.0. This component inflates the composite quality score regardless of actual data quality, breaking the intent of the outlier check.
**Fix:** Use a meaningful threshold. For example, check for structurally invalid RSI values (outside [0, 100]):
```sql
(i1->>'rsi_14') IS NOT NULL
AND (
    (i1->>'rsi_14')::float < 0
    OR (i1->>'rsi_14')::float > 100
    OR (i1->>'atr_14')::float < 0
)
```
Or use a permissive statistical bound: `ABS((i1->>'rsi_14')::float - 50) > 45` (RSI outside [5, 95]).

---

## Info

### IN-01: `_get_consumer_lag` opens a new broker connection every 15 seconds

**File:** `services/bar_aggregator_agent.py:442-466`
**Issue:** `_get_consumer_lag` creates a fresh `AIOKafkaConsumer`, connects to Redpanda, queries partition offsets, then disconnects. It is called unconditionally from `_update_health_metrics` every 15 seconds — approximately 240 broker connections per hour. The inline comment on line 445 says "This is expensive — only call for health summaries", but the actual call site in the 15-second loop is unconditional.
**Fix:** Either reduce polling to match the 60-second health summary (call from the existing 60-second log block in `_run` only), or reuse a persistent offset-query consumer initialized once during `_setup`.

---

### IN-02: `_handle_roll_event` event_type guard silently drops all roll events

**File:** `services/service_auditor_agent.py:536`
**Issue:** The guard `if event_type != "roll_complete": return` checks `payload.get("event_type")`. `RollComputeAgent` publishes `RollEvent.model_dump(mode="json")`, and `RollEvent` has no `event_type` field. So `event_type` is always `None`, the guard always triggers, and the ibkr-provider restart automation never fires. The feature is silently inoperative.
**Fix:** Remove the event_type guard (the topic is single-purpose), or add `event_type: str = "roll_event"` to the `RollEvent` model and update the guard string:
```python
async def _handle_roll_event(self, payload: dict) -> None:
    # topic_roll_events is single-purpose — every message is a confirmed roll
    symbol = payload.get("symbol", "")
    new_contract = payload.get("new_contract", "")
    old_contract = payload.get("old_contract", "")
    ...
```

---

### IN-03: Test file uses working-directory-relative paths

**File:** `tests/unit/test_grafana_dashboards.py:9`
**Issue:** All tests use `pathlib.Path("production/grafana/dashboards/...")` which resolves relative to the current working directory. Tests pass when run from the project root but fail with `FileNotFoundError` if pytest is invoked from another directory.
**Fix:** Anchor paths to the test file's location:
```python
_DASHBOARD_DIR = pathlib.Path(__file__).parent.parent.parent / "production" / "grafana" / "dashboards"
```

---

### IN-04: `_seed_context_cache` does not guard `i6 IS NOT NULL` in WHERE clause

**File:** `services/swarm_orchestrator_agent.py:218-228`
**Issue:** The seed query selects `i6` but only guards on `i1 IS NOT NULL AND i4 IS NOT NULL`. A row with `i6 = NULL` (possible during warmup or for HTF bars with insufficient history) will be passed to `seed_from_db_row` with a None value. Whether `SwarmContextCache.seed_from_db_row` handles this gracefully is not visible in this file.
**Fix:** Add `AND i6 IS NOT NULL` to the WHERE clause to match the guards applied to `i1` and `i4`.

---

### IN-05: Magic numbers in outlier SQL have no explaining comment

**File:** `services/ml_data_quality_agent.py:166`
**Issue:** `6 * 20` (= 120) appears inline with no comment explaining what 6 represents (sigma multiplier?) or 20 (baseline RSI std?). Combined with WR-06 (the condition is unreachable), this makes the intent of the check extremely hard to determine on a future read.
**Fix:** Define named module-level constants with docstrings, or replace with the meaningful threshold described in WR-06.

---

_Reviewed: 2026-04-14T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
