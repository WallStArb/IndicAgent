# Gotchas & Rare Pitfalls

**Version:** 2.9
**Status:** current
**Last Updated:** 2026-06-16

Real issues that burned once — reference when touching the relevant area. Add here when you get burned.

## asyncpg

- **JSONB**: asyncpg returns `dict` directly — no `json.loads()`. Pass dicts for jsonb columns — never `json.dumps()`.
- **Timestamps**: asyncpg returns `datetime` objects, not strings.
- **UUIDs**: always `str()` before JSON/Kafka serialization.
- **LEFT JOIN NULL trap**: `dict.get(key, default)` fails when a LEFT JOIN produces a row where the key exists but is NULL — use `val if (val := row.get(key)) is not None else default`.
- **`conn.fetch()` must be consumed inside the context manager block**: assigning outside `async with get_connection()` risks `NameError` if `fetch()` raises.
- **`get_connection()` test mocks**: returns an async context manager, not a coroutine — mock with `MagicMock(side_effect=async_cm_func)` not `AsyncMock`. `AsyncMock` wraps the return in a coroutine and breaks `async with`.

## Database

- **TimescaleDB migration**: Never use pg_dump/restore for hypertables — chunks do not restore cleanly. Use raw volume copy: `docker run --rm -v old-vol:/src:ro -v new-vol:/dst alpine sh -c "cd /src && cp -a . /dst/"`. Also: `pg_dump` with `2>&1` corrupts `--Fc` binary output — always redirect stderr separately.
- **Disable compression order**: Must `SELECT decompress_chunk(...)` on all compressed chunks BEFORE `ALTER TABLE SET (timescaledb.compress = false)` — the ALTER fails if any chunk is still compressed.

See `docs/operations/operations-database.md` for query/schema gotchas. `instruments.symbol` = base symbol, contract code lives in `contract_details`.

## Redpanda / Kafka

- **`KafkaProducerClient.publish()` kwarg is `msg=`** — not `value=`. Wrong kwarg silently fails at flush.
- **Topic naming**: dots only (not colons). Always via `src/core/stream_keys.py`.
- **`INDICAGENT_ENV` consistency**: mixed env prefixes → services subscribe to different topics → zero data flow.

## structlog

- **`event` kwarg collision**: Never pass `event=<value>` as keyword — use `signal=`, `payload=`, `data=` instead.

## BaseWriterAgent

- **`_parse_payload` return contract**: `None` triggers `_maybe_route_to_dlq` on the whole payload. For per-signal validation failures return `[]` (all-invalid) not `None`, to prevent double-DLQ. Reserve `None` for truly empty/unparseable payloads.

## CircuitBreaker

`src/observability/circuit_breaker.py`: `record_failure()` opens the breaker but `OPEN→HALF_OPEN` recovery only fires inside `call()`. For manual tracking outside `call()`, use `allow_request()` (time-based OPEN→HALF_OPEN check) and `record_success()` (resets failures, closes from HALF_OPEN).

## I7 Plugin Feature Access

- **Tier sub-dicts in `plugin_input`**: All I7 plugins read features via `frames.get("i1")`, `frames.get("smc")`, etc. (tier-keyed sub-dicts). If `run_i7_complete()` (or any caller) only provides a flat `"features"` key, ALL plugins construct an empty features dict and return `no_signal()` on every bar. Zero signals, zero errors, completely silent. Any change to how `plugin_input` is constructed MUST verify tier sub-dicts are present.

## Historical Backfill

ContFuture (`continuous=True`) hangs on multi-year requests — use named contracts with `--days 364` or `production/scripts/fetch_1d_bars.py` which chunks automatically.

## Lifecycle Replay

`lifecycle_replay.py` may hit PostgreSQL's 32,767 query argument limit on large (symbol, timeframe) pairs. Re-run picks up where it left off (skips resolved signals).

## Testing

- **Async mock gotcha**: `AsyncMock` with instance-level `__aiter__` silently yields 0 iterations — Python dunder lookup is on the type. Define `__aiter__` at class level in a real class when mocking async iterables (e.g., AIOKafkaConsumer).
- **Mock gotcha**: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0.
- **Service test `__new__` pattern**: `tests/unit/service_tests/` uses `ServiceClass.__new__(ServiceClass)` to bypass `__init__`. Any new instance attribute added in `__init__` must also be manually set in the test — otherwise service silently fails mid-test with a misleading error.
- **ServiceSpec fields in tests**: `ServiceSpec(unit, metrics_port, lag_threshold_messages, dag_order, market_hours_only)` — check `services/service_auditor_agent.py` for current fields before constructing test fixtures.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.

## Observability / Metrics

- **Two-tier OTel metric pattern**: `src/observability/metrics.py` is for shared/cross-cutting metrics (shadow promotion stats, persistence latency, circuit breaker state). Service-local counters (`_COMPUTE_CYCLES`, `_BARS_WRITTEN`, etc.) belong inline in the service file using `_xxx_meter = _otel_metrics.get_meter("indicagent")`. Do not add service-local counters to `metrics.py`; do not mix both patterns in the same file.

## Systemd

- **Watchdog discipline**: Only add `WatchdogSec` + `NotifyAccess` to unit files if the Python service sends `sd_notify("WATCHDOG=1")` heartbeats. Current agents do NOT implement sd_notify — do not add watchdog settings to new unit files.
- **`PYTHONUNBUFFERED=1` required** in all systemd service unit files — without it, Python buffers stdout and journald sees nothing even from print().

## Tooling

- **GSD phase directory padding**: `gsd-sdk` returns `phase_dir` without zero-padding (e.g., `67-observability-alerting-automation`) but actual directories use padded names (`067-*`). If init returns `plan_count: 0` but plan files exist, check both directory variants.

## Resolved (Historical Reference)

- **CIS weights column mismatch (fixed Phase 091):** `_load_cis_weights` was querying the `weights` JSONB column (always `{}`); actual learned weights live in `trend_w`/`momentum_w`/etc. columns. Fixed to read individual columns scoped to `asset_cluster='global' AND timeframe='global'`.
