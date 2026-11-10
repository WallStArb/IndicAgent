"""The corpus rerun step runner (186-31, todo 593): one DAG of oneshot steps under one run id.

    data_gate -> pin_gate -> pilot -> stage_1d -> for each span s: s.1h -> s.15m -> s.5m
      -> feature_complete -> ic_measure -> d19_bound -> canary

Each step refuses, loudly and before it writes anything, unless its upstream step of the same run
is completed; no flag skips a step. A completed step re-invoked is a no-op that reports its stored
outcome; a failed step retries once its cause is fixed. The runner writes only corpus_run and
corpus_run_step; the steps call the writers that own the data (run_rebuild_stage,
services/ic_measure.py) and the gates that judge it (186-32's data gate, the column screen, the
pilot compute gate, the canary).

- `data_gate`: 186-32's run_data_gate. On a pass, one transaction writes corpus_run.data_gate,
  appends the survivorship caveat unless a caveat with its code is already present, and completes
  the step; a refusal writes the counts and failing lists to the failed step's summary only.
- `pin_gate` (re-run before every compute step): the process runs from the run's detached
  worktree at corpus_run.code_commit; the rebuild code key and APR hash equal the run's; services
  is imported from the worktree; FetcherLock is free; every blocking timer is disabled and its
  service not active; no live writer process; the rebuild preconditions pass with the span disk
  term; the growth since launch plus the next step's own increment (its tf's rows in its span not
  yet loaded under the run, the WAL, two group spools) stays inside the limit.
- `pilot`: stage_1d's chunk 0 and one 1h unit of span 1 (ordinary units of the real stages, kept),
  G1-G3 (column screen) and G4-G5 (pilot compute gate) on them, per-unit wall time and DB load,
  the measured bytes per row, stored-per-spool ratio and compression ratio (the pilot's rows
  compressed in a dropped scratch hypertable) into corpus_run.measured; then the run's spans are
  re-projected with the larger bytes per row and the measured ratio, and the pilot fails if any
  overflows, before stage_1d.
- Stage and span steps: run_rebuild_stage on the full universe under the run id with the run's
  unit disk guard; a step fails on a failed, refused or abandoned unit, or a unit of its scope
  without a completed row that belongs to the run; after a span's 5m every chunk ending by the
  span's end (before the open chunk) must be compressed.
- `feature_complete`: the full scope re-planned now: every unit completed and the run's; no
  started or failed row under the run; no digest-blind symbol; the column screen per tf with
  G6, the post-warmup NULL share per (tf, column) at infra.corpus_rerun.max_null_fraction.
- `ic_measure` under the run id (it reports the units it skipped; only those are adopted, and
  every expected (tf, horizon) needs POOLED rows), `d19_bound` (no feature_ic_scores row at or
  after oos_start), `canary --run-id`; the ic_measure and canary summaries carry
  corpus_run.caveats verbatim. One corpus rerun runs at a time (a global advisory lock).

A unit skipped because a completed row with its identity exists keeps that row's run (completed
rows are immutable): the step records it as adopted, {unit_key, batch_key, adopted_from_run_id},
and every one-run check counts a unit when its completed row is the run's or adopted with the same
batch_key from the run it records (services/_batch_utils.py belongs_to_run).

Run it from the run's worktree with the main checkout's interpreter:

    .venv/bin/python -m services.corpus_rerun --new-run --plan-only   # spans, disk, data gate
    .venv/bin/python -m services.corpus_rerun --new-run                # creates run + worktree
    cd <worktree> && /home/bg/dev/indicagent/.venv/bin/python -m services.corpus_rerun \\
        --run-id <id> --through canary

Logs go to <main checkout>/logs/corpus_rerun.log (derived from git's common dir, never the
worktree's own logs); the worktree's logs/ is a symlink to it, so every subprocess logs there.
Runbook: docs/operations/corpus-rerun-runbook.md.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import structlog
from psycopg.types.json import Jsonb

from services._batch_utils import (
    RUN_ADOPTIONS_SQL,
    belongs_to_run,
    bulk_load_unit_key,
    load_config_service_sync,
    parse_run_id,
)
from services.corpus_rerun_apr import CorpusRerunApr, load_corpus_rerun_apr
from services.corpus_rerun_budget import (
    STAGE_1D,
    BudgetInputs,
    Peak,
    RowCounts,
    SpanPlanRefused,
    UnitDiskGuard,
    daily_peak,
    format_peaks,
    overflowing,
    plan_spans,
    project,
    span_peak,
    step_increment,
)
from src.config.settings import Settings
from src.core.canonical_json import canonical_json
from src.core.service_utils import setup_service_logging
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

_logger = structlog.get_logger(__name__)

_JOB = "corpus_rerun"
_FEATURE_TABLE = "feature_vectors"
_IC_TABLE = "feature_ic_scores"
_TARGET_TFS_KEY = "feature.factory.target_timeframes"
_IC_HORIZONS_KEY = "alpha.ic_measure.horizons"
_OOS_START_KEY = "alpha.validation.oos_start"
_WORKERS_KEY = "infra.feature_factory.workers"
INTRADAY_ORDER: tuple[str, ...] = ("1h", "15m", "5m")
OUTPUT_TAIL_CHARS = 4000
COMPRESSION_RATIO_MEASURED = "compression_ratio_measured"

# The recorded todo 445 decision the rebuild preconditions check (186-26's precheck record).
TODO445_DECISION_PATH = Path(
    ".planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/evidence/"
    "186-26-precheck-raw.json"
)
COLUMN_SCREEN = Path("scripts/ops/ops_feature_column_screen.py")
PILOT_COMPUTE_GATE = Path("scripts/ops/ops_pilot_compute_gate.py")
CANARY = Path("scripts/ops/alpha/ops_canary_integrity_assert.py")


# ---------------------------------------------------------------------------
# The DAG
# ---------------------------------------------------------------------------

DATA_GATE = "data_gate"
PIN_GATE = "pin_gate"
PILOT = "pilot"
FEATURE_COMPLETE = "feature_complete"
IC_MEASURE = "ic_measure"
D19_BOUND = "d19_bound"
CANARY_STEP = "canary"
SPAN = "span"


@dataclasses.dataclass(frozen=True)
class Step:
    name: str
    kind: str
    upstream: str | None
    tf: str | None = None
    span_index: int | None = None  # 0-based position in corpus_run.spans


def build_steps(spans: Sequence[tuple[datetime, datetime]]) -> list[Step]:
    """The fixed chain of a run with these spans; each step's upstream is the one before it."""
    kinds: list[tuple[str, str, str | None, int | None]] = [
        (DATA_GATE, DATA_GATE, None, None),
        (PIN_GATE, PIN_GATE, None, None),
        (PILOT, PILOT, None, None),
        (STAGE_1D, STAGE_1D, "1d", None),
    ]
    for k in range(len(spans)):
        kinds += [(f"s{k + 1}.{tf}", SPAN, tf, k) for tf in INTRADAY_ORDER]
    kinds += [(n, n, None, None) for n in (FEATURE_COMPLETE, IC_MEASURE, D19_BOUND, CANARY_STEP)]
    steps: list[Step] = []
    for name, kind, tf, index in kinds:
        steps.append(Step(name, kind, steps[-1].name if steps else None, tf, index))
    return steps


# ---------------------------------------------------------------------------
# Run identity and its paths
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CorpusRun:
    run_id: str
    code_commit: str
    code_key: str
    horizon: datetime
    apr_hash: str
    spans: tuple[tuple[datetime, datetime], ...]
    free_bytes_at_launch: int
    caveats: tuple[dict[str, Any], ...]
    measured: dict[str, Any]


def _git(args: Sequence[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def main_checkout_root(start: Path | None = None) -> Path:
    """The main checkout (the parent of git's common dir), whichever worktree runs this."""
    here = start or Path(__file__).resolve().parent
    common = Path(_git(["rev-parse", "--git-common-dir"], here))
    return (common if common.is_absolute() else here / common).resolve().parent


def main_logs_dir(start: Path | None = None) -> Path:
    return main_checkout_root(start) / "logs"


def run_worktree(run_id: str, main_root: Path | None = None) -> Path:
    """The run's detached worktree, a sibling of the main checkout named by the run id."""
    root = main_root or main_checkout_root()
    return root.parent / f"{root.name}-corpus-run-{run_id}"


def pinned_apr_keys(ic_tfs: Iterable[str]) -> list[str]:
    """Every APR key a step or gate of the run reads, from each module's own list: the rerun
    APR (data gate, disk budget, timers, G6), the column screen, the pilot compute gate, the
    rebuild preconditions, the rebuild's planning keys, ic_measure's keys per tf (oos_start and
    the horizons included, which d19_bound reads too) and the canary's."""
    from scripts.ops.alpha.ops_canary_integrity_assert import APR_KEYS as canary_keys
    from scripts.ops.ops_feature_column_screen import APR_KEYS as screen_keys
    from scripts.ops.ops_pilot_compute_gate import APR_KEYS as pilot_keys
    from services.backfill_feature_factory import rebuild_apr_keys
    from services.corpus_rerun_apr import APR_KEYS as rerun_keys
    from services.ic_measure import _OOS_START_KEY as ic_oos_key
    from services.ic_measure import apr_keys_read
    from services.rebuild_preconditions import APR_KEYS as precondition_keys

    keys = {*rerun_keys, *screen_keys, *pilot_keys, *precondition_keys, *rebuild_apr_keys()}
    keys |= {*canary_keys, ic_oos_key, _IC_HORIZONS_KEY}
    for tf in ic_tfs:
        keys.update(apr_keys_read(tf))
    return sorted(keys)


def apr_hash(values: Mapping[str, Any], factory_config: Any) -> str:
    """sha256 over every pinned APR value and the rebuild's feature config."""
    snapshot = {"apr": dict(values), "feature_factory": dataclasses.asdict(factory_config)}
    return hashlib.sha256(canonical_json(snapshot).encode()).hexdigest()


# ---------------------------------------------------------------------------
# The store: corpus_run and corpus_run_step (the runner's only writes) plus its reads
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class StepRow:
    status: str
    summary: dict[str, Any]


_INSERT_RUN_SQL = """
INSERT INTO corpus_run (run_id, code_commit, code_key, horizon, apr_hash, spans,
                        free_bytes_at_launch, measured)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""
_LOAD_RUN_SQL = """
SELECT run_id::text, code_commit, code_key, horizon, apr_hash, spans, free_bytes_at_launch,
       caveats, measured
FROM corpus_run WHERE run_id = %s
"""
_STEP_SQL = "SELECT status, summary FROM corpus_run_step WHERE run_id = %s AND step = %s"
_BEGIN_STEP_SQL = """
INSERT INTO corpus_run_step (run_id, step, status) VALUES (%s, %s, 'started')
ON CONFLICT (run_id, step) DO UPDATE
   SET status = 'started', started_at = now(), finished_at = NULL, summary = '{}'::jsonb
 WHERE corpus_run_step.status <> 'completed'
"""
FINISH_STEP_SQL = """
UPDATE corpus_run_step SET status = %s, summary = %s, finished_at = now()
WHERE run_id = %s AND step = %s AND status = 'started'
"""
# The data gate's persistence: the result and the caveat in one UPDATE, the caveat appended only
# when no element carries its code (a retried step never duplicates it; the 578 trigger keeps the
# array append only).
DATA_GATE_RUN_SQL = """
UPDATE corpus_run
   SET data_gate = %(record)s,
       caveats = CASE WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(caveats) e
                                   WHERE e->>'code' = %(code)s)
                      THEN caveats ELSE caveats || jsonb_build_array(%(caveat)s::jsonb) END
 WHERE run_id = %(run_id)s
"""
_MERGE_MEASURED_SQL = "UPDATE corpus_run SET measured = measured || %s WHERE run_id = %s"
_COMPLETED_ROWS_SQL = """
SELECT batch_key, run_id::text FROM provenance_batch
WHERE batch_key = ANY(%s) AND status = 'completed'
"""
_UNIT_COMPLETED_SQL = """
SELECT batch_key, run_id::text FROM provenance_batch WHERE unit_key = %s AND status = 'completed'
"""
_OPEN_ROWS_SQL = """
SELECT batch_key, status FROM provenance_batch
WHERE run_id = %s AND status IN ('started', 'failed') ORDER BY batch_key
"""
_COMPLETED_SUMMARIES_SQL = """
SELECT step, summary FROM corpus_run_step WHERE run_id = %s AND status = 'completed'
"""
_UNCOMPRESSED_CHUNKS_SQL = """
SELECT chunk_name, range_end FROM timescaledb_information.chunks
WHERE hypertable_name = %s AND NOT is_compressed AND range_end <= %s ORDER BY range_start
"""
_REACHING_OOS_SQL = (
    f"SELECT count(*), min(training_window_end) FROM {_IC_TABLE} " "WHERE training_window_end >= %s"
)
_LOADED_ROWS_SQL = """
SELECT COALESCE(sum(row_count), 0) FROM provenance_batch
WHERE run_id = %s AND status = 'completed' AND target_table = %s AND tf = %s
  AND range_start >= %s AND range_start < %s
"""
_POOLED_LOOKAHEADS_SQL = f"""
SELECT tf, lookahead_bars, count(*) FROM {_IC_TABLE}
WHERE symbol = 'POOLED' AND regime_scope = 'unstratified' GROUP BY tf, lookahead_bars
"""
_UNIT_STATS_SQL = """
SELECT batch_key, tf, unit_stats FROM provenance_batch
WHERE batch_key = ANY(%s) AND status = 'completed' AND target_table = 'feature_vectors'
"""
_RUN_LOCK_SQL = "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))"
# One corpus rerun at a time, whatever its run id: two runs would interleave their stages'
# compression and their units on the same table.
RUN_LOCK_NAME = "corpus_rerun"


class RunStore:
    """The runner's reads and its only writes (corpus_run, corpus_run_step) on one autocommit
    connection; the data gate's persistence is one explicit transaction."""

    def __init__(self, conn: Any):
        self.conn = conn

    def _one(self, sql: str, params: Any) -> Any:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _all(self, sql: str, params: Any) -> list[Any]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def try_lock(self) -> bool:
        """The global corpus rerun lock (session level, released when the connection closes)."""
        return bool(self._one(_RUN_LOCK_SQL, (RUN_LOCK_NAME,))[0])

    def unit_stats(self, batch_keys: Sequence[str]) -> list[tuple[str, str, dict | None]]:
        """(batch_key, tf, unit_stats) of the completed feature_vectors units among the keys."""
        return [tuple(r) for r in self._all(_UNIT_STATS_SQL, (list(batch_keys),))]

    def loaded_rows(self, run_id: str, tf: str, lo: datetime, hi: datetime) -> int:
        """Rows this run already loaded of one tf whose units start in [lo, hi)."""
        return int(self._one(_LOADED_ROWS_SQL, (run_id, _FEATURE_TABLE, tf, lo, hi))[0])

    def pooled_lookaheads(self) -> dict[str, dict[int, int]]:
        """POOLED unstratified feature_ic_scores rows per (tf, lookahead): the proposer units'."""
        out: dict[str, dict[int, int]] = {}
        for tf, horizon, n in self._all(_POOLED_LOOKAHEADS_SQL, ()):
            out.setdefault(tf, {})[int(horizon)] = int(n)
        return out

    def create_run(self, run: CorpusRun) -> None:
        spans = [[s.isoformat(), e.isoformat()] for s, e in run.spans]
        with self.conn.cursor() as cur:
            cur.execute(
                _INSERT_RUN_SQL,
                (
                    run.run_id,
                    run.code_commit,
                    run.code_key,
                    run.horizon,
                    run.apr_hash,
                    Jsonb(spans),
                    run.free_bytes_at_launch,
                    Jsonb(run.measured),
                ),
            )

    def load_run(self, run_id: str) -> CorpusRun:
        row = self._one(_LOAD_RUN_SQL, (run_id,))
        if row is None:
            raise LookupError(f"no corpus_run {run_id}")
        rid, commit, key, horizon, apr, spans, free, caveats, measured = row
        return CorpusRun(
            run_id=rid,
            code_commit=commit,
            code_key=key,
            horizon=horizon,
            apr_hash=apr,
            spans=tuple((datetime.fromisoformat(s), datetime.fromisoformat(e)) for s, e in spans),
            free_bytes_at_launch=int(free),
            caveats=tuple(caveats),
            measured=dict(measured),
        )

    def step(self, run_id: str, name: str) -> StepRow | None:
        row = self._one(_STEP_SQL, (run_id, name))
        return None if row is None else StepRow(row[0], dict(row[1]))

    def begin(self, run_id: str, name: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(_BEGIN_STEP_SQL, (run_id, name))

    def finish(self, run_id: str, name: str, status: str, summary: Mapping[str, Any]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(FINISH_STEP_SQL, (status, Jsonb(_json(summary)), run_id, name))

    def complete_data_gate(
        self,
        run_id: str,
        name: str,
        record: Mapping[str, Any],
        caveat: Mapping[str, Any],
        summary: Mapping[str, Any],
    ) -> None:
        """corpus_run.data_gate, the caveat (deduped on its code) and the step's completion in
        one transaction: a failure anywhere leaves none of them."""
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                DATA_GATE_RUN_SQL,
                {
                    "record": Jsonb(_json(record)),
                    "code": caveat["code"],
                    "caveat": Jsonb(_json(caveat)),
                    "run_id": run_id,
                },
            )
            cur.execute(FINISH_STEP_SQL, ("completed", Jsonb(_json(summary)), run_id, name))
            if cur.rowcount != 1:
                raise RuntimeError(f"data_gate: step {name} of run {run_id} is not started")

    def merge_measured(self, run_id: str, patch: Mapping[str, Any]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(_MERGE_MEASURED_SQL, (Jsonb(_json(patch)), run_id))

    def completed_rows(self, batch_keys: Sequence[str]) -> dict[str, str | None]:
        return dict(self._all(_COMPLETED_ROWS_SQL, (list(batch_keys),)))

    def unit_completed(self, unit_key: str) -> list[tuple[str, str | None]]:
        return [tuple(r) for r in self._all(_UNIT_COMPLETED_SQL, (unit_key,))]

    def open_rows(self, run_id: str) -> list[tuple[str, str]]:
        return [tuple(r) for r in self._all(_OPEN_ROWS_SQL, (run_id,))]

    def adoptions(self, run_id: str) -> dict[str, str | None]:
        return dict(self._all(RUN_ADOPTIONS_SQL, (run_id,)))

    def completed_summaries(self, run_id: str) -> dict[str, dict[str, Any]]:
        return {
            step: dict(summary) for step, summary in self._all(_COMPLETED_SUMMARIES_SQL, (run_id,))
        }

    def uncompressed_chunks(self, before: datetime) -> list[tuple[str, datetime]]:
        return [tuple(r) for r in self._all(_UNCOMPRESSED_CHUNKS_SQL, (_FEATURE_TABLE, before))]

    def rows_reaching(self, oos_start: datetime) -> tuple[int, datetime | None]:
        count, first = self._one(_REACHING_OOS_SQL, (oos_start,))
        return int(count), first


def _json(value: Any) -> Any:
    """JSON-safe copy (datetimes and dates as ISO strings, tuples as lists)."""
    return json.loads(json.dumps(value, default=lambda v: v.isoformat()))


def object_share_gate(
    stats: Sequence[tuple[str, str, Mapping[str, Any] | None]],
    objects: frozenset[str],
    applicable: Callable[[str], frozenset[str]],
    max_null_fraction: float,
    expected_tfs: Sequence[str],
) -> dict[str, Any]:
    """G6 for the object-dependent and event columns (lead ruling 2026-11-06): per (tf, column)
    the NULL share of the rows where the column's own object or validity state is true,
    sum(nan_present) / sum(present) over the units, against max_null_fraction. A column with
    present = 0 across a whole tf on which it applies fails, and so does a unit that carries no
    unit_stats (its rows cannot be judged). Every expected tf is judged, so a tf with no unit
    at all fails present = 0 on its applicable columns. Returns {failing, shares}."""
    sums: dict[str, dict[str, list[int]]] = {}
    failing: list[str] = []
    for batch_key, tf, unit in stats:
        if unit is None:
            failing.append(f"unit {batch_key[:12]} ({tf}) carries no unit_stats")
            continue
        per_tf = sums.setdefault(tf, {})
        for column, counts in unit.items():
            pair = per_tf.setdefault(column, [0, 0])
            pair[0] += int(counts["present"])
            pair[1] += int(counts["nan_present"])
    shares: dict[str, dict[str, float]] = {}
    for tf in sorted(set(expected_tfs) | set(sums)):
        per_tf = sums.get(tf, {})
        shares[tf] = {}
        for column in sorted(objects & applicable(tf)):
            present, nan_present = per_tf.get(column, (0, 0))
            if not present:
                failing.append(f"tf {tf} {column}: present = 0 on a tf where it applies")
                continue
            share = nan_present / present
            shares[tf][column] = round(share, 6)
            if share > max_null_fraction:
                failing.append(
                    f"tf {tf} {column}: null share {share:.1%} of its {present} present rows "
                    f"> {max_null_fraction:.1%}"
                )
    return {"failing": failing, "shares": shares}


# ---------------------------------------------------------------------------
# Measured inputs (the real implementations behind Deps)
# ---------------------------------------------------------------------------

_ROW_COUNTS_SQL = """
SELECT m.timeframe, c.idx, (date_trunc('month', m."timestamp" AT TIME ZONE 'UTC'))::date,
       count(*)
FROM market_data_ohlcv_tradeable m
JOIN unnest(%s::text[], %s::int[], %s::timestamptz[]) AS c(symbol, idx, floor_ts)
  ON c.symbol = m.symbol
WHERE m.timeframe = ANY(%s) AND m."timestamp" >= c.floor_ts AND m."timestamp" < %s
GROUP BY 1, 2, 3
"""
_CHUNK_INTERVAL_SQL = """
SELECT time_interval FROM timescaledb_information.dimensions
WHERE hypertable_name = %s AND dimension_type = 'Time'
"""
_DB_LOAD_SQL = """
SELECT (SELECT count(*) FROM pg_stat_activity
         WHERE state = 'active' AND pid <> pg_backend_pid() AND datname = current_database()),
       xact_commit, blks_read, blks_hit, tup_inserted, tup_fetched
FROM pg_stat_database WHERE datname = current_database()
"""


_ANY_COMPLETED_UNIT_SQL = (
    "SELECT EXISTS (SELECT 1 FROM provenance_batch WHERE target_table = %s "
    "AND status = 'completed')"
)
_COMPLETED_KEYS_SQL = (
    "SELECT batch_key FROM provenance_batch WHERE batch_key = ANY(%s) AND status = 'completed'"
)
# The stored rows of the units a run would adopt, on the planner's (tf, chunk, month) grid.
_ADOPTABLE_ROWS_SQL = """
WITH c AS (SELECT * FROM unnest(%s::text[], %s::int[]) AS c(symbol, idx)),
u AS (SELECT * FROM unnest(%s::text[], %s::int[], %s::timestamptz[], %s::timestamptz[])
        AS u(tf, idx, lo, hi))
SELECT m.tf, c.idx, (date_trunc('month', m.bar_ts AT TIME ZONE 'UTC'))::date, count(*)
FROM feature_vectors m
JOIN c ON c.symbol = m.symbol
JOIN u ON u.tf = m.tf AND u.idx = c.idx AND m.bar_ts >= u.lo AND m.bar_ts < u.hi
GROUP BY 1, 2, 3
"""


def adoptable_units(
    specs: Sequence[Any], completed: set[str], chunks: Sequence[tuple[str, ...]]
) -> list[tuple[str, int, datetime, datetime]]:
    """(tf, chunk index, range_start, range_end) of every planned unit whose identity is
    already completed: the run will skip and adopt exactly these, so only their rows are on disk
    for good. A unit stored under another identity (another code key, APR or input) is
    replaced: its new rows are growth, and the old space comes back only after a VACUUM."""
    index = {tuple(chunk): i for i, chunk in enumerate(chunks)}
    return [
        (spec.tf, index[tuple(spec.symbols)], spec.range_start, spec.range_end)
        for spec in specs
        if spec.batch_key in completed
    ]


def stored_row_counts(
    conn: Any,
    settings: Any,
    horizon: datetime,
    chunks: Sequence[tuple[str, ...]],
    planned: Callable[..., tuple[list[Any], set[str]]] | None = None,
) -> RowCounts:
    """The rows already stored that the run would adopt, as RowCounts (not growth). Plans the
    full scope only when feature_vectors has a completed unit at all."""
    with conn.cursor() as cur:
        cur.execute(_ANY_COMPLETED_UNIT_SQL, (_FEATURE_TABLE,))
        if not cur.fetchone()[0]:
            return RowCounts({})
    if planned is None:
        from services.backfill_feature_factory import planned_units as planned
    specs, _blind = planned(settings, conn, horizon)
    with conn.cursor() as cur:
        cur.execute(_COMPLETED_KEYS_SQL, ([spec.batch_key for spec in specs],))
        completed = {key for (key,) in cur.fetchall()}
    units = adoptable_units(specs, completed, chunks)
    if not units:
        return RowCounts({})
    names = [(s, i) for i, chunk in enumerate(chunks) for s in chunk]
    with conn.cursor() as cur:
        cur.execute(
            _ADOPTABLE_ROWS_SQL,
            (
                [s for s, _ in names],
                [i for _, i in names],
                [u[0] for u in units],
                [u[1] for u in units],
                [u[2] for u in units],
                [u[3] for u in units],
            ),
        )
        return RowCounts({(tf, int(i), month): int(n) for tf, i, month, n in cur.fetchall()})


def fetch_row_counts(
    conn: Any,
    chunks: Sequence[tuple[str, ...]],
    starts: Mapping[str, datetime],
    horizon: datetime,
    timeframes: Sequence[str],
) -> RowCounts:
    """Tradeable bars per (tf, symbol chunk, month) from each name's proven start to the horizon:
    the rows the rebuild will write, as the planner counts them."""
    from services.backfill_feature_factory import _NO_FLOOR

    names = [(s, i) for i, chunk in enumerate(chunks) for s in chunk]
    with conn.cursor() as cur:
        cur.execute(
            _ROW_COUNTS_SQL,
            (
                [s for s, _ in names],
                [i for _, i in names],
                [starts.get(s, _NO_FLOOR) for s, _ in names],
                list(timeframes),
                horizon,
            ),
        )
        return RowCounts({(tf, int(i), month): int(n) for tf, i, month, n in cur.fetchall()})


def counts_record(counts: RowCounts) -> list[list[Any]]:
    return [[tf, i, m.isoformat(), n] for (tf, i, m), n in sorted(counts.cells.items())]


def counts_from_record(record: Sequence[Sequence[Any]]) -> RowCounts:
    return RowCounts({(tf, int(i), date.fromisoformat(m)): int(n) for tf, i, m, n in record})


def chunk_interval(conn: Any) -> timedelta:
    with conn.cursor() as cur:
        cur.execute(_CHUNK_INTERVAL_SQL, (_FEATURE_TABLE,))
        row = cur.fetchone()
    if row is None or not isinstance(row[0], timedelta):
        raise RuntimeError(f"{_FEATURE_TABLE} has no time dimension interval")
    return row[0]


def db_load(conn: Any) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(_DB_LOAD_SQL)
        names = (
            "other_active",
            "xact_commit",
            "blks_read",
            "blks_hit",
            "tup_inserted",
            "tup_fetched",
        )
        return dict(zip(names, (int(v) for v in cur.fetchone())))


_SCRATCH_SCHEMA = "corpus_rerun_scratch"
_COMPRESSION_SETTINGS_SQL = """
SELECT attname, segmentby_column_index, orderby_column_index, orderby_asc
FROM timescaledb_information.compression_settings WHERE hypertable_name = %s
"""


def measure_compression(conn: Any, symbols: Sequence[str], tf: str) -> dict[str, Any]:
    """Copy the stored rows of (symbols, tf) into a scratch hypertable with feature_vectors'
    own chunk interval and compression settings, compress it, and return the stored bytes
    before and after and their ratio. The scratch table is dropped whatever happens;
    feature_vectors itself is only read, so no chunk a later unit needs is compressed."""
    from psycopg import sql

    table = sql.Identifier(_SCRATCH_SCHEMA, f"ratio_{uuid.uuid4().hex[:12]}")
    with conn.cursor() as cur:
        cur.execute(_COMPRESSION_SETTINGS_SQL, (_FEATURE_TABLE,))
        settings = cur.fetchall()
    segment = [a for a, seg, _o, _asc in sorted(settings, key=lambda r: r[1] or 0) if seg]
    order = [
        f"{a} {'ASC' if asc else 'DESC'}"
        for a, _s, o, asc in sorted(settings, key=lambda r: r[2] or 0)
        if o
    ]
    if not segment or not order:
        raise RuntimeError(f"{_FEATURE_TABLE} has no compression settings to copy")
    interval = chunk_interval(conn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(_SCRATCH_SCHEMA))
            )
            cur.execute(
                sql.SQL("CREATE TABLE {} (LIKE {} INCLUDING DEFAULTS INCLUDING INDEXES)").format(
                    table, sql.Identifier(_FEATURE_TABLE)
                )
            )
            cur.execute(
                "SELECT create_hypertable(%s::regclass, 'bar_ts', chunk_time_interval => %s)",
                (table.as_string(conn), interval),
            )
            cur.execute(
                sql.SQL(
                    "ALTER TABLE {} SET (timescaledb.compress, timescaledb.compress_segmentby = "
                    "{}, timescaledb.compress_orderby = {})"
                ).format(table, sql.Literal(", ".join(segment)), sql.Literal(", ".join(order)))
            )
            cur.execute(
                sql.SQL(
                    "INSERT INTO {} SELECT * FROM {} WHERE symbol = ANY(%s) AND tf = %s"
                ).format(table, sql.Identifier(_FEATURE_TABLE)),
                (list(symbols), tf),
            )
            rows = cur.rowcount
            cur.execute("SELECT hypertable_size(%s::regclass)", (table.as_string(conn),))
            before = int(cur.fetchone()[0] or 0)
            cur.execute(
                "SELECT count(compress_chunk(c)) FROM show_chunks(%s::regclass) c",
                (table.as_string(conn),),
            )
            cur.execute("SELECT hypertable_size(%s::regclass)", (table.as_string(conn),))
            after = int(cur.fetchone()[0] or 0)
    finally:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
    return {
        "rows": rows,
        "uncompressed_bytes": before,
        "compressed_bytes": after,
        "ratio": before / after if rows and after else None,
    }


def run_command(argv: Sequence[str], cwd: Path) -> tuple[int, str]:
    """Run one gate or writer as its own process from the worktree; (exit code, output tail)."""
    done = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True)
    return done.returncode, (done.stdout + done.stderr)[-OUTPUT_TAIL_CHARS:]


def systemctl(verb: str, unit: str) -> str:
    """The first line systemctl prints for `verb unit` (enabled, disabled, active, inactive...)."""
    done = subprocess.run(["systemctl", verb, unit], capture_output=True, text=True)
    lines = (done.stdout or done.stderr).strip().splitlines()
    return lines[0] if lines else ""


def fetcher_lock_free(dsn: str) -> bool:
    """Probe the IBKR history lock: acquire and release at once. A held lock (the fetcher or a
    manual history tool) means bars can move under the run."""
    from scripts.infrastructure.backfill._fetcher_lock import FetcherLock

    lock = FetcherLock(dsn, holder="corpus-rerun-pin-gate")
    try:
        return lock.acquire()
    finally:
        lock.close()


def module_files() -> list[str]:
    import services
    import services.backfill_feature_factory as writer

    return [str(services.__file__), str(writer.__file__)]


def rebuild_precondition_results(
    conn: Any, settings: Settings, includes_intraday: bool, disk: Mapping[str, int]
) -> list[Any]:
    """Every D-32 rebuild precondition (services/rebuild_preconditions.py run_all) on the live
    inputs; raises RebuildPreconditionFailure naming every failure."""
    from services import rebuild_preconditions as rp
    from services.backfill_feature_factory import _filter_etf_contracts, _get_target_timeframes
    from src.config.settings import get_active_contracts

    cfg = load_config_service_sync(conn)
    tfs = _get_target_timeframes(cfg)
    symbols = sorted(
        {
            c.symbol
            for c in _filter_etf_contracts(
                get_active_contracts(settings, dimension="compute_1d"), None
            )
        }
    )
    markers = rp.fetch_landed_markers(conn)
    grid = bool(markers.pop("grid_marker", False))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM unnest(%s::text[]) AS name WHERE to_regclass(name) IS NOT NULL",
            (sorted(rp.DROPS_DUE_BEFORE_REBUILD),),
        )
        present = {name for (name,) in cur.fetchall()}
    decision_path = rp._PROJECT_ROOT / TODO445_DECISION_PATH
    decision = json.loads(decision_path.read_text()).get("todo445_decision")
    return rp.run_all(
        bar_scan=rp.fetch_bar_verdict_inputs(conn, symbols, tfs),
        empty_history_spans=rp.fetch_empty_history_spans(conn, tfs),
        grid_marker_present=grid,
        grid_marker_detail="",
        d2_scan=rp.fetch_d2_inputs(conn, symbols),
        final_landed_markers=rp.fetch_final_landed_markers(),
        todo445_decision=decision,
        configured_tfs=tfs,
        dependency_markers=markers,
        present_relations=present,
        disk=disk,
        process_lines=rp.fetch_process_lines(),
        resumable_log_evidence="",
        includes_intraday=includes_intraday,
    )


@dataclasses.dataclass
class Deps:
    """Every effect the runner has besides corpus_run and corpus_run_step, injectable for tests."""

    settings: Any
    conn: Any
    python: str
    worktree: Path
    spool_root: Path
    run_data_gate: Callable[..., Any]
    run_stage: Callable[..., dict[str, Any]]
    planned_units: Callable[..., tuple[list[Any], set[str]]]
    symbol_chunks: Callable[[], list[tuple[str, ...]]]
    run_command: Callable[[Sequence[str], Path], tuple[int, str]]
    git_head: Callable[[Path], str]
    toplevel: Callable[[], Path]
    identity: Callable[[], dict[str, str]]  # {"code_key", "apr_hash"} as this process reads them
    module_files: Callable[[], list[str]]
    fetcher_lock_free: Callable[[], bool]
    systemctl: Callable[[str, str], str]
    no_live_run: Callable[[], Any]
    preconditions: Callable[[bool, Mapping[str, int]], list[Any]]
    free_bytes: Callable[[], int]
    wal_bytes: Callable[[], int]
    chunk_interval: Callable[[], timedelta]
    db_load: Callable[[], dict[str, int]]
    apr_value: Callable[[str], Any]
    measure_compression: Callable[[Sequence[str], str], dict[str, Any]]
    object_columns: frozenset[str]
    applicable: Callable[[str], frozenset[str]]
    read_json: Callable[[Path], Any]
    monotonic: Callable[[], float] = time.monotonic


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


class StepRefused(RuntimeError):
    """A step that may not start (upstream not completed, unknown step); nothing was written."""


class StepFailed(RuntimeError):
    """A step ran and failed; its summary is stored on the failed corpus_run_step row."""

    def __init__(self, message: str, summary: Mapping[str, Any]):
        super().__init__(message)
        self.summary = {"error": message, **summary}


_SELF_COMPLETED = object()  # a handler that completed its own step (data_gate's transaction)


class CorpusRerun:
    # The pilot's tf scope, one declaration for the staging calls, the column screen, the
    # unit list, the compression measures and the G6 expected_tfs (round 8: every site derives
    # from this tuple; ordered - the daily-stage tf first, the hour-unit tf second).
    PILOT_TFS = ("1d", "1h")

    def __init__(self, run: CorpusRun, store: RunStore, deps: Deps, apr: CorpusRerunApr):
        self.run = run
        self.store = store
        self.deps = deps
        self.apr = apr
        self.steps = build_steps(run.spans)
        self.by_name = {step.name: step for step in self.steps}

    # -- bookkeeping -----------------------------------------------------------

    def execute(self, name: str) -> dict[str, Any]:
        """Run one step: a no-op on a completed step, a refusal before any write when its
        upstream is not completed, otherwise started -> completed or failed."""
        step = self.by_name.get(name)
        if step is None:
            raise StepRefused(f"unknown step {name!r}; steps: {', '.join(self.by_name)}")
        stored = self.store.step(self.run.run_id, name)
        if stored is not None and stored.status == "completed":
            _logger.info("corpus_rerun.step_already_completed", step=name)
            return stored.summary
        if step.upstream is not None:
            upstream = self.store.step(self.run.run_id, step.upstream)
            if upstream is None or upstream.status != "completed":
                state = "has not run" if upstream is None else f"is {upstream.status}"
                raise StepRefused(
                    f"step {name} refused: its upstream step {step.upstream} {state} "
                    f"under run {self.run.run_id}"
                )
        self.store.begin(self.run.run_id, name)
        _logger.info("corpus_rerun.step_started", step=name, run_id=self.run.run_id)
        started = self.deps.monotonic()
        try:
            summary = getattr(self, f"_step_{step.kind}")(step)
        except StepFailed as failure:
            failure.summary["seconds"] = round(self.deps.monotonic() - started, 1)
            self.store.finish(self.run.run_id, name, "failed", failure.summary)
            self._record(step, "failure")
            _logger.error("corpus_rerun.step_failed", step=name, error=str(failure))
            raise
        except Exception as error:
            self.store.finish(
                self.run.run_id, name, "failed", {"error": f"{type(error).__name__}: {error}"}
            )
            self._record(step, "failure")
            _logger.error("corpus_rerun.step_error", step=name, error=str(error))
            raise
        if summary is not _SELF_COMPLETED:
            summary["seconds"] = round(self.deps.monotonic() - started, 1)
            self.store.finish(self.run.run_id, name, "completed", summary)
        self._record(step, "success")
        _logger.info("corpus_rerun.step_completed", step=name)
        stored = self.store.step(self.run.run_id, name)
        return {} if stored is None else stored.summary

    def through(self, name: str) -> None:
        """Every step in order up to and including `name`; stops at the first failure."""
        if name not in self.by_name:
            raise StepRefused(f"unknown step {name!r}")
        for step in self.steps:
            self.execute(step.name)
            if step.name == name:
                return

    @staticmethod
    def _record(step: Step, status: str) -> None:
        JOB_COMPLETED_TOTAL.add(1, {"job": f"{_JOB}.{step.kind}", "status": status})

    # -- data_gate -------------------------------------------------------------

    def _step_data_gate(self, step: Step) -> Any:
        result = self.deps.run_data_gate(
            self.deps.conn, self.deps.settings, self.apr, horizon=self.run.horizon
        )
        record = result.as_record()
        if not result.ok:
            raise StepFailed("the data gate refused the run", record)
        if not result.caveat or "code" not in result.caveat:
            raise StepFailed("a passing data gate returned no survivorship caveat", record)
        summary = {k: v for k, v in record.items() if k != "failing_name_years"}
        summary["seconds"] = 0.0
        self.store.complete_data_gate(self.run.run_id, step.name, record, result.caveat, summary)
        return _SELF_COMPLETED

    # -- pin_gate --------------------------------------------------------------

    def pin_checks(self, upcoming: Step) -> list[dict[str, Any]]:
        """Every pin check, each recorded whether it passes or not."""
        d, run = self.deps, self.run
        checks: list[dict[str, Any]] = []

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": bool(ok), "detail": detail})

        here = d.toplevel()
        check("worktree", here == d.worktree, f"running in {here}; the run's worktree {d.worktree}")
        head = d.git_head(d.worktree)
        check("head", head == run.code_commit, f"HEAD {head}; pinned {run.code_commit}")
        identity = d.identity()
        check(
            "code_key",
            identity["code_key"] == run.code_key,
            f"rebuild code key {identity['code_key']}; pinned {run.code_key}",
        )
        check(
            "apr_hash",
            identity["apr_hash"] == run.apr_hash,
            f"APR hash {identity['apr_hash']}; pinned {run.apr_hash}",
        )
        outside = [f for f in d.module_files() if not Path(f).resolve().is_relative_to(d.worktree)]
        check(
            "imports",
            not outside,
            (
                f"imported outside the worktree: {outside}"
                if outside
                else "services imports from the worktree"
            ),
        )
        free = d.fetcher_lock_free()
        check("fetcher_lock", free, "FetcherLock free" if free else "FetcherLock is held")
        for timer in self.apr.blocking_timers:
            enabled = d.systemctl("is-enabled", timer)
            service = timer.removesuffix(".timer") + ".service"
            active = d.systemctl("is-active", service)
            check(
                f"timer:{timer}",
                enabled in ("disabled", "masked") and active in ("inactive", "failed"),
                f"{timer} is {enabled or 'unknown'}; {service} is {active or 'unknown'}",
            )
        if upcoming.kind in (PILOT, STAGE_1D, SPAN, PIN_GATE):
            checks.extend(self._disk_and_preconditions(upcoming))
        else:
            live = d.no_live_run()
            check(live.name, live.ok, live.detail)
        return checks

    def _require_pin(self, upcoming: Step) -> list[dict[str, Any]]:
        checks = self.pin_checks(upcoming)
        failed = [c for c in checks if not c["ok"]]
        if failed:
            raise StepFailed(
                "pin gate: " + "; ".join(f"{c['name']}: {c['detail']}" for c in failed),
                {"pin_checks": checks},
            )
        return checks

    def _step_pin_gate(self, step: Step) -> dict[str, Any]:
        return {"pin_checks": self._require_pin(self.by_name[PILOT])}

    # -- disk --------------------------------------------------------------------

    def _inputs(
        self, bytes_per_row: float | None = None, compression_ratio: float | None = None
    ) -> BudgetInputs:
        measured = self.run.measured
        return BudgetInputs(
            free_bytes_at_launch=self.run.free_bytes_at_launch,
            max_disk_fraction=self.apr.max_disk_fraction,
            bytes_per_row=max(
                float(self.apr.bytes_per_row_uncompressed),
                float(measured.get("bytes_per_row_max", 0.0)),
                bytes_per_row or 0.0,
            ),
            compression_ratio=compression_ratio or self._compression_ratio(),
            stored_bytes_per_spool_byte=self._stored_per_spool(),
            wal_bytes=self.deps.wal_bytes(),
            chunk_interval=self.deps.chunk_interval(),
        )

    def _compression_ratio(self) -> float:
        """The pilot's measured ratio once it exists; the APR seed only before the pilot."""
        measured = self.run.measured.get(COMPRESSION_RATIO_MEASURED)
        return float(measured) if measured else self.apr.compression_ratio

    def _stored_per_spool(self) -> float:
        return max(
            self.apr.stored_bytes_per_spool_byte,
            float(self.run.measured.get("stored_per_spool_max", 0.0)),
        )

    def _counts(self) -> RowCounts:
        """The rows the run still had to write at launch: the counts less the stored rows of
        the units it would adopt (stored_row_counts); every other stored row is replaced, so
        its rewrite is growth."""
        counts = counts_from_record(self.run.measured["row_counts"])
        stored = self.run.measured.get("stored_row_counts")
        return counts.minus(counts_from_record(stored)) if stored else counts

    @staticmethod
    def _step_tf(step: Step) -> str:
        return step.tf if step.kind == SPAN and step.tf else "1d"

    def _peak_for(self, step: Step, inputs: BudgetInputs) -> Peak:
        counts = self._counts()
        if step.kind == SPAN and step.span_index is not None:
            return span_peak(self.run.spans, step.span_index, counts, inputs)
        return daily_peak(counts, inputs)

    def _increment(self, step: Step, inputs: BudgetInputs) -> float:
        """The upcoming step's own tf in its span, less what this run already loaded of it (a
        resumed step), plus the WAL and its spools. Growth since launch already holds the
        span's earlier tfs and everything compressed."""
        tf = self._step_tf(step)
        lo, hi = (
            self.run.spans[step.span_index]
            if step.kind == SPAN and step.span_index is not None
            else (datetime(1970, 1, 1, tzinfo=UTC), datetime(9999, 1, 1, tzinfo=UTC))
        )
        loaded = self.store.loaded_rows(self.run.run_id, tf, lo, hi)
        return step_increment(
            self.run.spans, step.span_index, tf, self._counts(), inputs, loaded_rows=loaded
        )

    def _disk_and_preconditions(self, upcoming: Step) -> list[dict[str, Any]]:
        inputs = self._inputs()
        peak = self._peak_for(upcoming, inputs)
        increment = self._increment(upcoming, inputs)
        free_now = self.deps.free_bytes()
        growth = self.run.free_bytes_at_launch - free_now
        start = (
            self.run.spans[upcoming.span_index][0]
            if upcoming.kind == SPAN and upcoming.span_index is not None
            else datetime(1970, 1, 1, tzinfo=UTC)
        )
        tfs = ("1d", *INTRADAY_ORDER) if upcoming.kind != SPAN else INTRADAY_ORDER
        remaining_rows = self._counts().rows(start, datetime(9999, 1, 1, tzinfo=UTC), tfs)
        disk = {
            "projected_compressed_bytes": int(
                remaining_rows * inputs.bytes_per_row / inputs.compression_ratio
            ),
            "span_peak_bytes": int(peak.working_set),
            "wal_bytes": int(inputs.wal_bytes),
            "free_bytes": int(free_now),
            "reserve_bytes": int(self.apr.disk_reserve_bytes),
        }
        checks = [
            {
                "name": "fraction_limit",
                "ok": growth + increment <= inputs.limit_bytes,
                "detail": (
                    f"growth since launch {growth / 1e9:,.0f} GB + {upcoming.name} increment "
                    f"{increment / 1e9:,.0f} GB vs limit {inputs.limit_bytes / 1e9:,.0f} GB"
                ),
            }
        ]
        try:
            results = self.deps.preconditions(upcoming.kind != STAGE_1D, disk)
        except Exception as error:
            results = getattr(error, "results", None)
            if results is None:
                raise
        checks += [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results]
        return checks

    def _guard(self) -> UnitDiskGuard:
        return UnitDiskGuard(
            free_bytes_at_launch=self.run.free_bytes_at_launch,
            max_disk_fraction=self.apr.max_disk_fraction,
            reserve_bytes=self.apr.disk_reserve_bytes,
            wal_bytes=self.deps.wal_bytes(),
            stored_bytes_per_spool_byte=self._stored_per_spool(),
            free_bytes=self.deps.free_bytes,
        )

    def _merge_measured(self, patch: Mapping[str, Any]) -> None:
        self.store.merge_measured(self.run.run_id, patch)
        self.run = dataclasses.replace(self.run, measured={**self.run.measured, **patch})

    def _measure_stage(self, summary: Mapping[str, Any]) -> None:
        """Fold a stage's measured maxima into corpus_run.measured (the guard's ratio and the
        projections use the largest seen in the run)."""
        measured = self.run.measured
        self._merge_measured(
            {
                "bytes_per_row_max": max(
                    float(measured.get("bytes_per_row_max", 0.0)), summary["bytes_per_row_max"]
                ),
                "stored_per_spool_max": max(
                    float(measured.get("stored_per_spool_max", 0.0)),
                    summary["stored_per_spool_max"],
                ),
            }
        )

    # -- the rebuild stages ----------------------------------------------------

    def _stage(self, **kwargs: Any) -> dict[str, Any]:
        summary = self.deps.run_stage(
            settings=self.deps.settings,
            symbols=None,
            db_conn=self.deps.conn,
            n_workers=int(self.deps.apr_value(_WORKERS_KEY)),
            horizon=self.run.horizon,
            spool_root=self.deps.spool_root,
            run_id=self.run.run_id,
            disk_guard=self._guard(),
            **kwargs,
        )
        self._measure_stage(summary)
        return summary

    def stage_problems(self, summary: Mapping[str, Any]) -> list[str]:
        """Why a stage's executed scope is not complete under this run (empty when it is)."""
        problems: list[str] = []
        for key in ("units_failed", "units_abandoned"):
            if summary.get(key):
                problems.append(f"{key} {summary[key]}")
        if summary.get("disk_refused"):
            problems.append(f"disk_refused {summary['disk_refused']}")
        scope = list(summary["scope_batch_keys"])
        adopted = {a["batch_key"]: a["adopted_from_run_id"] for a in summary.get("adopted", [])}
        rows = self.store.completed_rows(scope)
        missing = [k for k in scope if k not in rows]
        foreign = [
            f"{k} (run {rows[k]})"
            for k in scope
            if k in rows and not belongs_to_run(rows[k], k, self.run.run_id, adopted)
        ]
        if missing:
            problems.append(f"{len(missing)} units without a completed row: {missing[:20]}")
        if foreign:
            problems.append(f"{len(foreign)} units completed under another run: {foreign[:20]}")
        return problems

    def _step_stage_1d(self, step: Step) -> dict[str, Any]:
        pins = self._require_pin(step)
        summary = self._stage(timeframes=["1d"])
        problems = self.stage_problems(summary)
        if problems:
            raise StepFailed("stage_1d incomplete: " + "; ".join(problems), dict(summary))
        return {**summary, "pin_checks": pins}

    def _step_span(self, step: Step) -> dict[str, Any]:
        assert step.span_index is not None and step.tf is not None
        pins = self._require_pin(step)
        span = self.run.spans[step.span_index]
        summary = self._stage(timeframes=[step.tf], span=span)
        problems = self.stage_problems(summary)
        if step.tf == INTRADAY_ORDER[-1]:
            # After the span's last tf the compression bound has passed its end: every chunk
            # ending by then (short of the open chunk, which never compresses) is compressed.
            open_floor = datetime(self.run.horizon.year, 1, 1, tzinfo=UTC)
            left = self.store.uncompressed_chunks(min(span[1], open_floor))
            if left:
                problems.append(f"{len(left)} chunks ending by {span[1]:%Y-%m-%d} uncompressed")
        if problems:
            raise StepFailed(f"{step.name} incomplete: " + "; ".join(problems), dict(summary))
        return {**summary, "pin_checks": pins}

    # -- pilot -----------------------------------------------------------------

    def _step_pilot(self, step: Step) -> dict[str, Any]:
        pins = self._require_pin(step)
        d = self.deps
        load_before = d.db_load()
        t0 = d.monotonic()
        daily = self._stage(timeframes=[self.PILOT_TFS[0]], chunk_indices=[0])
        t1 = d.monotonic()
        span_start, span_end = self.run.spans[0]
        hourly: dict[str, Any] | None = None
        year = span_start.year
        while datetime(year, 1, 1, tzinfo=UTC) < span_end:
            # The first Jan-1 aligned year of span 1 holding a 1h unit of chunk 0; s1.1h later
            # skips it as completed.
            bounds = (datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC))
            hourly = self._stage(timeframes=[self.PILOT_TFS[1]], span=bounds, chunk_indices=[0])
            if hourly["units_total"]:
                break
            year += 1
        t2 = d.monotonic()
        load_after = d.db_load()
        summary: dict[str, Any] = {
            "pin_checks": pins,
            "stage_1d_chunk0": daily,
            "s1_1h_unit": hourly,
        }
        problems = self.stage_problems(daily)
        if hourly is None or not hourly["units_total"]:
            problems.append("no 1h unit of symbol chunk 0 inside span 1")
        else:
            problems += self.stage_problems(hourly)
        if not daily["units_total"]:
            problems.append("symbol chunk 0 has no 1d unit")
        if problems:
            raise StepFailed("pilot units: " + "; ".join(problems), summary)

        chunk0 = d.symbol_chunks()[0]
        # G6 in the pilot too: a NULL-share fault shows in the pilot hour, not after days
        screen = [d.python, str(COLUMN_SCREEN), "--null-gate"]
        screen += [arg for tf in self.PILOT_TFS for arg in ("--tf", tf)]
        for symbol in chunk0:
            screen += ["--symbol", symbol]
        units = [f"{s}:{tf}" for tf in self.PILOT_TFS for s in chunk0]
        gates = {
            "G1-G3": d.run_command(screen, d.worktree),
            "G4-G5": d.run_command(
                [d.python, str(PILOT_COMPUTE_GATE), "--units", *units], d.worktree
            ),
        }
        summary["gates"] = {
            name: {"returncode": rc, "output": out} for name, (rc, out) in gates.items()
        }

        measured = {
            "pilot_bytes_per_row_1d": daily["bytes_per_row_max"],
            "pilot_bytes_per_row_intraday": hourly["bytes_per_row_max"],
            "pilot_stored_per_spool": max(
                daily["stored_per_spool_max"], hourly["stored_per_spool_max"]
            ),
            "pilot_seconds_1d_chunk": round(t1 - t0, 1),
            "pilot_seconds_1h_unit": round(t2 - t1, 1),
        }
        counts = self._counts()
        every = (datetime(1970, 1, 1, tzinfo=UTC), datetime(9999, 1, 1, tzinfo=UTC))
        n_chunks = len(counts.chunks()) or 1
        hourly_rows = max(hourly["rows_loaded"], 1)
        measured["extrapolated_seconds"] = {
            "stage_1d": round((t1 - t0) * n_chunks, 0),
            **{
                tf: round((t2 - t1) / hourly_rows * counts.rows(*every, (tf,)), 0)
                for tf in INTRADAY_ORDER
            },
        }
        # The real compressed-to-uncompressed ratio of the pilot's rows (the 6.0 seed is the
        # plan-only preview's fallback); the smaller of the 1d and 1h ratios is the conservative
        # one for every later projection.
        compression = {tf: d.measure_compression(chunk0, tf) for tf in self.PILOT_TFS}
        measured["pilot_compression"] = compression
        ratios = [c["ratio"] for c in compression.values() if c.get("ratio")]
        if len(ratios) != len(compression):
            raise StepFailed("pilot: no compression ratio measured", {**summary, **measured})
        measured[COMPRESSION_RATIO_MEASURED] = min(ratios)
        measured["pilot_db_load"] = {
            "before": load_before,
            "after": load_after,
            "delta": {
                k: load_after[k] - load_before[k] for k in load_before if k != "other_active"
            },
        }
        self._merge_measured(measured)
        summary["measured"] = measured

        objects = self._object_gate(
            [*daily["scope_batch_keys"], *hourly["scope_batch_keys"]], list(self.PILOT_TFS)
        )
        summary["gates"]["G6-objects"] = objects
        failed_gates = [name for name, (rc, _) in gates.items() if rc != 0]
        if objects["failing"]:
            failed_gates.append("G6-objects")
        if failed_gates:
            raise StepFailed(f"pilot gates failed: {', '.join(failed_gates)}", summary)
        larger = max(measured["pilot_bytes_per_row_1d"], measured["pilot_bytes_per_row_intraday"])
        inputs = self._inputs(
            bytes_per_row=larger, compression_ratio=measured[COMPRESSION_RATIO_MEASURED]
        )
        peaks = project(self.run.spans, counts, inputs)
        summary["reprojection"] = [p.as_record() for p in peaks]
        over = overflowing(peaks, inputs)
        if over:
            raise StepFailed(
                "the pilot's measured bytes per row and compression ratio overflow the run's "
                "spans (spans are immutable: start a new run, which plans more spans):\n"
                + format_peaks(peaks, inputs.limit_bytes),
                summary,
            )
        return summary

    # -- feature_complete ---------------------------------------------------------

    def _step_feature_complete(self, step: Step) -> dict[str, Any]:
        d, run_id = self.deps, self.run.run_id
        specs, blind = d.planned_units(d.settings, d.conn, self.run.horizon)
        keys = [spec.batch_key for spec in specs]
        rows = self.store.completed_rows(keys)
        adoptions = self.store.adoptions(run_id)
        missing = [k for k in keys if k not in rows]
        foreign = [
            {"batch_key": k, "run_id": rows[k]}
            for k in keys
            if k in rows and not belongs_to_run(rows[k], k, run_id, adoptions)
        ]
        open_rows = [{"batch_key": k, "status": s} for k, s in self.store.open_rows(run_id)]
        for summary in self.store.completed_summaries(run_id).values():
            blind |= set(summary.get("digest_blind_symbols") or ())
            for part in ("stage_1d_chunk0", "s1_1h_unit"):
                blind |= set((summary.get(part) or {}).get("digest_blind_symbols") or ())
        screens = {
            tf: d.run_command([d.python, str(COLUMN_SCREEN), "--null-gate", "--tf", tf], d.worktree)
            for tf in self.apr_tfs()
        }
        summary = {
            "units_planned": len(keys),
            "units_missing": missing,
            "units_foreign": foreign,
            "open_rows": open_rows,
            "digest_blind_symbols": sorted(blind),
            "column_screen": {
                tf: {"returncode": rc, "output": out} for tf, (rc, out) in screens.items()
            },
        }
        problems = []
        if missing:
            problems.append(f"{len(missing)} planned units have no completed row")
        if foreign:
            problems.append(f"{len(foreign)} units completed under another run and not adopted")
        if open_rows:
            problems.append(f"{len(open_rows)} started or failed rows under the run")
        if blind:
            problems.append(f"{len(blind)} digest-blind symbols")
        failing = [tf for tf, (rc, _) in screens.items() if rc != 0]
        if failing:
            problems.append(f"column screen (G1-G3, G6 null share) fails on {failing}")
        objects = self._object_gate(keys, self.apr_tfs())
        summary["object_share"] = objects
        if objects["failing"]:
            problems.append(f"{len(objects['failing'])} object or event column shares fail")
        if problems:
            raise StepFailed("feature_complete: " + "; ".join(problems), summary)
        return summary

    def _object_gate(self, batch_keys: Sequence[str], tfs: Sequence[str]) -> dict[str, Any]:
        """object_share_gate over these units' unit_stats, judging every tf in `tfs`."""
        return object_share_gate(
            self.store.unit_stats(batch_keys),
            self.deps.object_columns,
            self.deps.applicable,
            self.apr.max_null_fraction,
            tfs,
        )

    def apr_tfs(self) -> list[str]:
        return list(self._json_apr(_TARGET_TFS_KEY))

    # -- ic_measure, d19_bound, canary -------------------------------------------

    def _caveats(self) -> list[dict[str, Any]]:
        """corpus_run.caveats as stored now (the data gate appended to it after load)."""
        return list(self.store.load_run(self.run.run_id).caveats)

    def _step_ic_measure(self, step: Step) -> dict[str, Any]:
        from services.ic_measure import (
            _DEFAULT_JOBS,
            TARGET_TABLE,
            active_jobs,
            job_replace_where,
            job_writer,
        )

        pins = self._require_pin(step)
        d = self.deps
        report_path = d.spool_root.parent / "corpus_rerun" / f"ic_measure_{self.run.run_id}.json"
        argv = [
            d.python,
            "-m",
            "services.ic_measure",
            "--run-id",
            self.run.run_id,
            "--report",
            str(report_path),
        ]
        rc, out = d.run_command(argv, d.worktree)
        summary: dict[str, Any] = {
            "pin_checks": pins,
            "returncode": rc,
            "output": out,
            "report": str(report_path),
            "caveats": self._caveats(),
        }
        if rc != 0:
            raise StepFailed(f"ic_measure exited {rc}", summary)
        outcomes = {o["unit_key"]: o for o in d.read_json(report_path)["outcomes"]}
        horizons = {tf: {int(h) for h in hs} for tf, hs in self._json_apr(_IC_HORIZONS_KEY).items()}
        adopted, problems = [], []
        for job in active_jobs(list(_DEFAULT_JOBS), []):
            for tf in horizons:
                unit_key = bulk_load_unit_key(
                    job_writer(job), TARGET_TABLE, tf, job_replace_where(job, tf)
                )
                problem, adoption = self._ic_unit(job, tf, outcomes.get(unit_key), unit_key)
                if problem:
                    problems.append(problem)
                if adoption:
                    adopted.append(adoption)
        summary["adopted"] = adopted
        # Every expected (tf, horizon) has POOLED unstratified rows (the proposer units, whose
        # rows the checks above tie to this run), and no unexpected horizon does.
        present = self.store.pooled_lookaheads()
        for tf, expected in sorted(horizons.items()):
            have = set(present.get(tf, {}))
            if expected - have:
                problems.append(f"tf {tf}: no POOLED rows at lookaheads {sorted(expected - have)}")
            if have - expected:
                problems.append(f"tf {tf}: unexpected lookaheads {sorted(have - expected)}")
        summary["pooled_lookaheads"] = {tf: sorted(v) for tf, v in present.items()}
        if problems:
            raise StepFailed("ic_measure units: " + "; ".join(problems), summary)
        return summary

    def _ic_unit(
        self, job: str, tf: str, outcome: Mapping[str, Any] | None, unit_key: str
    ) -> tuple[str | None, dict[str, Any] | None]:
        """(problem, adoption) for one ic_measure unit. Adopted only when this run's ic_measure
        reported it skipped (its identity was completed before the run computed it) and the
        unit's one completed row is exactly that batch_key; a loaded unit must be the run's own.
        A unit another writer completed mid-window matches neither and fails."""
        name = f"{job}/{tf}"
        if outcome is None:
            return f"{name}: no outcome in the ic_measure report", None
        rows = self.store.unit_completed(unit_key)
        if len(rows) != 1:
            return f"{name}: {len(rows)} completed rows", None
        batch_key, owner = rows[0]
        if batch_key != outcome["batch_key"]:
            return f"{name}: the completed row {batch_key[:12]} is not the reported unit", None
        if outcome["status"] == "skipped":
            if owner == self.run.run_id:
                return None, None
            return None, {
                "unit_key": unit_key,
                "batch_key": batch_key,
                "adopted_from_run_id": owner,
            }
        if outcome["status"] in ("loaded", "replaced") and owner == self.run.run_id:
            return None, None
        return f"{name}: {outcome['status']} and completed under run {owner}", None

    def _json_apr(self, key: str) -> Any:
        value = self.deps.apr_value(key)
        return json.loads(value) if isinstance(value, str) else value

    def _step_d19_bound(self, step: Step) -> dict[str, Any]:
        oos = self.deps.apr_value(_OOS_START_KEY)
        oos_start = (
            oos
            if isinstance(oos, datetime)
            else datetime.fromisoformat(str(oos).replace("Z", "+00:00"))
        )
        count, first = self.store.rows_reaching(oos_start)
        summary = {"oos_start": oos_start.isoformat(), "rows_reaching": count, "first": first}
        if count:
            raise StepFailed(f"{count} {_IC_TABLE} rows reach oos_start (D-19)", summary)
        return summary

    def _step_canary(self, step: Step) -> dict[str, Any]:
        d = self.deps
        rc, out = d.run_command([d.python, str(CANARY), "--run-id", self.run.run_id], d.worktree)
        summary = {"returncode": rc, "output": out, "caveats": self._caveats()}
        if rc != 0:
            raise StepFailed(f"canary exited {rc}", summary)
        return summary


# ---------------------------------------------------------------------------
# Wiring and the CLI
# ---------------------------------------------------------------------------


def _connect(settings: Settings) -> Any:
    return psycopg.connect(settings.database_url, autocommit=True)


def current_identity(conn: Any) -> dict[str, Any]:
    """The rebuild code key and the APR hash as THIS process's code reads them (the worktree's
    when run from it), with the pinned keys and their values for the record."""
    from services.backfill_feature_factory import _build_feature_factory_config, rebuild_code_key

    cfg = load_config_service_sync(conn)
    horizons = cfg.get_sync(_IC_HORIZONS_KEY)
    horizons = json.loads(horizons) if isinstance(horizons, str) else horizons
    keys = pinned_apr_keys(horizons or {})
    values = {key: cfg.get_sync(key) for key in keys}
    missing = sorted(k for k, v in values.items() if v is None)
    return {
        "code_key": rebuild_code_key(),
        "apr_hash": apr_hash(values, _build_feature_factory_config(cfg)),
        "apr_keys": keys,
        "apr_unseeded": missing,
    }


def real_deps(settings: Settings, conn: Any, worktree: Path) -> Deps:
    from services import backfill_feature_factory as factory
    from services import corpus_rerun_data_gate as gate
    from services import rebuild_preconditions as rp
    from src.intelligence.features.contract.registry import default_registry

    cfg = load_config_service_sync(conn)
    logs = main_logs_dir()
    registry = default_registry()
    return Deps(
        settings=settings,
        conn=conn,
        python=sys.executable,
        worktree=worktree.resolve(),
        spool_root=logs / "rebuild_spool",
        run_data_gate=gate.run_data_gate,
        run_stage=factory.run_rebuild_stage,
        planned_units=factory.planned_units,
        symbol_chunks=lambda: factory.symbol_chunks(settings, conn),
        run_command=run_command,
        git_head=lambda path: _git(["rev-parse", "HEAD"], path),
        toplevel=lambda: Path(_git(["rev-parse", "--show-toplevel"], Path.cwd())).resolve(),
        identity=lambda: current_identity(conn),
        module_files=module_files,
        fetcher_lock_free=lambda: fetcher_lock_free(settings.database_url),
        systemctl=systemctl,
        no_live_run=lambda: rp.check_no_live_run(rp.fetch_process_lines(), ""),
        preconditions=lambda intraday, disk: rebuild_precondition_results(
            conn, settings, intraday, disk
        ),
        free_bytes=lambda: factory.database_free_bytes(cfg),
        wal_bytes=lambda: factory.max_wal_bytes(conn),
        chunk_interval=lambda: chunk_interval(conn),
        db_load=lambda: db_load(conn),
        apr_value=lambda key: cfg.get_sync(key),
        measure_compression=lambda symbols, tf: measure_compression(conn, symbols, tf),
        object_columns=frozenset(registry.object_dependent_outputs()),
        applicable=lambda tf: frozenset(registry.applicable_outputs(tf)),
        read_json=lambda path: json.loads(path.read_text()),
    )


@dataclasses.dataclass(frozen=True)
class Plan:
    horizon: datetime
    counts: RowCounts
    stored: RowCounts
    inputs: BudgetInputs
    spans: list[tuple[datetime, datetime]]
    peaks: list[Peak]


def plan_run(conn: Any, settings: Settings, horizon: datetime) -> Plan:
    """The span plan --new-run records: counts, free space, max_wal_size, the chunk interval."""
    from services import backfill_feature_factory as factory

    cfg = load_config_service_sync(conn)
    apr = load_corpus_rerun_apr(cfg)
    ctx = factory._stage_context(settings, conn, None, None)
    counts = fetch_row_counts(conn, ctx.chunks, ctx.starts, horizon, ctx.all_timeframes)
    stored = stored_row_counts(conn, settings, horizon, ctx.chunks)
    inputs = BudgetInputs(
        free_bytes_at_launch=factory.database_free_bytes(cfg),
        max_disk_fraction=apr.max_disk_fraction,
        bytes_per_row=float(apr.bytes_per_row_uncompressed),
        compression_ratio=apr.compression_ratio,
        stored_bytes_per_spool_byte=apr.stored_bytes_per_spool_byte,
        wal_bytes=factory.max_wal_bytes(conn),
        chunk_interval=chunk_interval(conn),
    )
    plan = plan_spans(counts, inputs, stored=stored)
    return Plan(horizon, counts, stored, inputs, plan.spans, plan.peaks)


def _print_plan(plan: Plan) -> None:
    total = {
        tf: plan.counts.rows(datetime(1970, 1, 1, tzinfo=UTC), plan.horizon, (tf,))
        for tf in ("1d", *INTRADAY_ORDER)
    }
    print(
        f"horizon {plan.horizon:%Y-%m-%d}; rows "
        + ", ".join(f"{tf} {n:,.0f}" for tf, n in total.items())
    )
    print(
        f"free at launch {plan.inputs.free_bytes_at_launch / 1e9:,.0f} GB; limit "
        f"{plan.inputs.limit_bytes / 1e9:,.0f} GB; max_wal_size {plan.inputs.wal_bytes / 1e9:,.0f} GB; "
        f"chunk interval {plan.inputs.chunk_interval.days} days"
    )
    stored = sum(plan.stored.cells.values())
    print(
        f"rows of adoptable stored units (not growth) {stored:,}; compression ratio "
        f"{plan.inputs.compression_ratio:g} is the APR seed, a preview only: the pilot measures "
        "the real ratio and re-projects the spans before stage_1d"
    )
    print(f"{len(plan.spans)} spans: " + ", ".join(f"[{s:%Y}, {e:%Y})" for s, e in plan.spans))
    print(format_peaks(plan.peaks, plan.inputs.limit_bytes))


def _data_gate_verdict(conn: Any, settings: Settings, horizon: datetime) -> None:
    from services.corpus_rerun_data_gate import run_data_gate

    apr = load_corpus_rerun_apr(load_config_service_sync(conn))
    result = run_data_gate(conn, settings, apr, horizon=horizon)
    print(
        f"data_gate: {'PASS' if result.ok else 'FAIL'}; names {result.names_checked}; "
        f"failing name-years {len(result.failing_name_years)}; without a proven start "
        f"{len(result.names_without_proven_start)}"
    )
    for era, counts in result.eras.items():
        print(
            f"  {era}: names {counts.names}, at depth {counts.names_at_depth}, partial "
            f"{counts.names_partial}, none {counts.names_none}"
        )


def new_run(conn: Any, settings: Settings, horizon: datetime, commit: str) -> str:
    """Plan the spans, create the pinned worktree and record the run; returns the run id."""
    plan = plan_run(conn, settings, horizon)
    _print_plan(plan)
    main_root = main_checkout_root()
    commit = _git(["rev-parse", "--verify", f"{commit}^{{commit}}"], main_root)
    run_id = str(uuid.uuid4())
    worktree = run_worktree(run_id, main_root)
    _git(["worktree", "add", "--detach", str(worktree), commit], main_root)
    (worktree / ".env").symlink_to(main_root / ".env")
    (worktree / "logs").symlink_to(main_root / "logs", target_is_directory=True)
    probe = subprocess.run(
        [sys.executable, "-m", "services.corpus_rerun", "--print-identity"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=True,
    )
    identity = json.loads(probe.stdout.strip().splitlines()[-1])
    run = CorpusRun(
        run_id=run_id,
        code_commit=commit,
        code_key=identity["code_key"],
        horizon=horizon,
        apr_hash=identity["apr_hash"],
        spans=tuple(plan.spans),
        free_bytes_at_launch=plan.inputs.free_bytes_at_launch,
        caveats=(),
        measured={
            "row_counts": counts_record(plan.counts),
            "stored_row_counts": counts_record(plan.stored),
            "apr_keys": identity["apr_keys"],
            "apr_unseeded": identity["apr_unseeded"],
            "plan": [p.as_record() for p in plan.peaks],
            "wal_bytes_at_launch": plan.inputs.wal_bytes,
        },
    )
    RunStore(conn).create_run(run)
    print(f"run {run_id} created at {commit[:12]}; worktree {worktree}")
    print(
        f"next: cd {worktree} && {sys.executable} -m services.corpus_rerun --run-id {run_id} --through canary"
    )
    return run_id


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="The corpus rerun step runner (186-31)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--new-run", action="store_true", help="plan spans, create run + worktree")
    mode.add_argument("--run-id", type=parse_run_id, help="the corpus_run to drive")
    mode.add_argument("--print-identity", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="with --new-run: print the span " "plan and the data gate verdict, write nothing",
    )
    parser.add_argument(
        "--horizon",
        help="with --new-run: exclusive end, YYYY-MM-DD (default: "
        "the first day of the current UTC month)",
    )
    parser.add_argument("--commit", default="HEAD", help="with --new-run: the commit to pin")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--step", help="with --run-id: run this one step")
    which.add_argument("--through", help="with --run-id: run every step up to and including this")
    args = parser.parse_args(argv)
    if args.run_id and not (args.step or args.through):
        parser.error("--run-id needs --step or --through")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = Settings()
    conn = _connect(settings)
    if args.print_identity:
        try:
            print(json.dumps(current_identity(conn)))
        finally:
            conn.close()
        return 0
    setup_service_logging(str(main_logs_dir() / "corpus_rerun.log"))
    try:
        if args.new_run:
            from services.backfill_feature_factory import default_data_horizon

            horizon = (
                datetime.strptime(args.horizon, "%Y-%m-%d").replace(tzinfo=UTC)
                if args.horizon
                else default_data_horizon()
            )
            if args.plan_only:
                try:
                    _print_plan(plan_run(conn, settings, horizon))
                except SpanPlanRefused as refused:
                    print(f"REFUSED: {refused}")
                _data_gate_verdict(conn, settings, horizon)
                return 0
            try:
                new_run(conn, settings, horizon, args.commit)
            except SpanPlanRefused as refused:
                print(f"REFUSED: {refused}", file=sys.stderr)
                return 1
            return 0
        store = RunStore(conn)
        if not store.try_lock():
            print("another corpus rerun runner is live (one at a time)", file=sys.stderr)
            return 1
        run = store.load_run(args.run_id)
        apr = load_corpus_rerun_apr(load_config_service_sync(conn))
        runner = CorpusRerun(run, store, real_deps(settings, conn, run_worktree(run.run_id)), apr)
        try:
            if args.step:
                runner.execute(args.step)
            else:
                runner.through(args.through)
        except (StepRefused, StepFailed) as stop:
            print(f"STOPPED: {stop}", file=sys.stderr)
            return 1
        return 0
    finally:
        conn.close()
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    raise SystemExit(main())
