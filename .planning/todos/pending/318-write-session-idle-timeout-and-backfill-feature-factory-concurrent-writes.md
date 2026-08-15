# 318 - `compressed_hypertable_write_session` idle-timeout bug + `backfill_feature_factory.py` unprotected concurrent writes

**Filed:** 2026-08-15
**Source:** Found live running [[todo 316]]'s data remediation (recompute for the 80 missing ETF
symbols) immediately after `regime_writer`'s run finished.

## Bug 1: `compressed_hypertable_write_session`'s bracketing connection can be killed by an idle-session timeout before its `finally` runs

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

**Fix shape:** `compressed_hypertable_write_session` assumes its own connection stays alive for the
whole `yield` duration (true for every existing caller, e.g. `regime_writer.py`, which queries on
that same connection throughout). Either (a) document this as a hard contract (the session's own
connection must be used for at least periodic activity, or the caller is responsible for keepalives)
and treat what happened as caller misuse, not a bug in the helper -- or (b) make the helper robust
to this by sending a periodic no-op keepalive query on its own connection while the caller's `yield`
is open (harder, requires the context manager to run concurrently with the caller's work, which the
current `yield`-based design doesn't support without a background thread). Recommend (a) as the
minimal fix: add an explicit docstring warning + a defensive `finally`-block reconnect-and-retry (if
`session_conn` is dead, open a fresh connection scoped to the same hypertable and finish the
recompress+VACUUM on that one, rather than letting the whole cleanup silently fail) -- protects
future callers who make the same mistake without requiring every caller to get connection lifecycle
perfectly right.

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

pending, P1 -- Bug 1 is a real gap in shared, reused infrastructure (protects the next caller with
a similar "wrap external work" usage pattern); Bug 2 is a confirmed violation of an existing,
explicitly-named CLAUDE.md invariant that's been live and unaddressed since before this session.
Neither blocks [[todo 316]] (already completed, data verified correct) but both should be fixed
before the next routine `backfill_feature_factory.py --compute-only` run at scale (multiple workers,
long compute span) rather than relying on manual one-off mitigation again.

## Where

- `services/_batch_utils.py` -- `compressed_hypertable_write_session` (Bug 1)
- `services/backfill_feature_factory.py` -- `_run_compute_worker`, `_compute_symbol_tf`,
  `run_compute_stage` (Bug 2)
