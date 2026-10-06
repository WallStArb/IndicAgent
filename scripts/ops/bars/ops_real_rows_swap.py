"""Real-rows swap of market_data_ohlcv: read-only preflight and checks (todo 462 step 6, plan 185-25).

The swap rebuilds market_data_ohlcv from its real rows (every row whose source is not
'synthetic_fill') into a new table and swaps it in, instead of deleting the placeholders out of
compressed chunks. This module holds the planning and the checks; the DDL lives in migration 439.
Everything here is read-only: it never creates, alters, copies or drops anything.

Preflight (the default, a dry run) reports:

- per timeframe: total rows, synthetic_fill rows, real rows, rows with a NULL source (real rows a
  `source <> 'synthetic_fill'` filter would silently drop), synthetic rows with volume > 0 (rows
  the tradeable view shows today and would lose), the chunks holding the timeframe and its rows
  and estimated bytes in compressed versus uncompressed chunks;
- the copy estimate (the real rows' uncompressed size while the copy lands, before compression)
  times the `infra.real_rows_swap.disk_margin` APR multiplier, against free disk;
- the consumer audit: every raw `market_data_ohlcv` reader on the boundary allow-list
  (tests/unit/test_market_data_ohlcv_boundary.py), each with a checked-in verdict on whether it
  needs a contiguous series or treats a stored placeholder as fetched coverage;
- the 185-23 masked-slot gate (latest D7 fact per derived timeframe must read zero and be fresh);
- the writer check: nobody holds the IBKR history lock or lease, no writer process or unit runs,
  and no other session holds a write lock on the hypertable or any of its chunks;
- the digest-column check: the live column set equals the columns the per-(symbol, timeframe)
  digest covers, so a column added later cannot escape the comparison;
- the views that depend on the table (the swap must recreate them).

Exit status: 0 when every gate passes, 3 when any blocks, 2 on a usage error. `--verify` compares
the real rows of market_data_ohlcv with market_data_ohlcv_new per (symbol, timeframe), count and
digest, and refuses while any writer runs.

Measurement notes (performance SOP): counts run per chunk against the chunk tables, where
TimescaleDB's vectorized aggregation decompresses only `timeframe`, `source` and `volume` (about
0.1 s per compressed chunk); grouping on the hypertable by tableoid defeats vectorization (5x
slower, measured 2026-10-06). No full-table scan through the hypertable, no decompress_chunk.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from src.config.settings import Settings

_JOB = "ops-real-rows-swap"
_TABLE = "market_data_ohlcv"
_NEW_TABLE = "market_data_ohlcv_new"
_SYNTHETIC = "synthetic_fill"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BOUNDARY_TEST = _REPO_ROOT / "tests" / "unit" / "test_market_data_ohlcv_boundary.py"
_SELF = "scripts/ops/bars/ops_real_rows_swap.py"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BLOCKED = 3

# --- APR (migration 439) ---------------------------------------------------------------------

APR_DISK_MARGIN = "infra.real_rows_swap.disk_margin"
APR_STATEMENT_TIMEOUT_S = "infra.real_rows_swap.statement_timeout_s"
APR_MASKED_AUDIT_MAX_AGE_H = "infra.real_rows_swap.masked_audit_max_age_hours"
APR_DEFAULTS: dict[str, float] = {
    APR_DISK_MARGIN: 2.0,
    APR_STATEMENT_TIMEOUT_S: 600.0,
    APR_MASKED_AUDIT_MAX_AGE_H: 48.0,
}

# --- writers ----------------------------------------------------------------------------------

# Advisory locks held by an IBKR history writer: the D-29 lease and phase 189's fetcher lock.
# Keys derive as in src/core/resource_lease.py and scripts/infrastructure/backfill/_fetcher_lock.py.
WRITER_LOCK_NAMES = ("ibkr_history_stream", "ibkr_history_fetcher")
# Scripts that write market_data_ohlcv (or chain something that does). Matched against the
# basename of each argv element exactly, so a shell whose command line merely mentions a name
# never matches. Service identity, not a tunable: APR-exempt.
WRITER_SCRIPTS = frozenset(
    {
        "bar_derivation.py",
        "bar_writer.py",
        "bar_auditor.py",
        "backfill_feature_factory.py",
        "infrastructure_run_historical_pipeline.py",
        "infrastructure_nightly_backfill.py",
        "infrastructure_run_tradier_daily.py",
        "infrastructure_fetch_htf_bars.py",
        "intraday_chain.sh",
        "intraday_htf_lane.sh",
        "intraday_5m_lane.sh",
        "backfill_retry_loop.sh",
    }
)
WRITER_UNITS = (
    "indicagent-nightly-backfill.service",
    "indicagent-bar-derivation.service",
    "indicagent-bar-writer.service",
    "indicagent-bar-auditor.service",
)
_WRITE_LOCK_MODES = frozenset(
    {"RowExclusiveLock", "ShareRowExclusiveLock", "ExclusiveLock", "AccessExclusiveLock"}
)

# --- digest -----------------------------------------------------------------------------------

KEY_COLUMNS = ("symbol", "timeframe")
DIGEST_COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "base",
    "price_sanity_status",
)

# Real rows are `source IS DISTINCT FROM 'synthetic_fill'`: a NULL source is a real row, and the
# plain `<>` the plan sketched would drop it. ROW(...)::text distinguishes NULL from '' and floats
# print shortest-exact (PostgreSQL 12+), so equal digests mean equal rows. The session runs in UTC
# so timestamps print identically on both sides. Written out per table (not built from a name) so
# the boundary scan sees the raw read.
_OLD_DIGEST_SQL = """
SELECT timeframe, count(*),
       md5(string_agg(ROW("timestamp", open, high, low, close, volume, source, base,
                          price_sanity_status)::text, E'\\n' ORDER BY "timestamp"))
FROM market_data_ohlcv
WHERE symbol = %s AND source IS DISTINCT FROM 'synthetic_fill'
GROUP BY timeframe
"""
_NEW_DIGEST_SQL = """
SELECT timeframe, count(*),
       md5(string_agg(ROW("timestamp", open, high, low, close, volume, source, base,
                          price_sanity_status)::text, E'\\n' ORDER BY "timestamp"))
FROM market_data_ohlcv_new
WHERE symbol = %s AND source IS DISTINCT FROM 'synthetic_fill'
GROUP BY timeframe
"""
# Every symbol with any row, zero-volume real rows included (the tradeable view would miss a
# series of only zero-volume provider bars). symbol is a segmentby column, so this reads
# compressed-batch metadata, not the rows.
_OLD_SYMBOLS_SQL = "SELECT DISTINCT symbol FROM market_data_ohlcv"

# --- consumer audit ---------------------------------------------------------------------------

DEAD = "dead"  # no live consumer
REAL_ROWS = "real_rows"  # reads real rows or counts; placeholder removal is benign
PLACEHOLDER_COVERAGE = "placeholder_coverage"  # counts a stored placeholder as a covered slot
CONTIGUOUS = "contiguous"  # needs a contiguous series
SELF = "self"


@dataclass(frozen=True)
class ConsumerVerdict:
    category: str
    reason: str
    timeframes: tuple[str, ...] = ()  # where the dependency bites (placeholder_coverage)


# One verdict per allow-listed raw reader (todo 462 step 1, re-read 2026-10-06 against the
# current code). A reader on the allow-list with no verdict here blocks the swap.
CONSUMER_VERDICTS: dict[str, ConsumerVerdict] = {
    "services/signal_replay_auditor.py": ConsumerVerdict(DEAD, "v2.x Signal Ledger, archived"),
    "services/signal_probe_auditor.py": ConsumerVerdict(DEAD, "v2.x Signal Ledger, archived"),
    "scripts/debug/analysis/debug_batch_agent_memory.py": ConsumerVerdict(
        DEAD, "joins signal_ledger, zero rows, archived"
    ),
    "scripts/ops/pipeline/ops_pipeline_status.py": ConsumerVerdict(
        REAL_ROWS, "row count per timeframe and max(timestamp); counts drop, no series read"
    ),
    "scripts/infrastructure/backfill/infrastructure_nightly_backfill.py": ConsumerVerdict(
        REAL_ROWS, "_select_stalest ranks by max(timestamp); latest bars are real since 185-18"
    ),
    "scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py": ConsumerVerdict(
        PLACEHOLDER_COVERAGE,
        "legacy detect_gaps (1m, 4h) counts a stored placeholder as a present slot; 1m has "
        "answered-window coverage only since 2026-09-28 and 4h still writes placeholders, so "
        "removed slots inside a fetch window are re-requested (4h: re-filled)",
        ("1m", "4h"),
    ),
    "scripts/infrastructure/backfill/_d1_gaps.py": ConsumerVerdict(
        PLACEHOLDER_COVERAGE,
        "5m stored slots (_GRID_SLOTS_SQL) include placeholders; answered windows exist only "
        "since 2026-09-28, so a removed session-slot placeholder inside a fetch window becomes "
        "a re-ask (converges after one answered pass)",
        ("5m",),
    ),
    "services/bar_reconciliation_audit.py": ConsumerVerdict(
        REAL_ROWS, "counts rows by source; plan 25 task 3 makes a synthetic row a defect"
    ),
    "scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py": ConsumerVerdict(
        REAL_ROWS, "reads 1d with source <> 'synthetic_fill' already"
    ),
    "scripts/ops/bars/ops_masked_slot_baseline.py": ConsumerVerdict(
        REAL_ROWS, "measures synthetic rows; reads zero afterwards"
    ),
    "scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py": (
        ConsumerVerdict(
            REAL_ROWS,
            "'has any row' probe pick; a placeholder-only series becomes a never-fetched "
            "candidate, the truthful answer",
        )
    ),
    "src/api/routes/market_data.py": ConsumerVerdict(
        REAL_ROWS, "display surface returns stored rows as is; no grid reconstruction"
    ),
    "services/bar_auditor.py": ConsumerVerdict(
        PLACEHOLDER_COVERAGE,
        "1m completeness counts all rows in its recent lookback, placeholders included; unit "
        "inactive, gap requests go to the dormant streaming path",
        ("1m",),
    ),
    "scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh": ConsumerVerdict(
        REAL_ROWS, "seeds backfill_status from DISTINCT (symbol, timeframe); manual tool"
    ),
    "scripts/ops/bars/ops_export_known_answer_fixtures.py": ConsumerVerdict(
        REAL_ROWS, "exports price_sanity_status rows, real rows only"
    ),
    "services/bar_derivation.py": ConsumerVerdict(
        REAL_ROWS,
        "archive excludes synthetic_fill; the segment delete and checksum act on what is stored",
    ),
    "services/intraday_raw_archive.py": ConsumerVerdict(
        REAL_ROWS, "archive SELECT excludes synthetic_fill"
    ),
    _SELF: ConsumerVerdict(SELF, "this preflight"),
}


def load_allow_list(path: Path = _BOUNDARY_TEST) -> dict[str, str]:
    """The boundary test's `_ALLOW_LIST`, parsed (not imported) from its source."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            first = node.targets[0]
            target = first.id if isinstance(first, ast.Name) else None
        if target == "_ALLOW_LIST" and node.value is not None:
            return dict(ast.literal_eval(node.value))
    raise ValueError(f"_ALLOW_LIST not found in {path}")


def consumer_audit(
    allow_list: Iterable[str],
    synthetic_by_tf: Mapping[str, int],
    verdicts: Mapping[str, ConsumerVerdict] = CONSUMER_VERDICTS,
) -> tuple[list[dict[str, Any]], list[str]]:
    """One row per allow-listed reader, and the blockers.

    Blocks: a reader with no verdict, a reader that needs a contiguous series, and a reader that
    treats placeholders as coverage on a timeframe that still holds synthetic rows.
    """
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    for path in sorted(allow_list):
        verdict = verdicts.get(path)
        if verdict is None:
            rows.append({"path": path, "category": "unknown", "blocks": True, "reason": ""})
            blockers.append(f"consumer {path}: no verdict recorded")
            continue
        bites = [tf for tf in verdict.timeframes if synthetic_by_tf.get(tf, 0) > 0]
        blocks = verdict.category == CONTIGUOUS or (
            verdict.category == PLACEHOLDER_COVERAGE and bool(bites)
        )
        rows.append(
            {
                "path": path,
                "category": verdict.category,
                "timeframes_with_synthetic": bites,
                "blocks": blocks,
                "reason": verdict.reason,
            }
        )
        if blocks:
            detail = f" on {','.join(bites)}" if bites else ""
            blockers.append(f"consumer {path}: {verdict.category}{detail}")
    return rows, blockers


# --- chunk measurement ------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkInfo:
    schema: str
    name: str
    is_compressed: bool
    total_bytes: int
    before_bytes: int | None  # uncompressed size of a compressed chunk
    after_bytes: int | None  # compressed size of a compressed chunk


@dataclass(frozen=True)
class TfCount:
    total: int
    synthetic: int
    null_source: int
    synthetic_tradeable: int

    @property
    def real(self) -> int:
        return self.total - self.synthetic


@dataclass
class TfSummary:
    total: int = 0
    synthetic: int = 0
    real: int = 0
    null_source: int = 0
    synthetic_tradeable: int = 0
    chunks: int = 0
    rows_in_compressed_chunks: int = 0
    rows_in_uncompressed_chunks: int = 0
    est_compressed_bytes: float = 0.0
    est_uncompressed_bytes: float = 0.0
    est_real_uncompressed_bytes: float = 0.0


def _chunk_raw_bytes(chunk: ChunkInfo) -> int:
    """A chunk's size uncompressed: before-compression bytes, or its size when not compressed."""
    if chunk.is_compressed and chunk.before_bytes is not None:
        return chunk.before_bytes
    return chunk.total_bytes


def summarize(
    chunks: Sequence[ChunkInfo], counts: Mapping[str, Mapping[str, TfCount]]
) -> dict[str, TfSummary]:
    """Per timeframe totals from per-chunk counts (keyed by chunk name).

    Bytes per timeframe are estimates: a chunk's bytes are apportioned by its row share. Rows are
    fixed width, so the uncompressed share is close; placeholders compress far better than real
    rows, so the compressed share understates the real rows' part.
    """
    out: dict[str, TfSummary] = defaultdict(TfSummary)
    for chunk in chunks:
        by_tf = counts.get(chunk.name, {})
        chunk_rows = sum(c.total for c in by_tf.values())
        if chunk_rows == 0:
            continue
        raw = _chunk_raw_bytes(chunk)
        for tf, c in by_tf.items():
            s = out[tf]
            s.total += c.total
            s.synthetic += c.synthetic
            s.real += c.real
            s.null_source += c.null_source
            s.synthetic_tradeable += c.synthetic_tradeable
            s.chunks += 1
            share = c.total / chunk_rows
            if chunk.is_compressed:
                s.rows_in_compressed_chunks += c.total
                s.est_compressed_bytes += chunk.total_bytes * share
            else:
                s.rows_in_uncompressed_chunks += c.total
            s.est_uncompressed_bytes += raw * share
            s.est_real_uncompressed_bytes += raw * (c.real / chunk_rows)
    return dict(sorted(out.items()))


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


def disk_plan(summary: Mapping[str, TfSummary], free_bytes: int, margin: float) -> DiskPlan:
    """The copy lands uncompressed before its chunks compress, so the peak is the real rows'
    uncompressed size; the margin covers WAL, index builds and the estimate's error."""
    if margin < 1.0:
        raise ValueError(f"disk margin must be >= 1.0, got {margin}")
    peak = sum(s.est_real_uncompressed_bytes for s in summary.values())
    return DiskPlan(free_bytes, peak, margin, peak * margin)


def tradeable_blockers(summary: Mapping[str, TfSummary]) -> list[str]:
    """A synthetic row with volume > 0 is visible through the tradeable view today; dropping it
    would change what consumers see, so the swap must not proceed while any exists."""
    return [
        f"{tf}: {s.synthetic_tradeable} synthetic_fill rows with volume > 0"
        for tf, s in summary.items()
        if s.synthetic_tradeable
    ]


def digest_column_blockers(live_columns: Sequence[str]) -> list[str]:
    expected = set(KEY_COLUMNS) | set(DIGEST_COLUMNS)
    live = set(live_columns)
    out = []
    if live - expected:
        out.append(f"columns not covered by the digest: {sorted(live - expected)}")
    if expected - live:
        out.append(f"digest columns missing from the table: {sorted(expected - live)}")
    return out


# --- masked-slot gate (185-23) ----------------------------------------------------------------

MASKED_GATE_TIMEFRAMES = ("15m", "1h")


@dataclass(frozen=True)
class MaskedFact:
    timeframe: str
    value: float
    passed: bool
    evaluated_at: datetime


def masked_gate_blockers(
    facts: Mapping[str, MaskedFact], now: datetime, max_age: timedelta
) -> list[str]:
    """The latest D7 masked-slot fact per derived timeframe must exist, read zero, and be fresh."""
    out = []
    for tf in MASKED_GATE_TIMEFRAMES:
        fact = facts.get(tf)
        if fact is None:
            out.append(f"masked slots {tf}: no D7 fact")
        elif not fact.passed or fact.value != 0:
            out.append(f"masked slots {tf}: {fact.value:g} on derived symbols")
        elif now - fact.evaluated_at > max_age:
            out.append(f"masked slots {tf}: latest fact {format_ts(fact.evaluated_at)} is stale")
    return out


# --- writer check -----------------------------------------------------------------------------


@dataclass(frozen=True)
class WriterState:
    lock_holders: tuple[str, ...] = ()  # application_name of each advisory holder
    processes: tuple[str, ...] = ()  # "pid script" of each writer process
    active_units: tuple[str, ...] = ()
    write_locks: tuple[str, ...] = ()  # "pid mode relation" of each foreign write lock


def writer_blockers(state: WriterState) -> list[str]:
    """Every writer found, one line each. Empty means nothing writes the table right now."""
    return (
        [f"lock held: {h}" for h in state.lock_holders]
        + [f"writer process: {p}" for p in state.processes]
        + [f"writer unit active: {u}" for u in state.active_units]
        + [f"write lock: {w}" for w in state.write_locks]
    )


class SwapRefused(RuntimeError):
    """A writer is running; the operation would read or write a moving table."""


def refuse_if_writers(state: WriterState) -> None:
    blockers = writer_blockers(state)
    if blockers:
        raise SwapRefused("; ".join(blockers))


def advisory_key_parts(name: str) -> tuple[int, int]:
    """(classid, objid) of the session advisory lock on `name`, as pg_locks shows them."""
    key = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)
    return (key >> 32) & 0xFFFFFFFF, key & 0xFFFFFFFF


def writer_processes(cmdlines: Mapping[int, Sequence[str]], self_pid: int) -> list[str]:
    """Pids whose argv runs a writer script (exact basename match per argv element)."""
    found = []
    for pid, argv in sorted(cmdlines.items()):
        if pid == self_pid:
            continue
        for arg in argv:
            if os.path.basename(arg) in WRITER_SCRIPTS:
                found.append(f"{pid} {os.path.basename(arg)}")
                break
    return found


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


def _active_units(units: Sequence[str]) -> list[str]:
    result = subprocess.run(
        ["systemctl", "is-active", *units], capture_output=True, text=True, check=False
    )
    states = result.stdout.split()
    if len(states) != len(units):
        # Loud: an unreadable state is not "inactive".
        return [f"{u} (state unreadable)" for u in units]
    return [u for u, s in zip(units, states, strict=True) if s in {"active", "activating"}]


_LOCK_HOLDERS_SQL = """
SELECT a.pid, a.application_name
FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.locktype = 'advisory' AND l.granted AND (l.classid, l.objid) IN (SELECT * FROM unnest(%s::oid[], %s::oid[]))
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
  AND l.mode = ANY(%s)
ORDER BY l.pid, 3
"""


def load_writer_state(conn: Any) -> WriterState:
    parts = [advisory_key_parts(n) for n in WRITER_LOCK_NAMES]
    with conn.cursor() as cur:
        cur.execute(_LOCK_HOLDERS_SQL, ([p[0] for p in parts], [p[1] for p in parts]))
        holders = tuple(f"{pid} {app}" for pid, app in cur.fetchall())
        cur.execute(_WRITE_LOCKS_SQL, (_TABLE, _TABLE, sorted(_WRITE_LOCK_MODES)))
        locks = tuple(f"{pid} {mode} {rel}" for pid, mode, rel in cur.fetchall())
    return WriterState(
        lock_holders=holders,
        processes=tuple(writer_processes(_read_cmdlines(), os.getpid())),
        active_units=tuple(_active_units(WRITER_UNITS)),
        write_locks=locks,
    )


# --- digest comparison ------------------------------------------------------------------------

DigestMap = Mapping[tuple[str, str], tuple[int, str]]


@dataclass
class DigestComparison:
    missing_in_new: list[tuple[str, str]] = field(default_factory=list)
    extra_in_new: list[tuple[str, str]] = field(default_factory=list)
    count_mismatch: list[tuple[str, str, int, int]] = field(default_factory=list)
    digest_mismatch: list[tuple[str, str]] = field(default_factory=list)
    n_compared: int = 0

    @property
    def ok(self) -> bool:
        return not (
            self.missing_in_new or self.extra_in_new or self.count_mismatch or self.digest_mismatch
        )


def compare_digests(old: DigestMap, new: DigestMap) -> DigestComparison:
    """Per (symbol, timeframe): the new table's real-row count and digest equal the old's.

    A key on one side only is a mismatch too: a series lost in the copy, or one that appeared.
    """
    result = DigestComparison()
    for key in sorted(old.keys() | new.keys()):
        if key not in new:
            result.missing_in_new.append(key)
            continue
        if key not in old:
            result.extra_in_new.append(key)
            continue
        result.n_compared += 1
        (old_n, old_digest), (new_n, new_digest) = old[key], new[key]
        if old_n != new_n:
            result.count_mismatch.append((*key, old_n, new_n))
        elif old_digest != new_digest:
            result.digest_mismatch.append(key)
    return result


def _digests(
    conn: Any, digest_sql: str, symbols: Sequence[str]
) -> dict[tuple[str, str], tuple[int, str]]:
    out: dict[tuple[str, str], tuple[int, str]] = {}
    with conn.cursor() as cur:
        for symbol in symbols:
            cur.execute(digest_sql, (symbol,))
            for tf, n, digest in cur.fetchall():
                out[(symbol, tf)] = (int(n), str(digest))
    return out


# --- live IO ----------------------------------------------------------------------------------

_CHUNKS_SQL = """
SELECT c.chunk_schema, c.chunk_name, c.is_compressed, d.total_bytes,
       s.before_compression_total_bytes, s.after_compression_total_bytes
FROM timescaledb_information.chunks c
JOIN chunks_detailed_size(%s::regclass) d
  ON d.chunk_schema = c.chunk_schema AND d.chunk_name = c.chunk_name
LEFT JOIN chunk_compression_stats(%s::regclass) s
  ON s.chunk_schema = c.chunk_schema AND s.chunk_name = c.chunk_name
WHERE c.hypertable_name = %s
ORDER BY c.range_start
"""

_CHUNK_COUNTS_SQL = sql.SQL("""
SELECT timeframe, count(*),
       count(*) FILTER (WHERE source = 'synthetic_fill'),
       count(*) FILTER (WHERE source IS NULL),
       count(*) FILTER (WHERE source = 'synthetic_fill' AND volume > 0)
FROM {chunk}
GROUP BY timeframe
""")

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

_MASKED_FACTS_SQL = """
SELECT DISTINCT ON (subject) subject, metric_value, passed, evaluated_at
FROM integrity_monitor
WHERE monitor_type = 'bar_reconciliation' AND metric_name = 'masked_slots_derived_symbols'
ORDER BY subject, evaluated_at DESC
"""


def load_apr(conn: Any) -> tuple[dict[str, float], dict[str, str]]:
    """APR values and where each came from ('apr' or 'default', the latter until migration 439
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


def load_chunks(conn: Any) -> list[ChunkInfo]:
    with conn.cursor() as cur:
        cur.execute(_CHUNKS_SQL, (_TABLE, _TABLE, _TABLE))
        return [
            ChunkInfo(
                schema,
                name,
                bool(compressed),
                int(total),
                None if before is None else int(before),
                None if after is None else int(after),
            )
            for schema, name, compressed, total, before, after in cur.fetchall()
        ]


def count_chunk(conn: Any, chunk: ChunkInfo) -> dict[str, TfCount]:
    query = _CHUNK_COUNTS_SQL.format(chunk=sql.Identifier(chunk.schema, chunk.name))
    with conn.cursor() as cur:
        cur.execute(query)
        return {
            tf: TfCount(int(n), int(syn), int(null_src), int(syn_trade))
            for tf, n, syn, null_src, syn_trade in cur.fetchall()
        }


def load_masked_facts(conn: Any) -> dict[str, MaskedFact]:
    out = {}
    with conn.cursor() as cur:
        cur.execute(_MASKED_FACTS_SQL)
        for subject, value, passed, evaluated_at in cur.fetchall():
            tf = subject.rsplit("tf=", 1)[-1]
            out[tf] = MaskedFact(tf, float(value), bool(passed), evaluated_at)
    return out


def _fetch_column(conn: Any, query: str, params: Sequence[Any]) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return [row[0] for row in cur.fetchall()]


def format_ts(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gib(n: float) -> float:
    return round(n / 2**30, 2)


# --- commands ---------------------------------------------------------------------------------


def preflight(conn: Any, data_path: str) -> tuple[dict[str, Any], list[str]]:
    """The dry run: measure, audit, gate. Returns the report and the blockers."""
    apr, provenance = load_apr(conn)
    conn.execute(f"SET statement_timeout = '{int(apr[APR_STATEMENT_TIMEOUT_S])}s'")
    blockers: list[str] = []

    writers = load_writer_state(conn)
    blockers += writer_blockers(writers)

    chunks = load_chunks(conn)
    counts = {c.name: count_chunk(conn, c) for c in chunks}
    summary = summarize(chunks, counts)
    blockers += tradeable_blockers(summary)

    plan = disk_plan(summary, shutil.disk_usage(data_path).free, apr[APR_DISK_MARGIN])
    if not plan.ok:
        blockers.append(
            f"disk: {_gib(plan.free_bytes)} GiB free < {_gib(plan.required_bytes)} GiB required"
        )

    allow_list = load_allow_list()
    synthetic_by_tf = {tf: s.synthetic for tf, s in summary.items()}
    consumers, consumer_blockers = consumer_audit(allow_list, synthetic_by_tf)
    blockers += consumer_blockers

    now = datetime.now(UTC)
    max_age = timedelta(hours=apr[APR_MASKED_AUDIT_MAX_AGE_H])
    facts = load_masked_facts(conn)
    blockers += masked_gate_blockers(facts, now, max_age)

    columns = _fetch_column(conn, _COLUMNS_SQL, (_TABLE,))
    blockers += digest_column_blockers(columns)
    views = _fetch_column(conn, _DEPENDENT_VIEWS_SQL, (_TABLE, _TABLE))

    report: dict[str, Any] = {
        "job": _JOB,
        "mode": "dry_run",
        "measured_at": format_ts(now),
        "apr": {k: {"value": v, "source": provenance[k]} for k, v in apr.items()},
        "chunks": {
            "total": len(chunks),
            "compressed": sum(c.is_compressed for c in chunks),
            "compressed_bytes": sum(c.total_bytes for c in chunks if c.is_compressed),
            "uncompressed_bytes": sum(c.total_bytes for c in chunks if not c.is_compressed),
            "compressed_chunks_raw_bytes": sum(
                c.before_bytes or 0 for c in chunks if c.is_compressed
            ),
        },
        "by_timeframe": {
            tf: {
                "total": s.total,
                "synthetic_fill": s.synthetic,
                "real": s.real,
                "null_source": s.null_source,
                "synthetic_with_volume": s.synthetic_tradeable,
                "chunks": s.chunks,
                "rows_in_compressed_chunks": s.rows_in_compressed_chunks,
                "rows_in_uncompressed_chunks": s.rows_in_uncompressed_chunks,
                "est_compressed_gib": _gib(s.est_compressed_bytes),
                "est_uncompressed_gib": _gib(s.est_uncompressed_bytes),
                "est_real_uncompressed_gib": _gib(s.est_real_uncompressed_bytes),
            }
            for tf, s in summary.items()
        },
        "totals": {
            "rows": sum(s.total for s in summary.values()),
            "synthetic_fill": sum(s.synthetic for s in summary.values()),
            "real": sum(s.real for s in summary.values()),
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
        "writers": {
            "lock_holders": list(writers.lock_holders),
            "processes": list(writers.processes),
            "active_units": list(writers.active_units),
            "write_locks": list(writers.write_locks),
        },
        "masked_slots": {
            tf: {
                "value": f.value,
                "passed": f.passed,
                "evaluated_at": format_ts(f.evaluated_at),
            }
            for tf, f in sorted(facts.items())
        },
        "consumers": consumers,
        "dependent_views": views,
        "blockers": blockers,
        "verdict": "blocked" if blockers else "ready",
    }
    return report, blockers


def verify(conn: Any) -> tuple[dict[str, Any], list[str]]:
    """Compare real rows of the old and new tables per (symbol, timeframe). Read-only; refuses
    while a writer runs, since counts taken from a moving table prove nothing."""
    refuse_if_writers(load_writer_state(conn))
    apr, _ = load_apr(conn)
    conn.execute(f"SET statement_timeout = '{int(apr[APR_STATEMENT_TIMEOUT_S])}s'")
    conn.execute("SET TIME ZONE 'UTC'")
    with conn.cursor() as cur:
        cur.execute(_OLD_SYMBOLS_SQL)
        symbols = [row[0] for row in cur.fetchall()]
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT DISTINCT symbol FROM {}").format(sql.Identifier(_NEW_TABLE)))
        symbols = sorted(set(symbols) | {row[0] for row in cur.fetchall()})
    result = compare_digests(
        _digests(conn, _OLD_DIGEST_SQL, symbols), _digests(conn, _NEW_DIGEST_SQL, symbols)
    )
    report = {
        "job": _JOB,
        "mode": "verify",
        "compared": result.n_compared,
        "missing_in_new": result.missing_in_new,
        "extra_in_new": result.extra_in_new,
        "count_mismatch": result.count_mismatch,
        "digest_mismatch": result.digest_mismatch,
        "ok": result.ok,
    }
    return report, ([] if result.ok else ["digest comparison failed"])


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--verify",
        action="store_true",
        help=f"compare real rows of {_TABLE} and {_NEW_TABLE} (read-only)",
    )
    parser.add_argument(
        "--data-path",
        default="/var/lib/docker",
        help="a path on the filesystem holding the database volume (free-disk check)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = Settings()
    with psycopg.connect(settings.database_url, autocommit=True, application_name=_JOB) as conn:
        conn.execute("SET default_transaction_read_only = on")
        try:
            report, blockers = verify(conn) if args.verify else preflight(conn, args.data_path)
        except SwapRefused as error:
            print(json.dumps({"job": _JOB, "refused": str(error)}, indent=2))
            return EXIT_BLOCKED
    print(json.dumps(report, indent=2, default=str))
    return EXIT_BLOCKED if blockers else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
