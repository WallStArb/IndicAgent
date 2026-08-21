"""Shared utilities for batch oneshot services (psycopg-based, plus a small asyncpg
APR-loading helper for the async batch services)."""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager, contextmanager, nullcontext
from contextvars import ContextVar
from typing import Any

import numpy as np
import psycopg
import structlog

from src.config.config_service import ConfigService

_logger = structlog.get_logger()

_NULL_MARKER = r"\N"

_CONFIG_QUERY = (
    "SELECT cs.config_key, cs.config_value, csc.value_type "
    "FROM config_state cs "
    "JOIN config_schema csc USING (config_key)"
)


def connect_db_from_url(db_url: str) -> Any:
    """Open a psycopg connection from a raw DB URL, autocommit off.

    Shared by ic_engine.py and ensemble_ic_engine.py's ProcessPoolExecutor workers
    (each opens its own read-only connection per dispatch) and by ic_engine's
    higher-level _connect_db(settings) wrapper (todo 047 follow-up, 2026-07-02).
    """
    conn = psycopg.connect(db_url)
    conn.autocommit = False
    return conn


@contextmanager
def short_lived_conn(dsn: str):
    """Worker-side sibling of ic_engine.py's Settings-based `_short_lived_conn` (todo 129).

    Takes a dsn string (picklable, crosses a ProcessPoolExecutor boundary) instead of a
    `Settings` object -- `_short_lived_conn` is main-process only since a `Settings`
    object doesn't cross that boundary. Guarantees `conn.close()` exactly once, even
    when the caller's body raises mid-fetch: the 3 hand-rolled dsn `open -> use ->
    close` sites this replaces (`_compute_symbol_tf` x2, `_compute_cross_sectional_tf`
    x1 in services/ic_engine.py) had no try/finally, so any exception between open and
    the nearest explicit `conn.close()` call leaked a connection.
    """
    conn = connect_db_from_url(dsn)
    try:
        yield conn
    finally:
        conn.close()


def load_config_service_sync(conn: Any) -> ConfigService:
    """Load all APR keys from config_state into a cache-only ConfigService.

    conn: open psycopg connection. No DB reference is stored in the returned
    ConfigService — only the in-memory cache is populated.
    """
    cfg = ConfigService(database_url="")
    with conn.cursor() as cur:
        cur.execute(_CONFIG_QUERY)
        rows = cur.fetchall()
    for config_key, config_value, value_type in rows:
        cfg._cache[config_key] = cfg._parse_value(config_value, value_type)
    _logger.info("config_service_loaded", key_count=len(cfg._cache))
    return cfg


# Postgres `real` (IEEE 754 float4) representable range, sourced from numpy's own
# constants rather than hand-typed literals -- confirmed live 2026-08-14 (`SELECT
# 1e-45::real` parses, `1e-46::real` raises "value out of range: underflow"; `SELECT
# 1e50::real` raises "out of range" the other tail) that Postgres's own boundary matches
# IEEE754 float32 exactly, including the subnormal range down to smallest_subnormal --
# not just the "normal" range (tiny).
_REAL_MIN_MAGNITUDE = float(np.finfo(np.float32).smallest_subnormal)
_REAL_MAX_MAGNITUDE = float(np.finfo(np.float32).max)


def _clamp_to_real_range(value: Any) -> Any:
    """Clamp a Python float (typically computed in float64) to what Postgres's `real`
    column type can actually store, before it reaches a bulk_update_by_key COPY/UPDATE
    targeting one.

    Root-caused live 2026-08-14 (todo 312): regime_writer.py's HMM posterior
    probabilities occasionally produce a residual state probability (or entropy value)
    smaller in magnitude than float4 can represent at all -- e.g. 1e-50 for a highly
    confident state assignment. Postgres rejects such a value outright ("value out of
    range: underflow") rather than rounding it to zero, even though every consumer of
    these columns already truncates to float32 precision on read (migration 201/312's
    own rationale) -- so a near-zero residual is scientifically indistinguishable from
    exactly 0.0 at any precision that survives the round trip anyway. Clamping the
    underflow tail to 0.0 is the mathematically correct value at this precision, not an
    approximation being papered over. The overflow tail is symmetric defensive coverage
    (no currently known caller writes an out-of-range-large value into a `real` column,
    but the failure mode is identical and costs nothing to guard against here too).

    NaN/Infinity are valid IEEE754 float4 values Postgres accepts natively -- left
    untouched, not this function's concern. `None` (SQL NULL) passes through unchanged.
    """
    if value is None or not isinstance(value, float) or not math.isfinite(value):
        return value
    magnitude = abs(value)
    if magnitude == 0.0 or _REAL_MIN_MAGNITUDE <= magnitude <= _REAL_MAX_MAGNITUDE:
        return value
    if magnitude < _REAL_MIN_MAGNITUDE:
        return 0.0
    return math.copysign(_REAL_MAX_MAGNITUDE, value)


def bulk_update_by_key(
    conn: Any,
    *,
    table: str,
    temp_table: str,
    key_cols: list[str],
    set_cols: list[str],
    col_types: dict[str, str],
    rows: list[tuple],
) -> None:
    """Bulk UPDATE `table` keyed on `key_cols` via COPY into a temp table + one JOIN-UPDATE.

    Replaces per-row execute_batch UPDATE (one index probe per row) with a single
    set-based UPDATE (one merge/hash join for the whole batch). For 50k+ row updates
    this turns thousands of round-trip index lookups into one join — the difference
    between CPU-bound serial row updates and a bulk operation.

    rows: each tuple ordered as (*set_cols, *key_cols) — matches the parameter order
    psycopg executemany() callers already use for `SET ... WHERE key = %s` statements.
    conn: caller commits; this function does not call conn.commit().

    Raises RuntimeError if `table` is a known compressed hypertable
    (_KNOWN_COMPRESSED_HYPERTABLES, below) and no `compressed_hypertable_write_session` is
    currently active for it -- turns "caller forgot to wrap this write in a session" from a
    silent ~1000x-slower forced full-chunk scan (the 2026-08-14 incident: a full night's
    regime_writer.py run converged its HMM compute cleanly and wrote zero rows) into an
    immediate, loud failure at the first UPDATE attempt instead of a multi-hour hang only
    an EXPLAIN would have revealed.

    col_types: also the single source of truth for which columns get float-range-clamped
    (todo 312, 2026-08-14) -- any column declared "real" here has _clamp_to_real_range()
    applied to its value before it reaches the COPY buffer, protecting every current and
    future caller from Postgres's underflow/overflow rejection uniformly, in the shared
    write primitive, rather than requiring each caller to remember its own clamp. This
    makes col_types load-bearing for correctness, not just the temp table's DDL -- keep it
    in sync with the target table's actual column types (a caller that still declares
    "double precision" for a column migrated to "real" gets neither Postgres's DDL-level
    type check nor this clamp).
    """
    if table in _KNOWN_COMPRESSED_HYPERTABLES and _active_write_session_hypertable.get() != table:
        raise RuntimeError(
            f"bulk_update_by_key: {table!r} is a compressed hypertable -- wrap this call in "
            f"compressed_hypertable_write_session(conn, {table!r}) (or the async sibling) "
            "first. See that function's docstring for why a bare UPDATE against a compressed "
            "chunk is ~1000x more expensive than it looks (2026-08-14 incident)."
        )
    all_cols = set_cols + key_cols
    col_defs = ", ".join(f"{c} {col_types[c]}" for c in all_cols)
    real_positions = frozenset(i for i, c in enumerate(all_cols) if col_types[c] == "real")

    with conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE IF NOT EXISTS {temp_table} ({col_defs})")
        cur.execute(f"TRUNCATE {temp_table}")

        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            if real_positions:
                row = tuple(
                    _clamp_to_real_range(v) if i in real_positions else v for i, v in enumerate(row)
                )
            writer.writerow("" if v is None else v for v in row)
        buf.seek(0)
        with cur.copy(
            f"COPY {temp_table} ({', '.join(all_cols)}) FROM STDIN WITH (FORMAT CSV)"
        ) as copy:
            copy.write(buf.getvalue())

        set_clause = ", ".join(f"{c} = v.{c}" for c in set_cols)
        key_clause = " AND ".join(f"t.{c} = v.{c}" for c in key_cols)
        cur.execute(
            f"UPDATE {table} AS t SET {set_clause} FROM {temp_table} AS v WHERE {key_clause}"
        )


# ---------------------------------------------------------------------------
# Compressed-hypertable write session (psycopg-based batch services)
# ---------------------------------------------------------------------------
#
# Every table a batch job bulk-UPDATEs by key here is a compressed TimescaleDB hypertable
# (todo 306 follow-up, 2026-08-14). Deliberately a static set, not a live `timescaledb_
# information.hypertables WHERE compression_enabled` query: bulk_update_by_key's guard
# (below) checks this on every single write call and must not add a DB round trip to that
# hot path.
#
# The two drift directions are NOT equally safe (2026-08-14 altitude review correction --
# an earlier version of this comment claimed they were). A table left in this set after it
# stops being compressed is harmless: compressed_hypertable_write_session's own per-entry
# chunk query just finds zero chunks and no-ops. A table that's missing -- becomes
# compressed later, or is used via bulk_update_by_key for the first time while already
# compressed, before anyone adds it here -- is NOT caught by anything: bulk_update_by_key's
# guard is gated on membership in this exact set, so a missing entry means the guard simply
# never fires and the write proceeds unwrapped, silently reintroducing the ~1000x-slower
# forced-seq-scan bug this whole mechanism exists to prevent. Todo 308 tracks replacing this
# with a process-lifetime-cached live query (same cache-at-init shape as ConfigService/
# VocabularyService, so the hot-path objection above still holds) -- deliberately not done
# in the same sweep that added this set, for the same reason services/ic_engine.py's write
# paths were deferred to todo 307: a shared mutable cache with real sync/async and
# cross-test-isolation implications deserves its own focused pass, not a bolt-on in the
# final stretch of an already-large diff.
_KNOWN_COMPRESSED_HYPERTABLES = frozenset({"feature_vectors", "feature_ic_scores"})

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
# unless the caller opens one itself, unconfirmed live). regime_writer.py and
# forward_return_writer.py already disable this specific GUC at connect time
# (`options="-c idle_in_transaction_session_timeout=0"`), making this override redundant
# for them specifically -- kept anyway because compressed_hypertable_write_session is
# shared infrastructure serving callers that don't all follow that convention (e.g. a bare
# `psycopg.connect()`, todo 316's own one-off remediation script). See also
# src/intelligence/pipeline/cache_manager.py's independent `SET idle_session_timeout = 0`
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


def _validate_compressed_hypertable(hypertable: str) -> None:
    """Defense-in-depth: re-validate against the known-hypertable allow-list right before
    SQL interpolation (VACUUM's target can't be a bind parameter), even though every caller
    path sources `hypertable` from a hardcoded literal, never user input. Same pattern as
    regime_writer.py's `_validate_label_column` / `ops_regime_null_out_and_verify.py`'s
    `_validate_label_column`."""
    if hypertable not in _KNOWN_COMPRESSED_HYPERTABLES:
        raise ValueError(
            f"compressed_hypertable_write_session: {hypertable!r} is not a known compressed "
            f"hypertable ({sorted(_KNOWN_COMPRESSED_HYPERTABLES)}). Add it to "
            "_KNOWN_COMPRESSED_HYPERTABLES if this is a genuine new compressed write target."
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
def compressed_hypertable_write_session(conn: Any, hypertable: str):
    """Brackets a batch of row-level UPDATEs against a compressed TimescaleDB hypertable.

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
    both `_KNOWN_COMPRESSED_HYPERTABLES` tables is now bracketed, but a future new raw
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

        with conn.cursor() as cur:
            cur.execute(_COMPRESS_ALL_DECOMPRESSED_CHUNKS_SQL, (hypertable,))
            n_recompressed = cur.rowcount
        conn.commit()

        prior_autocommit = conn.autocommit
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                # hypertable validated against _KNOWN_COMPRESSED_HYPERTABLES above -- never
                # attacker-controlled, and VACUUM's target can't be a bind parameter.
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


def limit_blas_threads(n_threads: int) -> None:
    """ProcessPoolExecutor `initializer`: caps this worker's BLAS thread pool.

    Without this, every worker's numpy/scipy/hmmlearn calls default to spawning
    one OpenBLAS thread per logical core (24 on this host) -- with N ProcessPoolExecutor
    workers already providing process-level parallelism, that's an N x oversubscription
    of the same core count. Measured (todo 216): an isolated single-process GaussianHMM
    fit (50k rows, 5D obs, K=5 -- regime_writer's real shape) ran 2.5x slower at the
    default 24 threads than capped to 1 (4.65s vs 1.86s), with zero contention from other
    processes. Small-state HMM/rank-IC workloads operate on tiny per-step matrices; BLAS
    thread coordination overhead exceeds any parallel gain, even before counting the real
    12-worker contention this fixes on top of that.

    Thread count does change the exact floating-point result (not just wall time) --
    verified empirically, not assumed: the same fit at threads=1 vs threads=24 produced
    means_/transmat_/covars_ differing at ~1e-10 absolute, from BLAS reduction-order
    noise. But the discrete Viterbi state assignments -- what actually gets written as
    `regime` -- were byte-identical across all 50,000 observations in that test. This is
    why blas_threads_per_worker is classified OPERATIONAL, not COMPUTATIONAL, in
    ic_engine.py's fingerprint system (see _OPERATIONAL_CONFIG_FIELDS): it moves the
    16th significant digit, not the labels or IC values anything downstream reads.

    Called once per worker at pool startup (fork or spawn, both call the initializer
    before any task runs) -- not a context manager, the limit is meant to persist for
    the worker's whole lifetime.

    threadpoolctl.threadpool_limits() only reaches ALREADY-LOADED BLAS libraries (it
    calls into the runtime library's own thread-count API, it does not set an env var)
    -- if OpenBLAS isn't loaded yet when this runs, the call is a silent no-op and the
    worker's later `import numpy` gets an uncapped pool. The explicit `import numpy`
    below (this module's own top-level import would happen to cover it too, since
    unpickling this function to call it as a ProcessPoolExecutor initializer requires
    importing this module first -- but that's an incidental guarantee a future edit
    could break without any test catching it) makes the load-before-cap ordering
    load-bearing and self-contained instead.
    """
    import numpy  # noqa: F401  -- load-bearing: must be loaded before threadpool_limits()
    import threadpoolctl

    threadpoolctl.threadpool_limits(n_threads)


def make_worker_pool(
    n_workers: int, blas_threads_per_worker: int, **kwargs: Any
) -> ProcessPoolExecutor:
    """ProcessPoolExecutor with the BLAS thread cap already wired in (todo 216).

    Every batch service's ProcessPoolExecutor should be constructed through this, not
    directly -- a bare ProcessPoolExecutor(...) silently reintroduces the OpenBLAS
    oversubscription bug limit_blas_threads() fixes, with no test to catch the omission.
    kwargs forward to ProcessPoolExecutor unchanged (e.g. mp_context=).
    """
    return ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=limit_blas_threads,
        initargs=(blas_threads_per_worker,),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Async APR loading (asyncpg-based batch services)
# ---------------------------------------------------------------------------
#
# Consolidates a pattern previously copy-pasted verbatim across ensemble_trainer.py,
# alpha_publisher.py, and ensemble_ic_engine.py: load alpha.* (+ each service's own
# infra.<name>.* keys) into a raw dict, then cast with a small type-inferring helper
# (todo 048, 2026-07-02).


async def load_apr_dict_async(conn: Any, extra_like_patterns: list[str] | None = None) -> Any:
    """Load alpha.* (+ optional extra LIKE patterns, e.g. a service's own infra.<name>.*)
    APR keys via asyncpg into a raw {config_key: config_value} dict.

    conn: open asyncpg connection or pool-acquired connection.
    extra_like_patterns: additional SQL LIKE patterns (e.g. "infra.ensemble_ic_engine.%"),
        OR'd in alongside the default "alpha.%". Bound as a single array parameter via
        LIKE ANY($1::text[]) -- the codebase's established idiom for a dynamic-length
        pattern list (see ic_engine.py, bar_auditor.py, signal_probe_auditor.py), not a
        hand-rolled OR-chain of positional placeholders.

    Returns a plain dict, not a ConfigService -- callers cast values with cfg().
    """
    patterns = ["alpha.%", *(extra_like_patterns or [])]
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        patterns,
    )
    return {r["config_key"]: r["config_value"] for r in rows}


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
        # hypertable validated against _KNOWN_COMPRESSED_HYPERTABLES above -- never
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


def cfg(cfg_dict: dict[str, Any], key: str, default: Any) -> Any:
    """Cast a raw config_value to default's type, or return default if unset.

    bool is special-cased: config_value is always TEXT (e.g. "false"), and
    `bool("false")` is True in Python since any non-empty string is truthy --
    `type(default)(val)` would silently invert every falsy bool APR flag. Parsed
    via the same `str(val).lower() == "true"` idiom ic_engine.py's ConfigService
    path already uses for `alpha.regime.equity_model_enabled`.

    list/dict defaults are also special-cased (todo 187): `type(default)(val)` against
    a raw JSON-array/object string is a documented-broken cast (e.g.
    `list("[1,3,5,10]")` splits into individual characters, not the parsed list) --
    already fixed for dict defaults via `get_dict_config` below, generalized here so
    `cfg()` itself is safe for any json-typed default instead of every list-typed
    caller needing its own local `json.loads` workaround.
    """
    val = cfg_dict.get(key)
    if val is None:
        return default
    if isinstance(default, bool):
        return str(val).strip().lower() == "true"
    if isinstance(default, (list, dict)):
        return json.loads(val) if isinstance(val, str) else val
    return type(default)(val)


def resolve_per_tf(cfg_dict: dict[str, Any], key_base: str, tf: str, default: Any) -> Any:
    """Resolve a per-timeframe APR override, falling back to the global default.

    Exact precedent: alpha.frame.hold_max_bars.<regime>.<tf> (services/alpha_frame_writer.py).
    Relocated from services/ensemble_trainer.py (todo 009 Part D Item 4) — a pure,
    generic one-liner whose only dependency (cfg() above) already lives here, so a
    second consumer can use it without importing the whole ensemble_trainer service.
    meta_eligible (BH-FDR eligibility, ensemble_trainer-specific domain logic) stays
    in ensemble_trainer.py and calls this — only the generic resolver belongs in a
    shared services-wide utils file, not the eligibility logic built on top of it.
    """
    return cfg(cfg_dict, f"{key_base}.{tf}", default)


LOOKAHEAD_FALLBACKS_BY_TF: dict[str, dict[str, int]] = {
    "5m": {"fast": 1, "mid": 6, "slow": 12, "extended": 39},
    "15m": {"fast": 1, "mid": 2, "slow": 5, "extended": 10},
    "1h": {"fast": 1, "mid": 2, "slow": 20, "extended": 60},
    "1d": {"fast": 1, "mid": 2, "slow": 5, "extended": 10},
}
"""Todo 146's confirmed per-tf IC lookahead grid, as bar-count VALUES (distinct from
ACTIVE_SCALES_FALLBACKS_BY_TF above, which controls which of these are attempted).
1h's slow(20)/extended(60) are unchanged from the old global default -- these bar
counts were never the problem; the now-removed same-ET-session completeness gate
(todo 208) was. Whether 20/60 bars is still the *right* grid for 1h once measured
under the corrected, session-agnostic completeness definition is a separate, open
tier-count/spacing question (todo 208's Step 3, deliberately deferred, not settled
by this table). Single source of truth for ICEngineConfig, EnsembleICConfig, and
forward_return_writer.py's from_apr()/loading logic -- do not re-literal this grid
in any of those files; import it from here."""


def lookahead_by_scale_from_apr(get: Callable[[str, Any], Any]) -> dict[str, dict[str, int]]:
    """Build the {scale: {tf: lookahead_bars}} config-derived dict (todo 146), shared
    by ICEngineConfig.from_apr, EnsembleICConfig.from_apr, and AblationConfig.from_apr.
    `get(key, default)` abstracts over ConfigService.get_sync (ic_engine.py, wrapped
    in int() by the caller) vs. the dict-based cfg() helper above (ensemble_ic_engine.py,
    ops_ensemble_ablation.py) -- the two getter shapes those three from_apr()s use."""
    return {
        scale: {
            tf: get(f"alpha.ic.lookahead.{tf}.{scale}", fb[scale])
            for tf, fb in LOOKAHEAD_FALLBACKS_BY_TF.items()
        }
        for scale in _CANONICAL_SCALE_ORDER
    }


def lookaheads_for_tf(
    lookahead_fast: dict[str, int],
    lookahead_mid: dict[str, int],
    lookahead_slow: dict[str, int],
    lookahead_extended: dict[str, int],
    tf: str,
) -> dict[str, int]:
    """Shared resolver behind ICEngineConfig.lookaheads_for/EnsembleICConfig.lookaheads_for
    (todo 146). Both classes stay independent frozen+picklable dataclasses (separate
    ProcessPoolExecutor pools) -- only the per-tf lookup logic itself is shared."""
    return {
        "fast": lookahead_fast[tf],
        "mid": lookahead_mid[tf],
        "slow": lookahead_slow[tf],
        "extended": lookahead_extended[tf],
    }


def bars_to_scale_map(scale_to_bars: dict[str, int], *, context: str = "") -> dict[int, str]:
    """Invert a {scale: lookahead_bars} mapping (e.g. one tf's `lookaheads_for_tf()`
    output) into {lookahead_bars: scale}, raising loudly on a collision (two scales
    resolving to the same bar count) instead of silently letting the second overwrite
    the first -- an uncaught collision would slice a cell against the wrong scale's
    return_{scale}/complete_{scale} columns with no error. Single source of truth for
    this reverse-lookup, shared by every ops script that maps a `feature_ic_scores.
    lookahead_bars` DB value back to a scale name (todo 211 part 2's own fix
    surfaced two prior independent reimplementations, `ops_ic_shrinkage.py`'s
    `_lookahead_bars_to_scale_by_tf` and `ops_ic_null_calibration.py`'s inline
    comprehension, neither of which had this collision check).

    `context` is an optional caller-supplied label (e.g. a tf name) included only in
    the error message, for a clearer failure.
    """
    bars_to_scale: dict[int, str] = {}
    for scale, bars in scale_to_bars.items():
        if bars in bars_to_scale:
            label = f" (tf={context!r})" if context else ""
            raise ValueError(
                f"lookahead_bars={bars} for scale={scale!r} collides with scale "
                f"{bars_to_scale[bars]!r}{label}, already mapped to that same "
                "lookahead_bars value -- two lookahead APR keys must not resolve to "
                "the same lookahead_bars."
            )
        bars_to_scale[bars] = scale
    return bars_to_scale


def _get_json_typed_config(cfg_service: ConfigService, key: str, default: dict | list) -> Any:
    """Shared implementation behind `get_dict_config`/`get_list_config`: read a
    JSON-typed APR key via `ConfigService.get_sync()`, tolerating either a pre-parsed
    dict/list (the normal case -- `load_config_service_sync`'s `_parse_value` already
    `json.loads()`s `value_type='json'` keys at cache-load time) or a raw JSON string
    (test/fallback default path). `cfg()` above can't be reused here: its
    `type(default)(val)` cast breaks for a dict/list default against a raw JSON-string
    value.
    """
    v = cfg_service.get_sync(key, default)
    if isinstance(v, type(default)):
        return v
    if isinstance(v, str):
        return json.loads(v)
    return default


def get_dict_config(cfg_service: ConfigService, key: str, default: dict) -> dict:
    """Read a JSON-object APR key -- see `_get_json_typed_config`."""
    return _get_json_typed_config(cfg_service, key, default)


_CANONICAL_SCALE_ORDER: tuple[str, ...] = ("fast", "mid", "slow", "extended")


def canonicalize_active_scales(scales: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Normalize a configured active-scale list to _CANONICAL_SCALE_ORDER, deduped.

    The APR value's configured order is never semantically meaningful -- an
    operator editing alpha.ic.active_scales.{tf} via /config/parameters could
    write ["mid","fast"] or ["fast","mid"] and mean the identical active set.
    Canonicalizing here (rather than sorting inside _compute_apr_snapshot_key)
    keeps the fingerprint hash deterministic without special-casing tuple-valued
    dict entries in a function shared by every other COMPUTATIONAL config field.

    Raises ValueError on any name outside _CANONICAL_SCALE_ORDER -- a typo'd scale
    name must fail loud, not silently shrink the active set (CLAUDE.md: silent
    wrong answers are worse than loud crashes).

    An empty input list (`[]`) normalizes to a genuinely empty tuple `()` -- this
    function does NOT fall back to any default for an empty input. (The fallback
    to a tf's default active-scale set happens one layer up, in the config-read
    helpers, and only when the APR key is entirely ABSENT -- an explicitly
    configured empty list is passed through here as-is and stays empty.)
    """
    scale_set = set(scales)
    unknown = scale_set - set(_CANONICAL_SCALE_ORDER)
    if unknown:
        raise ValueError(
            f"canonicalize_active_scales: unknown scale name(s) {sorted(unknown)} -- "
            f"must be a subset of {_CANONICAL_SCALE_ORDER}."
        )
    return tuple(s for s in _CANONICAL_SCALE_ORDER if s in scale_set)


ACTIVE_SCALES_FALLBACKS_BY_TF: dict[str, tuple[str, ...]] = {
    "5m": _CANONICAL_SCALE_ORDER,
    "15m": _CANONICAL_SCALE_ORDER,
    "1h": _CANONICAL_SCALE_ORDER,
    "1d": _CANONICAL_SCALE_ORDER,
}
"""Per-tf active-scale set (2026-07-30 design, docs/superpowers/specs/2026-07-30-
per-tf-active-scale-set-design.md). All four tfs currently active at all four
scales (reverted 2026-07-30, migration 272): 1h's earlier slow/extended exclusion
was based on 0.000 completeness measured under the same-ET-session gate that
forward_return_writer.py has since removed (todo 208) -- that gate was the sole
reason 1h's slow/extended read as unmeasurable, not a property of 1h itself.
Reversible again via a single config change (alpha.ic.active_scales.1h) alone,
no code change, if a future investigation finds a real reason to exclude a
scale for some tf. Single source of truth for ICEngineConfig/EnsembleICConfig's
from_apr() -- do not re-literal this table in either file; import it from here."""


def get_list_config(cfg_service: ConfigService, key: str, default: list) -> list:
    """Read a JSON-array APR key -- see `_get_json_typed_config`. Sibling of
    `get_dict_config` above."""
    return _get_json_typed_config(cfg_service, key, default)


class Float32ChunkAccumulator:
    """Buffers rows into vstack-ready float32 chunks, freeing each chunk's Python-list
    intermediate as soon as it's converted (todo 087).

    Shared 'accumulate rows -> np.array chunk -> vstack once at the end, discarding
    intermediates' idiom behind ic_engine.py's per-symbol OOM fix (`_compute_symbol_tf`,
    a named server-side cursor streaming rows one at a time) and its cross-sectional
    OOM fix (`_compute_cross_sectional_tf`, a plain cursor re-executed per explicit
    timestamp chunk, fetching a whole batch per query). The query/cursor/pagination
    mechanics genuinely differ between those two callers and are left entirely to
    them; this owns only the buffer-to-float32-array bookkeeping both duplicated.

    Two append modes, matching the two callers' shapes:
    - append_row(): one row at a time, auto-flushed into a chunk every `flush_at` rows
      (the streaming-cursor shape).
    - append_chunk(): one pre-fetched batch at a time, converted to a chunk immediately
      (the re-executed-per-query-chunk shape). Ignores an empty batch.
    """

    def __init__(self, flush_at: int | None = None) -> None:
        self._flush_at = flush_at
        self._chunks: list[np.ndarray] = []
        self._buf: list = []

    def append_row(self, row: Any) -> None:
        self._buf.append(row)
        if self._flush_at is not None and len(self._buf) >= self._flush_at:
            self._flush_buf()

    def append_chunk(self, rows: Any) -> None:
        if len(rows):
            self._chunks.append(np.array(rows, dtype=np.float32))

    def _flush_buf(self) -> None:
        if self._buf:
            self._chunks.append(np.array(self._buf, dtype=np.float32))
            self._buf = []

    def finalize(self) -> np.ndarray | None:
        """vstack every chunk and free them; None if nothing was ever appended."""
        self._flush_buf()
        if not self._chunks:
            return None
        result = np.vstack(self._chunks)
        self._chunks = []
        return result
