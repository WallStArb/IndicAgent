---
phase: 56
plan: "07"
subsystem: swarm-services
tags: [swarm, orchestrator, writer, asyncpg, kafka, systemd, shadow-mode]
dependency_graph:
  requires: [56-03, 56-04, 56-06, 56-08]
  provides: [SwarmOrchestratorComputeAgent, SwarmWriterAgent, swarm-systemd-units]
  affects: [alpha_multiplier_shadow, topic_swarm_results, topic_swarm_alpha_path_a]
tech_stack:
  added: [SwarmOrchestratorComputeAgent, SwarmWriterAgent]
  patterns: [BaseAgent._run()/_setup()/_teardown(), asyncio.gather two-task loop, asyncpg batch insert with ON CONFLICT DO NOTHING, DLQ fan-out on malformed + DB failure]
key_files:
  created:
    - services/swarm_orchestrator_agent.py
    - services/swarm_writer_agent.py
    - tests/unit/service_tests/test_swarm_orchestrator_agent.py
    - tests/unit/service_tests/test_swarm_writer_agent.py
    - production/systemd/indicagent-swarm-orchestrator.service
    - production/systemd/indicagent-swarm-writer.service
    - src/intelligence/swarm/context.py
    - src/intelligence/swarm/aggregator.py
  modified:
    - src/core/stream_keys.py
    - src/intelligence/schemas.py
decisions:
  - SwarmWriterAgent uses __new__ pattern in tests; _write_batch() __aexit__ must return False for exception propagation through async context manager
  - SwarmOrchestratorComputeAgent uses two concurrent asyncio tasks (bar_loop + signal_loop) under asyncio.gather
  - systemd units committed as reference templates only (not installed from worktree to avoid production conflicts)
  - AgentResult and AlphaMultiplier schemas updated to Phase 56-04 shape (path/shadow_only/latency_ms on AgentResult; symbol/timeframe/production_multiplier on AlphaMultiplier)
metrics:
  duration: ~25 minutes
  completed: 2026-04-11T05:36:17Z
  tasks_completed: 4
  files_created: 8
  files_modified: 2
---

# Phase 56 Plan 07: Swarm Services (Orchestrator + Writer) Summary

**One-liner:** SwarmOrchestratorComputeAgent (two-phase bar+signal asyncio loop, path-A contributor fan-out) and SwarmWriterAgent (batch asyncpg insert to alpha_multiplier_shadow with DLQ) as BaseAgent subclasses with full SIGTERM drain.

## What Was Built

### SwarmWriterAgent (`services/swarm_writer_agent.py`)
- Consumes `topic_swarm_results()` — one AgentResult per message (fan-out from orchestrator)
- Batch-inserts to `alpha_multiplier_shadow` via asyncpg `executemany` (50-row batches, 2s flush interval)
- `ON CONFLICT (signal_id, agent_id) DO NOTHING` — idempotent dedup at application layer
- DLQ on malformed payload (missing required fields) and DB failure → `topic_swarm_writer_dlq()`
- `_teardown()` drains remaining batch on SIGTERM before closing pool

### SwarmOrchestratorComputeAgent (`services/swarm_orchestrator_agent.py`)
- Two concurrent asyncio tasks via `asyncio.gather`: `_bar_loop` + `_signal_loop`
- Bar loop: subscribes to `topic_market_bars` + `topic_market_bars_htf` → updates `SwarmContextCache`
- Signal loop: subscribes to `topic_intelligence_i7_signals` → builds SwarmContext → runs Path A contributors concurrently → fan-outs each AgentResult to `topic_swarm_results()` → assembles AlphaMultiplier → publishes to `topic_swarm_alpha_path_a()`
- DLQ on missing context (symbol/tf not yet cached) → `topic_swarm_orchestrator_dlq()`
- With zero contributors (current state — no agents deployed yet), publishes neutral AlphaMultiplier (production_multiplier=1.0, shadow_only=True)

### Systemd Units
- `production/systemd/indicagent-swarm-orchestrator.service`
- `production/systemd/indicagent-swarm-writer.service`
- Both: `Restart=always`, `RestartSec=10`, `PYTHONUNBUFFERED=1`

## Tests
- 6 unit tests pass: 3 per service
- `test_swarm_writer_agent.py`: insert-to-shadow-table, malformed-to-DLQ, DB-failure-to-DLQ
- `test_swarm_orchestrator_agent.py`: bar-loop-updates-cache, no-context-goes-to-DLQ, zero-contributors-returns-neutral

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Swarm topic functions missing from worktree stream_keys.py**
- **Found during:** Task 1, Step 2 (RED test run)
- **Issue:** `topic_swarm_results`, `topic_swarm_writer_dlq`, and all other Phase 56 swarm/ML topics absent from the worktree branch's `stream_keys.py` — they were added in Plan 56-06 which ran in a different parallel worktree
- **Fix:** Added all swarm topics (`topic_swarm_results`, `topic_swarm_alpha_path_a`, `topic_swarm_alpha_path_b`, `topic_swarm_world_state`, `topic_swarm_orchestrator_dlq`, `topic_swarm_writer_dlq`) and ML topics to the worktree's `stream_keys.py`
- **Files modified:** `src/core/stream_keys.py`
- **Commit:** `2ed27ab3`

**2. [Rule 1 - Bug] asyncio context manager mock __aexit__ suppresses exceptions by default**
- **Found during:** Task 1, Step 4 (GREEN test run) — `test_db_failure_sends_to_dlq` failing
- **Issue:** `AsyncMock().__aexit__` returns a truthy coroutine by default, which Python's `async with` interprets as "suppress exception" — the DB exception never reached the except block
- **Fix:** Changed mock to `ctx_mgr.__aexit__ = AsyncMock(return_value=False)` so exception propagates correctly
- **Files modified:** `tests/unit/service_tests/test_swarm_writer_agent.py`
- **Commit:** `2ed27ab3`

**3. [Rule 3 - Blocking] SwarmContext + SwarmAggregator missing from worktree swarm directory**
- **Found during:** Task 2, Step 2 (RED test run)
- **Issue:** `src/intelligence/swarm/context.py` and `aggregator.py` existed in main repo (added by parallel agents in Plans 56-03/56-04) but absent from this worktree
- **Fix:** Copied both files from main repo to worktree
- **Files modified:** `src/intelligence/swarm/context.py`, `src/intelligence/swarm/aggregator.py`
- **Commit:** `b8b9b961`

**4. [Rule 3 - Blocking] AgentResult and AlphaMultiplier schemas outdated in worktree**
- **Found during:** Task 2, Step 4 (GREEN test run) — Pydantic validation errors on `path` field missing in AgentResult, `symbol`/`timeframe`/`production_multiplier` missing in AlphaMultiplier
- **Issue:** Worktree had pre-Phase-56-04 schema shapes; the aggregator.py (copied from main) expected the updated shapes
- **Fix:** Updated `AgentResult` to add `path`, `shadow_only`, `latency_ms`, `error` fields; updated `AlphaMultiplier` to add `symbol`, `timeframe`, `path_a_multiplier`, `path_b_multiplier`, `path_b_discount`, `production_multiplier`, `shadow_only` and removed `path: Literal[...]`
- **Files modified:** `src/intelligence/schemas.py`
- **Commit:** `b8b9b961`

**5. [Rule 1 - Bug] Test mock: MagicMock() signal with no spec has MagicMock plugin attribute**
- **Found during:** Task 2, Step 4 (GREEN) — Pydantic `winner_plugin` validation error (expected str, got MagicMock)
- **Issue:** `SwarmContextCache.build()` passes `signal.plugin` directly to `SwarmContext.winner_plugin: str | None`, but bare `MagicMock()` returns another `MagicMock` for `.plugin`
- **Fix:** Use `MagicMock(spec=RankedSignal)` and set `sig.plugin = "TrendFollowing"` explicitly
- **Files modified:** `tests/unit/service_tests/test_swarm_orchestrator_agent.py`
- **Commit:** `b8b9b961`

**6. [Note] Plan's BaseAgent interface mismatch**
- The plan specified `async def run(self)` methods, but the actual `BaseAgent` requires `async def _run(self)` (abstract), `async def _setup(self)`, and `async def _teardown(self)`. The implementations were adapted accordingly. The plan also called `setup_service_logging()` in `main()` which is now handled by `BaseAgent.__init__()` via name auto-derivation.

**7. [Note] systemd unit installation skipped**
- The plan called for `sudo systemctl` install/start from the worktree. This was skipped — installing from a parallel worktree branch would conflict with production and other parallel agents. Units committed as reference templates for post-phase installation.

## Known Stubs
- `"features": None` in the AgentResult fan-out payload — the plan states "ShadowRecorder (Plan 56-08) adds features". This is intentional: the features field is stubbed as `None` until Plan 56-08 wires in the ShadowRecorder. The DB column accepts NULL.

## Threat Flags
None — new services consume/produce Kafka topics and write to `alpha_multiplier_shadow` (shadow-only table, no production signal modification). All paths are `shadow_only=True` by default.

## Self-Check: PASSED

All created files exist on disk. All 4 commits verified in git log:
- `2ed27ab3` feat(56-07): create SwarmWriterAgent with batch asyncpg insert + DLQ
- `b8b9b961` feat(56-07): create SwarmOrchestratorComputeAgent with two-phase signal processing
- `7efeb3c8` feat(56-07): add systemd units for swarm orchestrator + writer
- `39ff989c` style(56-07): lint + black fixes for swarm services

6/6 tests pass. Import verification passed. Ruff reports no errors.
