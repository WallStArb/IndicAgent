# Gotchas & Rare Pitfalls

**Version:** 2.12
**Status:** current
**Last Updated:** 2026-07-27

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
- **Migration numbering**: always `ls production/migrations/ | sort -V | tail -3` to confirm the actual current max before assigning a new number — a doc's claimed "next migration" can be stale if a migration landed without every cross-reference being updated.
- **Hypertables don't support `CREATE INDEX CONCURRENTLY` or `ADD CONSTRAINT ... USING INDEX`** (confirmed on TimescaleDB 2.27.1): both error outright ("hypertables do not support concurrent index creation" / "...adding a constraint using an existing index"). A migration that drops an old unique constraint and expects to replace it with a concurrently-built index will fail the build step but the drop can still succeed if sequenced naively — always build-and-verify the replacement index first (`SELECT 1 FROM pg_indexes WHERE indexname = '...'` inside a `DO` block), then drop the old constraint, never the reverse. Converting a `UNIQUE` constraint to a declared `PRIMARY KEY` on a live hypertable therefore requires a full blocking index rebuild (no zero-downtime path exists) — usually not worth it since `NOT NULL` + `UNIQUE` is functionally equivalent to a PK for dedup/`ON CONFLICT` purposes.
- **Compressed chunks make `UPDATE` cost nothing like a `SELECT`/`EXPLAIN` would predict** (todo 149, `market_data_ohlcv`, 248/250 chunks compressed): any mutating row in a compressed chunk forces decompress-then-modify, and a correlated `EXISTS`/`IN` subquery driven from the large source table (not the small known-target population) can silently balloon into a near-full-table scan. A read-only test is not evidence the write is cheap. Fix pattern: drive joins from the small target set, add a literal time-range bound when the target population is fixed, and `decompress_chunk()` the affected chunks first — neither alone was sufficient in practice.
- **High chunk count makes per-row `UPDATE`/`DELETE` pay a per-execution chunk-routing tax, invisible to `EXPLAIN` on a single row** (todo 161, `alpha_frames`, 1034 chunks): measured 29 rows/sec writing through the hypertable vs. 10,423 rows/sec (358x) writing the identical rows directly to their resolved `_timescaledb_internal.<chunk>` table, on the same connection. `EXPLAIN ANALYZE` showed 0.86ms single-row execution — the ~34ms/row gap was TimescaleDB's runtime chunk-exclusion overhead, paid on every execution regardless of asyncpg prepared-statement reuse across a batch. Not disk I/O (confirm via `iostat -x 1`, should show near-0% util) or lock contention (confirm via `pg_stat_activity.wait_event` — empty means on-CPU, not waiting). Reusable fix pattern: `services/counterfactual_tracker.py`'s `_load_chunk_index`/`_route_chunk` (fetch `timescaledb_information.chunks`' ranges once per run, binary-search each row's target chunk, write directly to it). Full investigation method: `docs/foundation/performance-investigation-sop.md`.

- **A killed Python asyncpg client doesn't always close its server-side backend connection**: check `pg_stat_activity` for a backend still `active` with an old `xact_start` well after the owning process is confirmed dead (`ps -p <pid>` returns nothing) — don't assume the kill rolled back the transaction. `SELECT pg_terminate_backend(<pid>)` it directly.
- **TimescaleDB runs in Docker (`timescaledb` container)**: `pg_stat_activity.client_addr` shows the docker bridge gateway (`172.19.0.1`), not a per-host-process identifier — correlate connections to a host PID via the backend PID / connection timing, never `client_addr`.
- **A compression policy job can report `last_run_status = 'Success'` while compressing zero chunks** (found 2026-08-02, `alpha_events`/`ensemble_alpha`, todo 233): both had `compress_after` policies scheduled every 12h with 57/57 successful runs logged in `timescaledb_information.job_stats`, yet 0 of 81 chunks compressed on either table despite most chunks being years past the compression threshold. A direct `CALL run_job(<job_id>)` (or manual `compress_chunk()`) fixed it instantly with no errors — the compression mechanism itself was fine, only the background-scheduler-triggered path was a silent no-op. Don't trust `job_stats.last_run_status` as proof a compression policy is doing anything; periodically check `timescaledb_information.chunks` grouped by `hypertable_name, is_compressed` instead. Root cause not yet diagnosed (todo 233).

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

ContFuture (`continuous=True`) hangs on multi-year requests — use named contracts with `--days 364` or `scripts/infrastructure/backfill/infrastructure_fetch_htf_bars.py` which chunks automatically.

## Lifecycle Replay

`lifecycle_replay.py` may hit PostgreSQL's 32,767 query argument limit on large (symbol, timeframe) pairs. Re-run picks up where it left off (skips resolved signals).

## Testing

- **Async mock gotcha**: `AsyncMock` with instance-level `__aiter__` silently yields 0 iterations — Python dunder lookup is on the type. Define `__aiter__` at class level in a real class when mocking async iterables (e.g., `KafkaConsumerClient.messages()`).
- **Mock gotcha**: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0.
- **Service test `__new__` pattern**: `tests/unit/service_tests/` uses `ServiceClass.__new__(ServiceClass)` to bypass `__init__`. Any new instance attribute added in `__init__` must also be manually set in the test — otherwise service silently fails mid-test with a misleading error.
- **ServiceSpec fields in tests**: `ServiceSpec(unit, metrics_port, lag_threshold_messages, dag_order, market_hours_only)` — check `services/service_auditor.py` for current fields before constructing test fixtures.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.
- **Integration tests can clobber a committed corpus manifest**: any `tests/integration/` suite that exercises a `BaseBatch` service (e.g. `-k cross_sectional_spread`) writes real `.planning/corpus_manifests/<service>.json` files as a side effect; running the suite after a real production run overwrites that manifest with synthetic test data. `git checkout -- .planning/corpus_manifests/<file>.json` to restore; this is expected test-fixture behavior, not corruption.

## Observability / Metrics

- **Two-tier OTel metric pattern**: `src/observability/metrics.py` is for shared/cross-cutting metrics (shadow promotion stats, persistence latency, circuit breaker state). Service-local counters (`_COMPUTE_CYCLES`, `_BARS_WRITTEN`, etc.) belong inline in the service file using `_xxx_meter = _otel_metrics.get_meter("indicagent")`. Do not add service-local counters to `metrics.py`; do not mix both patterns in the same file.

## Systemd

- **Watchdog discipline**: Only add `WatchdogSec` + `NotifyAccess` to unit files if the Python service sends `sd_notify("WATCHDOG=1")` heartbeats. Current agents do NOT implement sd_notify — do not add watchdog settings to new unit files.
- **`PYTHONUNBUFFERED=1` required** in all systemd service unit files — without it, Python buffers stdout and journald sees nothing even from print().

## Tooling

- **`py-spy` isn't on the default `sudo.ws` PATH**: use the full path, e.g. `echo '<pw>' | /usr/bin/sudo.ws -S /home/bg/.local/bin/py-spy dump --pid <pid>`.
- **GSD phase directory padding**: `gsd-sdk` returns `phase_dir` without zero-padding (e.g., `67-observability-alerting-automation`) but actual directories use padded names (`067-*`). If init returns `plan_count: 0` but plan files exist, check both directory variants.
- **`gsd-sdk query roadmap.annotate-dependencies` can report success without writing anything**: for phases created via `phase.insert` (decimal/INSERTED phases), it may return `"updated": false` with a correct wave count while ROADMAP.md's `Plans:` section still shows the `- [ ] TBD` placeholder. Verify the ROADMAP.md section directly after running it; manually write the wave/plan breakdown if the placeholder is still there.
- **Pre-commit runs 8 automated checks, including glossary enforcement**: a commit can fail with "glossary violation" because a changed file uses a term banned in `docs/foundation/glossary.md` in place of its canonical replacement — not a broken hook. Fix the term, don't bypass with `--no-verify`.
- **GSD worktree executors don't inherit gitignored `.venv`**: a fresh `git worktree add` has no `.venv`, so `.venv/bin/ruff`/`black`/`pytest` don't exist and the pre-commit hook's lint/format checks fail with "not found" on the first commit attempt. Fix: `ln -s <primary-checkout-path>/.venv .venv` from the worktree root before committing (the symlink is itself gitignored, won't be committed). Don't bypass with `--no-verify`.
- **Worktree isolation is unsafe for a GSD plan whose real deliverable is gitignored** (`logs/`, `.planning/corpus_manifests/*.json`): the worktree is force-removed after merge, silently destroying anything not committed. Route such plans through sequential (non-worktree) execution instead.

## Git / Concurrent Sessions

- **Isolated commits when concurrent work is suspected**: create a detached-HEAD scratch worktree off `origin/main` (`git worktree add <tmp-dir> origin/main --detach`), copy in just the specific files to change, commit, push, then `git worktree remove --force`. Never commit directly in the primary checkout if `git status` shows unexpected uncommitted files — that's another session's in-progress work.
- **`git push origin HEAD:main` from a detached-HEAD worktree does NOT fast-forward the primary checkout's local `main`** — its `git log -1` can go stale relative to `origin/main` after repeated pushes. Use `git fetch origin main && git log origin/main -1` as ground truth, not the primary checkout's local branch.

## Resolved (Historical Reference)

- **CIS weights column mismatch (fixed Phase 091):** `_load_cis_weights` was querying the `weights` JSONB column (always `{}`); actual learned weights live in `trend_w`/`momentum_w`/etc. columns. Fixed to read individual columns scoped to `asset_cluster='global' AND timeframe='global'`.
- **v2.x Signal Ledger schema (archived, no live consumer as of 2026-07-02):** `signal_schema_version` constant lives in `src/intelligence/trading/signal_schema.py`. `entry_type` values: `at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`. Status strings (raw, no enum): `"pending"`, `"active"`, `"regime_suppressed"`, `"expired"`. `signal_computed_at` is nullable — always `COALESCE(signal_computed_at, timestamp)`.
