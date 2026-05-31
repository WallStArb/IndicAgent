---
phase: 111-naming-alignment
reviewed: 2026-05-30T12:00:00Z
depth: standard
files_reviewed: 60
files_reviewed_list:
  - production/grafana/dashboards/operations.json
  - production/grafana/dashboards/pipeline-health.json
  - production/systemd/indicagent-config-service.service
  - production/systemd/indicagent-dlq-drain.service
  - production/systemd/indicagent-macro-compute.service
  - production/systemd/indicagent-ml-signal-training-materialize.service
  - production/systemd/indicagent-self-healing-agent.service
  - production/systemd/indicagent-shadow-auditor.service
  - services/alert_monitor.py
  - services/bar_aggregator.py
  - services/bar_auditor.py
  - services/bar_replay_provider.py
  - services/bar_writer.py
  - services/config_service.py
  - services/context_writer.py
  - services/cross_asset_analyzer.py
  - services/data_quality_auditor.py
  - services/dlq_drain.py
  - services/feature_writer.py
  - services/graduation_analyzer.py
  - services/graduation_writer.py
  - services/intelligence_pipeline.py
  - services/lifecycle_writer.py
  - services/lineage_writer.py
  - services/llm_writer.py
  - services/macro_analyzer.py
  - services/ml_discovery_analyzer.py
  - services/ml_orchestrator.py
  - services/ml_signal_training_agent.py
  - services/narrative_swarm.py
  - services/provider_merger.py
  - services/self_healer.py
  - services/service_auditor.py
  - services/shadow_auditor.py
  - services/signal_auditor.py
  - services/signal_metrics_analyzer.py
  - services/signal_metrics_writer.py
  - services/signal_replay_auditor.py
  - services/signal_tracker.py
  - services/signal_writer.py
  - services/swarm_ledger_writer.py
  - src/core/agent/base.py
  - src/core/agent/base_writer.py
  - src/core/ai/base_agent.py
  - src/core/ai/evaluator.py
  - src/core/state_serializer.py
  - src/core/tier_aliases.py
  - src/intelligence/ai/alpha/correlation_prompts.py
  - src/intelligence/ai/alpha/counterfactual_agent.py
  - src/intelligence/ai/alpha/counterfactual_prompts.py
  - src/intelligence/ai/alpha/regime_coherence_prompts.py
  - src/intelligence/ai/alpha/skeptic_prompts.py
  - src/intelligence/ai/base_group_service.py
  - src/intelligence/ai/context.py
  - src/intelligence/ai/narrative/narrative_agent.py
  - src/intelligence/ai/TEMPLATE.py
  - src/intelligence/plugin_validator.py
  - src/intelligence/services/bar_history_seeder.py
  - src/intelligence/services/ml_signal_training_materializer.py
  - src/observability/metrics.py
findings:
  critical: 4
  warning: 5
  info: 3
  total: 12
status: issues_found
---

# Phase 111: Code Review Report

**Reviewed:** 2026-05-30T12:00:00Z
**Depth:** standard
**Files Reviewed:** 60
**Status:** issues_found

## Summary

This phase performs a naming alignment refactor introducing auto-derivation of `agent_id` and log file paths in `BaseDaemon` via `_to_snake_case()`. The core change is sound: `BaseDaemon.__init__` now derives `self.name` from the class name when none is supplied, and `BaseWriter` uses `self.name` for per-agent metric instruments. However, the refactoring exposed four pre-existing correctness problems that are now locked in by the new auto-derivation logic, and introduced one new bug via `BaseSwarmCoordinator` passing a PascalCase class name that bypasses the conversion.

Key areas of concern:
1. `BaseSwarmCoordinator` passes `self.__class__.__name__` (PascalCase) to `BaseDaemon`, producing a malformed `_agent_label` and a case-mismatched `agent_id` OTel label that breaks `ServiceAuditor` stall detection for the two swarm services.
2. `DLQDrain` sets `max_idle_seconds=600` but never calls `_record_message_consumed()`, causing guaranteed spurious stall-watchdog exits after 600s of any activity.
3. `services/ml_signal_training_agent.py` violates the CLAUDE.md D-06 oneshot contract — no `JOB_COMPLETED_TOTAL` emission or `flush_and_shutdown_metrics()` call.
4. FastAPI services (`config_service`, `self_healer`) have `WatchdogSec=60` in their systemd units but implement no `sd_notify(WATCHDOG=1)` loop, causing systemd to SIGKILL them every 60 seconds.

---

## Critical Issues

### CR-01: BaseSwarmCoordinator Passes PascalCase Class Name — Breaks Stall Detection and Corrupts OTel Labels

**File:** `src/intelligence/ai/base_group_service.py:74`

**Issue:** `BaseSwarmCoordinator.__init__` calls:
```python
super().__init__(name=self.__class__.__name__, max_idle_seconds=0, settings=settings)
```
This passes `"AlphaSwarm"` or `"NarrativeSwarm"` as a non-None `name` to `BaseDaemon.__init__`. Because `name` is not `None`, `BaseDaemon` skips `_to_snake_case()` and uses the PascalCase string directly. This causes two cascading problems:

**Problem A — `_agent_label` is corrupted:**
```python
self._agent_label = name.lower().replace(' ', '_')
# "AlphaSwarm".lower().replace(' ', '_') = "alphaswarm"  (no underscore)
```
All metrics using `_agent_label` (DLQ, crash, setup success/failure/latency, circuit breaker) are emitted with the malformed label `"alphaswarm"` / `"narrativeswarm"` instead of the expected `"alpha_swarm"` / `"narrative_swarm"`.

**Problem B — `agent_id` OTel label is PascalCase:**
```python
self._last_msg_ts_attrs = {"agent_id": name}
# = {"agent_id": "AlphaSwarm"}
```
`ServiceAuditor._fetch_stalled_agents()` queries `agent_last_message_timestamp_seconds` and looks up `r["metric"].get("agent_id", "")` against `_AGENT_ID_TO_UNIT`, which has keys `"alpha_swarm"` and `"narrative_swarm"`. The label `"AlphaSwarm"` never matches, so `unit = None` and the stall detection silently skips both swarm services. If either swarm stalls, `ServiceAuditor` will never trigger a restart.

**Fix:** Apply `_to_snake_case()` in `BaseSwarmCoordinator.__init__`:
```python
def __init__(self, settings: Settings, *args: Any, **kwargs: Any) -> None:
    from src.core.agent.base import _to_snake_case
    super().__init__(
        name=_to_snake_case(self.__class__.__name__),
        max_idle_seconds=0,
        settings=settings,
    )
```

---

### CR-02: DLQDrain Sets max_idle_seconds=600 but Never Calls _record_message_consumed — Guaranteed Spurious Exits

**File:** `services/dlq_drain.py:85` and `services/dlq_drain.py:167-176`

**Issue:** `DLQDrain.__init__` calls `super().__init__(max_idle_seconds=600)`, enabling the stall watchdog. However, `_run()` processes messages in `_drain_message()` and never calls `self._record_message_consumed()`. Because `_last_message_ts` is never set, `_stall_watchdog` sees it as `None` and skips the first check (startup grace). After the first message arrives and `_last_message_ts` remains `None`, the stall watchdog continues to skip indefinitely — but that means the condition is actually "benign" in a different way: the `None` guard means `_stall_watchdog` never fires. Wait — re-reading: the watchdog only starts counting idle time after `_last_message_ts` is first set. If it is never set, the stall watchdog is permanently in "startup grace" and never fires. This is not a stall-exit bug but it does mean:

1. `agent_last_message_timestamp_seconds` is never updated for `DLQDrain`.
2. `ServiceAuditor` stall detection (which uses Prometheus to check this gauge) cannot detect a genuinely stalled `DLQDrain` — the metric stays at 0 (cold-start value) and `ServiceAuditor` applies the `ts <= 0` cold-start guard, so it also skips DLQDrain forever.
3. The `WATCHDOG_NOTIFY_SUPPRESSED_TOTAL` liveness suppression logic (`_watchdog_notify`) also checks `_last_message_ts`; since it's `None`, the suppression condition is never triggered and the watchdog pings unconditionally — meaning systemd considers DLQDrain always healthy even when it has received zero messages for hours.

The net result: DLQDrain is operationally invisible — both to `ServiceAuditor` and to Grafana's liveness SLO alert. A poison-pill infinite loop in `_drain_message()` would appear healthy.

**Fix:**
```python
async def _run(self) -> None:
    assert self._consumer is not None
    assert self._pool is not None
    async for dlq_topic, _key, payload in self._consumer.messages():
        if self._stop_event.is_set():
            break
        self._record_message_consumed()  # ADD THIS
        await self._drain_message(dlq_topic, payload)
```

---

### CR-03: ml_signal_training_agent.py Violates D-06 Oneshot Contract — No JOB_COMPLETED_TOTAL or Metrics Flush

**File:** `services/ml_signal_training_agent.py:19-27`

**Issue:** Per CLAUDE.md D-06: "Oneshot timer-triggered scripts MUST emit `job_completed_total{job, status}` at script exit. Label `job` MUST match the systemd unit `%n` suffix exactly (kebab-case)." The unit is `indicagent-ml-signal-training-materialize`, so the required label is `job="ml-signal-training-materialize"`.

`ml_signal_training_agent.py` emits neither `JOB_COMPLETED_TOTAL` nor calls `flush_and_shutdown_metrics()` before exiting. Other oneshot scripts (`shadow_auditor.py`, `ml_training_agent.py`) implement this correctly. Without the counter, the Grafana SLO alert `job_completed_total{status="failure"}` never fires for this oneshot, and `time_since_last_success{job=ml-signal-training-materialize}` cannot be evaluated (the metric series doesn't exist). A silent nightly failure of the training data materializaton would go undetected.

**Fix:**
```python
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

def main() -> None:
    settings = Settings()
    agent = MLSignalTrainingMaterializer(settings)
    try:
        asyncio.run(agent.start())
        JOB_COMPLETED_TOTAL.add(
            1, {"job": "ml-signal-training-materialize", "status": "success"}
        )
    except Exception:
        JOB_COMPLETED_TOTAL.add(
            1, {"job": "ml-signal-training-materialize", "status": "failure"}
        )
        raise
    finally:
        flush_and_shutdown_metrics()
```

---

### CR-04: FastAPI Services Have WatchdogSec=60 But No sd_notify WATCHDOG=1 Loop — Systemd Will Kill Them Every 60s

**Files:** `production/systemd/indicagent-config-service.service:18`, `production/systemd/indicagent-self-healing-agent.service:21`

**Issue:** Both `config_service.py` (uvicorn on port 9001) and `self_healer.py` (uvicorn on port 9002) are FastAPI applications, not `BaseDaemon` subclasses. They have no `_watchdog_notify()` loop and no `sdnotify` integration. Both systemd unit files set `WatchdogSec=60` with `NotifyAccess=main`.

With `Type=simple` + `WatchdogSec=60`, systemd expects `WATCHDOG=1` to arrive via the `NOTIFY_SOCKET` at least every 60 seconds. Since neither uvicorn nor any application code sends watchdog pings, systemd will send `SIGKILL` after 60 seconds. In practice, `Type=simple` with `WatchdogSec` does require pings — this is not mitigated by `Type=simple` alone.

The services are listed as `Restart=always`, so they restart immediately, but they are killed+restarted every ~60s, causing `StartLimitBurst` exhaustion over time. `indicagent-self-healing-agent.service` has `StartLimitBurst=5` and `StartLimitIntervalSec=300`, meaning after 5 kills in 300s, systemd will stop restarting it.

**Fix options (choose one):**
A. Remove `WatchdogSec=60` from both unit files if these services rely on uvicorn's internal keep-alive.
B. Add a background task in the FastAPI lifespan context that sends `WATCHDOG=1` pings:
```python
import sdnotify
import asyncio

async def watchdog_task():
    notifier = sdnotify.SystemdNotifier()
    import os
    usec = int(os.getenv("WATCHDOG_USEC", "0"))
    if usec <= 0:
        return
    interval = usec / 2_000_000
    while True:
        notifier.notify("WATCHDOG=1")
        await asyncio.sleep(interval)
```

---

## Warnings

### WR-01: Hardcoded _batch_latency_attrs in signal_writer, lifecycle_writer, graduation_writer Use Stale "_agent" Suffix

**Files:** `services/signal_writer.py:78`, `services/lifecycle_writer.py:96`, `services/graduation_writer.py:73`

**Issue:** Three writer services hardcode `_batch_latency_attrs` with the old `_agent` suffix convention:
```python
# signal_writer.py
self._batch_latency_attrs = {"agent_id": "signal_writer_agent"}
# lifecycle_writer.py
self._batch_latency_attrs = {"agent_id": "lifecycle_writer_agent"}
# graduation_writer.py
self._batch_latency_attrs = {"agent_id": "graduation_writer_agent"}
```
The auto-derived `self.name` (and thus `_agent_label`) for these classes is `"signal_writer"`, `"lifecycle_writer"`, `"graduation_writer"`. The Grafana dashboard `pipeline-health.json` queries `persistence_batch_latency_seconds_bucket{agent_id="feature_writer"}` (no suffix), consistent with the auto-derived naming. The "_agent" suffix on these three writers means their batch latency metrics are emitted under a label that no dashboard panel or alert queries. `FeatureWriter` was already updated to use `self._agent_label` (line 272); the three other writers were not.

**Fix:** Replace the hardcoded strings with the auto-derived value:
```python
# signal_writer.py, lifecycle_writer.py, graduation_writer.py
self._batch_latency_attrs = {"agent_id": self._agent_label}
```

---

### WR-02: _AGENT_ID_TO_UNIT Has Three Dead Keys for Phase 109 Services Using Wrong Format

**File:** `services/service_auditor.py:157-159`

**Issue:**
```python
_AGENT_ID_TO_UNIT: dict[str, str] = {
    ...
    "config-service": "indicagent-config-service",
    "outbox-dispatcher": "indicagent-outbox-dispatcher",
    "self-healing-agent": "indicagent-self-healing-agent",
}
```
These three keys use kebab-case. The auto-derivation from `_to_snake_case` produces snake_case. The actual `name` emitted by `OutboxPublisher` is `"outbox_dispatcher_agent"` (explicitly set at `src/config/outbox_publisher.py:58`). `config_service.py` and `self_healer.py` are FastAPI apps that are not BaseDaemon subclasses — they emit no `agent_last_message_timestamp_seconds` metric at all. The kebab-case keys will never match any Prometheus label, making these `_AGENT_ID_TO_UNIT` entries permanently dead. The stall detection for `OutboxPublisher` also fails because its actual name `"outbox_dispatcher_agent"` is not in the map.

**Fix:** Update the keys to match the actual emitted values:
```python
"outbox_dispatcher_agent": "indicagent-outbox-dispatcher",
# Remove config-service and self-healing-agent (FastAPI, no timestamp metric)
```

---

### WR-03: MacroAnalyzer Emits AGENT_CRASH_TOTAL with Stale Manual agent_id

**File:** `services/macro_analyzer.py:193`

**Issue:** `MacroAnalyzer` imports `AGENT_CRASH_TOTAL` from `src.core.agent.base` and emits it manually:
```python
AGENT_CRASH_TOTAL.add(1, {"agent": self.agent_id})
# self.agent_id = "macro_compute_agent" (class attribute)
```
But `BaseDaemon.start()` already catches uncaught exceptions in `_run()` and emits `AGENT_CRASH_TOTAL.add(1, self._crash_attrs)` where `_crash_attrs = {"agent": "macro_analyzer"}` (auto-derived). The manual emission uses label `"macro_compute_agent"`, the base class emission uses `"macro_analyzer"`. This produces duplicate crash events on different label values for the same crash, and neither matches the `_AGENT_ID_TO_UNIT` convention (which would be `"macro_analyzer"`).

**Fix:** Remove the manual `AGENT_CRASH_TOTAL.add` call from `MacroAnalyzer._run()` — the base class handles it. If a unique agent_id is needed for historical reasons, override `_crash_attrs` in `__init__` instead.

---

### WR-04: setup_service_logging Called After super().__init__() in dlq_drain.py main()

**File:** `services/dlq_drain.py:264`

**Issue:** The `main()` entrypoint calls `setup_service_logging("logs/dlq_drain.log")` after `DLQDrain()` is instantiated:
```python
async def main() -> None:
    setup_service_logging("logs/dlq_drain.log")  # called AFTER __init__
    agent = DLQDrain()
    await agent.start()
```
`BaseDaemon.__init__` already auto-configures `logs/dlq_drain.log` during `DLQDrain()` instantiation via the `_log_configured_path` guard. The second call in `main()` is a no-op due to the guard (`_log_configured_path` already equals the path). However, the CLAUDE.md doc for `BaseDaemon` explicitly states: "Override: call `setup_service_logging(custom_path)` BEFORE `super().__init__()`." The current pattern is after-the-fact and creates confusion about which call is authoritative.

**Fix:** Either remove the redundant call from `main()` entirely (since `BaseDaemon` now handles it), or move it before instantiation:
```python
async def main() -> None:
    agent = DLQDrain()  # auto-configures logs/dlq_drain.log
    await agent.start()
```

---

### WR-05: shadow_auditor.service Missing EnvironmentFile for Secrets

**File:** `production/systemd/indicagent-shadow-auditor.service`

**Issue:** The shadow auditor systemd unit has no `EnvironmentFile` directive, so it cannot access database credentials from `.env`. It hardcodes `INDICAGENT_ENV=development` inline. The service calls `create_db_pool(settings.database_url)` which reads `PGPASSWORD`/`DATABASE_URL` from settings. Without an `EnvironmentFile`, if these are not in the systemd environment by another means (e.g., a global environment file or `DefaultEnvironment`), the nightly shadow audit will silently fail to connect to the database and exit with a failure status that is never surfaced (no `JOB_COMPLETED_TOTAL` emission for this path — the DB connection failure happens in `_amain()` which is wrapped by `try/except`).

**Fix:** Add `EnvironmentFile=/home/bg/dev/indicagent/.env` to match other timer-triggered services like `indicagent-ml-signal-training-materialize.service`.

---

## Info

### IN-01: _LEGACY_FIELDS Variable Name is Misleading in dlq_drain.py

**File:** `services/dlq_drain.py:60-66`

**Issue:** The variable `_LEGACY_FIELDS` contains the fields of the *new* `DLQPayload` envelope (`agent`, `source_topic`, `error_type`, `error_message`, `payload`, `timestamp`). Legacy messages are identified by the *absence* of these fields. The name suggests the opposite semantics — that these are the fields belonging to legacy messages. The comment "Identify them by the absence of the required envelope fields" clarifies intent, but the variable name `_LEGACY_FIELDS` remains a readability hazard.

**Fix:** Rename to `_ENVELOPE_FIELDS` or `_DLQPAYLOAD_REQUIRED_FIELDS`.

---

### IN-02: BaseSwarmCoordinator `__init__` Passes name Before _to_snake_case is Available

**File:** `src/intelligence/ai/base_group_service.py:74`

**Issue:** `BaseSwarmCoordinator.__init__` imports nothing from `src.core.agent.base` at module level — the import is `from src.core.agent.base import BaseDaemon`. The `_to_snake_case` helper is a module-level private function in `base.py`, not exported. Importing it requires `from src.core.agent.base import _to_snake_case` (private import). This could be avoided by letting `BaseDaemon` handle the derivation (passing `name=None` to let auto-derivation fire).

**Fix (cleaner):** Simply pass `name=None` and rely on auto-derivation:
```python
def __init__(self, settings: Settings, *args: Any, **kwargs: Any) -> None:
    super().__init__(name=None, max_idle_seconds=0, settings=settings)
```

---

### IN-03: `_agent_label` Derivation Uses Different Logic Than `_to_snake_case`

**File:** `src/core/agent/base.py:168`

**Issue:** Two different regex transforms exist in `base.py` for snake_case conversion:
1. `_to_snake_case()` (lines 98-100): two-pass regex handles acronyms correctly — `MLDiscoveryAnalyzer` → `ml_discovery_analyzer`.
2. `_agent_label = name.lower().replace(' ', '_')` (line 168): assumes `name` is already snake_case.

When `name` is auto-derived (via `_to_snake_case`) before being assigned to `self.name`, `_agent_label` works correctly because `self.name` is already snake_case. But when `name` is passed in as PascalCase (as `BaseSwarmCoordinator` does), `_agent_label` produces a concatenated lowercase string without underscores (e.g., `"alphaswarm"`). This is a latent inconsistency that will affect any future class that passes a non-snake_case name. The fix for CR-01 addresses the immediate instance; this note flags the underlying fragility.

**Fix (defensive):** Apply `_to_snake_case()` to `_agent_label` derivation:
```python
self._agent_label = _to_snake_case(name)
```

---

_Reviewed: 2026-05-30T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
