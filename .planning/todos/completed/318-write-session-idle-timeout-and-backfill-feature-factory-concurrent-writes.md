# 318 - `compressed_hypertable_write_session` idle-timeout bug + `backfill_feature_factory.py` unprotected concurrent writes

**Filed:** 2026-08-15
**Source:** Found live running [[todo 316]]'s data remediation (recompute for the 80 missing ETF
symbols) immediately after `regime_writer`'s run finished.

## Bug 1: `compressed_hypertable_write_session`'s bracketing connection can be killed by an idle-session timeout before its `finally` runs -- FIXED 2026-08-15

The one-off remediation driver held the write-session's connection (`session_conn`) open around
*external* work -- `run_compute_stage()`'s actual writes happened on a completely separate
connection (a `ProcessPoolExecutor` worker's own `psycopg.connect()`), so `session_conn` itself ran
zero queries for the full compute span (~minutes, 320 symbol/tf pairs, single worker). Postgres's
`idle_session_timeout` killed it mid-wait. When the `with` block's `finally` tried to run
`_COMPRESS_ALL_DECOMPRESSED_CHUNKS_SQL` on the now-dead connection, it raised
`psycopg.errors.IdleSessionTimeout`, and the session's recompress+VACUUM never ran -- 3 chunks were
left decompressed until manually recovered (`compress_chunk` + `VACUUM feature_vectors`, done by
hand this session).

**Not a data-loss bug** -- the actual writes committed via the worker's own autocommit connection,
unaffected by `session_conn`'s death (confirmed: all 80 symbols' rows landed correctly). Purely a
"the safety wrapper's own cleanup step can silently fail to run" bug -- worse than a normal crash
because the `finally` block itself is what's supposed to be the last line of defense, and it can be
taken out by the exact kind of idle timeout a long external compute span invites.

**Fixed 2026-08-15, migration 315 + `services/_batch_utils.py`:** neither of the two options
originally proposed here (document as caller-contract, or a keepalive thread) was actually needed --
the real fix is deeper: `idle_session_timeout`/`idle_in_transaction_session_timeout` are now disabled
(APR key `infra.compressed_hypertable_write_session.idle_session_timeout_ms`, default 0) for the
session's entire duration on the SAME connection the `finally` block later uses, via a data-driven
`_SESSION_GUC_OVERRIDES` list shared with the pre-existing `statement_timeout` override
(consolidated into one combined `current_setting()`/`set_config()` round trip per direction, not
three separate SHOW/SET pairs). This eliminates the root cause outright -- the connection can now
legitimately sit idle for the whole external-compute span, of any duration, without Postgres ever
killing it for that reason, so there's no dead connection for the `finally` block to fail against in
the first place. No reconnect-retry logic needed. Verified live against the production DB (not just
mocked unit tests) before landing. Full detail: `services/_batch_utils.py`'s
`compressed_hypertable_write_session` docstring, migration 315's own comments.

## Bug 2: `backfill_feature_factory.py`'s `ProcessPoolExecutor` workers write directly and concurrently, unprotected

Confirmed reading the code: `_run_compute_worker` (subprocess) opens its own `psycopg.connect(dsn)`
and calls `_batch_insert()` directly -- writes happen from multiple subprocesses concurrently
whenever `n_workers > 1`, each on its own connection. This is exactly the pattern CLAUDE.md's own
invariant names and explicitly calls out as needing this fix in `backfill_feature_factory.py`
specifically ("ProcessPoolExecutor workers are compute-only... Never open a write connection...
from a worker subprocess -- concurrent writers on the same TimescaleDB hypertable cause index-page
deadlocks... pattern applies to all batch services: ic_engine, backfill_feature_factory, etc."),
but the code doesn't honor it -- workers return nothing to main for writing, they write themselves.

Separately, `run_compute_stage()`'s writes are not wrapped in `compressed_hypertable_write_session`
at all -- confirmed via grep, zero references in the file. Running it against a compressed
`feature_vectors` (the normal state -- job 1065's policy keeps it compressed) would hit the
documented "compressed chunk has no usable per-row index, forces a full decompressing scan" cost
(todo 306's second bug) on every write.

**Mitigated for [[todo 316]]'s one-off run** by wrapping the whole call in
`compressed_hypertable_write_session` externally (a driver script, not a code change) and forcing
`n_workers=1` to eliminate the concurrent-writer risk for that specific run. **Not a fix** -- the
next routine run of `backfill_feature_factory.py --compute-only` (e.g. the next universe expansion)
hits both gaps again unless this is fixed properly.

**Fix shape:** move worker writes back to the main process per the CLAUDE.md-mandated pattern
(workers return serializable rows/dicts, main process does the actual `_batch_insert` calls
serially), then wrap that main-process write span in `compressed_hypertable_write_session`. Real
refactor -- worker functions currently call `_compute_symbol_tf` -> `_batch_insert` inline; needs
`_compute_symbol_tf` to return computed rows instead of writing them, and a new aggregation step in
`run_compute_stage` to batch-insert everything the pool returns.

## Status

**Bug 1: FIXED, 2026-08-15** (migration 315 + `services/_batch_utils.py`, see above). Verified live
against the production DB, full unit suite green, `/code-review`-clean.

**Bug 2: FIXED, 2026-08-21.** Workers (`_run_compute_worker`/`_compute_symbol_tf`) are now
compute-only per the CLAUDE.md invariant -- they return computed rows + status metadata, never
write to `feature_vectors`/`backfill_status` themselves. All writes moved to the main process,
serially, on the single connection already open in `run_compute_stage`, wrapped in
`compressed_hypertable_write_session` for the whole pool span (closing the second gap this todo
named too -- writes are now protected against the compressed-chunk full-scan cost, not just the
concurrency risk). A `/simplify` pass (4 parallel agents) plus `/code-review medium` both surfaced
real follow-up findings, applied same session: per-cell write-failure isolation mirroring
`regime_writer.py`'s rollback-on-failure (one bad write no longer aborts the whole run), an
autocommit-contract fix (`db_conn` now flips to `autocommit=False` for the write span, matching
every other `compressed_hypertable_write_session` caller), two redundant derived fields
(`rows_written`/`pct`) dropped from the worker→main payload, and stale connection-lifecycle
comments corrected. One convergent finding (efficiency + altitude `/simplify` agents,
`/code-review`'s sole finding) was judged real but out of scope for this fix -- worker rows are now
held fully in memory per symbol before crossing the IPC boundary instead of streaming in
`insert_batch_size` chunks; filed as [339](339-backfill-feature-factory-worker-rows-unbounded-memory-across-ipc.md)
rather than expanding this diff's blast radius further. New regression test added
(`test_compute_cell_write_failure_does_not_abort_remaining_cells`). Full `tests/unit/` suite green,
ruff/black clean.

## Where

- `services/backfill_feature_factory.py` -- `_run_compute_worker`, `_compute_symbol_tf`,
  `run_compute_stage` (Bug 2, the only remaining open item)
