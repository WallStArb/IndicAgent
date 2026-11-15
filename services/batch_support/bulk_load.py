"""bulk_load: the sole writer of provenance_batch, with its advisory lock, precheck and recompress."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import psycopg.sql as pg_sql
import structlog
from psycopg.types.json import Jsonb

from services.batch_support.config import cfg
from services.batch_support.db import table_column_types
from src.core.canonical_json import canonical_json
from src.core.real_column_range import clamp_to_real_range
from src.core.service_utils import format_iso_ts

_logger = structlog.get_logger()


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
# The latest row of a batch_key: a returning superseded identity has several (migration 418).
_BULK_LOAD_SELECT_PROVENANCE_SQL = (
    "SELECT status, row_count, attempts, generation FROM provenance_batch "
    "WHERE batch_key = %s ORDER BY generation DESC LIMIT 1"
)
_BULK_LOAD_INSERT_PROVENANCE_SQL = (
    "INSERT INTO provenance_batch (batch_key, writer, target_table, time_column, tf, "
    "range_start, range_end, symbols, symbols_hash, code_key, apr_hash, apr_snapshot, "
    "input_digest, unit_key, generation, run_id) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
# A takeover re-stamps the run: a retry under a new run never keeps the old run_id (the 578 guard
# allows the change only on this transition to started).
_BULK_LOAD_TAKEOVER_PROVENANCE_SQL = (
    "UPDATE provenance_batch SET status = 'started', attempts = attempts + 1, "
    "started_at = now(), error = NULL, run_id = %s WHERE batch_key = %s AND generation = %s"
)
# unit_stats (migration 583): what the writer measured of the unit's rows (the rebuild's per
# object column present / nan_present counts), recorded with the completion and frozen with it.
_BULK_LOAD_COMPLETE_PROVENANCE_SQL = (
    "UPDATE provenance_batch SET status = 'completed', row_count = %s, "
    "finished_at = now(), error = NULL, unit_stats = %s "
    "WHERE batch_key = %s AND generation = %s"
)
_BULK_LOAD_FAIL_PROVENANCE_SQL = (
    "UPDATE provenance_batch SET status = 'failed', error = %s "
    "WHERE batch_key = %s AND generation = %s"
)
# The replace path's flip (186-14, migrations 416 and 418): every other completed row of the same
# unit (same unit_key: writer, target, tf and replace_where) becomes superseded; the guard trigger
# allows exactly this transition and changes nothing else on the row.
_BULK_LOAD_SUPERSEDE_PROVENANCE_SQL = (
    "UPDATE provenance_batch SET status = 'superseded' WHERE unit_key = %s "
    "AND status = 'completed' AND NOT (batch_key = %s AND generation = %s)"
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
    "generation",
    "run_id",
    "unit_stats",
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

_TIMESTAMPTZ_MIN = datetime(1, 1, 1, tzinfo=UTC)
_BULK_LOAD_HEX_32_64_RE = re.compile(r"^[0-9a-f]{32,64}$")


# Tables with exactly one bulk_load writer (single_writer invariant). bulk_load names the target
# through sql.Identifier, so no source grep can see a second caller; this check refuses one when
# its spec is built. A value ending in "." admits that service's jobs (ic_measure writes as
# "ic_measure.<job>"); any other value is the exact writer, because a reader matches it exactly
# (feature_inputs.REBUILD_WRITER for feature_vectors). feature_vectors: the rebuild writer (todo
# 590); feature_ic_scores: ic_measure (migration 413, D-17).
SOLE_BULK_LOAD_WRITERS: dict[str, str] = {
    "feature_vectors": "backfill-feature-factory",
    "feature_ic_scores": "ic_measure.",
}


def parse_run_id(value: str) -> str:
    """The canonical (lowercase, hyphenated) form of a corpus_run id; raises ValueError on
    anything that is not a uuid. Also the argparse `type` of every --run-id flag, so a bad id
    is refused before any compute."""
    return str(uuid.UUID(value))


# The units a corpus run adopted (186-31, lead amendment 2026-11-05): a unit skipped because a
# completed row with its identity already existed keeps that row's older run_id (completed rows
# are immutable), so the run records it in the completed step's summary as {unit_key, batch_key,
# adopted_from_run_id}. Every one-run check reads them through this query.
RUN_ADOPTIONS_SQL = (
    "SELECT a->>'batch_key', a->>'adopted_from_run_id' FROM corpus_run_step s "
    "CROSS JOIN LATERAL jsonb_array_elements(COALESCE(s.summary->'adopted', '[]'::jsonb)) a "
    "WHERE s.run_id = %s AND s.status = 'completed'"
)


def belongs_to_run(
    row_run_id: str | None, batch_key: str, run_id: str, adoptions: Mapping[str, str | None]
) -> bool:
    """A completed provenance row counts for `run_id` when it was loaded under it, or when the
    run adopted exactly this batch_key from exactly the run that row records."""
    if row_run_id == run_id:
        return True
    return batch_key in adoptions and adoptions[batch_key] == row_run_id


def bulk_load_unit_key(
    writer: str, target_table: str, tf: str, replace_where: Mapping[str, Any] | None
) -> str:
    """BulkLoadSpec.unit_key's one definition, for a reader that resolves a unit to its
    provenance rows without building a spec (the canary gate, 186-30)."""
    where = None
    if replace_where is not None:
        where = {
            column: (
                sorted(map(str, value))
                if isinstance(value, list | tuple | set | frozenset)
                else str(value)
            )
            for column, value in replace_where.items()
        }
    identity = {
        "writer": writer,
        "target_table": target_table,
        "tf": tf,
        "replace_where": where,
    }
    return hashlib.sha256(canonical_json(identity).encode()).hexdigest()


@dataclass(frozen=True)
class BulkLoadSpec:
    """Identity of one bulk-load unit; batch_key is its idempotency key (D-37).

    Every field but run_id participates in the identity: a change to any one of them (one APR
    value included, through apr_snapshot) produces a different batch_key, so a rerun
    that recomputed anything is a new load, not a skipped one. run_id is execution metadata,
    outside batch_key and unit_key: a unit resumed or skipped under another run keeps its
    identity.
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
    # the target rows it names (col = value, or col = ANY for a list, over all time, whatever
    # the range); loading it deletes them and supersedes the unit's prior completed batches in the
    # same transaction. See `unit_key`.
    replace_where: Mapping[str, Any] | None = None
    # The corpus_run this load runs under (migration 578), recorded on the provenance row; None
    # outside a run. Not identity: see the class docstring.
    run_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("writer", "target_table", "time_column", "tf"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"BulkLoadSpec.{name} must be a non-empty string")
        sole = SOLE_BULK_LOAD_WRITERS.get(self.target_table)
        admitted = (
            self.writer.startswith(sole) if sole and sole.endswith(".") else self.writer == sole
        )
        if sole is not None and not admitted:
            raise ValueError(
                f"BulkLoadSpec: {self.target_table!r} has one writer, {sole!r}; "
                f"refusing writer {self.writer!r}"
            )
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
        if self.run_id is not None and parse_run_id(self.run_id) != self.run_id:
            raise ValueError("BulkLoadSpec.run_id must be a canonical lowercase uuid string")

    @property
    def apr_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.apr_snapshot).encode()).hexdigest()

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
        return bulk_load_unit_key(self.writer, self.target_table, self.tf, self.replace_where)

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
        return hashlib.sha256(canonical_json(identity).encode()).hexdigest()


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
    preclamped_real: bool = False,
    unit_stats: Mapping[str, Any] | None = None,
) -> BulkLoadResult:
    """Load one (symbols x tf x time range) unit into spec.target_table (D-24).

    `unit_stats` (optional) is recorded on the completed provenance row (migration 583): what
    the writer measured of the rows it streamed, never part of the unit's identity.

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
      `preclamped_real=True` is the whole-column producer's opt-out: the caller
      guarantees every real-column value already satisfies the clamp (it ran
      `clamp_to_real_range_array` over its columns before spooling), so the per-row
      clamp is skipped. Time validation still runs on every row.
    - Append-only by default: a primary-key conflict on the target is a loud error,
      never ON CONFLICT DO NOTHING. A spec with `replace_where` is the explicit, atomic
      replacement of a unit's prior rows, used when a unit's identity changes (the IC
      writer, D-23): in the data transaction, before COPY, one DELETE over the mapping (col =
      value, or col = ANY for a list) across all time (the unit owns its whole scope), and every
      other completed provenance row with the same `spec.unit_key` flips to 'superseded', so
      a replaced unit keeps one completed row, the current key. The unit key hashes
      (writer, target, tf, replace_where) once, so the DELETE and the flip cannot disagree
      and a change of symbols, range, code, APR or input replaces the unit instead of
      loading beside it. Units that must coexist in one target differ in writer, tf or
      replace_where; nothing else separates them. A failure rolls back the DELETE, the flip
      and the COPY together. A superseded row is terminal, but its identity may return
      (inputs going back to an earlier state): the load then inserts a new provenance row of
      the same batch_key with generation + 1 (migration 418), leaving the superseded row as
      history. provenance_batch.target_table is immutable once written.
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
        return _bulk_load_locked(
            conn, spec, columns, rows, time_idx, compress_before, preclamped_real, unit_stats
        )
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
    preclamped_real: bool,
    unit_stats: Mapping[str, Any] | None = None,
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
        if existing is None or existing[0] == "superseded":
            # A first load, or an identity that another one replaced and that has returned: a new
            # row (generation + 1). The superseded row is history and stays as it is.
            generation = 1 if existing is None else int(existing[3]) + 1
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
                    generation,
                    spec.run_id,
                ),
            )
        else:  # started (a kill) or failed (a retry): take the row over
            generation = int(existing[3])
            cur.execute(_BULK_LOAD_TAKEOVER_PROVENANCE_SQL, (spec.run_id, batch_key, generation))
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
                cur.execute(
                    _BULK_LOAD_SUPERSEDE_PROVENANCE_SQL, (spec.unit_key, batch_key, generation)
                )
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
                    if real_positions and not preclamped_real:
                        row = tuple(
                            clamp_to_real_range(v) if i in real_positions else v
                            for i, v in enumerate(row)
                        )
                    copy.write_row(row)
                    row_count += 1
            cur.execute(
                _BULK_LOAD_COMPLETE_PROVENANCE_SQL,
                (
                    row_count,
                    None if unit_stats is None else Jsonb(dict(unit_stats)),
                    batch_key,
                    generation,
                ),
            )
        conn.commit()
    except Exception as error:
        conn.rollback()
        _bulk_load_mark_failed(conn, batch_key, generation, error)
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
    """The replace path's one DELETE: the mapping's equality (scalar) or = ANY (list) predicates,
    over all time. A replacing unit owns its whole scope (the unit_key hashes the mapping, not the
    range), so the DELETE and the provenance flip are one definition: a later run with another
    range replaces every row of the scope, leaving none behind without a completed batch. The
    spec's range still bounds the rows a load may write and is recorded as provenance metadata.
    Identifiers are composed, never formatted; the keys were validated against the live column
    set by the precheck."""
    clauses = []
    params: list[Any] = []
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
        # A replacing load's DELETE reaches the whole scope, so every chunk before range_end counts.
        overlap_from = _TIMESTAMPTZ_MIN if spec.replace_where is not None else spec.range_start
        cur.execute(
            _BULK_LOAD_COMPRESSED_CHUNKS_SQL,
            (spec.target_table, spec.range_end, overlap_from),
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


def _bulk_load_mark_failed(conn: Any, batch_key: str, generation: int, error: Exception) -> None:
    """Record the failure in its own commit (per-unit isolation, todo 343). A failure
    of the mark itself is logged once, never per row, and never masks the original
    exception (the caller re-raises it regardless)."""
    try:
        with conn.cursor() as cur:
            cur.execute(_BULK_LOAD_FAIL_PROVENANCE_SQL, (str(error)[:2000], batch_key, generation))
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
    batch_key: loading `spec` replaces it. Lets a dry run report would_replace. An append-only
    spec (no replace_where) replaces nothing, so it is False without a query."""
    if spec.replace_where is None:
        return False
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
