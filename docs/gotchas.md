# Gotchas

Rare pitfalls that aren't obvious from reading the code. Add here when you get burned.

## asyncpg

- **JSONB**: asyncpg returns `dict` directly — no `json.loads()`. Pass dicts for jsonb columns — never `json.dumps()`.
- **Timestamps**: asyncpg returns `datetime` objects, not strings.
- **UUIDs**: always `str()` before JSON/Kafka serialization.
- **LEFT JOIN NULL trap**: `dict.get(key, default)` fails when a LEFT JOIN produces a row where the key exists but is NULL — use `val if (val := row.get(key)) is not None else default`.
- **`conn.fetch()` must be consumed inside the context manager block**: assigning outside `async with get_connection()` risks `NameError` if `fetch()` raises.
- **`get_connection()` test mocks**: returns an async context manager, not a coroutine — mock with `MagicMock(side_effect=async_cm_func)` not `AsyncMock`. `AsyncMock` wraps the return in a coroutine and breaks `async with`.

## TimescaleDB

See `docs/operations/timescaledb-gotchas.md` for query/schema gotchas. `instruments.symbol` = base symbol, contract code lives in `contract_details`.

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

- **Tier sub-dicts in `plugin_input`**: Phase 112-04 migrated all I7 plugins to read features via `frames.get("i1")`, `frames.get("smc")`, etc. (tier-keyed sub-dicts). If `run_i7_complete()` (or any caller) only provides a flat `"features"` key, ALL plugins construct an empty features dict and return `no_signal()` on every bar. Zero signals, zero errors, completely silent. Any change to how `plugin_input` is constructed MUST verify tier sub-dicts are present.

## Historical Backfill

ContFuture (`continuous=True`) hangs on multi-year requests — use named contracts with `--days 364` or `production/scripts/backfill_1d.py` which chunks automatically.

## Lifecycle Replay

`lifecycle_replay.py` may hit PostgreSQL's 32,767 query argument limit on large (symbol, timeframe) pairs. Re-run picks up where it left off (skips resolved signals).
