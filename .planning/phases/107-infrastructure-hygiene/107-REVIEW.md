---
phase: 107-infrastructure-hygiene
reviewed: 2026-05-25T18:30:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - production/systemd/indicagent-bar-aggregator.service
  - services/bar_replay_provider_agent.py
  - services/service_auditor_agent.py
  - services/signal_replay_auditor_agent.py
  - services/swarm_ledger_writer_agent.py
  - src/core/agent/base.py
findings:
  critical: 2
  warning: 4
  info: 3
  total: 9
status: issues_found
---

# Phase 107: Code Review Report

**Reviewed:** 2026-05-25T18:30:00Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed 6 files from Phase 107 (Infrastructure Hygiene): BaseAgent lifecycle base class, four service agents migrated to BaseAgent, and one systemd unit file. The migration to BaseAgent lifecycle is largely sound, but two critical bugs will cause runtime crashes in production:

1. **Duplicate `_teardown()` in `bar_replay_provider_agent.py`** -- the second definition silently overrides the first, causing producer/pool resources to leak because the cleanup logic is never called.
2. **`self._stop` AttributeError in `signal_replay_auditor_agent.py`** -- the `_cycle()` method references `self._stop` (nonexistent) instead of `self._stop_event` (set by BaseAgent). This will crash every replay cycle iteration when the agent receives a SIGTERM.

Additionally, two agents use `self._settings` where BaseAgent exposes `self.settings`, which would cause AttributeError at runtime when those code paths execute.

## Critical Issues

### CR-01: Duplicate `_teardown()` -- first definition silently discarded, resources leak

**File:** `services/bar_replay_provider_agent.py:72` and `services/bar_replay_provider_agent.py:153`
**Issue:** The class defines `_teardown()` twice. Python silently uses the last definition (line 153), which only saves the checkpoint and calls `super()._teardown()`. The first definition (line 72) that closes `self._producer` and `self._pool` is never executed. This means on every shutdown:
- The Kafka producer is not stopped (connections leak)
- The asyncpg pool is not closed (DB connections leak)
- Only the checkpoint is saved and the no-op `super()._teardown()` runs

This is a one-shot batch service that restarts frequently, so leaked connections accumulate.

**Fix:** Merge both `_teardown()` implementations into a single method:

```python
async def _teardown(self) -> None:
    # Save checkpoint on shutdown for one-shot batch service
    if self._last_replayed_ts:
        self._save_checkpoint(self._last_replayed_ts)
    # Cleanup producer and pool
    if self._producer:
        await self._producer.stop()
    if self._pool:
        await self._pool.close()
```

Remove the first `_teardown()` at line 72 entirely.

### CR-02: `self._stop` AttributeError -- wrong attribute name in signal_replay_auditor

**File:** `services/signal_replay_auditor_agent.py:440`
**Issue:** The `_cycle()` method calls `self._stop.is_set()` but BaseAgent defines the attribute as `self._stop_event`. There is no `self._stop` attribute anywhere in the inheritance chain. When the SIGTERM handler sets `_stop_event` and `_cycle()` reaches line 440, it will raise `AttributeError: 'SignalReplayAuditorAgent' object has no attribute '_stop'`. This exception propagates up to `_run()` (line 467), which catches it, logs it, and continues -- so the agent never actually stops until `sys.exit()` from the stall watchdog or SIGKILL.

**Fix:**
```python
# Line 440: change self._stop to self._stop_event
if self._stop_event.is_set():
    return
```

## Warnings

### WR-01: `self._settings` should be `self.settings` in bar_replay_provider_agent

**File:** `services/bar_replay_provider_agent.py:121`
**Issue:** Line 121 uses `self._settings.env_name` but BaseAgent stores the settings as `self.settings` (no underscore prefix). This will raise `AttributeError` when `_publish_bar()` is called. The correct property is `self.env_name` (which reads from `self.settings.env_name`) or `self.settings.env_name`.

**Fix:**
```python
# Line 121: use self.settings or self.env_name
env = self.env_name  # preferred -- uses BaseAgent property
```

### WR-02: `self._settings` should be `self.settings` in signal_replay_auditor_agent

**File:** `services/signal_replay_auditor_agent.py:180`
**Issue:** Same as WR-01. Line 180 uses `self._settings.env_name` but BaseAgent exposes `self.settings` and `self.env_name`. This will raise `AttributeError` when `_replay_signal()` reaches the Kafka publish path.

**Fix:**
```python
# Line 180: use self.env_name
topic = topic_lifecycle_transitions(self.env_name)
```

### WR-03: SwarmLedgerWriterAgent manual logging overridden by BaseAgent

**File:** `services/swarm_ledger_writer_agent.py:84`
**Issue:** The `__init__` manually calls `setup_service_logging("logs/swarm_ledger_writer_agent.log")` before `super().__init__()`. But BaseAgent's `__init__` derives the path from the agent name `swarm_ledger_writer` -> `logs/swarm_ledger_writer.log` (without `_agent` suffix). The guard at `base.py:110` compares `BaseAgent._log_configured_path` against the derived path. Since the paths differ (`logs/swarm_ledger_writer_agent.log` vs `logs/swarm_ledger_writer.log`), BaseAgent reconfigures logging to the wrong file, overriding the correct manual path. The agent's logs will go to `logs/swarm_ledger_writer.log` instead of `logs/swarm_ledger_writer_agent.log`.

Per CLAUDE.md, the convention is `logs/<agent_snake_case>_agent.log`. The manual call is correct; BaseAgent's derivation is wrong for this agent.

**Fix:** Remove the manual `setup_service_logging()` call at line 84 and either:
(a) Rename the agent to `SwarmLedgerWriter` so BaseAgent derives `logs/swarm_ledger_writer.log` (but this breaks the naming convention), or
(b) Pass the log path to BaseAgent via an override mechanism (the docstring mentions this should work, but there is no parameter for it yet).

Simplest fix: remove the manual call and accept the derived path, or add a `log_path` parameter to `BaseAgent.__init__`.

### WR-04: ServiceAuditorAgent DB pool missing `pool_name`

**File:** `services/service_auditor_agent.py:273`
**Issue:** `create_db_pool(self.settings.database_url, min_size=1, max_size=3)` omits the `pool_name` parameter, which defaults to `"default"`. All other agents in this review pass `pool_name` (e.g., `"bar_replay_provider"`, `"signal_replay_auditor"`, `"swarm_ledger_writer"`). Without a unique pool name, the service_auditor's pool metrics (`db_pool_size`, `db_pool_idle`) are indistinguishable from any other pool that also uses the default name, making DB connection debugging harder.

**Fix:**
```python
self._db_pool = await create_db_pool(
    self.settings.database_url,
    pool_name="service_auditor",
    min_size=1,
    max_size=3,
)
```

## Info

### IN-01: Missing `asyncpg` import in bar_replay_provider_agent and signal_replay_auditor_agent

**File:** `services/bar_replay_provider_agent.py:52,92,108` and `services/signal_replay_auditor_agent.py:62,90,120,155,210,247,314`
**Issue:** Both files use `asyncpg.Pool` and `asyncpg.Record` in type annotations without importing `asyncpg`. This works at runtime because both files have `from __future__ import annotations` (PEP 563 defers evaluation), but it breaks IDE navigation and `isinstance()` checks. `swarm_ledger_writer_agent.py` correctly imports `asyncpg` for the same usage pattern.

**Fix:** Add `import asyncpg` to the import block in both files.

### IN-02: Stale CLAUDE.md gotcha -- label key is now `agent_id`, not `agent`

**File:** `CLAUDE.md` (project instructions, not a reviewed source file)
**Issue:** CLAUDE.md states: "`agent_last_message_timestamp_seconds` label key is `agent` not `agent_id`". The Phase 107 migration (commit 8f86d3e0) changed `base.py:120` from `{"agent": name}` to `{"agent_id": name}`, and `service_auditor_agent.py` was updated to match. The CLAUDE.md gotcha is now stale and will mislead future developers into using the wrong label key.

**Fix:** Update the CLAUDE.md gotcha to read: "`agent_last_message_timestamp_seconds` label key is `agent_id` (migrated in Phase 107)".

### IN-03: Unused import `TF_SECONDS` noqa comment references wrong plan number

**File:** `services/bar_replay_provider_agent.py:24`
**Issue:** The `noqa: F401` comment says "confirms Plan 02 dependency satisfied" but `TF_SECONDS` is not used anywhere in this file. The import exists solely for the dependency side-effect. The noqa comment references an old plan number and does not explain why a module-level import side-effect is needed.

**Fix:** Either remove the unused import or update the comment to explain the actual dependency reason.

---

_Reviewed: 2026-05-25T18:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
