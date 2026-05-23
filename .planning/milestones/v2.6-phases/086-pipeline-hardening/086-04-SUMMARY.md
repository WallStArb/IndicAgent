# Plan 086-04 Summary

## What Was Built

Added `GET /health/system` to the existing health router in `src/api/routes/health.py`. The endpoint queries Prometheus at `http://localhost:9090/api/v1/query` for four metrics and aggregates them into a single machine-readable JSON response. Any individual query failure degrades only that field to its null/empty default; the endpoint always returns HTTP 200 with the full response shape intact.

## Tasks Completed

- [x] Task 1: Add /system Prometheus-aggregation route to health router

## Key Changes

- `src/api/routes/health.py`: Added `import aiohttp` and appended `@router.get("/system") async def system_health()` handler using `aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3))` with four independent try/except-wrapped Prometheus queries.

## Prometheus Metric Names Used (resolved from src/observability/metrics.py)

| Field | Metric Name | Label Key |
|-------|-------------|-----------|
| `consumer_lag` | `persistence_consumer_lag_records` | `agent_id` |
| `dlq_depth` | `agent_dlq_total` | (summed across all labels) |
| `signal_replay_unresolved` | `signal_replay_unresolved_gauge` | (scalar, first result) |
| `agent_heartbeats` | `agent_last_message_timestamp_seconds` | `agent` |

Note: `service_auditor_agent.py` queries `persistence_consumer_lag` (no `_records` suffix) at line 575 - this appears to be a pre-existing discrepancy. The canonical name in `src/observability/metrics.py` line 99 is `persistence_consumer_lag_records`, which this endpoint uses per plan instructions.

## Agent Label Key for agent_heartbeats

`"agent"` - confirmed from `src/core/agent/base.py` line 120: `self._last_msg_ts_attrs = {"agent": name}`. Values are ISO8601 UTC timestamps derived via `datetime.fromtimestamp(ts, tz=UTC).isoformat()`.

## Response Shape

```json
{
  "timestamp": "2026-05-17T19:22:00+00:00",
  "consumer_lag": {"bar_writer_agent": 0, "feature_writer_agent": 3},
  "dlq_depth": 0,
  "signal_replay_unresolved": 12,
  "agent_heartbeats": {
    "bar_writer_agent": "2026-05-17T19:21:58+00:00",
    "intelligence_pipeline_agent": "2026-05-17T19:21:59+00:00"
  }
}
```

Degraded (Prometheus unreachable):
```json
{
  "timestamp": "2026-05-17T19:22:00+00:00",
  "consumer_lag": {},
  "dlq_depth": null,
  "signal_replay_unresolved": null,
  "agent_heartbeats": {}
}
```

## Endpoint Location

Registered at `GET /health/system` (router mounted at `/health` prefix in `main.py` line 131).

## Verification

- Tests pass: yes (3260 passed, 1 skipped)
- Lint clean: yes (ruff + black both pass)

## Self-Check: PASSED

- `src/api/routes/health.py` exists and contains `@router.get("/system")`: PASS
- Commit `8c2fa11d` exists: PASS
- All acceptance criteria grep checks pass: PASS
