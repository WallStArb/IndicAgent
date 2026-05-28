# Gotchas & Rare Pitfalls

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-22
Moved from CLAUDE.md to reduce per-turn token cost. These are real issues that burned once — reference when touching the relevant area.

## Database

- **TimescaleDB migration**: Never use pg_dump/restore for hypertables — chunks do not restore cleanly. Use raw volume copy: `docker run --rm -v old-vol:/src:ro -v new-vol:/dst alpine sh -c "cd /src && cp -a . /dst/"`. Also: `pg_dump` with `2>&1` corrupts `--Fc` binary output — always redirect stderr separately.
- **Disable compression order**: Must `SELECT decompress_chunk(...)` on all compressed chunks BEFORE `ALTER TABLE SET (timescaledb.compress = false)` — the ALTER fails if any chunk is still compressed.

## Resolved (Historical Reference)

- **CIS weights column mismatch (fixed Phase 091):** `_load_cis_weights` was querying the `weights` JSONB column (always `{}`); actual learned weights live in `trend_w`/`momentum_w`/etc. columns. Fixed to read individual columns scoped to `asset_cluster='global' AND timeframe='global'`.

## Testing

- **Async mock gotcha**: `AsyncMock` with instance-level `__aiter__` silently yields 0 iterations — Python dunder lookup is on the type. Define `__aiter__` at class level in a real class when mocking async iterables (e.g., AIOKafkaConsumer).
- **Mock gotcha**: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0.
- **Service test `__new__` pattern**: `tests/unit/service_tests/` uses `ServiceClass.__new__(ServiceClass)` to bypass `__init__`. Any new instance attribute added in `__init__` must also be manually set in test (e.g., `svc._regime_cache = defaultdict(dict)`), otherwise service silently fails mid-test with a misleading error.
- **ServiceSpec fields in tests**: `ServiceSpec(unit, metrics_port, lag_threshold_messages, dag_order, market_hours_only)` — check `services/service_auditor_agent.py` for current fields before constructing test fixtures.

## Observability / Metrics

- **Two-tier OTel metric pattern**: `src/observability/metrics.py` is for shared/cross-cutting metrics referenced by multiple services (shadow promotion stats, persistence latency, circuit breaker state, etc.). Service-local operational metrics (`_COMPUTE_CYCLES`, `_BARS_WRITTEN`, etc.) belong inline in the service file using a private `_xxx_meter = _otel_metrics.get_meter("indicagent")`. All meters share the same underlying `MeterProvider` so there is no functional difference — the distinction is purely organisational. Do not add service-local counters to `metrics.py`, and do not mix both patterns in the same file.

## Tooling

- **GSD phase directory padding**: `gsd-sdk` returns `phase_dir` without zero-padding (e.g., `67-observability-alerting-automation`) but actual directories use padded names (`067-*`). If init returns `plan_count: 0` but plan files exist, check both directory variants.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.

## Systemd

- **Systemd watchdog discipline**: Only add `WatchdogSec` + `NotifyAccess` to unit files if the Python service sends `sd_notify("WATCHDOG=1")` heartbeats. Current agents do NOT implement sd_notify — do not add watchdog settings to new unit files.
- **`PYTHONUNBUFFERED=1` required** in all systemd service unit files — without it, Python buffers stdout and journald sees nothing even from print().
