"""Shared utilities for batch oneshot services (psycopg-based, plus a small asyncpg
APR-loading helper for the async batch services)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np
import psycopg
import psycopg.sql as pg_sql
import structlog
from psycopg.types.json import Jsonb

from src.config.config_service import ConfigService
from src.core.code_identity import FIRST_PARTY_PACKAGES, code_key, import_closure
from src.core.real_column_range import REAL_MAX_MAGNITUDE, REAL_MIN_MAGNITUDE, clamp_to_real_range
from src.core.service_utils import format_iso_ts

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


# Postgres `real` (IEEE 754 float4) range clamp -- promoted to src/core/real_column_range.py
# (2026-09-22, underflow-7symbol-real-column debug session) so a Ring 1 module
# (feature_vector_persistence.py) can share it too without importing services/ (Ring rule).
# Aliased here under the original private names so this module's existing callers/tests don't
# need to change; the implementation lives in exactly one place now.
_REAL_MIN_MAGNITUDE = REAL_MIN_MAGNITUDE
_REAL_MAX_MAGNITUDE = REAL_MAX_MAGNITUDE
_clamp_to_real_range = clamp_to_real_range


def bulk_update_by_key(
    conn: Any,
    *,
    table: str,
    temp_table: str,
    key_cols: list[str],
    set_cols: list[str],
    col_types: dict[str, str],
    rows: list[tuple],
) -> int:
    """Bulk UPDATE `table` keyed on `key_cols` via COPY into a temp table + one JOIN-UPDATE.

    Returns the JOIN-UPDATE's rowcount (rows of `table` actually updated), so a caller can
    report what changed without a follow-up count query.

    Replaces per-row execute_batch UPDATE (one index probe per row) with a single
    set-based UPDATE (one merge/hash join for the whole batch). For 50k+ row updates
    this turns thousands of round-trip index lookups into one join — the difference
    between CPU-bound serial row updates and a bulk operation.

    rows: each tuple ordered as (*set_cols, *key_cols) — matches the parameter order
    psycopg executemany() callers already use for `SET ... WHERE key = %s` statements.
    conn: caller commits; this function does not call conn.commit().

    Raises RuntimeError if `table` is a known compressed hypertable
    (`_known_compressed_hypertables`, below) and no `compressed_hypertable_write_session` is
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
    if (
        table in _known_compressed_hypertables(conn)
        and _active_write_session_hypertable.get() != table
    ):
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
        return int(cur.rowcount)


# ---------------------------------------------------------------------------
# bulk_load: the one bulk-load primitive (phase 186 plan 06, D-24; absorbs
# todo 301 shared COPY primitive, todo 343 shared per-unit failure isolation,
# and todo 352 shared accumulate-and-flush -- streaming COPY removes the need
# to accumulate anything). No existing writer is converted: 186-14 (fresh IC
# writer) and 186-25 (feature_vectors rebuild) are the consumers.
# ---------------------------------------------------------------------------

_BULK_LOAD_STATEMENT_TIMEOUT_APR_KEY = "infra.bulk_load.statement_timeout_ms"
_BULK_LOAD_DEFAULT_STATEMENT_TIMEOUT_MS = 14_400_000  # see migration 386 for provenance
_BULK_LOAD_COMPRESS_ON_COMPLETE_APR_KEY = "infra.bulk_load.compress_on_complete"
_BULK_LOAD_DEFAULT_COMPRESS_ON_COMPLETE = True  # see migration 386 for provenance

_BULK_LOAD_APR_SQL = "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)"
_BULK_LOAD_COLUMNS_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = %s"
)


def table_column_types(conn: Any, table: str) -> dict[str, str]:
    """{column_name: data_type} of `table` in the connection's current schema, from
    information_schema (dtype comes from the schema, never from row data). A table with no
    columns does not exist, and raises, so a schema identifier that will be composed into SQL
    is validated by the same read that types its columns. The one sync read of this catalog:
    bulk_load and the IC writer use it; `fetch_table_columns` is its asyncpg twin over the
    public schema."""
    with conn.cursor() as cur:
        cur.execute(_BULK_LOAD_COLUMNS_SQL, (table,))
        types: dict[str, str] = dict(cur.fetchall())
    if not types:
        raise ValueError(f"table {table} does not exist in the current schema")
    return types


_BULK_LOAD_TIME_DIMENSION_SQL = (
    "SELECT column_name FROM timescaledb_information.dimensions "
    "WHERE hypertable_name = %s AND dimension_number = 1"
)
_BULK_LOAD_COMPRESSION_JOBS_SQL = (
    "SELECT job_id, scheduled, (config->>'compress_after')::interval AS compress_after "
    "FROM timescaledb_information.jobs "
    "WHERE hypertable_name = %s AND proc_name = 'policy_compression'"
)
_BULK_LOAD_COMPRESSED_CHUNKS_SQL = (
    "SELECT count(*) FROM timescaledb_information.chunks "
    "WHERE hypertable_name = %s AND is_compressed AND range_start < %s AND range_end > %s"
)
_BULK_LOAD_TRY_LOCK_SQL = "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))"
_BULK_LOAD_UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtextextended(%s, 0))"
_BULK_LOAD_SELECT_PROVENANCE_SQL = (
    "SELECT status, row_count, attempts FROM provenance_batch WHERE batch_key = %s"
)
_BULK_LOAD_INSERT_PROVENANCE_SQL = (
    "INSERT INTO provenance_batch (batch_key, writer, target_table, time_column, tf, "
    "range_start, range_end, symbols, symbols_hash, code_key, apr_hash, apr_snapshot, "
    "input_digest, unit_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_BULK_LOAD_TAKEOVER_PROVENANCE_SQL = (
    "UPDATE provenance_batch SET status = 'started', attempts = attempts + 1, "
    "started_at = now(), error = NULL WHERE batch_key = %s"
)
_BULK_LOAD_COMPLETE_PROVENANCE_SQL = (
    "UPDATE provenance_batch SET status = 'completed', row_count = %s, "
    "finished_at = now(), error = NULL WHERE batch_key = %s"
)
_BULK_LOAD_FAIL_PROVENANCE_SQL = (
    "UPDATE provenance_batch SET status = 'failed', error = %s WHERE batch_key = %s"
)
# The replace path's flip (186-14, migration 416): every other completed row of the same unit (same
# unit_key: writer, target, tf and replace_where) becomes superseded; the guard trigger allows
# exactly this transition and changes nothing else on the row.
_BULK_LOAD_SUPERSEDE_PROVENANCE_SQL = (
    "UPDATE provenance_batch SET status = 'superseded' WHERE unit_key = %s "
    "AND status = 'completed' AND batch_key <> %s"
)
_PRIOR_COMPLETED_UNIT_SQL = (
    "SELECT 1 FROM provenance_batch WHERE unit_key = %s AND status = 'completed' "
    "AND batch_key <> %s LIMIT 1"
)
_PROVENANCE_BATCH_COLUMNS = (
    "batch_key",
    "writer",
    "target_table",
    "time_column",
    "tf",
    "range_start",
    "range_end",
    "symbols",
    "symbols_hash",
    "code_key",
    "apr_hash",
    "apr_snapshot",
    "input_digest",
    "unit_key",
    "row_count",
    "status",
    "attempts",
    "error",
    "started_at",
    "finished_at",
)
_COMPLETED_PROVENANCE_SQL = (
    "SELECT " + ", ".join(_PROVENANCE_BATCH_COLUMNS) + " FROM provenance_batch "
    "WHERE batch_key = %s AND status = 'completed'"
)
_CHUNKS_TO_COMPRESS_SQL = (
    "SELECT chunk_schema, chunk_name FROM timescaledb_information.chunks "
    "WHERE hypertable_name = %s AND NOT is_compressed AND range_end <= %s "
    "ORDER BY range_start"
)
# %%I escaping, same reason as _DECOMPRESS_ALL_COMPRESSED_CHUNKS_SQL above: psycopg's
# client-side placeholder scanner rejects a single '%I' inside a parameterized statement.
_COMPRESS_ONE_CHUNK_SQL = (
    # ::text pins format()'s overload: with untyped parameters Postgres cannot choose
    # among format(text), format(text, text), ... and fails with IndeterminateDatatype.
    "SELECT compress_chunk(format('%%I.%%I', %s::text, %s::text)::regclass, "
    "if_not_compressed => true)"
)

_BULK_LOAD_HEX_32_64_RE = re.compile(r"^[0-9a-f]{32,64}$")


@dataclass(frozen=True)
class BulkLoadSpec:
    """Identity of one bulk-load unit; batch_key is its idempotency key (D-37).

    Every field participates in the identity: a change to any one of them (one APR
    value included, through apr_snapshot) produces a different batch_key, so a rerun
    that recomputed anything is a new load, not a skipped one.
    """

    writer: str
    target_table: str
    time_column: str
    tf: str
    range_start: datetime  # half-open unit range [range_start, range_end), tz-aware UTC
    range_end: datetime
    symbols: tuple[str, ...]  # stored sorted; order never changes the identity
    code_key: str  # per-kernel code key (D-23), lowercase hex
    apr_snapshot: Mapping[str, Any]
    input_digest: str  # lowercase hex
    # None: an append-only unit (a primary-key conflict is a loud error). A mapping: the unit owns
    # the target rows it names (col = value, or col = ANY for a list, within the half-open time
    # range); loading it deletes them and supersedes the unit's prior completed batches in the
    # same transaction. See `unit_key`.
    replace_where: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for name in ("writer", "target_table", "time_column", "tf"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"BulkLoadSpec.{name} must be a non-empty string")
        for name in ("range_start", "range_end"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise ValueError(f"BulkLoadSpec.{name} must be a tz-aware datetime")
        if self.range_start >= self.range_end:
            raise ValueError(
                "BulkLoadSpec.range_start must be before range_end (the unit range is half-open)"
            )
        if not self.symbols:
            raise ValueError("BulkLoadSpec.symbols must be non-empty")
        object.__setattr__(self, "symbols", tuple(sorted(self.symbols)))
        if self.replace_where is not None and not self.replace_where:
            raise ValueError("BulkLoadSpec.replace_where must name at least one column")
        for name in ("code_key", "input_digest"):
            if not _BULK_LOAD_HEX_32_64_RE.fullmatch(getattr(self, name)):
                raise ValueError(f"BulkLoadSpec.{name} must be 32-64 lowercase hex characters")

    @property
    def apr_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.apr_snapshot, sort_keys=True, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()

    @property
    def symbols_hash(self) -> str:
        return hashlib.sha256("|".join(self.symbols).encode()).hexdigest()

    @property
    def unit_key(self) -> str:
        """Identity of the unit whose rows a replacing load owns: sha256 over (writer, target,
        tf, replace_where), computed here once and used by both the DELETE predicate's owner
        (the mapping it hashes) and the provenance supersede flip. Symbols, range, code, APR and
        input are deliberately absent: a change to any of them replaces the unit instead of
        loading beside it. Two units that must coexist differ in writer, tf or replace_where.
        List values hash sorted, so their order never matters."""
        where = None
        if self.replace_where is not None:
            where = {
                column: (
                    sorted(map(str, value))
                    if isinstance(value, list | tuple | set | frozenset)
                    else str(value)
                )
                for column, value in self.replace_where.items()
            }
        identity = {
            "writer": self.writer,
            "target_table": self.target_table,
            "tf": self.tf,
            "replace_where": where,
        }
        return hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @property
    def batch_key(self) -> str:
        identity = {
            "writer": self.writer,
            "target_table": self.target_table,
            "tf": self.tf,
            "range_start": format_iso_ts(self.range_start),
            "range_end": format_iso_ts(self.range_end),
            "symbols_hash": self.symbols_hash,
            "code_key": self.code_key,
            "apr_hash": self.apr_hash,
            "input_digest": self.input_digest,
            "unit_key": self.unit_key,
        }
        return hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class BulkLoadResult:
    """Outcome of one bulk_load call: loaded (this call streamed the rows) or skipped
    (a completed provenance row with the same identity already exists)."""

    batch_key: str
    status: Literal["loaded", "skipped"]
    row_count: int
    chunks_compressed: int
    rows_replaced: int = 0  # rows the replace_where DELETE removed (0 when not replacing)


class BulkLoadRefused(RuntimeError):
    """bulk_load refused to write: a scheduled compression policy already covers the
    unit's range, a compressed chunk overlaps it, another session holds the unit's
    advisory lock, or the spec's time_column is not the target's time dimension.
    Refusals happen before any COPY; the target is untouched."""


def bulk_load(
    conn: Any,
    spec: BulkLoadSpec,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    compress_before: datetime | None = None,
) -> BulkLoadResult:
    """Load one (symbols x tf x time range) unit into spec.target_table (D-24).

    The one bulk-load primitive for phase 186's writers; no existing writer uses it
    yet (186-14, the fresh IC writer, and 186-25, the feature_vectors rebuild, are
    the consumers). Streams `rows` with COPY in time order into the rowstore chunks
    of the target, records one provenance_batch row whose primary key (batch_key) is
    the idempotency key, and compresses completed chunks.

    Contract (this is NOT bulk_update_by_key's caller-commits contract -- bulk_load
    commits, because the provenance lifecycle needs its own commits):

    - conn: a psycopg 3 sync connection, not in autocommit, with no open transaction
      holding uncommitted work. Async callers run bulk_load on a dedicated psycopg
      connection via asyncio.to_thread; there is one primitive, not an asyncpg
      sibling.
    - Idempotency: a completed provenance row for the same batch_key returns
      ("skipped", stored row_count) without touching the target. A started row (a
      kill) or a failed row is taken over: status back to started, attempts + 1.
      The started row is committed before any checks run, so a killed load leaves a
      visible started row and zero target rows (the data COPY and the completed
      provenance update commit atomically).
    - Session advisory lock on the batch key: another session loading the same unit
      raises BulkLoadRefused ("another session is loading unit ...").
    - Refusals (BulkLoadRefused), all before any COPY: a scheduled compression
      policy whose compress_after already covers range_start; any compressed chunk
      overlapping [range_start, range_end); a time_column that is not the target's
      time dimension. A column name not in the target's live schema raises
      ValueError.
    - The float32 clamp is driven by the live information_schema types, never by a
      caller-supplied col_types (the todo 312 drift class cannot happen here).
    - Append-only by default: a primary-key conflict on the target is a loud error,
      never ON CONFLICT DO NOTHING. A spec with `replace_where` is the explicit, atomic
      replacement of a unit's prior rows, used when a unit's identity changes (the IC
      writer, D-23): in the data transaction, before COPY, one DELETE bounded by the spec's
      half-open time range and the mapping (col = value, or col = ANY for a list), and every
      other completed provenance row with the same `spec.unit_key` flips to 'superseded', so
      a replaced unit keeps one completed row, the current key. The unit key hashes
      (writer, target, tf, replace_where) once, so the DELETE and the flip cannot disagree
      and a change of symbols, range, code, APR or input replaces the unit instead of
      loading beside it. Units that must coexist in one target differ in writer, tf or
      replace_where; nothing else separates them. A failure rolls back the DELETE, the flip
      and the COPY together. A superseded key is terminal and cannot be loaded again
      (BulkLoadRefused). provenance_batch.target_table is immutable once written.
    - Every row's time value is validated (tz-aware, inside the half-open unit
      range, non-decreasing) before it reaches the COPY buffer; a violation rolls
      the data transaction back, marks the provenance row failed in its own commit,
      and re-raises. A failure while marking failed is logged once and the original
      exception still propagates.
    - compress_before: when given (and infra.bulk_load.compress_on_complete is
      true), every chunk of the target entirely at or before that boundary is
      compress_chunk()ed after the data commit, one chunk per statement and commit.
      The table keeps its primary key (no direct-compress COPY, D-37).
    """
    batch_key = spec.batch_key
    if spec.time_column not in columns:
        raise ValueError(
            f"bulk_load: columns must contain the spec's time column {spec.time_column!r}"
        )
    time_idx = list(columns).index(spec.time_column)

    with conn.cursor() as cur:
        cur.execute(_BULK_LOAD_TRY_LOCK_SQL, (batch_key,))
        (locked,) = cur.fetchone()
    if not locked:
        raise BulkLoadRefused(f"another session is loading unit {batch_key}")

    try:
        return _bulk_load_locked(conn, spec, columns, rows, time_idx, compress_before)
    finally:
        # Session advisory locks survive commit/rollback, so the unlock is explicit;
        # the SELECT opens a read transaction that is rolled back immediately after.
        try:
            with conn.cursor() as cur:
                cur.execute(_BULK_LOAD_UNLOCK_SQL, (batch_key,))
            conn.rollback()
        except Exception as error:
            _logger.warning(
                "batch_utils.bulk_load_unlock_error",
                batch_key=batch_key,
                error=str(error),
            )


def _bulk_load_locked(
    conn: Any,
    spec: BulkLoadSpec,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    time_idx: int,
    compress_before: datetime | None,
) -> BulkLoadResult:
    """bulk_load's body, run under the batch key's session advisory lock."""
    batch_key = spec.batch_key

    # Provenance lifecycle first: the started row is visible (committed) before any
    # check or COPY, so a kill at any later point leaves a retryable started row.
    with conn.cursor() as cur:
        cur.execute(_BULK_LOAD_SELECT_PROVENANCE_SQL, (batch_key,))
        existing = cur.fetchone()
        if existing is not None and existing[0] == "completed":
            conn.rollback()  # read-only transaction, nothing to keep
            return BulkLoadResult(
                batch_key=batch_key,
                status="skipped",
                row_count=int(existing[1]),
                chunks_compressed=0,
            )
        if existing is not None and existing[0] == "superseded":
            conn.rollback()
            raise BulkLoadRefused(
                f"bulk_load: unit {batch_key} was superseded by a later identity; a "
                "superseded key is terminal and cannot be loaded again"
            )
        if existing is None:
            cur.execute(
                _BULK_LOAD_INSERT_PROVENANCE_SQL,
                (
                    batch_key,
                    spec.writer,
                    spec.target_table,
                    spec.time_column,
                    spec.tf,
                    spec.range_start,
                    spec.range_end,
                    list(spec.symbols),
                    spec.symbols_hash,
                    spec.code_key,
                    spec.apr_hash,
                    Jsonb(dict(spec.apr_snapshot)),
                    spec.input_digest,
                    spec.unit_key,
                ),
            )
        else:  # started (a kill) or failed (a retry): take the row over
            cur.execute(_BULK_LOAD_TAKEOVER_PROVENANCE_SQL, (batch_key,))
    conn.commit()

    real_positions = _bulk_load_precheck(conn, spec, columns)
    apr = _bulk_load_read_apr(conn)
    timeout_ms = cfg(
        apr, _BULK_LOAD_STATEMENT_TIMEOUT_APR_KEY, _BULK_LOAD_DEFAULT_STATEMENT_TIMEOUT_MS
    )
    compress_on_complete = cfg(
        apr,
        _BULK_LOAD_COMPRESS_ON_COMPLETE_APR_KEY,
        _BULK_LOAD_DEFAULT_COMPRESS_ON_COMPLETE,
    )

    row_count = 0
    rows_replaced = 0
    try:
        with conn.cursor() as cur:
            # SET LOCAL semantics (transaction-scoped) without a second round trip to
            # read the prior value: the data transaction below is short-lived and the
            # session-level value is untouched.
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(int(timeout_ms)),))
            if spec.replace_where is not None:
                delete_stmt, delete_params = _bulk_load_delete_statement(spec, spec.replace_where)
                cur.execute(delete_stmt, delete_params)
                rows_replaced = cur.rowcount
                cur.execute(_BULK_LOAD_SUPERSEDE_PROVENANCE_SQL, (spec.unit_key, batch_key))
            copy_stmt = pg_sql.SQL("COPY {} ({}) FROM STDIN").format(
                pg_sql.Identifier(spec.target_table),
                pg_sql.SQL(", ").join(pg_sql.Identifier(c) for c in columns),
            )
            last_time: datetime | None = None
            with cur.copy(copy_stmt) as copy:
                for row_idx, row in enumerate(rows):
                    row = tuple(row)
                    time_value = row[time_idx]
                    if not isinstance(time_value, datetime) or time_value.tzinfo is None:
                        raise ValueError(
                            f"bulk_load: row {row_idx} time value must be a tz-aware datetime"
                        )
                    if time_value < spec.range_start or time_value >= spec.range_end:
                        raise ValueError(
                            f"bulk_load: row {row_idx} time {format_iso_ts(time_value)} is "
                            "outside the unit range [range_start, range_end)"
                        )
                    if last_time is not None and time_value < last_time:
                        raise ValueError(
                            f"bulk_load: row {row_idx} time is earlier than the previous row "
                            "(rows must stream in time order)"
                        )
                    last_time = time_value
                    if real_positions:
                        row = tuple(
                            _clamp_to_real_range(v) if i in real_positions else v
                            for i, v in enumerate(row)
                        )
                    copy.write_row(row)
                    row_count += 1
            cur.execute(_BULK_LOAD_COMPLETE_PROVENANCE_SQL, (row_count, batch_key))
        conn.commit()
    except Exception as error:
        conn.rollback()
        _bulk_load_mark_failed(conn, batch_key, error)
        raise

    chunks_compressed = 0
    if compress_before is not None and compress_on_complete:
        chunks_compressed = compress_completed_chunks(conn, spec.target_table, compress_before)

    _logger.info(
        "batch_utils.bulk_load_complete",
        batch_key=batch_key,
        target=spec.target_table,
        rows=row_count,
        rows_replaced=rows_replaced,
        chunks_compressed=chunks_compressed,
    )
    return BulkLoadResult(
        batch_key=batch_key,
        status="loaded",
        row_count=row_count,
        chunks_compressed=chunks_compressed,
        rows_replaced=rows_replaced,
    )


def _bulk_load_delete_statement(
    spec: BulkLoadSpec, replace_where: Mapping[str, Any]
) -> tuple[pg_sql.Composed, list[Any]]:
    """The replace path's one DELETE: the unit's half-open time range plus the mapping's
    equality (scalar) or = ANY (list) predicates. Identifiers are composed, never formatted;
    the keys were validated against the live column set by the precheck."""
    clauses = [
        pg_sql.SQL("{} >= %s").format(pg_sql.Identifier(spec.time_column)),
        pg_sql.SQL("{} < %s").format(pg_sql.Identifier(spec.time_column)),
    ]
    params: list[Any] = [spec.range_start, spec.range_end]
    for column, value in replace_where.items():
        if isinstance(value, list | tuple | set | frozenset):
            clauses.append(pg_sql.SQL("{} = ANY(%s)").format(pg_sql.Identifier(column)))
            params.append(list(value))
        else:
            clauses.append(pg_sql.SQL("{} = %s").format(pg_sql.Identifier(column)))
            params.append(value)
    statement = pg_sql.SQL("DELETE FROM {} WHERE {}").format(
        pg_sql.Identifier(spec.target_table), pg_sql.SQL(" AND ").join(clauses)
    )
    return statement, params


def _bulk_load_precheck(
    conn: Any,
    spec: BulkLoadSpec,
    columns: Sequence[str],
) -> frozenset[int]:
    """All refusal checks, before any COPY. Returns the positions (into `columns`)
    whose live information_schema data_type is 'real' -- the clamp set, read from the
    live schema rather than any caller-supplied col_types (todo 312 drift class)."""
    live_columns = table_column_types(conn, spec.target_table)
    missing = [c for c in columns if c not in live_columns]
    if missing:
        raise ValueError(
            f"bulk_load: columns not present in the live schema of "
            f"{spec.target_table!r}: {missing}"
        )
    unknown_keys = [c for c in (spec.replace_where or {}) if c not in live_columns]
    if unknown_keys:
        raise ValueError(
            f"bulk_load: replace_where columns not present in the live schema of "
            f"{spec.target_table!r}: {unknown_keys}"
        )
    real_positions = frozenset(i for i, c in enumerate(columns) if live_columns[c] == "real")
    with conn.cursor() as cur:
        cur.execute(_BULK_LOAD_TIME_DIMENSION_SQL, (spec.target_table,))
        dimensions = [row[0] for row in cur.fetchall()]
    if not dimensions:
        return real_positions  # a plain table: no compression concerns apply
    if dimensions[0] != spec.time_column:
        raise BulkLoadRefused(
            f"bulk_load: {spec.target_table!r} time dimension is {dimensions[0]!r}, "
            f"spec says {spec.time_column!r}"
        )
    with conn.cursor() as cur:
        cur.execute(_BULK_LOAD_COMPRESSION_JOBS_SQL, (spec.target_table,))
        jobs = cur.fetchall()
        cur.execute(
            _BULK_LOAD_COMPRESSED_CHUNKS_SQL,
            (spec.target_table, spec.range_end, spec.range_start),
        )
        (compressed_in_range,) = cur.fetchone()
    for _job_id, scheduled, compress_after in jobs:
        if scheduled and compress_after is not None:
            if datetime.now(UTC) - spec.range_start > compress_after:
                raise BulkLoadRefused(
                    f"bulk_load: a scheduled compression policy on {spec.target_table!r} "
                    f"already covers {format_iso_ts(spec.range_start)} (compress_after "
                    f"{compress_after}); refusing to load under it"
                )
    if compressed_in_range:
        raise BulkLoadRefused(
            f"bulk_load: {compressed_in_range} compressed chunk(s) of "
            f"{spec.target_table!r} overlap the unit range"
        )
    return real_positions


def _bulk_load_read_apr(conn: Any) -> dict[str, Any]:
    """Both infra.bulk_load.* keys in one config_state read, the same direct read
    _assert_decompress_headroom uses (APR mandate: no hard-coded fallback path)."""
    with conn.cursor() as cur:
        cur.execute(
            _BULK_LOAD_APR_SQL,
            ([_BULK_LOAD_STATEMENT_TIMEOUT_APR_KEY, _BULK_LOAD_COMPRESS_ON_COMPLETE_APR_KEY],),
        )
        return dict(cur.fetchall())


def _bulk_load_mark_failed(conn: Any, batch_key: str, error: Exception) -> None:
    """Record the failure in its own commit (per-unit isolation, todo 343). A failure
    of the mark itself is logged once, never per row, and never masks the original
    exception (the caller re-raises it regardless)."""
    try:
        with conn.cursor() as cur:
            cur.execute(_BULK_LOAD_FAIL_PROVENANCE_SQL, (str(error)[:2000], batch_key))
        conn.commit()
    except Exception as mark_error:
        _logger.warning(
            "batch_utils.bulk_load_mark_failed_error",
            batch_key=batch_key,
            error=str(mark_error),
        )
        try:
            conn.rollback()
        except Exception:
            pass


def completed_provenance_batch(conn: Any, spec: BulkLoadSpec) -> dict[str, Any] | None:
    """The completed provenance row for spec.batch_key, or None. Lets a caller skip
    computing a unit before paying for it (186-25 resume after a kill)."""
    with conn.cursor() as cur:
        cur.execute(_COMPLETED_PROVENANCE_SQL, (spec.batch_key,))
        row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(_PROVENANCE_BATCH_COLUMNS, row))


def prior_completed_unit(conn: Any, spec: BulkLoadSpec) -> bool:
    """True when a completed batch of the same unit (spec.unit_key) exists under a different
    batch_key: loading `spec` replaces it. Lets a dry run report would_replace."""
    with conn.cursor() as cur:
        cur.execute(_PRIOR_COMPLETED_UNIT_SQL, (spec.unit_key, spec.batch_key))
        return cur.fetchone() is not None


def compress_completed_chunks(conn: Any, target_table: str, before: datetime) -> int:
    """Compress every uncompressed chunk of target_table whose range_end <= before,
    one compress_chunk(..., if_not_compressed => true) per chunk, committing after
    each, and return how many were compressed. Never takes TimescaleDB's
    direct-compress COPY path (it requires dropping the primary key, D-37); the
    table keeps its primary key."""
    with conn.cursor() as cur:
        cur.execute(_CHUNKS_TO_COMPRESS_SQL, (target_table, before))
        chunks = cur.fetchall()
    for chunk_schema, chunk_name in chunks:
        with conn.cursor() as cur:
            cur.execute(_COMPRESS_ONE_CHUNK_SQL, (chunk_schema, chunk_name))
        conn.commit()
    if chunks:
        _logger.info(
            "batch_utils.bulk_load_chunks_compressed",
            target=target_table,
            chunks=len(chunks),
        )
    return len(chunks)


# ---------------------------------------------------------------------------
# Provenance identity helpers (phase 186 plan 14, D-23): the per-kernel code key and the
# per-symbol bar content digest that, with the APR snapshot, make a unit's identity.
# ---------------------------------------------------------------------------


def kernel_code_key(
    modules: Iterable[str],
    *,
    own: Iterable[str] = (),
    packages: Collection[str] = FIRST_PARTY_PACKAGES,
) -> str:
    """Code identity of one job: sha256 over the AST-normalized source of the entry modules, every
    first-party module they import (transitively, found with `ast`, imports inside functions
    included) and the `own` modules, as 64 lowercase hex (D-23; see `src.core.code_identity`).

    The caller names the entry modules of the computation; the import closure is derived, so an
    import added to a computation module moves the key without a hand-kept list to update. Not
    ic_engine's all-imports key (`code_content_key`, which hashes everything loaded into the
    process): a module outside the closure never moves it. `own` modules are hashed as files
    without following their imports (a writer's orchestration module). Names are de-duplicated
    and sorted, so order does not matter. An empty entry list raises ValueError and a name that
    cannot be resolved raises ModuleNotFoundError, never a silent skip.
    """
    return code_key(kernel_code_modules(modules, own=own, packages=packages))


def kernel_code_modules(
    modules: Iterable[str],
    *,
    own: Iterable[str] = (),
    packages: Collection[str] = FIRST_PARTY_PACKAGES,
) -> tuple[str, ...]:
    """The sorted module names `kernel_code_key` hashes for these entries."""
    entries = sorted(set(modules))
    if not entries:
        raise ValueError("kernel_code_key: at least one module name is required")
    return import_closure(entries, own, packages)


_BAR_DIGEST_SQL = (
    "SELECT symbol, range_start, digest FROM bar_content_digest_current "
    "WHERE timeframe = %s AND symbol = ANY(%s) AND range_start >= %s AND range_start < %s"
)
_BAR_DIGEST_EMPTY_MONTH = "empty"
_BAR_DIGEST_ABSENT_SYMBOL = "absent"


def _month_starts(start: datetime, end_exclusive: datetime) -> list[datetime]:
    """UTC calendar month starts covering [start, end_exclusive)."""
    months = []
    cursor = start.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor < end_exclusive:
        months.append(cursor)
        cursor = (
            cursor.replace(year=cursor.year + 1, month=1)
            if cursor.month == 12
            else cursor.replace(month=cursor.month + 1)
        )
    return months


def bar_content_digests(
    conn: Any, tf: str, symbols: Sequence[str], start: datetime, end_exclusive: datetime
) -> dict[str, str]:
    """One digest per symbol for bars of `tf` in [start, end_exclusive), composed from phase
    185's month digests (`bar_content_digest_current`, the one definition of the bar content
    digest; nothing is re-hashed here and no second row encoding exists).

    Per symbol: sha256 over the month-ordered (month, digest) pairs, where a month in range with
    no digest row contributes the literal "empty", so a month gaining rows (a recovery, a
    scrub revision) flips the result; absence is explicit input, never a skipped aggregate.
    A symbol with no digest row at all maps to "absent": the caller must treat that as
    revision detection being blind for that symbol (digests only exist once 185 has written
    them), not as a stable value.

    Granularity is the calendar month: the month containing `end_exclusive` is digested whole,
    so a revision of a bar in that month after `end_exclusive` also moves the result
    (conservative over-invalidation); months wholly after it never do. The caller owns the read
    connection; this function does not commit.
    """
    for name, value in (("start", start), ("end_exclusive", end_exclusive)):
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"bar_content_digests: {name} must be a tz-aware datetime")
    if start >= end_exclusive:
        raise ValueError("bar_content_digests: start must be before end_exclusive")
    months = _month_starts(start, end_exclusive)
    with conn.cursor() as cur:
        cur.execute(_BAR_DIGEST_SQL, (tf, list(symbols), months[0], end_exclusive))
        rows = cur.fetchall()
    by_symbol: dict[str, dict[datetime, str]] = {}
    for symbol, range_start, digest in rows:
        by_symbol.setdefault(symbol, {})[range_start.astimezone(UTC)] = digest
    out: dict[str, str] = {}
    for symbol in symbols:
        present = by_symbol.get(symbol)
        if not present:
            out[symbol] = _BAR_DIGEST_ABSENT_SYMBOL
            continue
        lines = [
            f"{format_iso_ts(month)}:{present.get(month, _BAR_DIGEST_EMPTY_MONTH)}"
            for month in months
        ]
        out[symbol] = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    return out


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
# feature_ic_scores_v2 (phase 186 plan 14): an empty fresh table with no scheduled compression policy;
# the session runs against it for services/ic_measure.py (decompress, recompress and VACUUM, which
# the plan 186-14 integration test exercises on indicagent_test).
_WRITE_SESSION_HARDENED_TABLES = frozenset(
    {"feature_vectors", "feature_ic_scores", "feature_ic_scores_v2"}
)


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


# table_schema filter is mandatory: omitting it returns same-named tables from other schemas
# (e.g. timescaledb_internal), producing false "column exists" verdicts.
_TABLE_COLUMNS_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns"
    " WHERE table_schema = 'public' AND table_name = $1"
)


async def fetch_table_columns(conn: Any, table: str) -> dict[str, str]:
    """{column_name: data_type} of a public-schema table, from information_schema.

    `conn` is anything with an asyncpg-style `fetch(sql, *args)` (a connection, a pool or the
    DatabaseManager). dtype comes from the schema, never from inferred row data."""
    rows = await conn.fetch(_TABLE_COLUMNS_SQL, table)
    return {row["column_name"]: row["data_type"] for row in rows}


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

    Two accumulation modes (additive, Phase 174 D-04 / todo 371 -- NOT a forked
    parallel class; migration 249 already corrected that exact mistake once for
    `_check_cell_size` and RESEARCH.md's Don't-Hand-Roll table names it again):
    - In-RAM (default, disk_backed=False): byte-for-byte the original behavior above.
      `finalize()` holds the full chunk list AND the vstacked result in RAM
      simultaneously -- roughly 2x the cell size at peak. Fine for small cells; this
      is what OOM-killed ic_engine at universe scale for the largest cross-sectional
      cells (todo 371).
    - Disk-backed (disk_backed=True): both append modes write directly into an
      `np.memmap`-backed scratch file at a running row offset instead of a Python
      list of chunks. `finalize()` returns a VIEW over the memmap -- no
      `np.vstack`, no copy -- so peak anonymous RSS is bounded by one chunk's size,
      not the whole cell's size. Requires `estimated_rows` (a conservative upper
      bound on total rows the caller's pre-flight estimate produced) and `n_cols`
      up front to pre-allocate the memmap; `finalize()` trims the returned view to
      the actual rows written. An under-estimate is crash-loud (`ValueError`) rather
      than silently truncating the cell -- per CLAUDE.md, "silent wrong answers are
      worse than loud crashes," and a silently short cell would change what the
      corpus measures.

    Memmap ownership contract (disk-backed mode only -- load-bearing for Plans 05 and
    09, both reviewers flagged this as the phase's highest-risk ambiguity):
    - `finalize()` returns a VIEW over the memmap, not a copy.
    - The caller owns `close()` and calls it only after every consumer of the
      returned view has returned: the caller's `try`/`finally` must span every
      downstream consumer, not just the accumulation loop, so the scratch file's disk
      space is reclaimed as soon as the cell is done.
    - A view that outlives `close()` is still memory-safe: `close()` unlinks the file
      but never unmaps it, so the view keeps reading this cell's own data until it is
      garbage-collected (Linux keeps an unlinked, still-mapped inode alive). Holding
      one holds the scratch file's disk pages, so it is a leak to fix, never a
      correctness hazard.
    """

    def __init__(
        self,
        flush_at: int | None = None,
        *,
        disk_backed: bool = False,
        estimated_rows: int | None = None,
        n_cols: int | None = None,
        scratch_dir: str | None = None,
    ) -> None:
        self._flush_at = flush_at
        self._chunks: list[np.ndarray] = []
        self._buf: list = []
        self._disk_backed = disk_backed
        self._write_offset = 0
        self._estimated_rows: int | None = None
        self._memmap: np.memmap | None = None
        self._tmpfile: Any = None
        if disk_backed:
            missing = [
                name
                for name, val in (("estimated_rows", estimated_rows), ("n_cols", n_cols))
                if not val
            ]
            if missing:
                raise ValueError(
                    "Float32ChunkAccumulator(disk_backed=True) requires "
                    f"{' and '.join(missing)} to be set"
                )
            self._estimated_rows = estimated_rows
            if scratch_dir:
                os.makedirs(scratch_dir, exist_ok=True)
            self._tmpfile = tempfile.NamedTemporaryFile(
                dir=scratch_dir, suffix=".memmap", delete=False
            )
            self._memmap = np.memmap(
                self._tmpfile.name,
                dtype=np.float32,
                mode="w+",
                shape=(estimated_rows, n_cols),
            )

    def append_row(self, row: Any) -> None:
        if self._disk_backed and self._flush_at is None:
            # Without flush_at every row stays in the Python buffer until finalize(),
            # so a disk-backed accumulator would hold the whole cell in RAM -- the
            # exact thing disk-backing exists to prevent (174 review IN-07).
            raise ValueError(
                "Float32ChunkAccumulator(disk_backed=True).append_row() requires flush_at; "
                "use append_chunk() or construct with flush_at"
            )
        self._buf.append(row)
        if self._flush_at is not None and len(self._buf) >= self._flush_at:
            self._flush_buf()

    def append_chunk(self, rows: Any) -> None:
        if not len(rows):
            return
        if self._disk_backed:
            self._write_disk_chunk(rows)
        else:
            self._chunks.append(np.array(rows, dtype=np.float32))

    def _write_disk_chunk(self, rows: Any) -> None:
        """Write one batch directly into the memmap at the running offset.

        Crash-loud on overflow (Phase 174 D-04, todo 371 / T-174-06): a pre-flight
        row estimate that undercounts must fail loud, never silently truncate the
        cell -- that would change what is measured, exactly the failure class the
        cross-sectional cell-size guard already exists to forbid elsewhere.
        """
        arr = np.array(rows, dtype=np.float32)
        n = arr.shape[0]
        end = self._write_offset + n
        if self._estimated_rows is not None and end > self._estimated_rows:
            raise ValueError(
                f"Float32ChunkAccumulator disk-backed overflow: estimated_rows="
                f"{self._estimated_rows} but this write would reach {end} rows -- "
                "the pre-flight row estimate undercounted; fix the estimate, do not "
                "silently truncate the cell"
            )
        self._memmap[self._write_offset : end] = arr
        self._write_offset = end

    def _flush_buf(self) -> None:
        if not self._buf:
            return
        if self._disk_backed:
            self._write_disk_chunk(self._buf)
        else:
            self._chunks.append(np.array(self._buf, dtype=np.float32))
        self._buf = []

    def finalize(self) -> np.ndarray | None:
        """Disk-backed: flush any buffered rows, then return
        `self._memmap[: self._write_offset]` -- a VIEW over the memmap, no
        `np.vstack`, no copy. That view stays readable until, and only until, the
        caller calls `close()`; the caller's `try`/`finally` must span every
        downstream consumer of this return value, not just the accumulation loop
        (see the class docstring's memmap ownership contract). Returns `None` (and
        cleans up the scratch file immediately via `close()`) when nothing was ever
        appended, matching the in-RAM mode's empty contract.

        In-RAM: vstack every chunk and free them; None if nothing was ever appended.
        """
        self._flush_buf()
        if self._disk_backed:
            if self._write_offset == 0:
                self.close()
                return None
            return self._memmap[: self._write_offset]
        if not self._chunks:
            return None
        result = np.vstack(self._chunks)
        self._chunks = []
        return result

    def close(self) -> None:
        """Release a disk-backed accumulator's resources: flush and drop the memmap,
        close the underlying `NamedTemporaryFile` handle, then unlink the scratch file.
        Not closing the `NamedTemporaryFile` leaks one Python file descriptor per
        accumulator (T-174-39) -- across the thousands of cells in a corpus run that
        exhausts the process fd limit. The mapping itself is released when its last
        view is garbage-collected, never by an explicit close (see below).

        Idempotent: safe to call twice, and a no-op in in-RAM mode. Each step is
        wrapped independently so a failure in one does not skip the others. Plan 05's
        caller invokes this in a `finally` block that spans every consumer of
        `finalize()`'s returned view -- see the class docstring's ownership contract.
        """
        path = self._tmpfile.name if self._tmpfile is not None else None
        if self._memmap is not None:
            try:
                self._memmap.flush()
            except Exception as error:
                _logger.warning("float32_chunk_accumulator.mmap_flush_failed", error=str(error))
            # Drop the reference; never close the mmap explicitly. An explicit
            # `_mmap.close()` turned any still-live view into a use-after-unmap:
            # a segfault, or -- once a later cell's memmap reused the address -- a
            # silent read of another cell's data (174 review WR-06). Without it the
            # kernel unmaps when the last view is garbage-collected, and a stale read
            # returns this cell's own data.
            self._memmap = None
        if self._tmpfile is not None:
            try:
                self._tmpfile.close()
            except Exception as error:
                _logger.warning("float32_chunk_accumulator.tmpfile_close_failed", error=str(error))
            finally:
                self._tmpfile = None
        if path is not None:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except Exception as error:
                _logger.warning(
                    "float32_chunk_accumulator.unlink_failed", path=path, error=str(error)
                )

    def __enter__(self) -> Float32ChunkAccumulator:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
