# Gotchas & Rare Pitfalls

**Version:** 2.17
**Status:** current
**Last Updated:** 2026-09-27 (session-learnings pass from the todo 449 backfill audit: backfill_status `tf` column and partial intraday seed, calendar-grid "stored N bars" counts, hypertable_size() vs pg_total_relation_size, ugrep grep alias)

Real issues that burned once — reference when touching the relevant area. Add here when you get burned.

## asyncpg

- **JSONB**: asyncpg returns `dict` directly — no `json.loads()`. Pass dicts for jsonb columns — never `json.dumps()`.
- **Timestamps**: asyncpg returns `datetime` objects, not strings.
- **UUIDs**: always `str()` before JSON/Kafka serialization.
- **LEFT JOIN NULL trap**: `dict.get(key, default)` fails when a LEFT JOIN produces a row where the key exists but is NULL — use `val if (val := row.get(key)) is not None else default`.
- **`conn.fetch()` must be consumed inside the context manager block**: assigning outside `async with get_connection()` risks `NameError` if `fetch()` raises.
- **`get_connection()` test mocks**: returns an async context manager, not a coroutine — mock with `MagicMock(side_effect=async_cm_func)` not `AsyncMock`. `AsyncMock` wraps the return in a coroutine and breaks `async with`.
- **A chunked-insert helper called inside an open `conn.transaction()` must take that same `conn`, never `pool.acquire()` a second connection**: if the transaction's own uncommitted DELETE (or any write) touches the same PK rows the chunk INSERT targets, Postgres blocks the INSERT until the DELETE's transaction resolves (`XactLockTableWait`) — but if the DELETE's transaction is being driven by the same sequential async code that's `await`ing the chunk INSERT, neither side can ever resolve. Self-deadlock within one process, broken only by `statement_timeout` (server default 30min). Confirmed live 2026-08-30 in `alpha_publisher.py`'s `_flush_chunk` (todo 351): it acquired a separate `wconn` for its `INSERT ... ON CONFLICT DO NOTHING`, whose target PKs (`event_id` encodes `weight_version`) exactly matched the rows an open `DELETE FROM alpha_events WHERE weight_version = $1` on `conn` had just removed — two consecutive production runs hung for exactly ~30min and wrote zero new rows before this was fixed. `ensemble_trainer.py` and `ic_engine.py`'s equivalent full-replace paths already thread one connection through DELETE+INSERT correctly; `alpha_publisher.py` was the sole outlier.

## Database

- **TimescaleDB migration**: Never use pg_dump/restore for hypertables — chunks do not restore cleanly. Use raw volume copy: `docker run --rm -v old-vol:/src:ro -v new-vol:/dst alpine sh -c "cd /src && cp -a . /dst/"`. Also: `pg_dump` with `2>&1` corrupts `--Fc` binary output — always redirect stderr separately.
- **psycopg2 → psycopg (psycopg3) migration (2026-08-03), two silent behavior changes**: (1) a bare `with conn:` on an already-open connection **closes** it on exit under psycopg — psycopg2's `with conn:` only committed/rolled back and left it open. Any caller-owned connection reused across multiple calls (e.g. a per-feature loop calling the same helper many times on one connection) will die after the first call. Fix: `with conn.transaction():` — commits/rolls back identically, never closes (confirmed empirically). (2) `conn.commit()`/`cur.commit()` with no explicit offsets/args commits whatever the driver's *last actual fetch/position* was — it does **not** pick up a prior bare `seek()`/state change with nothing else in between. Concretely bit us in `KafkaConsumerClient.skip_lag_if_needed()` (unrelated confluent-kafka API, same root shape): `commit()` right after `seek(OFFSET_END)` silently committed the stale pre-seek offset. Always resolve the target explicitly and pass it, don't rely on implicit "current position." `execute_values`/`execute_batch` have no direct psycopg3 equivalent — `execute_batch(cur, sql, rows)` → `cur.executemany(sql, rows)` (psycopg 3.1+ batches this internally); `execute_values`' single UPDATE-FROM-(VALUES) statement has no drop-in replacement, rewrite as a plain per-row `UPDATE ... WHERE <composite key> = %s` and call via `executemany()`. `psycopg2.extras.RealDictCursor` → `conn.cursor(row_factory=psycopg.rows.dict_row)` (works combined with a named/server-side cursor too). `psycopg2.extras.register_uuid()` has no equivalent and isn't needed — psycopg adapts `uuid.UUID` natively. Named server-side cursors + `.itersize` chunked streaming (the OOM-prevention pattern in `ic_engine.py`) ported with zero API change — confirmed identical semantics.
- **Disable compression order**: Must `SELECT decompress_chunk(...)` on all compressed chunks BEFORE `ALTER TABLE SET (timescaledb.compress = false)` — the ALTER fails if any chunk is still compressed.
- **Migration numbering**: always `ls production/migrations/ | sort -V | tail -3` to confirm the actual current max before assigning a new number — a doc's claimed "next migration" can be stale if a migration landed without every cross-reference being updated.
- **Hypertables don't support `CREATE INDEX CONCURRENTLY` or `ADD CONSTRAINT ... USING INDEX`** (confirmed on TimescaleDB 2.27.1): both error outright ("hypertables do not support concurrent index creation" / "...adding a constraint using an existing index"). A migration that drops an old unique constraint and expects to replace it with a concurrently-built index will fail the build step but the drop can still succeed if sequenced naively — always build-and-verify the replacement index first (`SELECT 1 FROM pg_indexes WHERE indexname = '...'` inside a `DO` block), then drop the old constraint, never the reverse. Converting a `UNIQUE` constraint to a declared `PRIMARY KEY` on a live hypertable therefore requires a full blocking index rebuild (no zero-downtime path exists) — usually not worth it since `NOT NULL` + `UNIQUE` is functionally equivalent to a PK for dedup/`ON CONFLICT` purposes.
- **Compressed chunks make `UPDATE` cost nothing like a `SELECT`/`EXPLAIN` would predict** (todo 149, `market_data_ohlcv`, 248/250 chunks compressed): any mutating row in a compressed chunk forces decompress-then-modify, and a correlated `EXISTS`/`IN` subquery driven from the large source table (not the small known-target population) can silently balloon into a near-full-table scan. A read-only test is not evidence the write is cheap. Fix pattern: drive joins from the small target set, add a literal time-range bound when the target population is fixed, and `decompress_chunk()` the affected chunks first — neither alone was sufficient in practice.
- **High chunk count makes per-row `UPDATE`/`DELETE` pay a per-execution chunk-routing tax, invisible to `EXPLAIN` on a single row** (todo 161, `alpha_frames`, 1034 chunks): measured 29 rows/sec writing through the hypertable vs. 10,423 rows/sec (358x) writing the identical rows directly to their resolved `_timescaledb_internal.<chunk>` table, on the same connection. `EXPLAIN ANALYZE` showed 0.86ms single-row execution — the ~34ms/row gap was TimescaleDB's runtime chunk-exclusion overhead, paid on every execution regardless of asyncpg prepared-statement reuse across a batch. Not disk I/O (confirm via `iostat -x 1`, should show near-0% util) or lock contention (confirm via `pg_stat_activity.wait_event` — empty means on-CPU, not waiting). Reusable fix pattern: `services/counterfactual_tracker.py`'s `_load_chunk_index`/`_route_chunk` (fetch `timescaledb_information.chunks`' ranges once per run, binary-search each row's target chunk, write directly to it). Full investigation method: `docs/foundation/performance-investigation-sop.md`.
- **`pg_total_relation_size('market_data_ohlcv')` returns ~32 kB on a hypertable — size lives in the chunks**: use `hypertable_size('market_data_ohlcv')` and `timescaledb_information.chunks` for size and compression state.
- **`bar_ts = ANY(<array>)` does not chunk-exclude cleanly on a compressed hypertable, unlike `BETWEEN`** (todo 356, `feature_vectors`/`forward_returns`, 84-85/85 chunks compressed): `_compute_cross_sectional_tf`'s chunked fetch (`services/ic_engine.py`) took 95+ minutes and hadn't finished on the corpus's largest cross-sectional cell; `EXPLAIN (ANALYZE, BUFFERS)` showed the `ANY(<5000-element array>)` predicate expanding into a per-compressed-batch `OR`-chain of `_ts_meta_min_1`/`_ts_meta_max_1` range checks — one clause per array element, re-evaluated per batch (`O(batches × len(array))`) — instead of a single range exclusion. Fix: add a redundant `col BETWEEN array[0] AND array[-1]` predicate ahead of the `ANY()` clause when the array is a contiguous sorted slice (true here — `ts_chunk` is always a slice of an `ORDER BY ts` result). Measured 10,218ms → 315ms (~32x) on a representative chunk; correctness verified via matching row-count + order-sensitive checksum on real data.

- **A killed Python asyncpg client doesn't always close its server-side backend connection**: check `pg_stat_activity` for a backend still `active` with an old `xact_start` well after the owning process is confirmed dead (`ps -p <pid>` returns nothing) — don't assume the kill rolled back the transaction. `SELECT pg_terminate_backend(<pid>)` it directly.
- **`compressed_hypertable_write_session` (`services/_batch_utils.py`, hardened for `feature_vectors`/`feature_ic_scores` only) decompresses ALL compressed chunks of the whole table, not just the chunks a scoped write (e.g. `--symbols IHF`) will touch** — deliberate, incident-hardened design (2026-08-13/14), not a bug. Confirmed live 2026-09-22: a single-symbol `backfill_feature_factory.py --compute-only --symbols IHF` run took `AccessExclusiveLock` on ~40 `feature_vectors` chunks (plus their `compress_hyper_*` counterparts) for its whole decompress→write→recompress duration, blocking a concurrently-running `ensemble_trainer.py`'s unrelated read queries on the same table for ~10 minutes. Any write to either hardened table is a corpus-wide exclusive-lock operation regardless of how narrowly it's scoped — never run one concurrently with anything else that reads `feature_vectors`/`feature_ic_scores`, not just other writers.
- **TimescaleDB runs in Docker (`timescaledb` container)**: `pg_stat_activity.client_addr` shows the docker bridge gateway (`172.19.0.1`), not a per-host-process identifier — correlate connections to a host PID via the backend PID / connection timing, never `client_addr`.
- **A compression policy job can report `last_run_status = 'Success'` while compressing zero chunks** (found 2026-08-02, `alpha_events`/`ensemble_alpha`, todo 233): both had `compress_after` policies scheduled every 12h with 57/57 successful runs logged in `timescaledb_information.job_stats`, yet 0 of 81 chunks compressed on either table despite most chunks being years past the compression threshold. A direct `CALL run_job(<job_id>)` (or manual `compress_chunk()`) fixed it instantly with no errors — the compression mechanism itself was fine, only the background-scheduler-triggered path was a silent no-op. Don't trust `job_stats.last_run_status` as proof a compression policy is doing anything; periodically check `timescaledb_information.chunks` grouped by `hypertable_name, is_compressed` instead. Root cause not yet diagnosed (todo 233).

See `docs/operations/operations-database.md` for query/schema gotchas. `instruments.symbol` = base symbol, contract code lives in `contract_details`.

## Redpanda / Kafka

- **`KafkaProducerClient.publish()` kwarg is `msg=`** — not `value=`. Wrong kwarg silently fails at flush.
- **Topic naming**: dots only (not colons). Always via `src/core/stream_keys.py`.
- **`INDICAGENT_ENV` consistency**: mixed env prefixes → services subscribe to different topics → zero data flow.
- **`feature_vector_pipeline` subscribes to** `topic_market_bars` (1m) AND `topic_market_bars_htf` (HTF).

## structlog

- **`event` kwarg collision**: Never pass `event=<value>` as keyword — use `signal=`, `payload=`, `data=` instead.

## BaseWriter

- **`_parse_payload` return contract**: `None` triggers `_maybe_route_to_dlq` on the whole payload. For per-signal validation failures return `[]` (all-invalid) not `None`, to prevent double-DLQ. Reserve `None` for truly empty/unparseable payloads. (Moved from CLAUDE.md 2026-09-26; this is now the single statement.)
- **`BaseWriter.__init__` requires `name: str`** (non-optional): when removing `name=` from any writer, also update `BaseWriter.__init__` to accept `name: str | None = None`.

## CircuitBreaker

`src/observability/circuit_breaker.py`: `record_failure()` opens the breaker but `OPEN→HALF_OPEN` recovery only fires inside `call()`. For manual tracking outside `call()`, use `allow_request()` (time-based OPEN→HALF_OPEN check) and `record_success()` (resets failures, closes from HALF_OPEN).

## I7 Plugin Feature Access (v2.x, archived — no live consumer as of 2026-07-02)

- **Tier sub-dicts in `plugin_input`**: All I7 plugins read features via `frames.get("i1")`, `frames.get("smc")`, etc. (tier-keyed sub-dicts). If `run_i7_complete()` (or any caller) only provides a flat `"features"` key, ALL plugins construct an empty features dict and return `no_signal()` on every bar. Zero signals, zero errors, completely silent. Any change to how `plugin_input` is constructed MUST verify tier sub-dicts are present. The code (`src/intelligence/pipeline/{signal_processor,executor}.py`) still exists in the tree, but per CLAUDE.md the I1-I7 plugin tier has no live consumer — this gotcha applies if that code path is ever touched or revived, not to current production behavior.

## Historical Backfill

ContFuture (`continuous=True`) hangs on multi-year requests — use named contracts with `--days 364` or `scripts/infrastructure/backfill/infrastructure_fetch_htf_bars.py` which chunks automatically.
- **`backfill_status` column is `tf`, not `timeframe`** (differs from both `market_data_ohlcv` and `intelligence_features`), and its intraday rows cover only the old-universe subset until todo 449 closes — the 698 new names accrue row-by-row as they complete.
- **Backfill log lines "stored N bars" count calendar-grid cells, not real bars** (20y of 15m ≈ 700,555 = time slots); placeholders are flat carry-forward close with volume 0. Audit a symbol with its volume>0 count vs sessions × 26 (15m RTH) — healthy is ~99.6%.

**`detect_gaps()` reports large false-positive gap counts (hundreds of ranges) on 1h/15m/5m/1m for a symbol's earliest history.** `generate_session_slots()` expects a full extended-hours session from day one, but real IBKR extended-hours coverage ramps up over a symbol's first year (or the first days of a timeframe's retention window). Before treating a `detect_gaps()` count as a real problem, check whether every gap range falls near that (symbol, tf) pair's own `min(timestamp)`; if so it is benign ramp-up, not a connection-drop artifact.

## Corpus Pipeline

**`ops_corpus_pipeline_run.sh --from-step N` silently skips every step below N** —
a resumed run doesn't re-execute earlier writer steps, so it keeps consuming
whatever those steps last wrote, however stale. Concretely: `--from-step 5` skips
step 4 (`cross_sectional_regime_model.py`, sole writer of `market_regimes`) — a
same-session code fix to that step has zero effect on an already-running
`--from-step 5+` invocation. Grep the run's own log for `[skipped` markers before
assuming a live/resumed run reflects a recent upstream fix — don't infer it from
the `--from-step` value alone.

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
- **Label keys:** `agent_last_message_timestamp_seconds` and `PERSISTENCE_BATCH_LATENCY` use `agent_id` (query with `r["metric"].get("agent_id")`), not `agent`; `agent_crash_total` is the exception and uses `agent`.
- **API health router prefix is `/health`**, not `/api/health` (`/health/system`, `/health/database`, ...).
- **Oneshot `_agent.py` names kept on purpose:** `services/feature_validation_agent.py`, `hmm_training_agent.py`, `ml_training_agent.py`, `ml_signal_training_agent.py`.

## Systemd

- **Watchdog discipline**: Only add `WatchdogSec` + `NotifyAccess` to unit files if the Python service sends `sd_notify("WATCHDOG=1")` heartbeats. Current agents do NOT implement sd_notify — do not add watchdog settings to new unit files.
- **`PYTHONUNBUFFERED=1` required** in all systemd service unit files — without it, Python buffers stdout and journald sees nothing even from print().

## Tooling

- **`grep` on this box is ugrep**: patterns like `'^*'` error out ("invalid syntax") — escape the asterisk when filtering git output (`grep -v '^\*'`).
- **`py-spy` isn't on the default `sudo.ws` PATH**: use the full path, e.g. `echo '<pw>' | /usr/bin/sudo.ws -S /home/bg/.local/bin/py-spy dump --pid <pid>`.
- **`ps`'s `%CPU` column is a lifetime average, not current activity**: a multi-day `ic_engine.py` corpus run can look "stuck" by it long after heavy compute ended. Sample `/proc/<pid>/stat` `utime+stime` twice a few seconds apart for the instantaneous rate, or `py-spy dump --pid <pid>` for the actual stack (then confirm in `pg_stat_activity` whether the backend is executing or lock-waiting).
- **GSD phase directory padding**: `gsd-sdk` returns `phase_dir` without zero-padding (e.g., `67-observability-alerting-automation`) but actual directories use padded names (`067-*`). If init returns `plan_count: 0` but plan files exist, check both directory variants.
- **`gsd-sdk query roadmap.annotate-dependencies` can report success without writing anything**: for phases created via `phase.insert` (decimal/INSERTED phases), it may return `"updated": false` with a correct wave count while ROADMAP.md's `Plans:` section still shows the `- [ ] TBD` placeholder. Verify the ROADMAP.md section directly after running it; manually write the wave/plan breakdown if the placeholder is still there.
- **Pre-commit runs 9 automated checks (`tools/pre-commit.hook`), including glossary enforcement**: a commit can fail with "glossary violation" because a changed file uses a term banned in `docs/foundation/glossary.md` in place of its canonical replacement, not because the hook is broken. Fix the term, don't bypass with `--no-verify`.
- **GSD worktree executors don't inherit gitignored `.venv`**: a fresh `git worktree add` has no `.venv`, so `.venv/bin/ruff`/`black`/`pytest` don't exist and the pre-commit hook's lint/format checks fail with "not found" on the first commit attempt. Fix: `ln -s <primary-checkout-path>/.venv .venv` from the worktree root before committing (the symlink is itself gitignored, won't be committed). Don't bypass with `--no-verify`.
- **Worktree isolation is unsafe for a GSD plan whose real deliverable is gitignored** (`logs/`, `.planning/corpus_manifests/*.json`): the worktree is force-removed after merge, silently destroying anything not committed. Route such plans through sequential (non-worktree) execution instead.
- **A local `.git/hooks/pre-commit` check is not a real gate; only a CI job is**: `tools/pre-commit.hook` is opt-in per clone and `--no-verify` bypasses it. All 9 hook checks now have a matching `ci.yml` step. Before citing a hook check as "enforced," confirm it also has a `ci.yml` step.
- **A tool in `pyproject.toml`/`requirements.txt` but absent from `ci.yml` is a gap class of its own** (`vulture` and `[tool.mypy]` both sat configured but never run). Now wired: vulture blocks new findings against the frozen baseline in `tools/vulture_whitelist.py` (triage backlog: todo 309); mypy is report-only (`continue-on-error`) until it has a baseline mechanism (todo 311).
- **`pgrep -f` liveness checks must match a bare process/module name, not a path or flag-specific pattern**: `pgrep -f "services/regime_writer.py"` never matches the `-m services.regime_writer` invocation this project uses. A recurring bug class (three scripts had it).
- **`git commit -m "..."` with backticks or inline-code in the message breaks bash** (the shell interprets backtick-quoted text as command substitution before git ever sees it) — use `git commit -F <file>` for any message containing backtick-quoted code references, which most detailed commit messages in this codebase do.

## Git / Concurrent Sessions

- **Isolated commits when concurrent work is suspected**: create a detached-HEAD scratch worktree off `origin/main` (`git worktree add <tmp-dir> origin/main --detach`), copy in just the specific files to change, commit, push, then `git worktree remove --force`. Never commit directly in the primary checkout if `git status` shows unexpected uncommitted files — that's another session's in-progress work.
- **`git push origin HEAD:main` from a detached-HEAD worktree does NOT fast-forward the primary checkout's local `main`** — its `git log -1` can go stale relative to `origin/main` after repeated pushes. Use `git fetch origin main && git log origin/main -1` as ground truth, not the primary checkout's local branch.

## OHLCV prices are split-adjusted

`market_data_ohlcv` holds IBKR `TRADES` bars, which are split-adjusted back through history
(NVDA closes at 8.81 on 2020-06-01, when it traded near 350; AAPL at 108.94 on 2020-08-03, before
its 4:1 split). Returns and ratios are unaffected. Anything that depends on the absolute price
level at the time (option strikes, round-number levels, tick-size regimes, "price below $5"
filters) is wrong for every name that later split, unless it un-adjusts with a split history
first. The project holds no split history yet (found 2026-09-25, research architecture family 8).

## Tests must never append to D1 or spawn derivation against the live database

`bar_derivation` takes the latest observation per bar from D1 (`ohlcv_request`, `ohlcv_observation`), so a
fixture row a test appends on a real symbol and date becomes a canonical bar (27 rows on SPY 2024-01-02 to
01-04 would have stored close 100.5 for 472.65; found 2026-10-03). D1 was append-only then and those rows stayed;
the owner has since made D1 mutable (migration 438, 2026-10-03), so such rows are removable now, but the
exposure is the same until D2 reads them. D2 excludes requests whose caller starts with `test-`; point every
test that appends at `indicagent_test`. A unit test that drives `infrastructure_nightly_backfill.main()` must
patch every stage it calls (`_run_split_detect`, `_run_daily_stage`, `_prepare_grid_stage`, `_run_grid_stage`);
an unpatched stage spawns a real `bar_derivation --apply` against production. Todo 494 tracks the CI guard.

## Grants are invisible to unit tests

`bar_derivation_writer` had SELECT, INSERT, DELETE on `market_data_ohlcv`; the daily stage's
`INSERT ... ON CONFLICT DO UPDATE` needs UPDATE and every unit test passed while the first apply failed on
all symbols (migration 435). On a compressed hypertable grant at table level: a column grant propagates to
the compressed hypertable, which has no such columns. Cover a new write path with an integration test that
runs the real statement under the real role on `indicagent_test`.

## The integration baseline lags the migrations above its cutoff

`tests/integration/conftest.py` replays only migrations above `_BASELINE_MIGRATION_CUTOFF`, and its dump is
schema-only. Data seeded by a migration at or below the cutoff (APR rows, vocabulary, tags) is absent unless a
seed file carries it (`seed_config_*.sql`), and a migration numbered below the cutoff but written later (phase 185's
reserved 404 to 408) never reaches the test database. Check this before trusting a green integration run
(todo 495).

## Moved from CLAUDE.md (5.60.0 trim): backfill and IBKR

- Historical backfill: `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` (default `--client-id 40`; provider uses 35; IDs stay <= `_MAX_CLIENT_ID=50` in `ibkr.py`). Every IBKR history fetch takes the `ibkr_history_stream` lease (`src/core/resource_lease.py`, CI: `test_ibkr_history_lease_boundary.py`): one stream at a time, the nightly at priority tier, chains and manual runs at bulk tier; holders show in `pg_stat_activity` as `lease:ibkr_history_stream:<tier>:<holder>`.
- Wrapper scripts and symbol lists in `logs/backfill_ops/` are git-tracked (force-added; `logs/` is otherwise ignored), so `git add` under that tree always needs `-f`: the ignore rule aborts a plain add inside a `&&` chain even for tracked files.
- Todo 449 campaign (through ~2026-10): lane watchdog logs are the progress monitor; never edit a lane script while its loop runs; loops exit after ~50 attempts (gateway-down attempts ~2 min; working attempts run hours), so after a gateway outage over ~2 h relaunch `nohup bash logs/backfill_ops/intraday_chain.sh` (gap-aware; htf lane first, 5m follows).
- IBKR history starts at a stock's last listing-venue move: SMART-routed requests (1d and intraday) serve nothing before it (AMD 2015, PEP 2017, TLT 2016); the same contract routed to the old venue (`NYSE`, `ARCA`, `ISLAND`=Nasdaq, `AMEX`, `BATS`) serves it with venue-only volume. Error 162 "Query failed" marks it. `ohlcv_empty_history` rows written before todo 433's fix may be false.
- Lane pauses are usually pacing, not hangs: the in-process limiter (58 req/10 min shared) logs nothing while a request waits for budget; the 25-min lane watchdog is the backstop (todo 485 adds a wait log line). Before calling the gateway down, probe a known-good symbol on a spare client ID (e.g. 41): a name-specific hang (HOOD 2026-10-01) looks identical in the lane log.
- Gateway 2FA hang: login state lives in `docker logs ib-gateway` ("Second Factor Authentication" = waiting on human Keychain approval; "Login has completed" = authed). `docker restart ib-gateway` re-sends the push; IBKR's server-side rate limit survives the restart (~5 min wait), then IBC's fresh login fires a new push. The nightly 23:59 UTC restart can re-trigger it (todo 395).
- Clock surfaces differ: host `uptime`/`journalctl` print EDT; Postgres and container logs are UTC; IBC's gateway log lines are container-local. Correlate with `date -u` before computing elapsed times.
- Timers: `systemctl list-timers | grep indicagent`. Nightly backfill 01:00 EDT and regime coverage auditor 02:00 EDT fire; `indicagent-roll-batch.timer` is disabled (`scripts/ops/roll/ops_roll_batch.py` promotes the front month in `contract_metadata`). Docker logging caps (`max-size/max-file`) must stay (TimescaleDB grew a 29GB log without them).

## Moved from CLAUDE.md (5.60.0 trim): data and code patterns

- Dividends (todo 428): stored bars are price-only. `dividend_events` (Yahoo daily, owner-approved; IBKR cross-check comes with phase 185 D5) is read through `dividend_events_reconciled`; outside `dividend_event_coverage` a name's dividends are unknown, never zero. Any research spec that holds across a session boundary declares `panel.total_return` (`src/intelligence/research/dividends.py`); intraday-only families do not.
- Raw `market_data_ohlcv` is a continuous calendar grid with synthetic-fill and IBKR flat-carry-forward placeholder bars (~82% of intraday rows). Raw-table access outside the allow-list needs a `tests/unit/test_market_data_ohlcv_boundary.py` entry with a reason; deleting an allow-listed script requires removing its entry in the same commit.
- Instrument filters: `instruments.contract_details->>'asset_class'` is `'equity'` (ETFs), `'futures'` or `'fx'`; there is no top-level column. Eligibility dimensions `compute_eligible` / `compute_eligible_1d` / `live_tradeable` (migration 337) are read via `get_active_contracts(dimension=)`; `is_active` alone conflates backfill, compute and live scope.
- Onboarding instruments: `docs/foundation/instrument-onboarding-sop.md`. Never screen names on history or returns, never hand-write `instruments`, never deactivate a dead name (185 D8).
- asyncpg: JSONB comes back as `dict` only on a pooled connection from `BaseBatch`'s `create_pool()` (codec registered). A bare `asyncpg.connect()` returns raw JSON text; call `src.core.database_manager._setup_codecs(conn)` first. UUIDs go through `str()` before Kafka. Derive column dtypes from `conn.prepare(sql).get_attributes()`, never from fetched rows (an all-NULL early chunk silently mistypes and a downstream `dtype.kind in "fc"` filter drops the column with no error).
- pandas 3: `DatetimeIndex.asi8` returns the index's own unit, not epoch-ns. Use `pd.DatetimeIndex(values).to_numpy(dtype="datetime64[ns]").astype(np.int64)` (pattern: `scripts/research/feature_matrix.py::_epoch_ns`).
- `bulk_update_by_key`'s `col_types` is load-bearing: columns declared `"real"` are float32-range-clamped before write (`services/_batch_utils.py::_clamp_to_real_range`). A stale `"double precision"` after a migration narrows a column loses the clamp and can fail with "value out of range". Keep it in sync with the live schema.
- Never `SELECT tbl.*` a full corpus into a DataFrame (200+ columns x millions of rows; chunking or `del df` only moves the OOM, todo 234). Build the matrix from asyncpg rows (`scripts/research/feature_matrix.py::fetch_feature_matrix`).
- Never log per-row inside a loop over the full corpus; accumulate a counter and log once per partition or run.
- Module-level APR pattern: `_config_service: Any | None = None` + `set_config_service()` + `get_sync()` wrapper, registered in `FeatureVectorPipeline._prewarm_threshold_config()`. Plugin dataclasses: `_config_service: Any = field(default=None, compare=False, repr=False)`, read via `cfg.get_sync(key, fallback) if cfg else fallback`.
- Metrics API (OTel SDK, never `prometheus_client`): counters `.add(1, attrs)`, histograms `.record(val, attrs)`, up-down gauges `.add(delta, attrs)`, point gauges `.set(value, attrs)`. Spans: `observed_span(name, attributes={...})` with `ATTR_*` constants.
- Every `BaseDaemon` inherits 5 OTel signals: `agent_last_message_timestamp_seconds`, `agent_crash_total`, `agent_dlq_total`, `watchdog_notify_total`, `watchdog_notify_suppressed_total`. Four use label `agent_id`; `agent_crash_total` uses `agent`. Oneshots emit `job_completed_total{job, status}` with `job` equal to the kebab-case systemd unit `%n` suffix.
- Service logs rotate daily (~00:3x UTC): an empty current `.log` does not mean the process died; check `.log.1` and `.log.N.gz`.

## Moved from CLAUDE.md (5.60.0 trim): processes, git and research

- Killing a ProcessPoolExecutor service orphans its forkserver workers (still holding DB connections and writing). After `kill <main_pid>`, run `ps -eo pid,cmd | awk '/<script.py>/ && !/awk/ {print $1}' | xargs kill` and confirm zero remain. Never `pkill -f`/`pgrep -f` a pattern that appears in your own command line (kills the invoking shell, exit 144; bracket the pattern). Then find any backend still running the killed query (`pg_stat_activity`, state `active`, wait `ClientWrite`) and `pg_terminate_backend()` it: it keeps its chunk locks and blocks the restart's writes.
- Never edit a module the batch writer imports while its run is live or resumable: `code_content_key` hashes every first-party module it loads, so one edit discards every completed cell. Kill-and-resume with the same command is safe.
- Running from a git worktree: symlink `.env` (`ln -s /home/bg/dev/indicagent/.env <worktree>/.env`; `Settings` reads the `.env` beside its own source tree) and commit with `PATH=/home/bg/dev/indicagent/.venv/bin:$PATH` (worktrees have no `.venv`; pre-commit blocks on missing ruff/black).
- `git add` with several pathspecs aborts entirely if any path does not match (e.g. the pre-rename side of a moved todo): none get staged. Stage a renamed path alone (`git add -- <new_path>`) first. After `git mv`, re-`git add` the new path or earlier unstaged edits stay out of the commit.
- Shared checkout: `git commit -m "..." -- <paths>` always carries an explicit pathspec (a bare commit has swept another session's staged file to origin). Never chain `git push` with a first-time commit: commit, check `git show HEAD --stat`, push separately (`reset --soft HEAD^` is the only recovery in the unpushed window).
- A migration applied live via `psql -f` has no forcing function to get committed; commit it in the same breath as applying it.
- Planning: `gsd-sdk query phase.add` numbers from `.planning/phases/` directories, not ROADMAP.md (check `grep -n "### Phase" .planning/ROADMAP.md | tail`; add by hand on a collision). ROADMAP.md plan checkboxes plus `NN-SUMMARY.md` presence are the granular truth; STATE.md phase entries lag (todo 383), so check `git log --oneline` before calling a phase unexecuted. STATE.md Strategic Plan edits replace stale bullets with plain corrected facts, no stacked `CORRECTED <date>` blocks. Orchestrator executor subagents are in-process and die with their session (`/clear` keeps the process alive); hand off via memory, per-task atomic commits make any plan resumable.
- Docs: `docs/research/` docs can be filename-stable (edited in place); check for a stale `YYYY-MM-DD-<name>.md` fork before citing or editing. Before archiving anything in `docs/plans/` or `docs/research/`, `grep -rl <filename>` first.
- Performance investigations of slow hypertable batch writes: follow `docs/foundation/performance-investigation-sop.md`; measure (`pg_stat_activity.wait_event`, `iostat -x 1`, `EXPLAIN ANALYZE`) before theorizing, never trust a read-only test for a write-path question, check chunk count and compression status first (todos 149, 161).
- Validating a test statistic: check the H0 mean and sd of t and rejection counts against a binomial bound at each level, never one-sided p ranges alone (E16's bias hid behind p 0.28-0.77). Commit the pass criterion before the result exists.
- Shift nulls have (sessions - L) / tau effective draws, not one per shift: a persistent signal (tau 40-60) gets about 60-90 and cannot resolve p < 0.00167.
- Ad hoc multiprocess scripts: build the pool with `make_worker_pool(n, blas_threads_per_worker=1)` or export `OMP_NUM_THREADS=1`; a bare pool spawns 24 BLAS threads per numpy worker.
