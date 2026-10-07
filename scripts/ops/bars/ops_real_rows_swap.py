r"""Real-rows swap of market_data_ohlcv: preflight, copy, verify, swap, rollback, drop (todo 462 step 6, plan 185-25).

The swap rebuilds market_data_ohlcv from its real rows (every row whose source is not
'synthetic_fill', NULL source included) into a new table and swaps it in, instead of deleting the
placeholders out of compressed chunks. Migration 439 creates the empty target
(market_data_ohlcv_new, structurally identical, marked by its COMMENT); this script does the rest.
The dry run, --status, --verify and --post-check are read-only; --copy, --swap, --rollback and
--drop-old write, and each refuses unless the state (absent, pre, swapped, done) allows it.

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
  and no other session holds a write lock on the hypertable or any of its chunks (process and
  unit checks run only when the target is the live database);
- the digest-column check: the live column set equals the columns the per-(symbol, timeframe)
  digest covers, so a column added later cannot escape the comparison;
- the views that depend on the table (the swap recreates them).

Write steps:

- --copy: the gates above (placeholder_coverage consumers pass only with
  --accept-placeholder-coverage) plus shape parity of the two tables, then the real rows copy one
  chunk-aligned window per transaction; each finished window's chunk is compressed (when the
  policy would have) and vacuumed. Restartable: a compressed window is done, any other is
  cleared and copied again.
- --swap: the gates, then the full per-(symbol, timeframe) count and digest verify (a mismatch
  aborts with the original live and untouched), then one transaction under ACCESS EXCLUSIVE on
  both tables: the original's write counters must equal the ones taken before the verify, the
  per-timeframe counts are rechecked, the tables and their indexes are renamed, every dependent
  view is recreated from its own definition, the compression policy moves. The post-swap checks
  run next; if any fails or raises, the exchange is rolled back before the script exits.
- --rollback: the reverse exchange while market_data_ohlcv_old exists.
- --drop-old: re-runs the post-swap checks, drops market_data_ohlcv_old (never CASCADE), then a
  bare `VACUUM market_data_ohlcv;` (compressed-hypertable rule: compress_chunk leaves the heap
  pages of the copied rows behind). Re-runnable: in `done` it only vacuums.

Exit status: 0 when every gate or check passes, 3 when any blocks or a step aborts, 2 on a usage
error. --dsn targets a scratch database for rehearsals
(tests/integration/test_ops_real_rows_swap_scratch.py).

Live runbook (the lane and every writer stopped for the whole run; expected wall time about 45 to
75 minutes, extrapolated from the scratch rehearsal at 60 symbols: copy 2.0M real rows of 7.5M
in 8 s, verify 2.0M rows in 3.8 s, and a live one-symbol digest of SPY's 623k real rows in 0.8 s):

 1. Record the lane's position: `tail -5 logs/backfill_ops/intraday_htf/htf_all_loop.log`.
 2. Stop the lane, outermost first so nothing respawns, by PID (never pkill -f; bracket the
    pattern so grep does not match itself):
      ps -eo pid,ppid,args | grep -E '[i]ntraday_chain\.sh'                  # kill this first
      ps -eo pid,ppid,args | grep -E '[i]ntraday_(htf|5m)_lane\.sh'          # then these
      ps -eo pid,ppid,args | grep -E '[i]bkr_history_fetcher\.py'            # then this
    `kill <pid>` each, then confirm all three greps print nothing.
 3. Orphan workers: `ps -eo pid,ppid,args | grep -E '[m]ultiprocessing|[f]orkserver'` must show
    nothing from the pipeline; kill any by PID.
 4. Lease and backends: this must return no rows (pg_terminate_backend any leftover worker):
      SELECT pid, application_name, state, wait_event, left(query, 60) FROM pg_stat_activity
      WHERE datname = 'indicagent' AND pid <> pg_backend_pid()
        AND (application_name LIKE 'lease:%' OR query ILIKE '%market_data_ohlcv%');
 5. Units and timers: `systemctl is-active indicagent-ibkr-history-fetcher.service
    indicagent-tradier-daily.service indicagent-bar-derivation.service
    indicagent-bar-writer.service indicagent-bar-auditor.service` all inactive;
    `systemctl list-timers --all | grep -E 'ibkr-history-fetcher|tradier-daily'` shows no
    next run inside the window (stop the timer for the window if it does).
 6. Dry run: `.venv/bin/python -m scripts.ops.bars.ops_real_rows_swap`. Only the
    placeholder_coverage consumer blockers may remain; the masked-slot fact must be under 48 h old.
 7. Apply migration 439: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent
    -v ON_ERROR_STOP=1 -f production/migrations/439_market_data_ohlcv_real_rows_swap.sql`.
 8. `--copy --accept-placeholder-coverage` (about 15 to 30 min; re-run after any interruption).
 9. `--swap --accept-placeholder-coverage` (verify about 10 min, exclusive lock about 30 s,
    post-checks about 5 to 15 min). Exit 0 means swapped with the original kept.
10. `--status`, then `--drop-old` (drop plus VACUUM, minutes); record its reclaimed_gib.
11. Restart any timer stopped in step 5 (the lane scripts this step once relaunched were
    deleted in plan 189-07; the IBKR history fetcher's ledger resumes where fetching stopped).

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
import re
import shutil
import subprocess
import sys
import time
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
APR_COPY_TIMEOUT_S = "infra.real_rows_swap.copy_statement_timeout_s"
APR_LOCK_TIMEOUT_S = "infra.real_rows_swap.lock_timeout_s"
APR_STATS_WAIT_S = "infra.real_rows_swap.stats_flush_wait_s"
APR_DEFAULTS: dict[str, float] = {
    APR_DISK_MARGIN: 2.0,
    APR_STATEMENT_TIMEOUT_S: 600.0,
    APR_MASKED_AUDIT_MAX_AGE_H: 48.0,
    APR_COPY_TIMEOUT_S: 7200.0,
    APR_LOCK_TIMEOUT_S: 30.0,
    APR_STATS_WAIT_S: 11.0,
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
        "infrastructure_run_tradier_daily.py",
        "infrastructure_fetch_htf_bars.py",
        "ibkr_history_fetcher.py",
    }
)
WRITER_UNITS = (
    "indicagent-ibkr-history-fetcher.service",
    "indicagent-tradier-daily.service",
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
    "scripts/infrastructure/backfill/_history_fetch.py": ConsumerVerdict(
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
    "scripts/ops/bars/ops_source_policy.py": ConsumerVerdict(
        REAL_ROWS, "EXISTS probe for a stored tradier 1d row; placeholders are never tradier"
    ),
    "scripts/ops/bars/ops_data_bar_check.py": ConsumerVerdict(
        REAL_ROWS, "reads the stored row of 87 fixed 1d known-answer keys (plan 185-34)"
    ),
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


def load_writer_state(conn: Any, host_checks: bool = True) -> WriterState:
    """Database checks always; host checks (processes, units) only when the target is the live
    database, since the host's writers write that database and no other (a scratch rehearsal
    must not be refused by the live lane, and must not pass the live run by skipping it)."""
    parts = [advisory_key_parts(n) for n in WRITER_LOCK_NAMES]
    with conn.cursor() as cur:
        cur.execute(_LOCK_HOLDERS_SQL, ([p[0] for p in parts], [p[1] for p in parts]))
        holders = tuple(f"{pid} {app}" for pid, app in cur.fetchall())
        cur.execute(_WRITE_LOCKS_SQL, (_TABLE, _TABLE, sorted(_WRITE_LOCK_MODES)))
        locks = tuple(f"{pid} {mode} {rel}" for pid, mode, rel in cur.fetchall())
    return WriterState(
        lock_holders=holders,
        processes=tuple(writer_processes(_read_cmdlines(), os.getpid())) if host_checks else (),
        active_units=tuple(_active_units(WRITER_UNITS)) if host_checks else (),
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
    return _count_relation(conn, chunk.schema, chunk.name)


def _count_relation(conn: Any, schema: str, name: str) -> dict[str, TfCount]:
    query = _CHUNK_COUNTS_SQL.format(chunk=sql.Identifier(schema, name))
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


def preflight(
    conn: Any, data_path: str, host_checks: bool = True
) -> tuple[dict[str, Any], list[str]]:
    """The dry run: measure, audit, gate. Returns the report and the blockers."""
    apr, provenance = load_apr(conn)
    conn.execute(f"SET statement_timeout = '{int(apr[APR_STATEMENT_TIMEOUT_S])}s'")
    blockers: list[str] = []

    writers = load_writer_state(conn, host_checks)
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
            "host_checks": host_checks,
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


def verify(conn: Any, host_checks: bool = True) -> tuple[dict[str, Any], list[str]]:
    """Compare real rows of the old and new tables per (symbol, timeframe). Read-only; refuses
    while a writer runs, since counts taken from a moving table prove nothing.

    The digests compare real rows on both sides; a synthetic_fill row in the new table would hide
    behind that filter, so the new table's synthetic count must also read zero."""
    refuse_if_writers(load_writer_state(conn, host_checks))
    require_state(conn, PRE)
    apr, _ = load_apr(conn)
    conn.execute(f"SET statement_timeout = '{int(apr[APR_STATEMENT_TIMEOUT_S])}s'")
    conn.execute("SET TIME ZONE 'UTC'")
    with conn.cursor() as cur:
        cur.execute(_OLD_SYMBOLS_SQL)
        symbols = [row[0] for row in cur.fetchall()]
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT DISTINCT symbol FROM {}").format(sql.Identifier(_NEW_TABLE)))
        symbols = sorted(set(symbols) | {row[0] for row in cur.fetchall()})
    started = time.monotonic()
    old_digests = _digests(conn, _OLD_DIGEST_SQL, symbols)
    new_digests = _digests(conn, _NEW_DIGEST_SQL, symbols)
    result = compare_digests(old_digests, new_digests)
    new_synthetic = sum(c.synthetic for c in table_counts(conn, _NEW_TABLE).values())
    ok = result.ok and new_synthetic == 0
    report = {
        "job": _JOB,
        "mode": "verify",
        "symbols": len(symbols),
        "compared": result.n_compared,
        "real_rows_compared": sum(n for n, _ in old_digests.values()),
        "missing_in_new": result.missing_in_new,
        "extra_in_new": result.extra_in_new,
        "count_mismatch": result.count_mismatch,
        "digest_mismatch": result.digest_mismatch,
        "synthetic_in_new": new_synthetic,
        "seconds": round(time.monotonic() - started, 1),
        "ok": ok,
    }
    blockers = []
    if not result.ok:
        blockers.append("digest comparison failed")
    if new_synthetic:
        blockers.append(f"{_NEW_TABLE} holds {new_synthetic} synthetic_fill rows")
    return report, blockers


# --- write path: state ------------------------------------------------------------------------

_OLD_TABLE = "market_data_ohlcv_old"
# COMMENT prefix migration 439 puts on the rebuilt table; it travels with every rename, so it names
# the rebuilt table in every state.
MARKER = "real_rows_swap_439"
SUFFIX_REBUILT = "_rebuilt"  # the rebuilt table's index names while it is not live
SUFFIX_ORIGINAL = "_original"  # the original table's index names while it is not live

ABSENT = "absent"  # migration 439 part 2 not applied: only the original table
PRE = "pre"  # original live, rebuilt at market_data_ohlcv_new
SWAPPED = "swapped"  # rebuilt live, original kept at market_data_ohlcv_old (the rollback)
DONE = "done"  # rebuilt live, original dropped
INCONSISTENT = "inconsistent"


class SwapAborted(RuntimeError):
    """A check failed. The step that raised changed nothing (its transaction rolled back)."""


def classify_state(tables: Mapping[str, bool]) -> str:
    """The swap's state from which of the three names exist and whether each carries the rebuilt
    table's marker. Any other combination is inconsistent and every write step refuses it."""
    names = set(tables)
    if names == {_TABLE}:
        return DONE if tables[_TABLE] else ABSENT
    if names == {_TABLE, _NEW_TABLE} and not tables[_TABLE] and tables[_NEW_TABLE]:
        return PRE
    if names == {_TABLE, _OLD_TABLE} and tables[_TABLE] and not tables[_OLD_TABLE]:
        return SWAPPED
    return INCONSISTENT


_STATE_SQL = """
SELECT c.relname, coalesce(obj_description(c.oid, 'pg_class'), '') LIKE %s
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND c.relname = ANY(%s)
"""


def load_state(conn: Any) -> str:
    with conn.cursor() as cur:
        cur.execute(_STATE_SQL, (MARKER + "%", [_TABLE, _NEW_TABLE, _OLD_TABLE]))
        return classify_state({name: bool(marked) for name, marked in cur.fetchall()})


def require_state(conn: Any, *allowed: str) -> str:
    state = load_state(conn)
    if state not in allowed:
        raise SwapAborted(f"state is {state}; this step runs only in {' or '.join(allowed)}")
    return state


# --- write path: table shape ------------------------------------------------------------------


@dataclass(frozen=True)
class TableShape:
    """Everything that must be identical between the original and the rebuilt table. Index names
    are compared without the swap suffixes; NOT NULL constraint names are compared as they are."""

    columns: tuple[tuple[str, str, bool], ...]
    constraints: tuple[tuple[str, str], ...]
    indexes: tuple[tuple[str, str], ...]
    dimensions: tuple[tuple[str, ...], ...]
    columnstore: tuple[str, ...]
    acl: tuple[tuple[str, str], ...]
    reloptions: tuple[str, ...]
    owner: str


def index_base(name: str) -> str:
    for suffix in (SUFFIX_REBUILT, SUFFIX_ORIGINAL):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def index_signature(unique: bool, definition: str) -> str:
    """`CREATE [UNIQUE] INDEX name ON table USING ...` reduced to what does not name anything."""
    _, _, using = definition.partition(" USING ")
    return ("UNIQUE " if unique else "") + using


def shape_differences(a: TableShape, b: TableShape) -> list[str]:
    return [
        f"{name}: {getattr(a, name)!r} != {getattr(b, name)!r}"
        for name in TableShape.__dataclass_fields__
        if getattr(a, name) != getattr(b, name)
    ]


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
    return TableShape(
        columns, constraints, indexes, dimensions, columnstore, acl, tuple(reloptions), owner
    )


# --- write path: policy -----------------------------------------------------------------------


@dataclass(frozen=True)
class Policy:
    job_id: int
    compress_after: str
    schedule_interval: str
    scheduled: bool
    config: str  # the job config without hypertable_id, compared across the two tables


_POLICY_SQL = """
SELECT job_id, config->>'compress_after', schedule_interval::text, scheduled,
       (config - 'hypertable_id')::text
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_compression' AND hypertable_schema = 'public' AND hypertable_name = %s
ORDER BY job_id
"""


def load_policies(conn: Any, table: str) -> list[Policy]:
    with conn.cursor() as cur:
        cur.execute(_POLICY_SQL, (table,))
        return [Policy(int(j), str(a), str(s), bool(sc), str(c)) for j, a, s, sc, c in cur]


def policy_differences(live: Sequence[Policy], kept: Sequence[Policy]) -> list[str]:
    """After an exchange: the live table has one scheduled policy, the kept table's are all
    unscheduled, and the two carry the same config and schedule."""
    out = []
    if len(live) != 1 or not live[0].scheduled:
        out.append(f"live table policies {live!r}: want exactly one, scheduled")
    if any(p.scheduled for p in kept):
        out.append(f"kept table policy still scheduled: {kept!r}")
    if live and kept:
        a, b = live[0], kept[0]
        if (a.config, a.schedule_interval) != (b.config, b.schedule_interval):
            out.append(f"policy differs: {a!r} vs {b!r}")
    return out


# --- write path: copy -------------------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


def chunk_windows(lo: datetime, hi: datetime, interval: timedelta) -> list[Window]:
    """Windows covering [lo, hi) on the rebuilt table's chunk grid: TimescaleDB aligns time chunks
    to whole multiples of the interval from the Unix epoch, so each window is exactly one chunk of
    the rebuilt table (checked after every window's copy, never assumed)."""
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
    """The rebuilt table's one chunk for this window, or None when the window holds no rows."""
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
_CHUNK_NAMES_SQL = """
SELECT chunk_schema, chunk_name FROM timescaledb_information.chunks
WHERE hypertable_schema = 'public' AND hypertable_name = %s ORDER BY range_start
"""
# The copy's own statements, written out (not built from a name) so the boundary scans see them.
# The column list is every column; digest_column_blockers proves the table has no other.
COPY_COLUMNS = (*KEY_COLUMNS, *DIGEST_COLUMNS)
_COPY_WINDOW_SQL = """
INSERT INTO market_data_ohlcv_new
    ("timestamp", symbol, timeframe, open, high, low, close, volume, source, base,
     price_sanity_status)
SELECT "timestamp", symbol, timeframe, open, high, low, close, volume, source, base,
       price_sanity_status
FROM market_data_ohlcv
WHERE "timestamp" >= %s AND "timestamp" < %s AND source IS DISTINCT FROM 'synthetic_fill'
"""
_CLEAR_WINDOW_SQL = """
DELETE FROM market_data_ohlcv_new WHERE "timestamp" >= %s AND "timestamp" < %s
"""


def _window_chunks(conn: Any, table: str, window: Window) -> list[ChunkRange]:
    with conn.cursor() as cur:
        cur.execute(_WINDOW_CHUNKS_SQL, (table, window.end, window.start))
        return [ChunkRange(s, n, a, b, bool(c)) for s, n, a, b, c in cur.fetchall()]


def table_counts(conn: Any, table: str) -> dict[str, TfCount]:
    """Per timeframe counts of a hypertable, summed per chunk (the vectorized path)."""
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for schema, name in _rows(conn, _CHUNK_NAMES_SQL, (table,)):
        for tf, c in _count_relation(conn, schema, name).items():
            acc = totals[tf]
            acc[0] += c.total
            acc[1] += c.synthetic
            acc[2] += c.null_source
            acc[3] += c.synthetic_tradeable
    return {tf: TfCount(*acc) for tf, acc in sorted(totals.items())}


def count_differences(original: Mapping[str, TfCount], rebuilt: Mapping[str, TfCount]) -> list[str]:
    """Per timeframe: the rebuilt table holds exactly the original's real rows, no synthetic."""
    out = []
    for tf in sorted(original.keys() | rebuilt.keys()):
        want = original[tf].real if tf in original else 0
        got = rebuilt[tf] if tf in rebuilt else TfCount(0, 0, 0, 0)
        if got.synthetic:
            out.append(f"{tf}: {got.synthetic} synthetic_fill rows in the rebuilt table")
        if got.total != want:
            out.append(f"{tf}: rebuilt {got.total} rows, original {want} real rows")
    return out


def _rows(conn: Any, query: Any, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return list(cur.fetchall())


def _scalar(conn: Any, query: Any, params: Sequence[Any] = ()) -> Any:
    rows = _rows(conn, query, params)
    return rows[0][0] if rows else None


def _set_timeouts(conn: Any, statement_s: float) -> None:
    conn.execute(f"SET statement_timeout = '{int(statement_s)}s'")
    conn.execute("SET TIME ZONE 'UTC'")


def copy_real_rows(conn: Any, apr: Mapping[str, float]) -> dict[str, Any]:
    """Copy the original's real rows into the rebuilt table, one chunk window per transaction.

    Restart-safe: a window is done when its rebuilt chunk is compressed, since a window is only
    compressed after its copy committed. Any other window is cleared and copied again, so a
    crash between the copy and the compression, or mid-copy, costs that one window. Windows newer
    than the compression policy's compress_after stay uncompressed (as the policy leaves them)
    and are copied again on every run. Each compressed or cleared chunk is vacuumed at once, so
    the copy's peak disk is one window's rows uncompressed, not the whole table's.
    """
    require_state(conn, PRE)
    policies = load_policies(conn, _TABLE)
    if len(policies) != 1:
        raise SwapAborted(f"{_TABLE} has {len(policies)} compression policies; want exactly one")
    interval = _scalar(conn, _TIME_INTERVAL_SQL, (_NEW_TABLE,))
    if not isinstance(interval, timedelta):
        raise SwapAborted(f"{_NEW_TABLE} chunk interval {interval!r} is not a fixed duration")
    lo, hi = _rows(conn, _CHUNK_SPAN_SQL, (_TABLE,))[0]
    cutoff = _scalar(conn, "SELECT now() - %s::interval", (policies[0].compress_after,))
    _set_timeouts(conn, apr[APR_COPY_TIMEOUT_S])

    started = time.monotonic()
    windows = [] if lo is None else chunk_windows(lo, hi, interval)
    log: list[dict[str, Any]] = []
    for window in windows:
        t0 = time.monotonic()
        chunk = window_chunk(_window_chunks(conn, _NEW_TABLE, window), window)
        if chunk is not None and chunk.is_compressed:
            log.append({"window": format_ts(window.start), "status": "done_earlier"})
            continue
        with conn.transaction():
            cleared = conn.execute(_CLEAR_WINDOW_SQL, window_params(window)).rowcount
            copied = conn.execute(_COPY_WINDOW_SQL, window_params(window)).rowcount
        chunk = window_chunk(_window_chunks(conn, _NEW_TABLE, window), window)
        compress = chunk is not None and window.end < cutoff
        if compress:
            conn.execute(
                "SELECT compress_chunk(format('%%I.%%I', %s::text, %s::text)::regclass)",
                (chunk.schema, chunk.name),
            )
        if chunk is not None and (compress or cleared):
            conn.execute(sql.SQL("VACUUM {}").format(sql.Identifier(chunk.schema, chunk.name)))
        if copied or cleared:
            log.append(
                {
                    "window": format_ts(window.start),
                    "status": "copied",
                    "rows": copied,
                    "cleared": cleared,
                    "compressed": compress,
                    "seconds": round(time.monotonic() - t0, 2),
                }
            )
    copy_seconds = time.monotonic() - started
    original, rebuilt = table_counts(conn, _TABLE), table_counts(conn, _NEW_TABLE)
    differences = count_differences(original, rebuilt)
    return {
        "windows": len(windows),
        "windows_copied": sum(1 for e in log if e["status"] == "copied"),
        "windows_done_earlier": sum(1 for e in log if e["status"] == "done_earlier"),
        "rows_copied": sum(e.get("rows", 0) for e in log),
        "copy_seconds": round(copy_seconds, 1),
        "log": log,
        "rebuilt_by_timeframe": {tf: c.total for tf, c in rebuilt.items()},
        "original_real_by_timeframe": {tf: c.real for tf, c in original.items()},
        "count_differences": differences,
    }


def window_params(window: Window) -> tuple[datetime, datetime]:
    return (window.start, window.end)


# --- write path: exchange ---------------------------------------------------------------------

# A table's write counters: every write to the hypertable, a chunk or a compressed chunk moves
# them, updates included (a count check cannot see an UPDATE). Compared before the verify and
# again under the swap's exclusive lock.
_WRITE_COUNTERS_SQL = """
WITH rels AS (
    SELECT %s::regclass AS rel
    UNION ALL
    SELECT show_chunks(%s::regclass)
    UNION ALL
    SELECT format('%%I.%%I', cc.schema_name, cc.table_name)::regclass
    FROM _timescaledb_catalog.hypertable h
    JOIN _timescaledb_catalog.chunk c ON c.hypertable_id = h.id
    JOIN _timescaledb_catalog.chunk cc ON cc.id = c.compressed_chunk_id
    WHERE h.schema_name = 'public' AND h.table_name = %s
)
SELECT count(*), coalesce(sum(s.n_tup_ins + s.n_tup_upd + s.n_tup_del), 0)
FROM rels LEFT JOIN pg_stat_all_tables s ON s.relid = rels.rel
"""


def write_counters(conn: Any, table: str) -> tuple[int, int]:
    conn.execute("SELECT pg_stat_clear_snapshot()")
    n_rels, n_writes = _rows(conn, _WRITE_COUNTERS_SQL, (table, table, table))[0]
    return int(n_rels), int(n_writes)


_DEPENDENT_VIEW_DEFS_SQL = """
SELECT DISTINCT n.nspname, v.relname, v.relkind::text, pg_get_viewdef(v.oid)
FROM pg_depend d
JOIN pg_rewrite r ON r.oid = d.objid
JOIN pg_class v ON v.oid = r.ev_class
JOIN pg_namespace n ON n.oid = v.relnamespace
WHERE d.refobjid = %s::regclass AND v.oid <> %s::regclass
ORDER BY 1, 2
"""
_INDEX_NAMES_SQL = """
SELECT i.relname FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
WHERE x.indrelid = %s::regclass ORDER BY 1
"""


def dependent_views(conn: Any, table: str) -> list[tuple[str, str, str, str]]:
    return [tuple(r) for r in _rows(conn, _DEPENDENT_VIEW_DEFS_SQL, (table, table))]


def plan_index_renames(
    live: Sequence[str], incoming: Sequence[str], live_suffix: str, incoming_suffix: str
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(old, new) renames: the live table's indexes take `live_suffix`, the incoming table's drop
    `incoming_suffix`. Both sides must name the same index set, or nothing is renamed."""
    stray = [n for n in live if index_base(n) != n]
    missing_suffix = [n for n in incoming if not n.endswith(incoming_suffix)]
    if stray or missing_suffix:
        raise SwapAborted(f"index names out of pattern: live {stray}, incoming {missing_suffix}")
    incoming_base = {n[: -len(incoming_suffix)] for n in incoming}
    if set(live) != incoming_base:
        raise SwapAborted(f"index sets differ: live {sorted(live)}, incoming {sorted(incoming)}")
    return (
        [(n, n + live_suffix) for n in sorted(live)],
        [(n, n[: -len(incoming_suffix)]) for n in sorted(incoming)],
    )


def exchange(
    conn: Any, *, live_to: str, live_suffix: str, incoming: str, incoming_suffix: str
) -> dict[str, Any]:
    """Rename the live table away and `incoming` into its name, in the caller's transaction (the
    caller holds ACCESS EXCLUSIVE on both). Every view on the live table is recreated from its
    own definition, captured before the rename (CREATE OR REPLACE keeps its grants and owner);
    the compression policy moves with the name. Ends by proving no view still reads the table
    that left the name."""
    views = dependent_views(conn, _TABLE)
    not_plain = [f"{s}.{v} ({k})" for s, v, k, _ in views if k != "v"]
    if not_plain:
        raise SwapAborted(f"dependents that are not plain views: {not_plain}")
    live_renames, incoming_renames = plan_index_renames(
        [r[0] for r in _rows(conn, _INDEX_NAMES_SQL, (_TABLE,))],
        [r[0] for r in _rows(conn, _INDEX_NAMES_SQL, (incoming,))],
        live_suffix,
        incoming_suffix,
    )
    outgoing_policies = load_policies(conn, _TABLE)
    incoming_policies = load_policies(conn, incoming)
    if len(outgoing_policies) != 1:
        raise SwapAborted(f"{_TABLE} has policies {outgoing_policies!r}; want exactly one")
    if len(incoming_policies) > 1:
        raise SwapAborted(f"{incoming} has policies {incoming_policies!r}; want at most one")

    conn.execute(
        sql.SQL("ALTER TABLE {} RENAME TO {}").format(
            sql.Identifier(_TABLE), sql.Identifier(live_to)
        )
    )
    for old, new in live_renames:
        conn.execute(
            sql.SQL("ALTER INDEX {} RENAME TO {}").format(sql.Identifier(old), sql.Identifier(new))
        )
    conn.execute(
        sql.SQL("ALTER TABLE {} RENAME TO {}").format(
            sql.Identifier(incoming), sql.Identifier(_TABLE)
        )
    )
    for old, new in incoming_renames:
        conn.execute(
            sql.SQL("ALTER INDEX {} RENAME TO {}").format(sql.Identifier(old), sql.Identifier(new))
        )
    for schema, view, _, definition in views:
        conn.execute(
            sql.SQL("CREATE OR REPLACE VIEW {} AS {}").format(
                sql.Identifier(schema, view), sql.SQL(definition.strip().rstrip(";"))
            )
        )

    outgoing = outgoing_policies[0]
    conn.execute("SELECT alter_job(%s, scheduled => false)", (outgoing.job_id,))
    if incoming_policies:
        policy = incoming_policies[0]
        if (policy.config, policy.schedule_interval) != (
            outgoing.config,
            outgoing.schedule_interval,
        ):
            raise SwapAborted(f"incoming policy {policy!r} differs from {outgoing!r}")
        conn.execute("SELECT alter_job(%s, scheduled => true)", (policy.job_id,))
    else:
        conn.execute(
            "SELECT add_compression_policy(%s::regclass, compress_after => %s::interval,"
            " schedule_interval => %s::interval)",
            (_TABLE, outgoing.compress_after, outgoing.schedule_interval),
        )

    left_behind = dependent_views(conn, live_to)
    bound = [(s, v) for s, v, _, _ in dependent_views(conn, _TABLE)]
    if left_behind or bound != [(s, v) for s, v, _, _ in views]:
        raise SwapAborted(f"views not rebound: left on {live_to} {left_behind}, bound {bound}")
    return {
        "views_recreated": [f"{s}.{v}" for s, v in bound],
        "index_renames": live_renames + incoming_renames,
        "policy_unscheduled": outgoing.job_id,
        "policy_on_live": [p.job_id for p in load_policies(conn, _TABLE)],
    }


def _lock_pair(conn: Any, apr: Mapping[str, float], other: str) -> None:
    conn.execute(f"SET LOCAL lock_timeout = '{int(apr[APR_LOCK_TIMEOUT_S])}s'")
    conn.execute(
        sql.SQL("LOCK TABLE {}, {} IN ACCESS EXCLUSIVE MODE").format(
            sql.Identifier(_TABLE), sql.Identifier(other)
        )
    )


# --- write path: post-swap checks -------------------------------------------------------------


def rebind_view_sql(definition: str, table: str) -> str:
    """A view definition read against another table (every whole-word table reference)."""
    return re.sub(rf"\b{_TABLE}\b", table, definition.strip().rstrip(";"))


def real_rows_view_sql(definition: str, table: str) -> str:
    """A view definition read against `table`'s real rows only: a CTE named like the live table
    shadows it, so qualified column references in the definition keep working."""
    return (
        f"WITH {_TABLE} AS (SELECT * FROM {table} WHERE source IS DISTINCT FROM '{_SYNTHETIC}') "
        + definition.strip().rstrip(";")
    )


# The view whose rows must not change at all (plan 185-25 must-have): it already hides every
# volume = 0 placeholder, so the swap removes nothing from it.
_UNCHANGED_VIEWS = frozenset({"market_data_ohlcv_tradeable"})


def view_blockers(
    view: str,
    live: Mapping[str, int],
    original_real: Mapping[str, int],
    original_all: Mapping[str, int],
) -> list[str]:
    """The rebuilt table's view equals the view over the original's real rows; a view in
    _UNCHANGED_VIEWS also equals the view over the original as it was."""
    out = []
    if dict(live) != dict(original_real):
        out.append(f"view {view} counts differ: {dict(live)} vs real rows {dict(original_real)}")
    if view.rsplit(".", 1)[-1] in _UNCHANGED_VIEWS and dict(live) != dict(original_all):
        out.append(f"view {view} changed: {dict(live)} vs before {dict(original_all)}")
    return out


def _view_counts(conn: Any, definition: str) -> dict[str, int]:
    query = sql.SQL("SELECT timeframe, count(*) FROM ({}) v GROUP BY 1 ORDER BY 1").format(
        sql.SQL(definition.strip().rstrip(";"))
    )
    return {tf: int(n) for tf, n in _rows(conn, query)}


# The planner's own stored-slot SQL is the smoke read for the nightly's gap planner; this one is
# the comparison side, on the kept original table.
_OLD_SERIES_REAL_SQL = """
SELECT count(*) FROM market_data_ohlcv_old
WHERE symbol = %s AND timeframe = %s AND source IS DISTINCT FROM 'synthetic_fill'
"""
_SAMPLE_SYMBOL_SQL = "SELECT symbol FROM market_data_ohlcv WHERE timeframe = %s LIMIT 1"


def post_check(conn: Any, apr: Mapping[str, float]) -> tuple[dict[str, Any], list[str]]:
    """The checks the old table's drop waits on. In `swapped` it compares the live (rebuilt) table
    with the kept original: per-timeframe counts, shape, policy, that no view still reads the
    original, every dependent view's per-timeframe counts against the same definition read on
    the original, and a smoke read through the gap planner's stored-slot SQL. In `done` only the
    live table's own checks remain."""
    state = require_state(conn, SWAPPED, DONE)
    _set_timeouts(conn, apr[APR_COPY_TIMEOUT_S])
    started = time.monotonic()
    blockers: list[str] = []
    live_counts = table_counts(conn, _TABLE)
    synthetic = sum(c.synthetic for c in live_counts.values())
    if synthetic:
        blockers.append(f"{_TABLE} holds {synthetic} synthetic_fill rows")
    report: dict[str, Any] = {
        "state": state,
        "live_by_timeframe": {tf: c.total for tf, c in live_counts.items()},
        "synthetic_fill": synthetic,
    }
    live_policies = load_policies(conn, _TABLE)
    if state == DONE:
        if len(live_policies) != 1 or not live_policies[0].scheduled:
            blockers.append(f"live table policies {live_policies!r}: want one, scheduled")
        report["seconds"] = round(time.monotonic() - started, 1)
        return report, blockers

    old_counts = table_counts(conn, _OLD_TABLE)
    report["original_real_by_timeframe"] = {tf: c.real for tf, c in old_counts.items()}
    blockers += count_differences(old_counts, live_counts)
    blockers += [
        f"shape {d}"
        for d in shape_differences(load_shape(conn, _TABLE), load_shape(conn, _OLD_TABLE))
    ]
    blockers += policy_differences(live_policies, load_policies(conn, _OLD_TABLE))
    left = dependent_views(conn, _OLD_TABLE)
    if left:
        blockers.append(f"views still read {_OLD_TABLE}: {[f'{s}.{v}' for s, v, _, _ in left]}")

    views: dict[str, Any] = {}
    for schema, view, _, definition in dependent_views(conn, _TABLE):
        name = f"{schema}.{view}"
        live_view = _view_counts(conn, definition)
        old_real = _view_counts(conn, real_rows_view_sql(definition, _OLD_TABLE))
        old_all = _view_counts(conn, rebind_view_sql(definition, _OLD_TABLE))
        views[name] = {
            "live": live_view,
            "original_real_rows": old_real,
            "removed_by_swap": {tf: n - live_view.get(tf, 0) for tf, n in old_all.items()},
        }
        blockers += view_blockers(name, live_view, old_real, old_all)
    report["views"] = views

    from scripts.infrastructure.backfill import _d1_gaps  # the planner's own stored-slot SQL

    smoke: dict[str, Any] = {}
    far_past, far_future = datetime(1900, 1, 1, tzinfo=UTC), datetime(2200, 1, 1, tzinfo=UTC)
    for tf in sorted(live_counts):
        symbol = _scalar(conn, _SAMPLE_SYMBOL_SQL, (tf,))
        if symbol is None:
            continue
        planner = len(_rows(conn, _d1_gaps._GRID_SLOTS_SQL, (symbol, tf, far_past, far_future)))
        original = int(_scalar(conn, _OLD_SERIES_REAL_SQL, (symbol, tf)))
        smoke[tf] = {"symbol": symbol, "planner_slots": planner, "original_real": original}
        if planner != original:
            blockers.append(f"smoke {symbol} {tf}: planner reads {planner}, original {original}")
    report["smoke"] = smoke
    report["seconds"] = round(time.monotonic() - started, 1)
    return report, blockers


# --- write path: commands ---------------------------------------------------------------------


def accept_placeholder_coverage(
    consumers: Sequence[Mapping[str, Any]], blockers: Sequence[str], accept: bool
) -> tuple[list[str], list[str]]:
    """Split off the placeholder-coverage consumer blockers the operator accepted (their cost is
    a re-asked fetch window, never a wrong row). Every other blocker stays."""
    if not accept:
        return list(blockers), []
    prefixes = tuple(
        f"consumer {row['path']}: {PLACEHOLDER_COVERAGE}"
        for row in consumers
        if row["category"] == PLACEHOLDER_COVERAGE and row["blocks"]
    )
    kept = [b for b in blockers if not (prefixes and b.startswith(prefixes))]
    accepted = [b for b in blockers if prefixes and b.startswith(prefixes)]
    return kept, accepted


def write_gates(
    conn: Any, data_path: str, host_checks: bool, accept: bool
) -> tuple[dict[str, Any], list[str]]:
    """The preflight's gates plus shape parity of the original and rebuilt tables."""
    report, blockers = preflight(conn, data_path, host_checks)
    blockers, accepted = accept_placeholder_coverage(report["consumers"], blockers, accept)
    blockers += [
        f"shape {d}"
        for d in shape_differences(load_shape(conn, _TABLE), load_shape(conn, _NEW_TABLE))
    ]
    gates = {
        "by_timeframe": report["by_timeframe"],
        "disk": report["disk"],
        "writers": report["writers"],
        "masked_slots": report["masked_slots"],
        "accepted": accepted,
        "blockers": blockers,
    }
    return gates, blockers


def run_copy(
    conn: Any, data_path: str, host_checks: bool, accept: bool
) -> tuple[dict[str, Any], list[str]]:
    require_state(conn, PRE)
    gates, blockers = write_gates(conn, data_path, host_checks, accept)
    report: dict[str, Any] = {"job": _JOB, "mode": "copy", "gates": gates}
    if blockers:
        report["result"] = "refused: nothing copied"
        return report, blockers
    apr, _ = load_apr(conn)
    report["copy"] = copy_real_rows(conn, apr)
    report["result"] = (
        "copied" if not report["copy"]["count_differences"] else "copied, counts differ"
    )
    return report, list(report["copy"]["count_differences"])


def run_swap(
    conn: Any, data_path: str, host_checks: bool, accept: bool
) -> tuple[dict[str, Any], list[str]]:
    """Gates, the full per-(symbol, timeframe) verify, then the exchange in one transaction under
    ACCESS EXCLUSIVE, then the post-swap checks. A failed verify or recheck leaves the original
    live and untouched; failed post-swap checks roll the exchange back before returning."""
    started = time.monotonic()
    require_state(conn, PRE)
    gates, blockers = write_gates(conn, data_path, host_checks, accept)
    report: dict[str, Any] = {"job": _JOB, "mode": "swap", "gates": gates}
    if blockers:
        report["result"] = "refused: nothing changed"
        return report, blockers
    apr, _ = load_apr(conn)

    # Writes committed just before this point can sit unflushed in their backend's stats for up
    # to the idle flush interval; wait it out so the baseline already includes them.
    time.sleep(apr[APR_STATS_WAIT_S])
    counters_before = write_counters(conn, _TABLE)
    verified, verify_blockers = verify(conn, host_checks)
    report["verify"] = verified
    if verify_blockers:
        report["result"] = "aborted at verify: original untouched"
        return report, verify_blockers
    refuse_if_writers(load_writer_state(conn, host_checks))

    lock_started = time.monotonic()
    with conn.transaction():
        _lock_pair(conn, apr, _NEW_TABLE)
        time.sleep(apr[APR_STATS_WAIT_S])
        counters_after = write_counters(conn, _TABLE)
        if counters_after != counters_before:
            raise SwapAborted(
                f"{_TABLE} was written after the verify began (chunks, writes) "
                f"{counters_before} -> {counters_after}; original untouched"
            )
        recheck = count_differences(table_counts(conn, _TABLE), table_counts(conn, _NEW_TABLE))
        if recheck:
            raise SwapAborted(f"recheck under lock failed: {recheck}; original untouched")
        report["exchange"] = exchange(
            conn,
            live_to=_OLD_TABLE,
            live_suffix=SUFFIX_ORIGINAL,
            incoming=_NEW_TABLE,
            incoming_suffix=SUFFIX_REBUILT,
        )
    report["lock_seconds"] = round(time.monotonic() - lock_started, 1)

    try:
        post, post_blockers = post_check(conn, apr)
    except Exception as error:
        # A check that cannot run has not passed: put the original back before raising.
        report["rollback"] = _rollback_exchange(conn, apr)
        raise SwapAborted(
            f"post-swap checks raised {error!r}; rolled back, original live again"
        ) from error
    report["post_check"] = {**post, "blockers": post_blockers}
    if post_blockers:
        report["rollback"] = _rollback_exchange(conn, apr)
        report["result"] = "post-swap checks failed: rolled back, original live again"
    else:
        report["result"] = "swapped; original kept as market_data_ohlcv_old"
    report["seconds"] = round(time.monotonic() - started, 1)
    return report, post_blockers


def _rollback_exchange(conn: Any, apr: Mapping[str, float]) -> dict[str, Any]:
    with conn.transaction():
        _lock_pair(conn, apr, _OLD_TABLE)
        result = exchange(
            conn,
            live_to=_NEW_TABLE,
            live_suffix=SUFFIX_REBUILT,
            incoming=_OLD_TABLE,
            incoming_suffix=SUFFIX_ORIGINAL,
        )
    require_state(conn, PRE)
    return result


def run_rollback(conn: Any, host_checks: bool) -> tuple[dict[str, Any], list[str]]:
    """Put the original back under the live name; the rebuilt table returns to
    market_data_ohlcv_new with its policy unscheduled. Only possible before --drop-old."""
    require_state(conn, SWAPPED)
    refuse_if_writers(load_writer_state(conn, host_checks))
    apr, _ = load_apr(conn)
    _set_timeouts(conn, apr[APR_STATEMENT_TIMEOUT_S])
    result = _rollback_exchange(conn, apr)
    return {"job": _JOB, "mode": "rollback", "exchange": result, "state": load_state(conn)}, []


def run_post_check(conn: Any) -> tuple[dict[str, Any], list[str]]:
    apr, _ = load_apr(conn)
    report, blockers = post_check(conn, apr)
    return {"job": _JOB, "mode": "post_check", **report, "blockers": blockers}, blockers


def run_drop_old(conn: Any, data_path: str, host_checks: bool) -> tuple[dict[str, Any], list[str]]:
    """Drop the kept original once the post-swap checks pass, then the bare VACUUM. Re-runnable:
    in `done` it only vacuums."""
    state = require_state(conn, SWAPPED, DONE)
    refuse_if_writers(load_writer_state(conn, host_checks))
    apr, _ = load_apr(conn)
    report: dict[str, Any] = {"job": _JOB, "mode": "drop_old", "state_before": state}
    free_before = shutil.disk_usage(data_path).free
    if state == SWAPPED:
        post, blockers = post_check(conn, apr)
        report["post_check"] = post
        if blockers:
            report["result"] = "post-swap checks failed: nothing dropped"
            return report, blockers
        report["original_bytes"] = int(
            _scalar(conn, "SELECT hypertable_size(%s::regclass)", (_OLD_TABLE,))
        )
        with conn.transaction():
            _lock_pair(conn, apr, _OLD_TABLE)
            left = dependent_views(conn, _OLD_TABLE)
            if left:
                raise SwapAborted(f"views still read {_OLD_TABLE}: {left}")
            conn.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(_OLD_TABLE)))
    t0 = time.monotonic()
    _set_timeouts(conn, apr[APR_COPY_TIMEOUT_S])
    conn.execute(sql.SQL("VACUUM {}").format(sql.Identifier(_TABLE)))
    free_after = shutil.disk_usage(data_path).free
    report.update(
        {
            "vacuum_seconds": round(time.monotonic() - t0, 1),
            "free_before_gib": _gib(free_before),
            "free_after_gib": _gib(free_after),
            "reclaimed_gib": _gib(free_after - free_before),
            "live_bytes": int(_scalar(conn, "SELECT hypertable_size(%s::regclass)", (_TABLE,))),
            "state": load_state(conn),
            "result": "original dropped, VACUUM done",
        }
    )
    return report, []


def run_status(conn: Any) -> tuple[dict[str, Any], list[str]]:
    state = load_state(conn)
    tables = {}
    for name in (_TABLE, _NEW_TABLE, _OLD_TABLE):
        if _scalar(conn, "SELECT to_regclass(%s)", (f"public.{name}",)) is None:
            continue
        tables[name] = {
            "bytes": int(_scalar(conn, "SELECT hypertable_size(%s::regclass)", (name,)) or 0),
            "chunks": len(_rows(conn, _CHUNK_NAMES_SQL, (name,))),
            "policies": [p.__dict__ for p in load_policies(conn, name)],
            "views": [f"{s}.{v}" for s, v, _, _ in dependent_views(conn, name)],
        }
    report = {"job": _JOB, "mode": "status", "state": state, "tables": tables}
    return report, ([] if state != INCONSISTENT else ["state inconsistent"])


_MODES = ("verify", "status", "copy", "swap", "post_check", "rollback", "drop_old")
_WRITE_MODES = frozenset({"copy", "swap", "rollback", "drop_old"})


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--verify",
        action="store_true",
        help=f"compare real rows of {_TABLE} and {_NEW_TABLE} (read-only)",
    )
    modes.add_argument("--status", action="store_true", help="print the swap state (read-only)")
    modes.add_argument(
        "--copy", action="store_true", help=f"copy the real rows into {_NEW_TABLE} (restartable)"
    )
    modes.add_argument(
        "--swap", action="store_true", help="verify, exchange the tables, run the post-checks"
    )
    modes.add_argument("--post-check", action="store_true", help="the post-swap checks (read-only)")
    modes.add_argument(
        "--rollback", action="store_true", help=f"put the original back from {_OLD_TABLE}"
    )
    modes.add_argument(
        "--drop-old",
        action="store_true",
        help=f"drop {_OLD_TABLE} after the post-checks pass, then VACUUM {_TABLE}",
    )
    parser.add_argument(
        "--accept-placeholder-coverage",
        action="store_true",
        help="accept the placeholder_coverage consumer blockers (re-asked fetch windows)",
    )
    parser.add_argument(
        "--data-path",
        default="/var/lib/docker",
        help="a path on the filesystem holding the database volume (free-disk check)",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="target database (rehearsals on a scratch database); default: the configured one",
    )
    return parser.parse_args(argv)


def _mode(args: argparse.Namespace) -> str:
    return next((m for m in _MODES if getattr(args, m)), "dry_run")


def _dbname(dsn: str) -> str | None:
    return psycopg.conninfo.conninfo_to_dict(dsn).get("dbname")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = _mode(args)
    live_dsn = Settings().database_url
    dsn = args.dsn or live_dsn
    with psycopg.connect(dsn, autocommit=True, application_name=_JOB) as conn:
        # Host checks (writer processes and units) guard the live database only.
        host_checks = _scalar(conn, "SELECT current_database()") == _dbname(live_dsn)
        if mode not in _WRITE_MODES:
            conn.execute("SET default_transaction_read_only = on")
        try:
            if mode == "verify":
                report, blockers = verify(conn, host_checks)
            elif mode == "status":
                report, blockers = run_status(conn)
            elif mode == "copy":
                report, blockers = run_copy(
                    conn, args.data_path, host_checks, args.accept_placeholder_coverage
                )
            elif mode == "swap":
                report, blockers = run_swap(
                    conn, args.data_path, host_checks, args.accept_placeholder_coverage
                )
            elif mode == "post_check":
                report, blockers = run_post_check(conn)
            elif mode == "rollback":
                report, blockers = run_rollback(conn, host_checks)
            elif mode == "drop_old":
                report, blockers = run_drop_old(conn, args.data_path, host_checks)
            else:
                report, blockers = preflight(conn, args.data_path, host_checks)
        except (SwapRefused, SwapAborted) as error:
            kind = "refused" if isinstance(error, SwapRefused) else "aborted"
            print(json.dumps({"job": _JOB, "mode": mode, kind: str(error)}, indent=2))
            return EXIT_BLOCKED
    print(json.dumps(report, indent=2, default=str))
    return EXIT_BLOCKED if blockers else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
