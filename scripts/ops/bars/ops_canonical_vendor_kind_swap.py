r"""market_data_ohlcv_v2 build: canonical `source` becomes `vendor` plus `kind` (phase 191 plan 12).

Design doc step 7, first half (docs/plans/2026-10-12-unified-raw-bar-table-design.md). Updating
`market_data_ohlcv` in place is banned and the dependent views block a column drop, so this is a
rebuild: migration 496 creates an empty `market_data_ohlcv_v2` (structurally identical except
`source` is `vendor text NOT NULL` plus `kind text NOT NULL`); this script copies the live table
into it with the source-to-(vendor, kind) mapping rendered from vendor_kind.LABEL_TO_VENDOR_KIND,
proves the copy equal, and opens nothing else. Plan 14 adds `--swap`, `--post-check` and
`--rollback`; plan 17 drops the kept original and runs the bare `VACUUM market_data_ohlcv;`.

Planner decision D-191-G (owner acknowledgement pending): the build is a copy-with-map from the
live canonical table rather than the design doc's INSERT SELECT from raw. Plan 07 proved
selection-from-raw equals canonical for the direct timeframes; the selection gate re-run on v2
here is the final proof. The copy is exact and avoids recomputing selection over about 450M rows.

Modes (exactly one; none is the preflight dry run):

--preflight   measure and gate, change nothing. Gates: the cutover window is open and every unit
              it holds is inactive; no writer lock, process or unit touches market_data_ohlcv;
              the 186-26 feature rebuild is not running (pg_stat_activity on feature_vectors_v2,
              host processes, and the STATE.md 186-26 lines); every source label of the live
              table maps through LABEL_TO_VENDOR_KIND (NULL included; an unmapped label aborts
              the build, since vendor is NOT NULL); free disk covers the copy estimate times
              infra.canonical_swap.disk_margin; the two tables' shapes match (source exchanged
              for vendor and kind, everything else identical); and the live column set is exactly
              what the copy and digest cover, so a column added later cannot escape them.
--build       the gates, then the copy: one 90-day chunk window per transaction, one serial
              connection, the mapping rendered into the copy SQL. Restartable: a window is done
              when its v2 row count equals the old table's (a compressed chunk is done by
              construction); any other window is cleared and copied again. Windows older than the
              live compression policy's compress_after are compressed and vacuumed as they
              finish, so the copy's peak disk is one window's rows, not the table's.
--prove       per (symbol, timeframe): count equality and a digest of every copied column
              (timestamp, OHLCV, vendor, kind, base, price_sanity_status) between v2 and the old
              table through the mapping; zero differences required. It then runs the plan 07
              selection gate (`ops_selection_gate.py --compare --target market_data_ohlcv_v2`,
              timeframes 1m, 5m and 4h) and requires exit 0: v2 must be a pure function of raw
              plus policy, not merely a faithful copy of whatever canonical held.

Every mode refuses while a writer runs: counts taken from a moving table prove nothing. Exit
status: 0 when every gate or check passes, 3 when any blocks or a step aborts, 2 on a usage
error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.vendor_kind import LABEL_TO_VENDOR_KIND  # noqa: E402

_JOB = "ops-vendor-kind-swap"
_TABLE = "market_data_ohlcv"
_V2_TABLE = "market_data_ohlcv_v2"
_WINDOW_RECORD = project_root / "logs" / "raw_cutover_window.json"
_STATE_MD = project_root / ".planning" / "STATE.md"
_GATE_MODULE = "scripts.ops.bars.ops_selection_gate"
_GATE_REPORT_RE = re.compile(r"^report: (\S+)$", re.MULTILINE)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BLOCKED = 3

# --- APR (migration 496) ----------------------------------------------------------------------

APR_DISK_MARGIN = "infra.canonical_swap.disk_margin"
APR_STATEMENT_TIMEOUT_S = "infra.canonical_swap.statement_timeout_s"
APR_COPY_TIMEOUT_S = "infra.canonical_swap.copy_statement_timeout_s"
APR_LOCK_TIMEOUT_S = "infra.canonical_swap.lock_timeout_s"
APR_STATS_WAIT_S = "infra.canonical_swap.stats_flush_wait_s"
APR_DEFAULTS: dict[str, float] = {
    APR_DISK_MARGIN: 2.0,
    APR_STATEMENT_TIMEOUT_S: 600.0,
    APR_COPY_TIMEOUT_S: 7200.0,
    APR_LOCK_TIMEOUT_S: 30.0,
    APR_STATS_WAIT_S: 11.0,
}

# --- writers ----------------------------------------------------------------------------------

# Advisory lock held by an IBKR history writer: phase 189's fetcher lock, keys derived as in
# scripts/infrastructure/backfill/_fetcher_lock.py.
WRITER_LOCK_NAMES = ("ibkr_history_fetcher",)
# Scripts that write market_data_ohlcv (or chain something that does). Matched against the
# basename of each argv element exactly, so a shell whose command line merely mentions a name
# never matches. Service identity, not a tunable: APR-exempt.
WRITER_SCRIPTS = frozenset(
    {
        "bar_derivation.py",
        "bar_writer.py",
        "bar_auditor.py",
        "bar_reconciliation_audit.py",
        "ibkr_history_fetcher.py",
        "ops_bar_nightly.py",
        "ops_bar_load.py",
    }
)
WRITER_UNITS = (
    "indicagent-ibkr-history-fetcher.service",
    "indicagent-bar-derivation.service",
    "indicagent-bar-writer.service",
    "indicagent-bar-auditor.service",
    "indicagent-bar-reconciliation-audit.service",
)
# The 186-26 feature rebuild (fingerprinted batch writers over feature_vectors_v2) must not run
# in the window either: it reads canonical through the tradeable view while v2 fills the disk.
REBUILD_SCRIPTS = frozenset({"feature_vector_pipeline.py", "ml_orchestrator.py"})
REBUILD_TABLE_PATTERN = "feature_vectors"
_WRITE_LOCK_MODES = frozenset(
    {"RowExclusiveLock", "ShareRowExclusiveLock", "ExclusiveLock", "AccessExclusiveLock"}
)

# --- mapping and digest -----------------------------------------------------------------------

KEY_COLUMNS = ("symbol", "timeframe")
# Every column the copy carries and the digest covers. The preflight proves the live table has
# exactly these (minus the mapping), so a column added later cannot escape the comparison.
DIGEST_COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vendor",
    "kind",
    "base",
    "price_sanity_status",
)
# What the live table must carry: the digest columns with vendor and kind (the v2 side's names
# for the mapped pair) exchanged for source, plus the key columns.
_LIVE_COLUMNS = (frozenset(KEY_COLUMNS) | set(DIGEST_COLUMNS) | {"source"}) - {"vendor", "kind"}
_PLAIN_TOKEN = re.compile(r"^[A-Za-z0-9_]+$")


def _literal(token: str) -> str:
    if not _PLAIN_TOKEN.match(token):
        raise ValueError(f"refusing to render {token!r} into SQL: not a plain token")
    return f"'{token}'"


def mapping_case(column: str) -> str:
    """`CASE source WHEN ... THEN ... END` selecting `column` of the mapped (vendor, kind) pair,
    rendered from vendor_kind.LABEL_TO_VENDOR_KIND (sorted, so the SQL is deterministic). An
    unmapped label (NULL included) yields NULL, which the NOT NULL vendor column rejects loudly."""
    if column not in ("vendor", "kind"):
        raise ValueError(f"no mapped column {column!r}: want 'vendor' or 'kind'")
    index = 0 if column == "vendor" else 1
    whens = " ".join(
        f"WHEN {_literal(label)} THEN {_literal(pair[index])}"
        for label, pair in sorted(LABEL_TO_VENDOR_KIND.items())
    )
    return f"CASE source {whens} END"


_VENDOR_CASE = mapping_case("vendor")
_KIND_CASE = mapping_case("kind")

# The copy's own statements, written out at module level so the boundary scans see the raw reads.
_COPY_WINDOW_SQL = f"""
INSERT INTO market_data_ohlcv_v2
    ("timestamp", symbol, timeframe, open, high, low, close, volume, vendor, kind, base,
     price_sanity_status)
SELECT "timestamp", symbol, timeframe, open, high, low, close, volume,
       {_VENDOR_CASE}, {_KIND_CASE}, base, price_sanity_status
FROM market_data_ohlcv
WHERE "timestamp" >= %s AND "timestamp" < %s
"""
_CLEAR_WINDOW_SQL = """
DELETE FROM market_data_ohlcv_v2 WHERE "timestamp" >= %s AND "timestamp" < %s
"""
_OLD_COUNT_WINDOW_SQL = """
SELECT count(*) FROM market_data_ohlcv WHERE "timestamp" >= %s AND "timestamp" < %s
"""
_V2_COUNT_WINDOW_SQL = """
SELECT count(*) FROM market_data_ohlcv_v2 WHERE "timestamp" >= %s AND "timestamp" < %s
"""

# ROW(...)::text distinguishes NULL from '' and floats print shortest-exact (PostgreSQL 12+), so
# equal digests mean equal rows. The session runs in UTC so timestamps print identically on both
# sides; the old side maps source to (vendor, kind) with the same CASE the copy renders.
_OLD_DIGEST_SQL = f"""
SELECT symbol, timeframe, count(*),
       md5(string_agg(ROW("timestamp", open, high, low, close, volume,
                          {_VENDOR_CASE}, {_KIND_CASE}, base, price_sanity_status)::text,
                          E'\\n' ORDER BY "timestamp"))
FROM market_data_ohlcv
WHERE symbol = ANY(%s)
GROUP BY symbol, timeframe
"""
_V2_DIGEST_SQL = """
SELECT symbol, timeframe, count(*),
       md5(string_agg(ROW("timestamp", open, high, low, close, volume, vendor, kind,
                          base, price_sanity_status)::text, E'\\n' ORDER BY "timestamp"))
FROM market_data_ohlcv_v2
WHERE symbol = ANY(%s)
GROUP BY symbol, timeframe
"""
# Every symbol with any row on either side (a series on one side only is a difference). symbol is
# a segmentby column, so this reads compressed-batch metadata, not the rows.
_SYMBOLS_SQL = "SELECT DISTINCT symbol FROM {}"


class SwapAborted(RuntimeError):
    """A check failed. The step that raised changed nothing (its transaction rolled back)."""


class SwapRefused(RuntimeError):
    """A writer is running; the operation would read or write a moving table."""


def format_ts(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gib(n: float) -> float:
    return round(n / 2**30, 2)


# --- writer and rebuild checks ----------------------------------------------------------------


@dataclass(frozen=True)
class WriterState:
    lock_holders: tuple[str, ...] = ()  # application_name of each advisory holder
    processes: tuple[str, ...] = ()  # "pid script" of each writer process
    active_units: tuple[str, ...] = ()
    write_locks: tuple[str, ...] = ()  # "pid mode relation" of each foreign write lock
    rebuild_activity: tuple[str, ...] = ()  # "pid left(query,60)" of each feature_vectors session
    rebuild_processes: tuple[str, ...] = ()


def writer_blockers(state: WriterState) -> list[str]:
    """Every writer found, one line each. Empty means nothing writes the table right now."""
    return (
        [f"lock held: {h}" for h in state.lock_holders]
        + [f"writer process: {p}" for p in state.processes]
        + [f"writer unit active: {u}" for u in state.active_units]
        + [f"write lock: {w}" for w in state.write_locks]
        + [f"186-26 session: {s}" for s in state.rebuild_activity]
        + [f"186-26 process: {p}" for p in state.rebuild_processes]
    )


def refuse_if_writers(state: WriterState) -> None:
    blockers = writer_blockers(state)
    if blockers:
        raise SwapRefused("; ".join(blockers))


def advisory_key_parts(name: str) -> tuple[int, int]:
    """(classid, objid) of the session advisory lock on `name`, as pg_locks shows them.
    The 64-bit key itself is the FROZEN derivation in scripts/infrastructure/backfill/
    _fetcher_lock.py (fetcher_lock_key); only the pg_locks split lives here."""
    from scripts.infrastructure.backfill._fetcher_lock import fetcher_lock_key

    key = fetcher_lock_key(name)
    return (key >> 32) & 0xFFFFFFFF, key & 0xFFFFFFFF


def _read_cmdlines() -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if raw:
            out[int(entry.name)] = [a.decode(errors="replace") for a in raw.split(b"\0") if a]
    return out


def _processes(cmdlines: Mapping[int, Sequence[str]], names: frozenset[str], self_pid: int):
    found = []
    for pid, argv in sorted(cmdlines.items()):
        if pid == self_pid:
            continue
        for arg in argv:
            if os.path.basename(arg) in names:
                found.append(f"{pid} {os.path.basename(arg)}")
                break
    return found


def _active_units(units: Sequence[str]) -> list[str]:
    result = subprocess.run(
        ["systemctl", "is-active", *units], capture_output=True, text=True, check=False
    )
    states = result.stdout.split()
    if len(states) != len(units):
        return [f"{u} (state unreadable)" for u in units]  # loud, never "inactive"
    return [u for u, s in zip(units, states, strict=True) if s in {"active", "activating"}]


# pg_locks is cluster-wide: both queries keep to the current database, where an advisory key or a
# relation OID means what it says (another database's OIDs can collide with this one's).
_LOCK_HOLDERS_SQL = """
SELECT a.pid, a.application_name
FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.locktype = 'advisory' AND l.granted
  AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND (l.classid, l.objid) IN (SELECT * FROM unnest(%s::oid[], %s::oid[]))
ORDER BY a.pid
"""

_WRITE_LOCKS_SQL = """
WITH rels AS (
    SELECT %s::regclass AS rel
    UNION ALL
    SELECT format('%%I.%%I', chunk_schema, chunk_name)::regclass
    FROM timescaledb_information.chunks WHERE hypertable_name = %s
)
SELECT l.pid, l.mode, l.relation::regclass::text
FROM pg_locks l JOIN rels ON rels.rel = l.relation
WHERE l.locktype = 'relation' AND l.granted AND l.pid <> pg_backend_pid()
  AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND l.mode = ANY(%s)
ORDER BY l.pid, 3
"""

_REBUILD_ACTIVITY_SQL = """
SELECT pid, left(query, 60), application_name FROM pg_stat_activity
WHERE pid <> pg_backend_pid() AND datname = current_database()
  AND (query ILIKE '%%' || %s || '%%' OR application_name ILIKE '%%' || %s || '%%')
ORDER BY pid
"""


def load_writer_state(conn: Any) -> WriterState:
    parts = [advisory_key_parts(n) for n in WRITER_LOCK_NAMES]
    with conn.cursor() as cur:
        cur.execute(_LOCK_HOLDERS_SQL, ([p[0] for p in parts], [p[1] for p in parts]))
        holders = tuple(f"{pid} {app}" for pid, app in cur.fetchall())
        cur.execute(_WRITE_LOCKS_SQL, (_TABLE, _TABLE, sorted(_WRITE_LOCK_MODES)))
        locks = tuple(f"{pid} {mode} {rel}" for pid, mode, rel in cur.fetchall())
        cur.execute(_REBUILD_ACTIVITY_SQL, (REBUILD_TABLE_PATTERN, REBUILD_TABLE_PATTERN))
        activity = tuple(f"{pid} {q} ({app})" for pid, q, app in cur.fetchall())
    cmdlines = _read_cmdlines()
    return WriterState(
        lock_holders=holders,
        processes=tuple(_processes(cmdlines, WRITER_SCRIPTS, os.getpid())),
        active_units=tuple(_active_units(WRITER_UNITS)),
        write_locks=locks,
        rebuild_activity=activity,
        rebuild_processes=tuple(_processes(cmdlines, REBUILD_SCRIPTS, os.getpid())),
    )


def state_md_rebuild_lines() -> list[str]:
    """The .planning/STATE.md lines naming the 186-26 rebuild, as preflight context: the file is
    the plan-level record that it is blocked and runs only after plans 11 to 14 land."""
    if not _STATE_MD.exists():
        return ["(no .planning/STATE.md)"]
    return [line.strip() for line in _STATE_MD.read_text().splitlines() if "186-26" in line]


def window_state(ctl: Any = _active_units) -> dict[str, Any]:
    """The cutover window record plus the live state of every unit it holds. The build runs only
    inside the window ops_raw_cutover_window.py opened (fetcher, bar_derivation, D7, bar writers
    and auditors held); a unit that came back is a blocker."""
    if not _WINDOW_RECORD.exists():
        return {"record": str(_WINDOW_RECORD), "state": "absent", "units": []}
    data = json.loads(_WINDOW_RECORD.read_text())
    units = data.get("units", [])
    names = [u["name"] for u in units]
    active = ctl(names) if names else []
    return {
        "record": str(_WINDOW_RECORD),
        "state": data.get("state", "open"),
        "opened_at": data.get("opened_at"),
        "units": [
            {"name": name, "cleared_by": u.get("cleared_by"), "active": name in active}
            for u, name in zip(units, names, strict=True)
        ],
        "active_units": active,
    }


def window_blockers(window: Mapping[str, Any]) -> list[str]:
    if window["state"] == "absent":
        return ["cutover window: no record; run ops_raw_cutover_window.py open first"]
    out = []
    if window["state"] != "open":
        out.append(f"cutover window: record state is {window['state']!r}, want 'open'")
    # A unit may resume only after it is cleared (the reader plans' evidence), so a held unit
    # that is active again means someone restarted a writer inside the window.
    uncleared = [u["name"] for u in window["units"] if u["cleared_by"] is None and u["active"]]
    if uncleared:
        out.append(f"cutover window: units active while uncleared: {', '.join(uncleared)}")
    return out


# --- chunk measurement ------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkInfo:
    schema: str
    name: str
    is_compressed: bool
    total_bytes: int
    before_bytes: int | None  # uncompressed size of a compressed chunk


def _rows(conn: Any, query: Any, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return list(cur.fetchall())


def _scalar(conn: Any, query: Any, params: Sequence[Any] = ()) -> Any:
    found = _rows(conn, query, params)
    return found[0][0] if found else None


_CHUNKS_SQL = """
SELECT c.chunk_schema, c.chunk_name, c.is_compressed, d.total_bytes,
       s.before_compression_total_bytes
FROM timescaledb_information.chunks c
JOIN chunks_detailed_size(%s::regclass) d
  ON d.chunk_schema = c.chunk_schema AND d.chunk_name = c.chunk_name
LEFT JOIN chunk_compression_stats(%s::regclass) s
  ON s.chunk_schema = c.chunk_schema AND s.chunk_name = c.chunk_name
WHERE c.hypertable_name = %s
ORDER BY c.range_start
"""

_CHUNK_SOURCES_SQL = sql.SQL("SELECT source, count(*) FROM {chunk} GROUP BY 1")

_CHUNK_TF_COUNTS_SQL = sql.SQL("SELECT timeframe, count(*) FROM {chunk} GROUP BY 1")

_CHUNK_NAMES_SQL = """
SELECT chunk_schema, chunk_name FROM timescaledb_information.chunks
WHERE hypertable_schema = 'public' AND hypertable_name = %s ORDER BY range_start
"""


def load_chunks(conn: Any, table: str = _TABLE) -> list[ChunkInfo]:
    return [
        ChunkInfo(
            schema, name, bool(compressed), int(total), None if before is None else int(before)
        )
        for schema, name, compressed, total, before in _rows(
            conn, _CHUNKS_SQL, (table, table, table)
        )
    ]


def _chunk_raw_bytes(chunk: ChunkInfo) -> int:
    """A chunk's size uncompressed: before-compression bytes, or its size when not compressed."""
    if chunk.is_compressed and chunk.before_bytes is not None:
        return chunk.before_bytes
    return chunk.total_bytes


def count_sources(conn: Any) -> dict[str | None, int]:
    """Per source label row counts of the live table, summed per chunk (the vectorized path:
    grouping on the hypertable by tableoid defeats TimescaleDB's vectorized aggregation, 5x
    slower, measured 2026-10-06)."""
    totals: dict[str | None, int] = defaultdict(int)
    for schema, name in _rows(conn, _CHUNK_NAMES_SQL, (_TABLE,)):
        for label, count in _rows(
            conn, _CHUNK_SOURCES_SQL.format(chunk=sql.Identifier(schema, name))
        ):
            totals[label] += int(count)
    return dict(totals)


def table_tf_counts(conn: Any, table: str) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for schema, name in _rows(conn, _CHUNK_NAMES_SQL, (table,)):
        for tf, count in _rows(
            conn, _CHUNK_TF_COUNTS_SQL.format(chunk=sql.Identifier(schema, name))
        ):
            totals[tf] += int(count)
    return dict(sorted(totals.items()))


def unmapped_source_blockers(sources: Mapping[str | None, int]) -> list[str]:
    return [
        f"source label {label!r} ({count} rows) has no (vendor, kind) mapping"
        for label, count in sorted(sources.items(), key=lambda kv: (kv[0] is None, kv[0]))
        if label not in LABEL_TO_VENDOR_KIND
    ]


@dataclass(frozen=True)
class DiskPlan:
    free_bytes: int
    copy_peak_bytes: float
    margin: float
    required_bytes: float

    @property
    def headroom_bytes(self) -> float:
        return self.free_bytes - self.required_bytes

    @property
    def ok(self) -> bool:
        return self.headroom_bytes >= 0


def disk_plan(chunks: Sequence[ChunkInfo], free_bytes: int, margin: float) -> DiskPlan:
    """The copy lands uncompressed before its chunks compress, so the peak is the whole table
    uncompressed; the margin covers WAL, index builds and the estimate's error."""
    if margin < 1.0:
        raise ValueError(f"disk margin must be >= 1.0, got {margin}")
    peak = sum(_chunk_raw_bytes(c) for c in chunks)
    return DiskPlan(free_bytes, peak, margin, peak * margin)


def digest_column_blockers(live_columns: Sequence[str]) -> list[str]:
    expected = set(_LIVE_COLUMNS)
    live = set(live_columns)
    out = []
    if live - expected:
        out.append(f"columns not covered by the copy and digest: {sorted(live - expected)}")
    if expected - live:
        out.append(f"expected columns missing from the table: {sorted(expected - live)}")
    return out


_COLUMNS_SQL = """
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position
"""

_DEPENDENT_VIEWS_SQL = """
SELECT DISTINCT v.oid::regclass::text
FROM pg_depend d
JOIN pg_rewrite r ON r.oid = d.objid
JOIN pg_class v ON v.oid = r.ev_class
WHERE d.refobjid = %s::regclass AND v.oid <> %s::regclass
ORDER BY 1
"""


# --- table shape ------------------------------------------------------------------------------


@dataclass(frozen=True)
class TableShape:
    """Everything the v2 table must share with the live one, compared by `shape_differences`
    with the source-to-(vendor, kind) exchange applied. Index names are compared without the
    `_rebuilt` suffix."""

    columns: tuple[tuple[str, str, bool], ...]  # (name, type, attnotnull)
    constraints: tuple[tuple[str, str], ...]  # (name, definition)
    indexes: tuple[tuple[str, str], ...]  # (base name, "UNIQUE ... USING ...")
    dimensions: tuple[tuple[str, ...], ...]
    columnstore: tuple[str, ...]
    acl: tuple[tuple[str, str], ...]
    reloptions: tuple[str, ...]
    owner: str


_REBUILT_SUFFIX = "_rebuilt"

_SHAPE_COLUMNS_SQL = """
SELECT attname, format_type(atttypid, atttypmod), attnotnull FROM pg_attribute
WHERE attrelid = %s::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum
"""
_SHAPE_CONSTRAINTS_SQL = """
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid = %s::regclass ORDER BY 1
"""
_SHAPE_INDEXES_SQL = """
SELECT i.relname, x.indisunique, pg_get_indexdef(x.indexrelid)
FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
WHERE x.indrelid = %s::regclass ORDER BY 1
"""
_SHAPE_DIMENSIONS_SQL = """
SELECT column_name::text, column_type::text, dimension_type::text,
       coalesce(time_interval::text, ''), coalesce(integer_interval::text, ''),
       coalesce(num_partitions::text, '')
FROM timescaledb_information.dimensions
WHERE hypertable_schema = 'public' AND hypertable_name = %s ORDER BY dimension_number
"""
_SHAPE_COLUMNSTORE_SQL = """
SELECT coalesce(segmentby::text, ''), coalesce(orderby::text, ''),
       coalesce(compress_interval_length::text, ''), coalesce(index::text, '')
FROM timescaledb_information.hypertable_columnstore_settings WHERE hypertable = %s::regclass
"""
_SHAPE_ACL_SQL = """
SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE a.grantee::regrole::text END, a.privilege_type
FROM pg_class c, aclexplode(c.relacl) a WHERE c.oid = %s::regclass ORDER BY 1, 2
"""
_SHAPE_CLASS_SQL = """
SELECT coalesce(reloptions, '{}'::text[]), relowner::regrole::text FROM pg_class
WHERE oid = %s::regclass
"""

# The intended exchange: the live table's source column and its NOT VALID synthetic_fill check
# have no v2 counterpart; v2 adds the vendor and kind NOT NULL constraints, named after the
# v2 table (the shared columns keep the live names, so the plan 14 renames stay mechanical).
_DROPPED_COLUMNS = ("source",)
_DROPPED_CONSTRAINTS = frozenset({"market_data_ohlcv_no_synthetic_fill"})
_ADDED_COLUMNS = (("vendor", "text", True), ("kind", "text", True))


def _added_constraint(column: str) -> str:
    return f"market_data_ohlcv_v2_{column}_not_null"


def index_base(name: str) -> str:
    return name[: -len(_REBUILT_SUFFIX)] if name.endswith(_REBUILT_SUFFIX) else name


def index_signature(unique: bool, definition: str) -> str:
    """`CREATE [UNIQUE] INDEX name ON table USING ...` reduced to what does not name anything."""
    _, _, using = definition.partition(" USING ")
    return ("UNIQUE " if unique else "") + using


def load_shape(conn: Any, table: str) -> TableShape:
    with conn.cursor() as cur:
        cur.execute(_SHAPE_COLUMNS_SQL, (table,))
        columns = tuple((n, t, bool(nn)) for n, t, nn in cur.fetchall())
        cur.execute(_SHAPE_CONSTRAINTS_SQL, (table,))
        constraints = tuple((n, d) for n, d in cur.fetchall())
        cur.execute(_SHAPE_INDEXES_SQL, (table,))
        indexes = tuple(
            sorted((index_base(n), index_signature(u, d)) for n, u, d in cur.fetchall())
        )
        cur.execute(_SHAPE_DIMENSIONS_SQL, (table,))
        dimensions = tuple(tuple(r) for r in cur.fetchall())
        cur.execute(_SHAPE_COLUMNSTORE_SQL, (table,))
        row = cur.fetchone()
        columnstore = tuple(row) if row else ()
        cur.execute(_SHAPE_ACL_SQL, (table,))
        acl = tuple((g, p) for g, p in cur.fetchall())
        cur.execute(_SHAPE_CLASS_SQL, (table,))
        reloptions, owner = cur.fetchone()
    # `timescaledb.*` options are normalized away: TimescaleDB 2.18+ stores compression in the
    # columnstore catalog (compared above), and whether the ALTER leaves a reloption trace is a
    # version detail, not a shape property. Everything else (autovacuum options) must match.
    plain_options = tuple(o for o in (reloptions or ()) if not o.startswith("timescaledb."))
    return TableShape(
        columns, constraints, indexes, dimensions, columnstore, acl, plain_options, owner
    )


def _expected_v2_columns(old_columns: Sequence[tuple[str, str, bool]]):
    columns = [c for c in old_columns if c[0] not in _DROPPED_COLUMNS]
    source_at = next(i for i, c in enumerate(old_columns) if c[0] in _DROPPED_COLUMNS)
    columns[source_at:source_at] = _ADDED_COLUMNS
    return tuple(columns)


def shape_differences(old: TableShape, v2: TableShape) -> list[str]:
    """Everything that differs between the live table and v2 beyond the intended exchange."""
    out: list[str] = []
    if v2.columns != _expected_v2_columns(old.columns):
        out.append(f"columns: {v2.columns} != {_expected_v2_columns(old.columns)}")
    # The expected v2 constraints: everything the live table carries except the NOT VALID
    # synthetic_fill check (its column is gone), plus the two NOT NULLs of the new columns.
    old_constraints = {n: d for n, d in old.constraints if n not in _DROPPED_CONSTRAINTS}
    for column, _, _ in _ADDED_COLUMNS:
        old_constraints[_added_constraint(column)] = f"NOT NULL {column}"
    v2_constraints = dict(v2.constraints)
    if v2_constraints != old_constraints:
        out.append(
            f"constraints: v2 {sorted(v2_constraints)} != expected {sorted(old_constraints)}"
        )
    if v2.indexes != old.indexes:
        out.append(f"indexes: {v2.indexes} != {old.indexes}")
    for name in TableShape.__dataclass_fields__:
        if name in ("columns", "constraints", "indexes"):
            continue
        if getattr(old, name) != getattr(v2, name):
            out.append(f"{name}: {getattr(v2, name)!r} != {getattr(old, name)!r}")
    return out


# --- APR --------------------------------------------------------------------------------------


def load_apr(conn: Any) -> tuple[dict[str, float], dict[str, str]]:
    """APR values and where each came from ('apr' or 'default', the latter until migration 496
    is applied). The provenance is printed so a fallback is never silent."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
            (list(APR_DEFAULTS),),
        )
        found = {k: v for k, v in cur.fetchall()}
    values: dict[str, float] = {}
    provenance: dict[str, str] = {}
    for key, default in APR_DEFAULTS.items():
        if key in found:
            raw = found[key]
            values[key] = float(json.loads(raw) if isinstance(raw, str) else raw)
            provenance[key] = "apr"
        else:
            values[key] = default
            provenance[key] = "default"
    return values, provenance


# --- preflight --------------------------------------------------------------------------------


def preflight(conn: Any, data_path: str) -> tuple[dict[str, Any], list[str]]:
    """The dry run: measure, gate, change nothing. Returns the report and the blockers."""
    apr, provenance = load_apr(conn)
    conn.execute(f"SET statement_timeout = '{int(apr[APR_STATEMENT_TIMEOUT_S])}s'")
    blockers: list[str] = []

    window = window_state()
    blockers += window_blockers(window)

    writers = load_writer_state(conn)
    blockers += writer_blockers(writers)

    chunks = load_chunks(conn)
    sources = count_sources(conn)
    blockers += unmapped_source_blockers(sources)

    plan = disk_plan(chunks, shutil.disk_usage(data_path).free, apr[APR_DISK_MARGIN])
    if not plan.ok:
        blockers.append(
            f"disk: {_gib(plan.free_bytes)} GiB free < {_gib(plan.required_bytes)} GiB required"
        )

    columns = [row[0] for row in _rows(conn, _COLUMNS_SQL, (_TABLE,))]
    blockers += digest_column_blockers(columns)
    views = [row[0] for row in _rows(conn, _DEPENDENT_VIEWS_SQL, (_TABLE, _TABLE))]

    v2_exists = _scalar(conn, "SELECT to_regclass(%s)", (f"public.{_V2_TABLE}",)) is not None
    shape: list[str] = []
    if v2_exists:
        shape = shape_differences(load_shape(conn, _TABLE), load_shape(conn, _V2_TABLE))
        blockers += [f"shape {difference}" for difference in shape]
    else:
        blockers.append(f"{_V2_TABLE} does not exist: apply the migration first")

    tf_counts = table_tf_counts(conn, _TABLE)
    report: dict[str, Any] = {
        "job": _JOB,
        "mode": "preflight",
        "measured_at": format_ts(datetime.now(UTC)),
        "apr": {k: {"value": v, "source": provenance[k]} for k, v in apr.items()},
        "window": window,
        "writers": {
            "lock_holders": list(writers.lock_holders),
            "processes": list(writers.processes),
            "active_units": list(writers.active_units),
            "write_locks": list(writers.write_locks),
            "rebuild_activity": list(writers.rebuild_activity),
            "rebuild_processes": list(writers.rebuild_processes),
            "state_md_186_26_lines": state_md_rebuild_lines(),
        },
        "chunks": {
            "total": len(chunks),
            "compressed": sum(c.is_compressed for c in chunks),
            "compressed_bytes": sum(c.total_bytes for c in chunks if c.is_compressed),
            "uncompressed_bytes": sum(c.total_bytes for c in chunks if not c.is_compressed),
            "uncompressed_estimate_bytes": sum(_chunk_raw_bytes(c) for c in chunks),
        },
        "by_timeframe": tf_counts,
        "totals": {"rows": sum(tf_counts.values())},
        "sources": {
            str(k): v for k, v in sorted(sources.items(), key=lambda kv: (kv[0] is None, kv[0]))
        },
        "disk": {
            "path": data_path,
            "free_gib": _gib(plan.free_bytes),
            "copy_peak_gib": _gib(plan.copy_peak_bytes),
            "margin": plan.margin,
            "required_gib": _gib(plan.required_bytes),
            "headroom_gib": _gib(plan.headroom_bytes),
            "ok": plan.ok,
        },
        "columns": columns,
        "dependent_views": views,
        "v2_exists": v2_exists,
        "shape_differences": shape,
        "blockers": blockers,
        "verdict": "blocked" if blockers else "ready",
    }
    return report, blockers


def write_gates(conn: Any, data_path: str) -> tuple[dict[str, Any], list[str]]:
    """The preflight's gates (the build runs only when every one passes)."""
    report, blockers = preflight(conn, data_path)
    return (
        {
            "window": report["window"],
            "writers": report["writers"],
            "disk": report["disk"],
            "sources": report["sources"],
            "shape_differences": report["shape_differences"],
            "blockers": blockers,
        },
        blockers,
    )


# --- build: chunk windows ---------------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    def params(self) -> tuple[datetime, datetime]:
        return (self.start, self.end)


def chunk_windows(lo: datetime, hi: datetime, interval: timedelta) -> list[Window]:
    """Windows covering [lo, hi) on the v2 table's chunk grid: TimescaleDB aligns time chunks to
    whole multiples of the interval from the Unix epoch, so each window is exactly one chunk of
    the v2 table (checked after every window's copy, never assumed)."""
    if interval <= timedelta(0):
        raise ValueError(f"chunk interval must be positive, got {interval}")
    start = _EPOCH + ((lo - _EPOCH) // interval) * interval
    out = []
    while start < hi:
        out.append(Window(start, start + interval))
        start += interval
    return out


@dataclass(frozen=True)
class ChunkRange:
    schema: str
    name: str
    start: datetime
    end: datetime
    is_compressed: bool


def window_chunk(chunks: Sequence[ChunkRange], window: Window) -> ChunkRange | None:
    """The v2 table's one chunk for this window, or None when the window holds no rows."""
    if not chunks:
        return None
    if len(chunks) != 1 or (chunks[0].start, chunks[0].end) != (window.start, window.end):
        raise SwapAborted(
            f"chunk grid misaligned for window {format_ts(window.start)}: "
            f"{[(format_ts(c.start), format_ts(c.end)) for c in chunks]}"
        )
    return chunks[0]


_WINDOW_CHUNKS_SQL = """
SELECT chunk_schema, chunk_name, range_start, range_end, is_compressed
FROM timescaledb_information.chunks
WHERE hypertable_schema = 'public' AND hypertable_name = %s AND range_start < %s AND range_end > %s
ORDER BY range_start
"""
_TIME_INTERVAL_SQL = """
SELECT time_interval FROM timescaledb_information.dimensions
WHERE hypertable_schema = 'public' AND hypertable_name = %s AND dimension_number = 1
"""
_CHUNK_SPAN_SQL = """
SELECT min(range_start), max(range_end) FROM timescaledb_information.chunks
WHERE hypertable_schema = 'public' AND hypertable_name = %s
"""
_POLICY_SQL = """
SELECT job_id, config->>'compress_after', schedule_interval::text, scheduled
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_compression' AND hypertable_schema = 'public' AND hypertable_name = %s
ORDER BY job_id
"""


@dataclass(frozen=True)
class Policy:
    job_id: int
    compress_after: str
    scheduled: bool


def load_policies(conn: Any, table: str) -> list[Policy]:
    # schedule_interval is selected for the report context but not carried: only compress_after
    # and the scheduled flag gate the copy's compression step.
    return [
        Policy(int(job), str(after), bool(scheduled))
        for job, after, _schedule_interval, scheduled in _rows(conn, _POLICY_SQL, (table,))
    ]


def _window_chunks(conn: Any, table: str, window: Window) -> list[ChunkRange]:
    return [
        ChunkRange(s, n, a, b, bool(c))
        for s, n, a, b, c in _rows(conn, _WINDOW_CHUNKS_SQL, (table, window.end, window.start))
    ]


def _set_timeouts(conn: Any, statement_s: float) -> None:
    conn.execute(f"SET statement_timeout = '{int(statement_s)}s'")
    conn.execute("SET TIME ZONE 'UTC'")


def copy_windows(conn: Any, apr: Mapping[str, float]) -> dict[str, Any]:
    """Copy the live table into v2 one 90-day chunk window per transaction, mapping source to
    (vendor, kind).

    Restart-safe: a window is done when its v2 row count equals the old table's (a compressed
    chunk got there only through a committed copy); any other window is cleared and copied
    again, so a crash mid-copy costs that one window. Windows older than the live compression
    policy's compress_after are compressed when they finish, and every cleared or compressed
    chunk is vacuumed at once (compress_chunk leaves the copied rows' heap pages behind,
    docs/foundation/timescaledb-compressed-column-migration.md), so the copy's peak disk is one
    window's rows, not the table's."""
    policies = load_policies(conn, _TABLE)
    if len(policies) != 1:
        raise SwapAborted(f"{_TABLE} has {len(policies)} compression policies; want exactly one")
    interval = _scalar(conn, _TIME_INTERVAL_SQL, (_V2_TABLE,))
    if not isinstance(interval, timedelta):
        raise SwapAborted(f"{_V2_TABLE} chunk interval {interval!r} is not a fixed duration")
    lo, hi = _rows(conn, _CHUNK_SPAN_SQL, (_TABLE,))[0]
    cutoff = _scalar(conn, "SELECT now() - %s::interval", (policies[0].compress_after,))
    _set_timeouts(conn, apr[APR_COPY_TIMEOUT_S])

    started = time.monotonic()
    windows = [] if lo is None else chunk_windows(lo, hi, interval)
    log: list[dict[str, Any]] = []
    for window in windows:
        t0 = time.monotonic()
        chunk = window_chunk(_window_chunks(conn, _V2_TABLE, window), window)
        if chunk is not None and chunk.is_compressed:
            log.append({"window": format_ts(window.start), "status": "done_earlier_compressed"})
            continue
        old_n = int(_scalar(conn, _OLD_COUNT_WINDOW_SQL, window.params()))
        v2_n = int(_scalar(conn, _V2_COUNT_WINDOW_SQL, window.params()))
        if v2_n == old_n:
            status = "done_earlier"
            copied = cleared = 0
            # Nothing ran in between: the first chunk fetch is still the catalog truth.
        else:
            with conn.transaction():
                cleared = conn.execute(_CLEAR_WINDOW_SQL, window.params()).rowcount
                copied = conn.execute(_COPY_WINDOW_SQL, window.params()).rowcount
            v2_n = int(_scalar(conn, _V2_COUNT_WINDOW_SQL, window.params()))
            if v2_n != old_n:
                raise SwapAborted(
                    f"window {format_ts(window.start)} copied {v2_n} rows, "
                    f"the original holds {old_n}; nothing swapped"
                )
            status = "copied"
            chunk = window_chunk(_window_chunks(conn, _V2_TABLE, window), window)
        chunk = window_chunk(_window_chunks(conn, _V2_TABLE, window), window)
        compress = chunk is not None and window.end < cutoff and not chunk.is_compressed
        if compress:
            conn.execute(
                "SELECT compress_chunk(format('%%I.%%I', %s::text, %s::text)::regclass)",
                (chunk.schema, chunk.name),
            )
        if chunk is not None and (compress or cleared):
            conn.execute(sql.SQL("VACUUM {}").format(sql.Identifier(chunk.schema, chunk.name)))
        if status == "copied" or cleared:
            log.append(
                {
                    "window": format_ts(window.start),
                    "status": status,
                    "rows": copied,
                    "cleared": cleared,
                    "compressed": compress,
                    "seconds": round(time.monotonic() - t0, 2),
                }
            )
    old_counts, v2_counts = table_tf_counts(conn, _TABLE), table_tf_counts(conn, _V2_TABLE)
    differences = [
        f"{tf}: v2 {v2_counts.get(tf, 0)} rows, original {old_counts.get(tf, 0)}"
        for tf in sorted(old_counts.keys() | v2_counts.keys())
        if v2_counts.get(tf, 0) != old_counts.get(tf, 0)
    ]
    return {
        "windows": len(windows),
        "windows_copied": sum(1 for e in log if e["status"] == "copied"),
        "windows_done_earlier": sum(1 for e in log if e["status"] != "copied"),
        "rows_copied": sum(e.get("rows", 0) for e in log),
        "copy_seconds": round(time.monotonic() - started, 1),
        "compress_after": policies[0].compress_after,
        "log": log,
        "original_by_timeframe": old_counts,
        "v2_by_timeframe": v2_counts,
        "count_differences": differences,
    }


def run_build(conn: Any, data_path: str) -> tuple[dict[str, Any], list[str]]:
    refuse_if_writers(load_writer_state(conn))
    gates, blockers = write_gates(conn, data_path)
    report: dict[str, Any] = {"job": _JOB, "mode": "build", "gates": gates}
    if blockers:
        report["result"] = "refused: nothing copied"
        return report, blockers
    apr, _ = load_apr(conn)
    report["copy"] = copy_windows(conn, apr)
    report["result"] = (
        "copied" if not report["copy"]["count_differences"] else "copied, counts differ"
    )
    return report, list(report["copy"]["count_differences"])


# --- prove ------------------------------------------------------------------------------------


DigestMap = Mapping[tuple[str, str], tuple[int, str]]


@dataclass
class DigestComparison:
    missing_in_v2: list[tuple[str, str]] = field(default_factory=list)
    extra_in_v2: list[tuple[str, str]] = field(default_factory=list)
    count_mismatch: list[tuple[str, str, int, int]] = field(default_factory=list)
    digest_mismatch: list[tuple[str, str]] = field(default_factory=list)
    n_compared: int = 0

    @property
    def ok(self) -> bool:
        return not (
            self.missing_in_v2 or self.extra_in_v2 or self.count_mismatch or self.digest_mismatch
        )


def compare_digests(old: DigestMap, v2: DigestMap) -> DigestComparison:
    """Per (symbol, timeframe): v2's count and digest equal the original's through the mapping.
    A key on one side only is a mismatch too: a series lost in the copy, or one that appeared."""
    result = DigestComparison()
    for key in sorted(old.keys() | v2.keys()):
        if key not in v2:
            result.missing_in_v2.append(key)
            continue
        if key not in old:
            result.extra_in_v2.append(key)
            continue
        result.n_compared += 1
        (old_n, old_digest), (v2_n, v2_digest) = old[key], v2[key]
        if old_n != v2_n:
            result.count_mismatch.append((*key, old_n, v2_n))
        elif old_digest != v2_digest:
            result.digest_mismatch.append(key)
    return result


def _digests(
    conn: Any, digest_sql: str, symbols: Sequence[str], chunk_size: int = 100
) -> dict[tuple[str, str], tuple[int, str]]:
    """Per-(symbol, timeframe) digests, symbols in chunks: one round trip per ~100 symbols
    instead of per symbol (about 3,000 queries became about 30 on the 1,529-symbol prove),
    while the statement's string_agg memory stays bounded by the chunk."""
    out: dict[tuple[str, str], tuple[int, str]] = {}
    with conn.cursor() as cur:
        for start in range(0, len(symbols), chunk_size):
            chunk = symbols[start : start + chunk_size]
            cur.execute(digest_sql, (chunk,))
            for symbol, tf, n, digest in cur.fetchall():
                out[(symbol, tf)] = (int(n), str(digest))
    return out


def _symbols(conn: Any, table: str) -> set[str]:
    query = sql.SQL(_SYMBOLS_SQL).format(sql.Identifier(table))
    return {row[0] for row in _rows(conn, query)}


def run_selection_gate() -> tuple[dict[str, Any], list[str]]:
    """The plan 07 selection gate against v2 (timeframes 1m, 5m and 4h, its defaults). v2 must be
    a pure function of raw plus policy, not merely a faithful copy: exit 0 is required, and the
    gate's own report file is loaded into this one."""
    proc = subprocess.run(
        [sys.executable, "-m", _GATE_MODULE, "--compare", "--target", _V2_TABLE],
        capture_output=True,
        text=True,
        check=False,
        cwd=project_root,
    )
    entry: dict[str, Any] = {
        "command": f"{_GATE_MODULE} --compare --target {_V2_TABLE}",
        "exit_code": proc.returncode,
    }
    match = _GATE_REPORT_RE.search(proc.stdout)
    if match and Path(match.group(1)).exists():
        entry["report_file"] = match.group(1)
        gate_report = json.loads(Path(match.group(1)).read_text())
        entry["totals"] = gate_report.get("totals", {})
    blockers = (
        []
        if proc.returncode == EXIT_OK
        else [f"selection gate exit {proc.returncode} against {_V2_TABLE} (0 required)"]
    )
    if proc.returncode != EXIT_OK:
        entry["stdout_tail"] = proc.stdout[-2000:]
        entry["stderr_tail"] = proc.stderr[-2000:]
    return entry, blockers


def run_prove(conn: Any) -> tuple[dict[str, Any], list[str]]:
    """Count and digest equality per (symbol, timeframe), then the selection gate on v2. Both
    must be exactly clean; refuses while a writer runs, since counts taken from a moving table
    prove nothing."""
    refuse_if_writers(load_writer_state(conn))
    apr, _ = load_apr(conn)
    _set_timeouts(conn, apr[APR_STATEMENT_TIMEOUT_S])
    started = time.monotonic()
    symbols = sorted(_symbols(conn, _TABLE) | _symbols(conn, _V2_TABLE))
    old_digests = _digests(conn, _OLD_DIGEST_SQL, symbols)
    v2_digests = _digests(conn, _V2_DIGEST_SQL, symbols)
    result = compare_digests(old_digests, v2_digests)
    old_total = sum(n for n, _ in old_digests.values())
    v2_total = sum(n for n, _ in v2_digests.values())
    blockers = []
    if not result.ok:
        blockers.append("digest comparison failed")
    report: dict[str, Any] = {
        "job": _JOB,
        "mode": "prove",
        "symbols": len(symbols),
        "series_compared": result.n_compared,
        "rows_original": old_total,
        "rows_v2": v2_total,
        "rows_equal": old_total == v2_total,
        "missing_in_v2": result.missing_in_v2[:50],
        "n_missing_in_v2": len(result.missing_in_v2),
        "extra_in_v2": result.extra_in_v2[:50],
        "n_extra_in_v2": len(result.extra_in_v2),
        "count_mismatch": result.count_mismatch[:50],
        "n_count_mismatch": len(result.count_mismatch),
        "digest_mismatch": result.digest_mismatch[:50],
        "n_digest_mismatch": len(result.digest_mismatch),
    }
    if blockers:
        report["result"] = "digest differences: nothing may proceed to the swap"
        report["seconds"] = round(time.monotonic() - started, 1)
        return report, blockers

    gate, gate_blockers = run_selection_gate()
    report["selection_gate"] = gate
    blockers += gate_blockers
    report["result"] = (
        "proven equal and gate-clean" if not blockers else "digests equal, selection gate not clean"
    )
    report["seconds"] = round(time.monotonic() - started, 1)
    return report, blockers


# --- entry ------------------------------------------------------------------------------------

_MODES = ("build", "prove")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--preflight", action="store_true", help="measure and gate (default)")
    modes.add_argument("--build", action="store_true", help=f"copy into {_V2_TABLE} (restartable)")
    modes.add_argument(
        "--prove", action="store_true", help=f"prove v2 equal to {_TABLE} and gate-clean"
    )
    parser.add_argument(
        "--data-path",
        default="/var/lib/docker",
        help="a path on the filesystem holding the database volume (free-disk check)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = next((m for m in (*_MODES, "preflight") if getattr(args, m)), "preflight")
    with psycopg.connect(Settings().database_url, autocommit=True, application_name=_JOB) as conn:
        if mode == "preflight":
            conn.execute("SET default_transaction_read_only = on")
        try:
            if mode == "build":
                report, blockers = run_build(conn, args.data_path)
            elif mode == "prove":
                report, blockers = run_prove(conn)
            else:
                report, blockers = preflight(conn, args.data_path)
        except (SwapRefused, SwapAborted) as error:
            kind = "refused" if isinstance(error, SwapRefused) else "aborted"
            print(json.dumps({"job": _JOB, "mode": mode, kind: str(error)}, indent=2))
            return EXIT_BLOCKED
    print(json.dumps(report, indent=2, default=str))
    return EXIT_BLOCKED if blockers else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
