---
phase: 071-base-agent-infrastructure-alignment
plan: 04
status: complete
completed: "2026-04-14"
commits:
  - ff61601f feat(071-04): add default _report_consumer_lag() to BaseAgent with cached metric
  - 7d96369c feat(071-04): override _report_consumer_lag() in BaseWriterAgent for buffer depth
  - c526305a refactor(071-04): remove all manual _report_consumer_lag() overrides from agents
---

# Summary: Default _report_consumer_lag() in BaseAgent — Boilerplate Eliminated

## What Was Done

Implemented Change 3 from the design doc: BaseAgent now provides a working default `_report_consumer_lag()` that emits `PERSISTENCE_CONSUMER_LAG` with the agent name. BaseWriterAgent overrides it to report buffer depth. All 17 manual overrides removed from agent files.

### Task 1: BaseAgent default (commit ff61601f)
- Added `from src.observability.metrics import PERSISTENCE_CONSUMER_LAG` to `src/core/agent/base.py`
- Cached labeled Prometheus child at `__init__` time: `self._consumer_lag_gauge = PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name)`
- Replaced the no-op `_report_consumer_lag()` with a working default that loops until `_stop_event`, sets gauge to 0, sleeps 15s

### Task 2: BaseWriterAgent buffer-depth override (commit 7d96369c)
- Added import and `asyncio` to `src/core/agent/base_writer.py`
- Added `_report_consumer_lag()` override that reports `len(self._buffer)` — actual unflushed record count

### Task 3: Remove all manual overrides (commit c526305a)
17 agent files cleaned:

| File | Action |
|------|--------|
| ai_narrative_agent.py | Import + method removed |
| bar_aggregator_agent.py | Import + method removed |
| bar_auditor_agent.py | Import removed from shared import, method removed |
| contract_metadata_writer_agent.py | Import + method removed |
| cross_asset_service.py | Removed from `counter, gauge` import, method removed |
| feature_snapshot_writer_agent.py | Method removed; import KEPT (used in `_flush()` post-flush metric) |
| intelligence_pipeline_agent.py | Removed from block import, method removed |
| lifecycle_writer_agent.py | Removed from block import, unused `_consumer_lag` cache removed, method removed |
| parity_auditor_agent.py | Removed from block import, method removed |
| roll_compute_agent.py | Import + method removed |
| service_auditor_agent.py | Removed from shared import, method removed |
| signal_auditor_agent.py | Import + method removed |
| signal_metrics_compute_agent.py | Import + method removed |
| signal_metrics_writer_agent.py | Import + method removed |
| signal_tracker_compute_agent.py | No-op method removed (had no import) |
| signal_writer_agent.py | Removed from block import, unused `_consumer_lag` cache removed, method removed |
| swarm_orchestrator_agent.py | Import + method removed |

## Decisions

- **feature_snapshot_writer_agent.py**: Inherits `BaseAgent` (not `BaseWriterAgent`), so buffer-depth reporting is not auto-provided by base class. The `_flush()` method already emits `PERSISTENCE_CONSUMER_LAG` post-flush (always 0 after buffer clear); periodic override removed per plan. Import retained since `_flush()` uses it.
- **lifecycle_writer_agent / signal_writer_agent**: Both inherit `BaseWriterAgent` — their manual buffer-depth overrides were redundant; removed. The unused `self._consumer_lag` cached gauge was also removed.
- **signal_tracker_compute_agent**: Had a no-op override (just `asyncio.sleep(15)`, no metric) — removed cleanly; inherits BaseAgent default.

## Verification

```
$ grep -l "async def _report_consumer_lag" services/*.py | grep -v "_archived" | grep -v "llm_writer_service.py"
# (no output — CLEAN)
```

- Unit tests: 2997 passed (82 pre-existing failures unrelated to this plan)
- Ruff: 99 auto-fixed (unused imports from removed overrides), 337 pre-existing E501 violations
