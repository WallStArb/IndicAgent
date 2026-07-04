# BaseAgent Infrastructure Alignment

**Date:** 2026-04-14
**Status:** Approved
**Scope:** 6 targeted changes to eliminate boilerplate, fix bugs, and close observability gaps across the agent base class hierarchy.

---

## Problem

Adding a new agent requires tribal knowledge:
- Call `setup_service_logging()` before super, or after?
- Set `self._settings = Settings()` where — `__init__`, `_setup()`?
- Override `_report_consumer_lag()` with what boilerplate?
- Remember `init_tracing()` in `__main__`?

The base classes already provide most of this, but the seams leak. Result: 15 agents repeat the same patterns, one agent (LLMWriterService) bypasses the base entirely, observability coverage is partial, and some agents run duplicate lag reporting tasks.

## Design Principles

Renaissance rules applied:
- **Instrument everything** — tracing should be automatic, not opt-in per agent
- **Let the system run** — no manual steps that can be forgotten
- **Modularity + reuse** — if 15 agents repeat identical code, the base class should provide it
- **Simplicity** — no mixin decomposition, no DI framework, no Protocol explosion. Four base classes is enough.

## Changes

### 1. `self.settings` in BaseAgent — Singleton via `get_settings()`

**What:** BaseAgent.__init__() sets `self.settings = get_settings()` using the existing singleton in `src/config/settings.py`.

**Why:** Every agent independently writes `self._settings = Settings()` — 15+ times, with inconsistent placement (before super, after super, in `_setup()`). This is a maintenance smell and a config-before-super ordering gotcha (see `base_provider_agent.py` comments at line 59).

**How:**
- BaseAgent.__init__() calls `self.settings = get_settings()`
- Rename all `self._settings` references in agents to `self.settings`
- BaseProviderAgent passes `settings=get_settings()` to super().__init__; BaseAgent skips re-creation when settings kwarg is provided
- BaseWriterAgent and SwarmBaseAgent inherit self.settings automatically

**Files:** `src/core/agent/base.py`, all 15 agent files in `services/`

**Risk:** Low. `get_settings()` already returns a cached singleton. No behavioral change — same Settings object, same values.

### 2. Auto `init_tracing()` in BaseAgent — Tracing for everyone

**What:** BaseAgent.start() calls `init_tracing(self.name)` before `_setup()`, guarded by a module-level flag to ensure idempotency.

**Why:** 6-8 agents call `init_tracing()` in their `__main__` blocks, others don't. The OTel tracer from BaseAgent is a no-op when `init_tracing()` hasn't been called — partial coverage silently. Renaissance rule: instrument everything.

**How:**
- Add `_tracing_initialized: bool = False` module-level flag in `base.py`
- In `start()`, before `_setup()`: if not `_tracing_initialized`, call `init_tracing(self.name)`, set flag
- Remove `init_tracing()` calls from `__main__` blocks in all agents
- The guard means calling `init_tracing()` twice is harmless (already the case — the function creates a tracer provider, second call is a no-op)

**Files:** `src/core/agent/base.py`, 6-8 agent `__main__` blocks

**Risk:** Low. `init_tracing()` is already idempotent. The flag is defense-in-depth.

### 3. Default `_report_consumer_lag()` — Eliminate boilerplate

**What:** BaseAgent provides a working default `_report_consumer_lag()` that emits `PERSISTENCE_CONSUMER_LAG` with the agent name. BaseWriterAgent overrides it to report buffer depth instead.

**Why:** 15 agents override `_report_consumer_lag()` with near-identical code: import PERSISTENCE_CONSUMER_LAG, label with agent_id, set to 0, sleep 15. This is pure boilerplate. Worse, several agents create their own `lag_task = asyncio.create_task(self._report_consumer_lag())` inside `_run()` even though BaseAgent.start() already creates one at line 155 — resulting in duplicate lag tasks.

**How:**
- BaseAgent._report_consumer_lag() default implementation:
  - Cache `PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name)` at __init__ time
  - Loop: set gauge to 0, sleep 15s (current pattern for non-buffer agents)
- BaseWriterAgent._report_consumer_lag() override:
  - Set gauge to `len(self._buffer)` (current pattern for writer agents)
  - Uses existing `_consumer_lag` gauge from BaseWriterAgent if already cached
- Remove all 15 manual overrides
- Remove duplicate `lag_task` creation in agents that create their own

**Files:** `src/core/agent/base.py`, `src/core/agent/base_writer.py`, 15 agent files

**Risk:** Medium. Lag reporting is observability-critical. Verify each agent's override is truly identical to the default before removing. Writer agents that report buffer depth must get the BaseWriterAgent override.

### 4. Remove vestigial `setup_service_logging()` calls

**What:** Remove manual `setup_service_logging()` calls from `__main__` blocks where BaseAgent already handles it.

**Why:** Since Phase 52.2, BaseAgent auto-configures logging in `__init__()` (line 88-92). The `__main__` calls are harmless (idempotent "first call wins" per WR-05 fix) but are vestigial noise that obscures the actual pattern.

**How:**
- Remove `setup_service_logging(...)` from `__main__` blocks in agents that inherit BaseAgent
- Keep `setup_service_logging()` in LLMWriterService until it's migrated (Change 5)
- Verify logging still works by checking log files after restart

**Files:** 6-8 agent `__main__` blocks

**Risk:** None. "First call wins" means removing the second call has zero effect.

### 5. Migrate LLMWriterService to BaseWriterAgent

**What:** Rewrite `services/llm_writer_service.py` to inherit from `BaseWriterAgent` instead of rolling its own lifecycle, signal handling, metrics, and logging.

**Why:** LLMWriterService is the only active agent that doesn't inherit from BaseAgent. It manually implements signal handling, batch buffering, DLQ routing, and metrics — all of which BaseWriterAgent provides for free. It imports `AGENT_CRASH_TOTAL` from BaseAgent's module but doesn't inherit it.

**How:**
- Create `LLMWriterAgent(BaseWriterAgent)` class
- Implement `_topic_name()` → return primary topic (llm.calls)
- Implement `_consumer_group` → "llm_writer"
- Implement `_parse_payload()` → parse LLM call/outcome messages
- Implement `_flush_batch()` → batch INSERT to llm_calls / UPDATE outcomes
- Move score recomputation (15-min interval) to a background task in `_run()`
- Wire `_dlq_topic()` → `topic_llm_writer_dlq()`
- Get DLQ routing, stall detection, crash metrics, setup latency metrics for free
- Update systemd service entry point if needed

**Files:** `services/llm_writer_service.py`, possibly `services/indicagent-llm-writer.service`

**Risk:** Medium. LLMWriterService has two consumers (calls + outcomes) plus a 15-min recomputation loop — slightly more complex than typical writer agents. The BaseWriterAgent pattern assumes one consumer, so `_run()` will need to handle the dual-consumer + timer pattern manually (which is allowed — BaseWriterAgent subclasses own their `_run()`).

### 6. Remove duplicate lag task creation

**What:** Remove manual `lag_task = asyncio.create_task(self._report_consumer_lag())` from agents that create their own, since BaseAgent.start() already creates this task.

**Why:** BaseAgent.start() creates the lag task at line 155. Several agents create a second one in their `_run()` method, resulting in two concurrent lag reporting loops per agent. This wastes resources and can cause metric contention.

**How:**
- Identify agents with manual lag_task creation (found in: `roll_compute_agent.py`, `signal_metrics_compute_agent.py`, `signal_metrics_writer_agent.py`, `service_auditor_agent.py`, `contract_metadata_writer_agent.py`, `bar_aggregator_agent.py`, `cross_asset_service.py`, `swarm_orchestrator_agent.py`, `ai_narrative_agent.py`, `signal_auditor_agent.py`, `parity_auditor_agent.py`)
- Remove the manual `lag_task` creation and its cancel/await code
- These agents already have `_report_consumer_lag()` overrides which will be called by BaseAgent's task

**Files:** 11 agent files

**Risk:** Low. The BaseAgent.start() task already calls the overridden `_report_consumer_lag()`. Removing the duplicate is pure cleanup. With Change 3 providing a default implementation, agents that only override for the PERSISTENCE_CONSUMER_LAG metric can drop their override entirely.

## What We're NOT Doing

- **No mixin decomposition** — BaseAgent at ~420 lines is not bloated. Four base classes is the right granularity.
- **No Protocol/ABC explosion** — The current hierarchy is clean. Don't add abstractions that don't earn their complexity.
- **No dependency injection framework** — Constructor args and `get_settings()` singleton suffice.
- **No changes to SwarmBaseAgent** — It's correct as-is and is Phase 56 territory.
- **No changes to BaseProviderAgent's adapter pattern** — It works. The Settings kwargs passthrough (Change 1) is the only touch.

## Execution Order

Dependencies determine order:

1. **Change 1** (Settings singleton) — foundational, no dependencies
2. **Change 2** (Auto init_tracing) — foundational, no dependencies
3. **Change 4** (Vestigial cleanup) — depends on Changes 1+2 being in place
4. **Change 3** (Default consumer lag) — depends on Change 6 (remove duplicates first to avoid conflicts)
5. **Change 6** (Remove duplicate lag tasks) — independent but cleaner if done with Change 3
6. **Change 5** (LLMWriter migration) — depends on Changes 1-3 for full benefit

Parallelize: Changes 1 + 2 can land together. Changes 3 + 6 can land together.

## Testing

- Unit tests: `tests/unit/test_base_agent.py` — add tests for settings singleton, auto tracing, default lag reporting
- Integration: restart each affected service, verify log output, metrics, and tracing
- Regression: run full unit suite (`.venv/bin/pytest tests/unit/ -v`)
- Manual: `systemctl restart` each changed service, check `logs/*.log` for structured output
