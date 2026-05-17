# Plan 086-03 Summary

## What Was Built

Added `last_processed_at: datetime | None` property to `BaseAgent`, set via wall-clock UTC in `_record_message_consumed` alongside the existing monotonic `_last_message_ts` used by `_stall_watchdog`. Wired a Prometheus-driven stall detector into `service_auditor_agent._prometheus_check_loop` that queries `agent_last_message_timestamp_seconds`, detects agents idle for more than 360 seconds (300s watchdog + 60s grace), and restarts them via the existing `_restart_service_by_unit` helper.

## Tasks Completed

- [x] Task 1: Add `last_processed_at` property to BaseAgent - property and wall-clock setter in `_record_message_consumed`, monotonic `_last_message_ts` untouched
- [x] Task 2: Add Prometheus-driven stall detection to service_auditor - `_fetch_stalled_agents` method + wiring in `_prometheus_check_loop` + `_STALL_THRESHOLD_SECONDS = 360`

## Key Changes

- `src/core/agent/base.py`: Added top-level `from datetime import UTC, datetime`; `self._last_processed_at: datetime | None = None` in `__init__`; `last_processed_at` property; `self._last_processed_at = datetime.now(UTC)` in `_record_message_consumed` between monotonic assignment and OTel set call; removed now-redundant local datetime imports from `_send_to_dlq` and `_send_alert`
- `services/service_auditor_agent.py`: Added `import time`; added `_STALL_THRESHOLD_SECONDS: int = 360` constant near `_LAG_THRESHOLDS`; added `_fetch_stalled_agents` async method; wired stall restart loop at end of `_prometheus_check_loop` try block

## OTel Label Key Confirmed

The label key for `agent_last_message_timestamp_seconds` is `"agent"` (not `"agent_id"`). Confirmed from `BaseAgent.__init__` line 118: `self._last_msg_ts_attrs = {"agent": name}`. The `_fetch_stalled_agents` method uses `r["metric"].get("agent", "")` consistently.

## Cold-Start False-Positive Guard

Chose: skip restart when `ts <= 0`. This is the simplest mechanism - `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` is only set when `_record_message_consumed` is called, so a freshly-started agent that has not yet processed any messages will either have no metric series in Prometheus or a zero value from default initialization. The `ts <= 0` guard handles both cases without requiring any additional systemd uptime queries.

Alternative considered: query `systemctl show <unit> --property=ActiveEnterTimestamp` to compare uptime vs stall threshold. Rejected because it adds a subprocess per stalled agent on every 15s cycle; the `ts <= 0` guard is simpler and covers the same scenario with no I/O overhead.

## Recommended Follow-Up Integration Test

A unit test mocking `_query_prometheus` and `_restart_service_by_unit` to assert restart is requested when `ts` is stale:

```python
async def test_fetch_stalled_agents_triggers_restart():
    agent = ServiceAuditorAgent.__new__(ServiceAuditorAgent)
    # inject a stale timestamp (now - 400s)
    stale_ts = time.time() - 400
    agent._query_prometheus = AsyncMock(return_value=[
        {"metric": {"agent": "intelligence_pipeline_agent"}, "value": [0, str(stale_ts)]}
    ])
    agent._restart_service_by_unit = AsyncMock()
    stalled = await agent._fetch_stalled_agents()
    assert "indicagent-intelligence-pipeline" in stalled
```

## Verification

- Tests pass: yes (3260 passed, 1 skipped)
- Lint clean: yes (ruff + black both clean, pre-commit hooks passed)

## Commits

- `3f260401`: feat(086-03): add last_processed_at property to BaseAgent
- `aeb57f4d`: feat(086-03): add Prometheus-driven stall detection to service_auditor

## Self-Check: PASSED

- `src/core/agent/base.py` contains `from datetime import UTC, datetime` - FOUND
- `src/core/agent/base.py` contains `self._last_processed_at: datetime | None = None` - FOUND
- `src/core/agent/base.py` contains `def last_processed_at` property - FOUND
- `src/core/agent/base.py` contains `self._last_processed_at = datetime.now(UTC)` - FOUND
- `services/service_auditor_agent.py` contains `_STALL_THRESHOLD_SECONDS: int = 360` - FOUND
- `services/service_auditor_agent.py` contains `async def _fetch_stalled_agents` - FOUND
- `services/service_auditor_agent.py` contains `agent_last_message_timestamp_seconds` - FOUND
- `services/service_auditor_agent.py` contains `service_auditor.stall_detected` - FOUND
- Commits 3f260401 and aeb57f4d exist in git log
