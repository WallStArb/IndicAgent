"""Compressed-hypertable write sessions (decompress, write, recompress) and the headroom checks."""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager, contextmanager, nullcontext
from contextvars import ContextVar
from typing import Any

import structlog

from services.batch_support.config import cfg
from services.batch_support.db import load_apr_dict_async

_logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Compressed-hypertable write session (psycopg-based batch services)
# ---------------------------------------------------------------------------
#
# Every table a batch job bulk-UPDATEs by key here is a compressed TimescaleDB hypertable
# (todo 306 follow-up, 2026-08-14). Which tables those are is discovered by one live query
# against `timescaledb_information.hypertables`, cached for the process lifetime (todo 308)
# -- same MOTIVATION as ConfigService/VocabularyService's cache-at-init pattern (a hot path
# stays a zero-DB-round-trip check after the first call), but NOT the same shape: those two
# are explicitly prewarmed once during a daemon's controlled async setup, before any
# concurrent reader exists (see CLAUDE.md's "Migrate-as-you-go" section, and
# src/core/vocabulary_access.py's register/prewarm/reset-for-test triplet). This cache
# instead populates lazily on whichever call reaches it first, because bulk_update_by_key/
# compressed_hypertable_write_session are called from ~8 independent oneshot batch scripts
# (regime_writer.py, ic_engine.py, ops_regime_null_out_and_verify.py, etc.), each with its
# own connection setup and no single shared init hook to hang an explicit prewarm off of --
# retrofitting all of them to call a prewarm step is real, valid follow-up work (flagged by
# code review as the more idiomatic shape) but is out of scope for todo 308's own "Where"
# (this file + its tests only). Safe under the same "known callers run sequentially"
# assumption `_active_write_session_hypertable` below already documents for this exact
# file: two callers racing to populate this cache before it's ever warm would both fire the
# same idempotent query and converge on the same value (wasted round trip, not a
# correctness bug) -- if that assumption ever stops holding, add a lock here the same way
# that comment already flags for its own guard.
#
# Previously a hardcoded `frozenset({"feature_vectors", "feature_ic_scores"})`. The two
# drift directions of a hand-maintained list are NOT equally safe (2026-08-14 altitude
# review correction -- an earlier version of this comment claimed they were): a table left
# in the set after it stops being compressed is harmless (compressed_hypertable_write_
# session's own per-entry chunk query just finds zero chunks and no-ops), but a table
# that's missing -- becomes compressed later, or is used via bulk_update_by_key for the
# first time while already compressed, before a human remembers to add it -- is NOT caught
# by anything: the guard is gated on set membership, so a missing entry means it simply
# never fires and the write proceeds unwrapped, silently reintroducing the ~1000x-slower
# forced-seq-scan bug this whole mechanism exists to prevent. A live query can't drift out
# of sync with the actual schema the way a hand-maintained list can.
_LIVE_COMPRESSED_HYPERTABLES_SQL = (
    "SELECT hypertable_name FROM timescaledb_information.hypertables WHERE compression_enabled"
)

# Process-lifetime cache shared between the sync (psycopg) and async (asyncpg) accessors
# below -- the underlying fact (which hypertables have compression enabled) doesn't depend
# on which driver asks, so either one populates it and the other reuses it. Reset to None
# by an autouse fixture in tests/unit/test_batch_utils.py between tests so a mocked DB
# response in one test can't leak into another's assertions via this shared module state.
_compressed_hypertable_names_cache: frozenset[str] | None = None


def _known_compressed_hypertables(conn: Any) -> frozenset[str]:
    """Sync (psycopg) accessor for the live-cached compressed-hypertable set -- see the
    module comment above this cache's declaration for the full todo 308 rationale."""
    global _compressed_hypertable_names_cache
    if _compressed_hypertable_names_cache is None:
        with conn.cursor() as cur:
            cur.execute(_LIVE_COMPRESSED_HYPERTABLES_SQL)
            _compressed_hypertable_names_cache = frozenset(row[0] for row in cur.fetchall())
    return _compressed_hypertable_names_cache


async def _known_compressed_hypertables_async(conn: Any) -> frozenset[str]:
    """asyncpg sibling of `_known_compressed_hypertables` -- shares the same module-level
    cache, populated by whichever driver calls first."""
    global _compressed_hypertable_names_cache
    if _compressed_hypertable_names_cache is None:
        rows = await conn.fetch(_LIVE_COMPRESSED_HYPERTABLES_SQL)
        _compressed_hypertable_names_cache = frozenset(r["hypertable_name"] for r in rows)
    return _compressed_hypertable_names_cache


# Set for the duration of an active compressed_hypertable_write_session /
# async_compressed_hypertable_write_session (value = the hypertable name), so
# bulk_update_by_key can tell "no session running" apart from "session running for a
# different table" apart from "session running for this exact table." Per-task/coroutine
# isolated by asyncio (a concurrent task without its own session correctly sees None, not
# another task's value) and correct in the sync/single-threaded batch-script case this
# guard actually protects (bulk_update_by_key is psycopg/sync-only).
_active_write_session_hypertable: ContextVar[str | None] = ContextVar(
    "_active_write_session_hypertable", default=None
)

# Shared by both compressed_hypertable_write_session (sync) and its async sibling --
# one key, one fallback, defined once.
_STATEMENT_TIMEOUT_APR_KEY = "infra.compressed_hypertable_write_session.statement_timeout_ms"
_DEFAULT_STATEMENT_TIMEOUT_MS = 14_400_000  # 4h -- see migration 314 for provenance

# todo 318: idle_session_timeout is a DIFFERENT GUC from statement_timeout -- it bounds
# how long this connection may sit completely idle between statements, not how long any
# single statement may run. Confirmed live 2026-08-15: regime_writer.py's session
# connection decompressed cleanly, then sat idle for ~55min while its ProcessPoolExecutor
# workers computed HMM fits (real, necessary work happening in separate processes -- this
# connection genuinely had nothing to do), and was killed by the role/database default
# idle_session_timeout (1h) -- stranding feature_vectors fully decompressed across all 85
# chunks, same failure shape as the missing-statement-timeout incident (migration 314)
# this file already protects against, just triggered by idle time instead of a single
# long-running statement. Default is disabled (0) -- there is no safe non-zero cap for a
# gap this function cannot bound (worker/caller compute time is not this function's
# concern).
#
# Also applied to idle_in_transaction_session_timeout (same APR key, same value) as
# defense-in-depth, NOT because the live incident hit it -- it didn't (this session's own
# conn.commit() right before yield means there is no open transaction during the idle gap
# unless the caller opens one itself, unconfirmed live). regime_writer.py
# already disables this specific GUC at connect time
# (`options="-c idle_in_transaction_session_timeout=0"`), making this override redundant
# for it specifically -- kept anyway because compressed_hypertable_write_session is
# shared infrastructure serving callers that don't all follow that convention (e.g. a bare
# `psycopg.connect()`, todo 316's own one-off remediation script). See also
# src/config/instruments_listener.py's independent `SET idle_session_timeout = 0`
# for the same underlying GUC-vs-legitimately-idle-connection problem in a different
# connection-ownership shape (owns its connection for life, no restore needed).
_IDLE_SESSION_TIMEOUT_APR_KEY = "infra.compressed_hypertable_write_session.idle_session_timeout_ms"
_DEFAULT_IDLE_SESSION_TIMEOUT_MS = 0  # 0 = disabled -- see migration 315 for provenance

# GUCs compressed_hypertable_write_session/async_compressed_hypertable_write_session
# override for their duration and restore to the connection's prior value on exit --
# (guc_name, apr_key, default_ms). A data-driven list, not copy-pasted SHOW/SET/restore
# per GUC: adding a future GUC override (e.g. if `lock_timeout` bites the same way one
# day) is a one-line addition here, not a repeat of this file's own SHOW/SET/restore shape
# a third time. idle_session_timeout and idle_in_transaction_session_timeout share one
# APR key (same value applied to both, see the idle-timeout comment above).
_SESSION_GUC_OVERRIDES: tuple[tuple[str, str, int], ...] = (
    ("statement_timeout", _STATEMENT_TIMEOUT_APR_KEY, _DEFAULT_STATEMENT_TIMEOUT_MS),
    ("idle_session_timeout", _IDLE_SESSION_TIMEOUT_APR_KEY, _DEFAULT_IDLE_SESSION_TIMEOUT_MS),
    (
        "idle_in_transaction_session_timeout",
        _IDLE_SESSION_TIMEOUT_APR_KEY,
        _DEFAULT_IDLE_SESSION_TIMEOUT_MS,
    ),
)

_FIND_COMPRESSION_JOBS_SQL = (
    "SELECT job_id, scheduled FROM timescaledb_information.jobs "
    "WHERE hypertable_name = %s AND proc_name = 'policy_compression'"
)

# Disk the session's decompress-all step needs (todo 426): the chunks' uncompressed size, the
# conservative peak while compressed and decompressed copies coexist.
_DECOMPRESS_BYTES_SQL = (
    "SELECT COALESCE(sum(before_compression_total_bytes), 0)::bigint "
    "FROM chunk_compression_stats(%s) WHERE compression_status = 'Compressed'"
)
_DECOMPRESS_BYTES_ASYNCPG_SQL = _DECOMPRESS_BYTES_SQL.replace("%s", "$1")
_DISK_PATH_KEY = "infra.compressed_hypertable_write_session.disk_path"
_MIN_FREE_AFTER_KEY = "infra.compressed_hypertable_write_session.min_free_after_fraction"
_DISK_PATH_DEFAULT = "/"
_MIN_FREE_AFTER_DEFAULT = 0.10


def check_decompress_headroom(
    hypertable: str, required_bytes: int, disk_path: str, min_free_after_fraction: float
) -> None:
    """Raise before anything is decompressed when the decompress-all step would leave less
    than `min_free_after_fraction` of the filesystem free (todo 426: feature_vectors reached
    491 GB decompressed against 414 GB free, a disk-full before any row is written, the
    2026-08-13 incident shape). `disk_path` must be on the filesystem that holds the database
    volume."""
    usage = shutil.disk_usage(disk_path)
    reserve = int(min_free_after_fraction * usage.total)
    if usage.free - required_bytes < reserve:
        raise RuntimeError(
            f"compressed_hypertable_write_session({hypertable!r}) refused: decompressing its "
            f"compressed chunks needs {required_bytes / 1e9:.0f} GB, {usage.free / 1e9:.0f} GB "
            f"is free on {disk_path}, and {min_free_after_fraction:.0%} "
            f"({reserve / 1e9:.0f} GB) must stay free. Write per chunk (todo 426) or free space."
        )


def _assert_decompress_headroom(conn: Any, hypertable: str) -> None:
    """Sync session's pre-flight: measured bytes + APR, then check_decompress_headroom."""
    with conn.cursor() as cur:
        cur.execute(_DECOMPRESS_BYTES_SQL, (hypertable,))
        (required_bytes,) = cur.fetchone()
        cur.execute(
            "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
            ([_DISK_PATH_KEY, _MIN_FREE_AFTER_KEY],),
        )
        apr = dict(cur.fetchall())
    conn.commit()
    check_decompress_headroom(
        hypertable,
        int(required_bytes),
        apr.get(_DISK_PATH_KEY, _DISK_PATH_DEFAULT),
        float(apr.get(_MIN_FREE_AFTER_KEY, _MIN_FREE_AFTER_DEFAULT)),
    )


async def _assert_decompress_headroom_async(conn: Any, hypertable: str) -> None:
    """Async session's pre-flight, same check."""
    required_bytes = await conn.fetchval(_DECOMPRESS_BYTES_ASYNCPG_SQL, hypertable)
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1)",
        [_DISK_PATH_KEY, _MIN_FREE_AFTER_KEY],
    )
    apr = {r["config_key"]: r["config_value"] for r in rows}
    check_decompress_headroom(
        hypertable,
        int(required_bytes),
        apr.get(_DISK_PATH_KEY, _DISK_PATH_DEFAULT),
        float(apr.get(_MIN_FREE_AFTER_KEY, _MIN_FREE_AFTER_DEFAULT)),
    )


_DECOMPRESS_ALL_COMPRESSED_CHUNKS_SQL = (
    # %%I (not %I): psycopg's client-side placeholder scanner treats any single '%' in the
    # query text as a potential bind placeholder and rejects '%I' as an unrecognized one
    # (only %s/%b/%t are valid) -- confirmed live 2026-08-14, this exact query raised
    # psycopg.ProgrammingError before the doubling was added. format()'s own %I/%L
    # directives need escaping to %%I/%%L to survive psycopg's parameter substitution
    # before ever reaching the server. asyncpg has no equivalent client-side scanning (its
    # $1-style placeholders don't collide with '%'), so the asyncpg sibling constants below
    # use a single %I, unescaped -- confirmed live, not assumed.
    "SELECT decompress_chunk(format('%%I.%%I', chunk_schema, chunk_name)::regclass, "
    "if_compressed => true) FROM timescaledb_information.chunks "
    "WHERE hypertable_name = %s AND is_compressed"
)
_COMPRESS_ALL_DECOMPRESSED_CHUNKS_SQL = (
    "SELECT compress_chunk(format('%%I.%%I', chunk_schema, chunk_name)::regclass, "
    "if_not_compressed => true) FROM timescaledb_information.chunks "
    "WHERE hypertable_name = %s AND NOT is_compressed"
)


# compressed_hypertable_write_session/async_compressed_hypertable_write_session's heavy
# machinery (decompress-all, pause compression jobs, override session GUCs, bare VACUUM)
# has only ever been built, incident-hardened, and exercised against these two specific
# tables (see that function's docstring for the 2026-08-13/14 incident history). This is
# DELIBERATELY a small, hand-curated allow-list, NOT the live-queried
# `_known_compressed_hypertables(conn)` set above -- the two checks answer different
# questions with OPPOSITE-direction risk. `_known_compressed_hypertables` answers "is this
# table compressed at all" for `bulk_update_by_key`'s "did you forget to wrap this write in
# a session" guard, where a MISSING entry is the dangerous direction (a write silently
# proceeds unprotected). This allow-list answers "has this specific, disruptive mechanism
# actually been validated for this table," where a PRESENT-when-it-shouldn't-be entry is
# the dangerous direction: confirmed live (2026-09-17 code review) that this database
# currently has 26 compressed hypertables total (not 2) -- if this check used the same live
# query as `_known_compressed_hypertables`, any of the other 24 (including
# market_data_ohlcv, 258 chunks, an active compression-policy job) would silently pass
# validation and let a future/mistaken call run this session's full decompress/pause-jobs/
# GUC-override/VACUUM sequence against a table it was never designed or tested for. Adding
# a table here must be a deliberate, reviewed decision -- a live query must never make it
# on this mechanism's behalf.
# feature_ic_scores (the migration 413 table): no scheduled compression policy; the session
# runs against it for services/ic_measure.py (decompress, recompress and VACUUM, which
# the plan 186-14 integration test exercises on indicagent_test).
# feature_vectors left the set at migration 570 (2026-11-04): the hardening was for the dropped v1
# table, and the table now under that name has one writer, bulk_load (D-24, append only). Keeping
# it here would let the legacy in-place UPDATE writers (regime_writer and the corpus repair
# scripts) overwrite the rebuild's walk-forward labels behind provenance that still names the
# rebuild; without it every such session refuses loudly.
_WRITE_SESSION_HARDENED_TABLES = frozenset({"feature_ic_scores"})


def _validate_compressed_hypertable(hypertable: str) -> None:
    """Defense-in-depth: re-validate against the hand-curated hardened-table allow-list
    right before SQL interpolation (VACUUM's target can't be a bind parameter), even though
    every caller path sources `hypertable` from a hardcoded literal, never user input. Same
    pattern as regime_writer.py's `_validate_label_column` / `ops_regime_null_out_and_
    verify.py`'s `_validate_label_column`. Shared by both the sync and async write-session
    functions -- a pure, static membership check needs no conn/await either way."""
    if hypertable not in _WRITE_SESSION_HARDENED_TABLES:
        raise ValueError(
            f"compressed_hypertable_write_session: {hypertable!r} is not one of the tables "
            f"this mechanism has been built and incident-hardened for "
            f"({sorted(_WRITE_SESSION_HARDENED_TABLES)}). Add it to "
            "_WRITE_SESSION_HARDENED_TABLES only after deliberately validating this "
            "session's decompress/pause-jobs/GUC-override/VACUUM sequence against it -- "
            "this is intentionally not the live-queried compressed-hypertable set."
        )


def _log_write_session_entering(hypertable: str, n_chunks: int) -> None:
    _logger.warning(
        "compressed_hypertable_write_session.entering",
        hypertable=hypertable,
        chunks_to_decompress=n_chunks,
    )


def _log_write_session_exited(hypertable: str, n_chunks: int) -> None:
    _logger.info(
        "compressed_hypertable_write_session.exited",
        hypertable=hypertable,
        chunks_recompressed=n_chunks,
    )


def _restore_compression_jobs_sync(
    conn: Any, hypertable: str, compression_jobs: list[tuple[int, bool]]
) -> None:
    """Restore each paused compression-policy job to its own prior `scheduled` value.

    Called from two places (code review, todo 314): the normal exit `finally` block, AND
    an entry-phase exception handler -- a job paused right before a decompress that then
    fails (statement timeout, idle-session kill -- both documented as having happened live
    against this exact call) must not stay paused forever with no compensating mechanism,
    unlike decompress_chunk's own idempotent self-healing.
    """
    if not compression_jobs:
        return
    with conn.cursor() as cur:
        for job_id, prior_scheduled in compression_jobs:
            cur.execute("SELECT alter_job(%s, scheduled => %s)", (job_id, prior_scheduled))
    conn.commit()
    _logger.info(
        "compressed_hypertable_write_session.compression_jobs_restored",
        hypertable=hypertable,
        job_ids=[job_id for job_id, _ in compression_jobs],
    )


@contextmanager
def compressed_hypertable_write_session(conn: Any, hypertable: str, *, decompress: bool = True):
    """decompress=False (todo 426) keeps the job pause and GUC overrides but skips the
        decompress-all, recompress and VACUUM: for INSERT/UPSERT writers, which TimescaleDB 2.27's
        native DML decompression handles per (symbol, tf) segment. Measured 2026-09-25: one
        symbol's 4,834-row 1d upsert took 3.9 s with every chunk left compressed and no disk growth,
        where decompress-all needed 527 GB of 454 GB free. Row-level UPDATE writers
        (bulk_update_by_key, regime_writer) keep decompress=True until their native cost is
        measured.

    Brackets a batch of row-level UPDATEs against a compressed TimescaleDB hypertable.

        Proven necessary 2026-08-14: a compressed TimescaleDB chunk has no usable per-row index
        at all. Confirmed via EXPLAIN: a 4,875-row single-symbol UPDATE against feature_vectors
        forced a Seq Scan of the full chunk (cost ~1.2M) instead of an Index Scan on the PK
        (cost ~1,200 on the same chunk decompressed) -- roughly 1000x, independent of how
        selective the UPDATE's WHERE/JOIN predicate is. `bulk_update_by_key` and any hand-rolled
        UPDATE against a compressed hypertable both hit this identically -- the cost comes from
        TimescaleDB's chunk-level compression storage, not from the query shape.

        A batch job issuing more than a handful of row-level UPDATEs (e.g. regime_writer.py's
        ~1,000 sequential per-symbol/tf writes) must bracket the whole batch in this session
        instead of letting TimescaleDB decompress-and-recompress per call -- that per-call
        pattern is what turned a 12-hour compression policy cycle into a disk-fill incident
        (2026-08-13/14): every call decompresses, nothing waits for the next call before
        autovacuum/compression can catch up, so dead-tuple bloat compounds across calls faster
        than it's reclaimed. Every write in that incident also failed outright (statement
        timeout) -- this isn't only a disk-space fix, the writes literally cannot complete
        against a compressed hypertable at this call volume.

        Decompresses every currently-compressed chunk of `hypertable` on entry (one server-side
        statement -- `decompress_chunk()` invoked per matching chunk row inside a single SELECT,
        not a per-chunk round trip), then yields, then -- in a `finally`, so this always runs
        even if the caller's write loop raises -- recompresses every chunk left decompressed
        (same single-statement shape) and issues a bare top-level `VACUUM` (autocommit; VACUUM
        cannot run inside a transaction block, see docs/foundation/timescaledb-compressed-
        column-migration.md step 4). `decompress_chunk(if_compressed=True)` /
        `compress_chunk(if_not_compressed=True)` are idempotent -- a session resumed after a
        prior run was killed mid-way finds those chunks already decompressed and safely no-ops
        them instead of erroring or double-working. That resumed run still recompresses +
        VACUUMs everything at its own exit, so the table converges back to fully-compressed
        state as long as one session eventually runs to completion.

        Scoped to the whole hypertable, not the caller's actual write footprint -- matches the
        canonical decompress-all/recompress-all reference pattern in the migration doc above,
        and TimescaleDB compression is a chunk-granularity operation regardless (there is no
        row-scoped decompress). A caller writing a narrow slice (e.g. one training_window_end)
        pays decompress/recompress work on chunks it didn't need to touch; not optimized here
        without measured evidence it matters for those lower-frequency callers.

        Does NOT protect against the process dying without running Python `finally` blocks at
        all (SIGKILL, OOM, power loss) -- that leaves the table decompressed with elevated disk
        usage until the next session that runs to completion. Logs chunk-compression counts on
        entry/exit at WARNING/INFO so this state is visible in `logs/` immediately instead of
        requiring a live investigation to notice, which is what the 2026-08-13/14 incident cost.

        Sets `_active_write_session_hypertable` for the duration so `bulk_update_by_key` can
        detect a caller that forgot to open a session at all (see that function's docstring) --
        does NOT protect against a *different*, un-bracketed writer touching the same
        hypertable concurrently (ic_engine.py's two feature_ic_scores UPDATE call sites were
        exactly this gap until todo 307 wrapped them 2026-08-20 -- every known writer against
        both known compressed-hypertable tables is now bracketed, but a future new raw
        UPDATE against either table would reopen it): this session's exit recompresses "every
        chunk currently decompressed," not only the ones it personally decompressed, so a
        concurrent unbracketed writer's chunk could be recompressed out from under it mid-
        write. Safe today because every known caller runs sequentially (`ops_corpus_pipeline_
        run.sh`'s step ordering) -- if that ever stops being true, this session needs a real
        advisory lock, not just a contextvar.

        conn: caller-owned, open psycopg connection (autocommit False is fine -- this function
        manages its own commits and only toggles autocommit for the final VACUUM). Never closed
        here -- same ownership contract as bulk_update_by_key.

        Overrides the GUCs in _SESSION_GUC_OVERRIDES (statement_timeout, idle_session_timeout,
        idle_in_transaction_session_timeout) for the duration of the session, in one combined
        round trip per direction, and restores the connection's prior values on exit.

        statement_timeout (infra.compressed_hypertable_write_session.statement_timeout_ms APR
        key, default 4h) bounds how long any single statement this function itself issues may
        run. Confirmed necessary live 2026-08-14: the role/database default (30min, tuned for
        interactive/API queries) killed regime_writer.py's very first decompress_chunk() call
        outright with zero rows written, and repeating that failure compounds -- every killed
        attempt leaves dead-tuple bloat that recruits more autovacuum workers onto the same
        chunks, slowing the next attempt's decompress further.

        idle_session_timeout (infra.compressed_hypertable_write_session.idle_session_timeout_ms
        APR key, default disabled) is a DIFFERENT failure mode: this connection can legitimately
        sit completely idle for a long time between statements (e.g. while a caller's
        ProcessPoolExecutor workers compute HMM fits in separate processes), and the role/
        database default idle_session_timeout has nothing to do with any single statement's
        runtime. Confirmed necessary live 2026-08-15: regime_writer.py's session decompressed
        cleanly, sat idle ~55min waiting on worker compute, and was killed by the role/database
        default (1h) -- stranding the table fully decompressed across all 85 chunks (todo 318).

        idle_in_transaction_session_timeout (same APR key/value as idle_session_timeout) is
        defense-in-depth, not itself observed live -- see _SESSION_GUC_OVERRIDES's comment for
        why it's still covered.

        Pauses `hypertable`'s own TimescaleDB compression policy job(s) (`alter_job(job_id,
        scheduled => false)`) for the session's duration and restores each job's prior
        `scheduled` value on exit (todo 314). Proven necessary 2026-08-14: `Columnstore Policy
        [1065]` (feature_vectors' compression job) ran concurrently with a regime_writer.py
        write session and deadlocked -- the job held `AccessExclusiveLock` compressing a chunk
        this session's decompress had already opened with `RowExclusiveLock`, each waiting on
        the other. `alter_job(scheduled => false)` only stops FUTURE scheduled runs from being
        picked up; it does not cancel a run already in progress -- if the policy job is already
        executing at the moment this session starts, this does not retroactively stop it (same
        residual race the manual "pause job 1065, kill the wedged backend" 2026-08-14 mitigation
        had to handle by hand). No known caller has hit that narrower race live; documented so
        it isn't mistaken for full protection.
    """
    _validate_compressed_hypertable(hypertable)
    if decompress:
        _assert_decompress_headroom(conn, hypertable)
    guc_names = [name for name, _, _ in _SESSION_GUC_OVERRIDES]
    compression_jobs: list[tuple[int, bool]] = []
    try:
        with conn.cursor() as cur:
            # Pause hypertable's own compression-policy job(s) first, in the same combined
            # entry round trip as the GUC overrides below (todo 314 -- keeps the "one round
            # trip per direction" shape this function already uses for GUCs, not a second
            # separate commit()).
            cur.execute(_FIND_COMPRESSION_JOBS_SQL, (hypertable,))
            compression_jobs = cur.fetchall()
            for job_id, _ in compression_jobs:
                cur.execute("SELECT alter_job(%s, scheduled => false)", (job_id,))

            # Scoped lookup, not load_config_service_sync(conn) -- that helper pulls the
            # whole config_state/config_schema JOIN (793 rows as of 2026-08-14) just to
            # read a handful of keys, and the caller (e.g. regime_writer.py) has almost
            # always already loaded the full APR table once for its own run moments
            # earlier. Mirrors the async sibling's scoped
            # `load_apr_dict_async(conn, ["infra....%"])` load.
            apr_keys = list({apr_key for _, apr_key, _ in _SESSION_GUC_OVERRIDES})
            cur.execute(
                "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
                (apr_keys,),
            )
            apr_rows = dict(cur.fetchall())
            override_values = [
                str(int(apr_rows.get(apr_key, default)))
                for _, apr_key, default in _SESSION_GUC_OVERRIDES
            ]

            # One combined round trip per direction instead of one SHOW/SET pair per GUC
            # -- current_setting()/set_config() are ordinary scalar functions, so N of
            # them can be selected/called in a single statement (confirmed live
            # 2026-08-15). Verified below that this genuinely returns/applies all N in
            # the row's positional order, not just the last one.
            cur.execute(
                "SELECT " + ", ".join("current_setting(%s)" for _ in guc_names),
                tuple(guc_names),
            )
            prior_values = list(cur.fetchone())
            cur.execute(
                "SELECT " + ", ".join("set_config(%s, %s, false)" for _ in guc_names),
                tuple(x for name, val in zip(guc_names, override_values) for x in (name, val)),
            )

            n_decompressed = 0
            if decompress:
                cur.execute(_DECOMPRESS_ALL_COMPRESSED_CHUNKS_SQL, (hypertable,))
                n_decompressed = cur.rowcount
        conn.commit()
    except BaseException:
        # Code review, todo 314: a compression job paused above, followed by ANY failure
        # in this same entry phase (the GUC override or the decompress itself -- both
        # documented as having actually failed live: statement-timeout kill 2026-08-14,
        # idle-session kill 2026-08-15) must not leave that job stuck at scheduled=false
        # forever. Unlike decompress_chunk's own idempotent self-healing, there is no
        # other mechanism that would ever notice or fix a job stranded paused here -- the
        # normal exit `finally` below is never reached because this exception propagates
        # out of the function before `try: yield` runs.
        conn.rollback()
        _restore_compression_jobs_sync(conn, hypertable, compression_jobs)
        raise
    if compression_jobs:
        _logger.info(
            "compressed_hypertable_write_session.compression_jobs_paused",
            hypertable=hypertable,
            job_ids=[job_id for job_id, _ in compression_jobs],
        )
    _log_write_session_entering(hypertable, n_decompressed)

    token = _active_write_session_hypertable.set(hypertable)
    try:
        yield
    finally:
        _active_write_session_hypertable.reset(token)

        # If the caller's write raised a real DB-level error (a statement timeout, a
        # constraint violation -- exactly the failure mode this whole mechanism exists to
        # protect against), the connection is left in Postgres's aborted-transaction state
        # and the very next statement raises InFailedSqlTransaction regardless of what it
        # is. Without this rollback, that masks the caller's real error and skips both
        # recompress and VACUUM entirely (2026-08-14 code review finding -- regime_writer.py
        # happens to already roll back per-cell internally so it never hit this, but the
        # other three psycopg call sites had no such guard). Safe unconditionally, including
        # on the success path: rollback() on a connection with no pending transaction (e.g.
        # right after the caller's own conn.commit()) is a no-op, never discards durably
        # committed work.
        conn.rollback()

        n_recompressed = 0
        if decompress:
            with conn.cursor() as cur:
                cur.execute(_COMPRESS_ALL_DECOMPRESSED_CHUNKS_SQL, (hypertable,))
                n_recompressed = cur.rowcount
            conn.commit()

            prior_autocommit = conn.autocommit
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    # hypertable validated against _WRITE_SESSION_HARDENED_TABLES above --
                    # never attacker-controlled, and VACUUM's target can't be a bind parameter.
                    cur.execute(f"VACUUM {hypertable}")
            finally:
                conn.autocommit = prior_autocommit

        with conn.cursor() as cur:
            cur.execute(
                "SELECT " + ", ".join("set_config(%s, %s, false)" for _ in guc_names),
                tuple(x for name, val in zip(guc_names, prior_values) for x in (name, val)),
            )
        conn.commit()

        _restore_compression_jobs_sync(conn, hypertable, compression_jobs)

        _log_write_session_exited(hypertable, n_recompressed)


def compressed_hypertable_write_session_or_noop(conn: Any, hypertable: str, *, apply: bool):
    """`compressed_hypertable_write_session(conn, hypertable)` when `apply` is true,
    `contextlib.nullcontext()` otherwise -- the shared shape every dry-run-by-default /
    resume-aware caller needs (a dry-run or an all-cells-already-done resume issues zero
    UPDATEs, so decompressing/recompressing the table would be pure side-effecting overhead
    a "zero DB writes" contract must not perform). One caller-supplied boolean instead of
    each script hand-rolling its own `_write_session(...) if cond else nullcontext()`
    ternary (two independent copies of this exact conditional existed before this helper).
    """
    return compressed_hypertable_write_session(conn, hypertable) if apply else nullcontext()


_FIND_COMPRESSION_JOBS_ASYNCPG_SQL = (
    "SELECT job_id, scheduled FROM timescaledb_information.jobs "
    "WHERE hypertable_name = $1 AND proc_name = 'policy_compression'"
)

_DECOMPRESS_ALL_COMPRESSED_CHUNKS_ASYNCPG_SQL = (
    "SELECT decompress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass, "
    "if_compressed => true) FROM timescaledb_information.chunks "
    "WHERE hypertable_name = $1 AND is_compressed"
)
_COMPRESS_ALL_DECOMPRESSED_CHUNKS_ASYNCPG_SQL = (
    "SELECT compress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass, "
    "if_not_compressed => true) FROM timescaledb_information.chunks "
    "WHERE hypertable_name = $1 AND NOT is_compressed"
)


async def _restore_compression_jobs_async(
    conn: Any, hypertable: str, compression_jobs: list[tuple[int, bool]]
) -> None:
    """Async sibling of `_restore_compression_jobs_sync` -- see its docstring."""
    if not compression_jobs:
        return
    for job_id, prior_scheduled in compression_jobs:
        await conn.execute("SELECT alter_job($1, scheduled => $2)", job_id, prior_scheduled)
    _logger.info(
        "compressed_hypertable_write_session.compression_jobs_restored",
        hypertable=hypertable,
        job_ids=[job_id for job_id, _ in compression_jobs],
    )


@asynccontextmanager
async def async_compressed_hypertable_write_session(conn: Any, hypertable: str):
    """asyncpg sibling of `compressed_hypertable_write_session` (sync/psycopg, above) --
    same contract, same rationale, same concurrency caveat (see that function's docstring
    for the full incident writeup, the whole-hypertable-not-write-footprint scoping
    decision, and why a *different* unbracketed writer touching the same hypertable
    concurrently isn't safe), ported for asyncpg-based batch services (e.g. ops_stale_k3_
    hmm_fields_cleanup.py) rather than forcing them onto a second DB driver just for this
    session. Sets `_active_write_session_hypertable` too, for symmetry -- `bulk_update_by_
    key` is psycopg/sync-only today so nothing currently reads it from this path, but a
    future asyncpg-based bulk-update helper can rely on the same guard without this session
    needing a second change.

    conn: an acquired asyncpg connection (e.g. `async with pool.acquire() as conn`), not a
    pool -- decompress/recompress and every write in between must share one session so the
    chunk-compression state this function manages stays consistent for the whole bracket.
    Must NOT be called from inside an open `conn.transaction()` block: the final VACUUM
    cannot run inside a transaction, and asyncpg has no equivalent of psycopg's autocommit
    toggle to escape one mid-connection.

    Overrides the GUCs in _SESSION_GUC_OVERRIDES (same list, same APR keys, same
    live-incident rationale as the sync sibling above -- see its docstring) for the
    duration of the session, in one combined round trip per direction, and restores the
    connection's prior values on exit.

    Pauses/restores `hypertable`'s own TimescaleDB compression policy job(s), same
    mechanism and same residual-race caveat as the sync sibling (todo 314) -- see that
    function's docstring for the full incident rationale.
    """
    _validate_compressed_hypertable(hypertable)
    await _assert_decompress_headroom_async(conn, hypertable)
    guc_names = [name for name, _, _ in _SESSION_GUC_OVERRIDES]

    compression_jobs = [
        (r["job_id"], r["scheduled"])
        for r in await conn.fetch(_FIND_COMPRESSION_JOBS_ASYNCPG_SQL, hypertable)
    ]
    for job_id, _ in compression_jobs:
        await conn.execute("SELECT alter_job($1, scheduled => false)", job_id)

    try:
        apr = await load_apr_dict_async(conn, ["infra.compressed_hypertable_write_session.%"])
        override_values = [
            str(int(cfg(apr, apr_key, default))) for _, apr_key, default in _SESSION_GUC_OVERRIDES
        ]

        # One combined round trip per direction instead of one SHOW/SET pair per GUC
        # (same rationale as the sync sibling). set_config_sql is reused for both the
        # entry override and the exit restore -- same placeholder shape, different
        # values each time.
        set_config_sql = "SELECT " + ", ".join(
            f"set_config(${2 * i + 1}, ${2 * i + 2}, false)" for i in range(len(guc_names))
        )

        prior_row = await conn.fetchrow(
            "SELECT " + ", ".join(f"current_setting(${i + 1})" for i in range(len(guc_names))),
            *guc_names,
        )
        prior_values = list(prior_row.values())
        await conn.execute(
            set_config_sql,
            *(x for name, val in zip(guc_names, override_values) for x in (name, val)),
        )

        # asyncpg's execute() returns the command tag ("SELECT <n>") for a plain SELECT
        # -- confirmed live 2026-08-14 -- so the affected-row count comes for free from
        # the same call that runs the statement, same shape as ops_stale_k3_hmm_fields_
        # cleanup.py's own `int(result.split()[-1])` idiom and the sync sibling's
        # cur.rowcount. No count(*) subquery wrapper needed (an earlier version of this
        # function used one).
        result = await conn.execute(_DECOMPRESS_ALL_COMPRESSED_CHUNKS_ASYNCPG_SQL, hypertable)
        n_decompressed = int(result.split()[-1])
    except BaseException:
        # Code review, todo 314: same entry-phase exception-safety gap as the sync
        # sibling -- see its docstring/comment for the full rationale. A job paused
        # above must not be stranded at scheduled=false if the GUC override or
        # decompress that follows fails.
        await _restore_compression_jobs_async(conn, hypertable, compression_jobs)
        raise
    if compression_jobs:
        _logger.info(
            "compressed_hypertable_write_session.compression_jobs_paused",
            hypertable=hypertable,
            job_ids=[job_id for job_id, _ in compression_jobs],
        )
    _log_write_session_entering(hypertable, n_decompressed)

    token = _active_write_session_hypertable.set(hypertable)
    try:
        yield
    finally:
        _active_write_session_hypertable.reset(token)

        result = await conn.execute(_COMPRESS_ALL_DECOMPRESSED_CHUNKS_ASYNCPG_SQL, hypertable)
        n_recompressed = int(result.split()[-1])
        # hypertable validated against _WRITE_SESSION_HARDENED_TABLES above -- never
        # attacker-controlled, and VACUUM's target can't be a bind parameter.
        await conn.execute(f"VACUUM {hypertable}")

        await conn.execute(
            set_config_sql,
            *(x for name, val in zip(guc_names, prior_values) for x in (name, val)),
        )

        await _restore_compression_jobs_async(conn, hypertable, compression_jobs)

        _log_write_session_exited(hypertable, n_recompressed)


def async_compressed_hypertable_write_session_or_noop(conn: Any, hypertable: str, *, apply: bool):
    """Async sibling of `compressed_hypertable_write_session_or_noop` -- see that
    function's docstring."""
    return async_compressed_hypertable_write_session(conn, hypertable) if apply else nullcontext()
