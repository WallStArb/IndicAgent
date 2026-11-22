"""The corpus rerun step runner (186-31, todo 593): one DAG of oneshot steps under one run id.

    data_gate -> pin_gate -> pilot -> stage_1d -> for each span s: s.1h -> s.15m -> s.5m
      -> feature_complete -> ic_measure -> d19_bound -> canary

A run of scope `1d` (`--data-gate-scope 1d`) has no span and no span step: data_gate, pin_gate,
pilot, stage_1d, feature_complete, ic_measure, d19_bound, canary, every one of them restricted to
the 1d timeframe (the intraday tier is a later run at scope `all`). A run records its scope; one
without a valid scope refuses at construction.

Each step refuses, loudly and before it writes anything, unless its upstream step of the same run
is completed; no flag skips a step. A completed step re-invoked is a no-op that reports its stored
outcome; a failed step retries once its cause is fixed. The runner writes only corpus_run and
corpus_run_step; the steps call the writers that own the data (run_rebuild_stage,
services/ic_measure.py) and the gates that judge it (186-32's data gate, the column screen, the
pilot compute gate, the canary).

- `data_gate`: 186-32's run_data_gate over the scope recorded in the run (`--data-gate-scope`,
  required with --new-run, kept in corpus_run.measured; `1d` gates on the 1d term alone, `all` on
  both). The scope is part of the stored verdict. `pilot` (its 1h unit) and the span steps compute
  intraday features, so they refuse unless the stored data_gate verdict's scope is `all`: a 1d-only
  verdict never unlocks them, and a verdict without a scope refuses too. A `1d` run's pilot is 1d
  only and needs no intraday verdict; its stages refuse any other timeframe. On a pass, one transaction writes corpus_run.data_gate,
  appends the survivorship caveat unless a caveat with its code is already present, and completes
  the step; a refusal writes the counts and failing lists to the failed step's summary only.
- `pin_gate` (re-run before every compute step): the process runs from the run's detached
  worktree at corpus_run.code_commit; the rebuild code key and APR hash equal the run's; services
  is imported from the worktree; FetcherLock is free; every blocking timer is disabled and its
  service not active; no live writer process; the rebuild preconditions pass with the span disk
  term; the growth since launch plus the next step's own increment (its tf's rows in its span not
  yet loaded under the run, the WAL, two group spools) stays inside the limit.
- `pilot`: stage_1d's chunk 0 and one 1h unit of span 1 (ordinary units of the real stages, kept;
  at scope `1d` the 1d unit only, with every gate and projection on 1d alone, and the summary
  records the proven-start disclosure), G1-G3 (column screen) and G4-G5 (pilot compute gate) on
  them, per-unit wall time and DB load,
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
batch_key from the run it records (services/batch_support/bulk_load.py belongs_to_run).

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
import importlib
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

from services import corpus_pilot_sample as pilot_rule
from services.batch_support.bulk_load import (
    RUN_ADOPTIONS_SQL,
    belongs_to_run,
    bulk_load_unit_key,
    parse_run_id,
)
from services.batch_support.db import load_config_service_sync
from services.corpus_rerun_apr import (
    DATA_GATE_SCOPES,
    SCOPE_1D,
    SCOPE_ALL,
    CorpusRerunApr,
    load_corpus_rerun_apr,
    load_quiesce_apr,
)
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
    plan_daily_only,
    plan_spans,
    project,
    span_peak,
    step_increment,
)
from services.corpus_rerun_quiesce import timer_is_quiet
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
_FIRST_ROW_KEY = (
    "feature.momentum.zscore_window"  # the rows a series skips before its first stored row
)
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
DATA_GATE_SCOPE_KEY = "data_gate_scope"  # corpus_run.measured: the scope chosen at --new-run
PIN_GATE = "pin_gate"
PILOT = "pilot"
FEATURE_COMPLETE = "feature_complete"
IC_MEASURE = "ic_measure"
D19_BOUND = "d19_bound"
CANARY_STEP = "canary"
SPAN = "span"
# Steps that compute intraday features: they need a data_gate verdict judged over scope `all`.
# The pilot computes its 1h unit only in a run of scope `all`; a `1d` run's pilot is 1d only.
INTRADAY_STEP_KINDS = frozenset({PILOT, SPAN})
DAILY_TF = "1d"


@dataclasses.dataclass(frozen=True)
class Step:
    name: str
    kind: str
    upstream: str | None
    tf: str | None = None
    span_index: int | None = None  # 0-based position in corpus_run.spans


def build_steps(spans: Sequence[tuple[datetime, datetime]], scope: str) -> list[Step]:
    """The fixed chain of a run of this scope; each step's upstream is the one before it. A `1d`
    run has no span step and no span (the intraday tier is a later run at scope `all`); a scope
    that is neither is refused, and so is a `1d` run that carries spans."""
    if scope not in DATA_GATE_SCOPES:
        raise ValueError(f"run scope {scope!r} is not one of {DATA_GATE_SCOPES}")
    if scope == SCOPE_1D and spans:
        raise ValueError(f"a run of scope {SCOPE_1D!r} has no spans, got {len(spans)}")
    kinds: list[tuple[str, str, str | None, int | None]] = [
        (DATA_GATE, DATA_GATE, None, None),
        (PIN_GATE, PIN_GATE, None, None),
        (PILOT, PILOT, None, None),
        (STAGE_1D, STAGE_1D, "1d", None),
    ]
    for k in range(len(spans)):  # none at scope `1d`
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
    f"SELECT count(*), min(training_window_end) FROM {_IC_TABLE} "
    "WHERE training_window_end >= %s AND (%s::text[] IS NULL OR tf = ANY(%s::text[]))"
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

    def rows_reaching(
        self, oos_start: datetime, tfs: Sequence[str] | None = None
    ) -> tuple[int, datetime | None]:
        """Rows of feature_ic_scores whose training window reaches oos_start, in `tfs` (all tfs
        when None)."""
        tf_list = None if tfs is None else list(tfs)
        count, first = self._one(_REACHING_OOS_SQL, (oos_start, tf_list, tf_list))
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
WITH c AS (SELECT * FROM unnest(%s::text[], %s::int[], %s::text[]) AS c(symbol, idx, tf)),
u AS (SELECT * FROM unnest(%s::text[], %s::int[], %s::timestamptz[], %s::timestamptz[])
        AS u(tf, idx, lo, hi))
SELECT m.tf, c.idx, (date_trunc('month', m.bar_ts AT TIME ZONE 'UTC'))::date, count(*)
FROM feature_vectors m
JOIN c ON c.symbol = m.symbol AND c.tf = m.tf
JOIN u ON u.tf = m.tf AND u.idx = c.idx AND m.bar_ts >= u.lo AND m.bar_ts < u.hi
GROUP BY 1, 2, 3
"""


def _combined(results: Iterable[tuple[int, str]]) -> tuple[int, str]:
    """Several commands' (returncode, output) as one: the first non-zero code, outputs joined."""
    found = list(results)
    code = next((rc for rc, _ in found if rc), 0)
    return code, "\n".join(out for _, out in found)


def adoptable_units(
    specs: Sequence[Any], completed: set[str], chunks: Sequence[tuple[str, ...]]
) -> list[tuple[str, int, datetime, datetime]]:
    """(tf, chunk index, range_start, range_end) of every planned unit whose identity is
    already completed: the run will skip and adopt exactly these, so only their rows are on disk
    for good. A unit stored under another identity (another code key, APR or input) is
    replaced: its new rows are growth, and the old space comes back only after a VACUUM."""
    # An intraday unit holds only the 5m tier's names of its chunk, so its chunk is found by any
    # one of its symbols (all share one chunk), not by the whole tuple.
    index = {s: i for i, chunk in enumerate(chunks) for s in chunk}
    return [
        (spec.tf, index[spec.symbols[0]], spec.range_start, spec.range_end)
        for spec in specs
        if spec.batch_key in completed
    ]


def stored_row_counts(
    conn: Any,
    settings: Any,
    horizon: datetime,
    chunks: Sequence[tuple[str, ...]],
    intraday: frozenset[str],
    planned: Callable[..., tuple[list[Any], set[str]]] | None = None,
    timeframes: Sequence[str] | None = None,
) -> RowCounts:
    """The rows already stored that the run would adopt, as RowCounts (not growth). Plans the
    full scope (the run's `timeframes` when given) only when feature_vectors has a completed unit
    at all."""
    with conn.cursor() as cur:
        cur.execute(_ANY_COMPLETED_UNIT_SQL, (_FEATURE_TABLE,))
        if not cur.fetchone()[0]:
            return RowCounts({})
    if planned is None:
        from services.backfill_feature_factory import planned_units as planned
    specs, _blind = planned(settings, conn, horizon, timeframes)
    with conn.cursor() as cur:
        cur.execute(_COMPLETED_KEYS_SQL, ([spec.batch_key for spec in specs],))
        completed = {key for (key,) in cur.fetchall()}
    units = adoptable_units(specs, completed, chunks)
    if not units:
        return RowCounts({})
    from services.backfill_feature_factory import _chunk_for

    # The names each timeframe stores per chunk: an intraday unit owns only the 5m tier's.
    names = [
        (s, i, tf)
        for tf in sorted({u[0] for u in units})
        for i, chunk in enumerate(chunks)
        for s in _chunk_for(tf, chunk, intraday)
    ]
    with conn.cursor() as cur:
        cur.execute(
            _ADOPTABLE_ROWS_SQL,
            (
                [s for s, _, _ in names],
                [i for _, i, _ in names],
                [t for _, _, t in names],
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
    intraday: frozenset[str],
) -> RowCounts:
    """Tradeable bars per (tf, symbol chunk, month) from each name's proven start to the horizon:
    the rows the rebuild will write, as the planner counts them. 1d counts every name; an
    intraday timeframe only the 5m tier's (names outside it have bars but no features)."""
    from services.backfill_feature_factory import NO_FLOOR, _chunk_for

    cells: dict[tuple[str, int, date], int] = {}
    for tfs in (
        [tf for tf in timeframes if tf == "1d"],
        [tf for tf in timeframes if tf != "1d"],
    ):
        if not tfs:
            continue
        names = [
            (s, i) for i, chunk in enumerate(chunks) for s in _chunk_for(tfs[0], chunk, intraday)
        ]
        with conn.cursor() as cur:
            cur.execute(
                _ROW_COUNTS_SQL,
                (
                    [s for s, _ in names],
                    [i for _, i in names],
                    [starts.get(s, NO_FLOOR) for s, _ in names],
                    tfs,
                    horizon,
                ),
            )
            cells.update({(tf, int(i), month): int(n) for tf, i, month, n in cur.fetchall()})
    return RowCounts(cells)


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


_IC_UNIVERSE_READERS = ("services.ic_measure", "src.intelligence.research.snapshot")
_UNIVERSE_SOURCE_ATTR = "UNIVERSE_SOURCE"
# The corpus computes both timeframes over the membership (1d) and its 5m tier (5m).
_CORPUS_TIMEFRAMES = ("1d", "5m")


def check_ic_universe_aligned(import_module: Callable[[str], Any] = importlib.import_module) -> Any:
    """Blocks the corpus rerun while the IC measurement reads another universe than the corpus
    computes (todo 609 blocker I1), per timeframe. ic_measure and research S0 each declare, as a
    module-level `UNIVERSE_SOURCE` mapping timeframe to reader, where a timeframe's universe comes
    from; for every corpus timeframe it must be `snapshot.membership_inputs`, the reader of the
    point-in-time membership mask. A module that cannot be imported, has no mapping, or lacks a
    timeframe or declares another reader fails
    with the module and timeframe named; the check never raises."""
    from services import rebuild_preconditions as rp
    from src.intelligence.research.snapshot import membership_inputs

    problems: list[str] = []
    for name in _IC_UNIVERSE_READERS:
        try:
            module = import_module(name)
        except Exception as error:
            problems.append(f"{name} cannot be imported ({type(error).__name__}: {error})")
            continue
        declared = getattr(module, _UNIVERSE_SOURCE_ATTR, None)
        if not isinstance(declared, dict):
            problems.append(f"{name} declares no {_UNIVERSE_SOURCE_ATTR} (reads the flags)")
            continue
        for tf in _CORPUS_TIMEFRAMES:
            if tf not in declared:
                problems.append(f"{name} declares no {tf} universe (reads the flags)")
            elif declared[tf] is not membership_inputs:
                problems.append(f"{name}.{_UNIVERSE_SOURCE_ATTR}[{tf!r}] is not membership_inputs")
    detail = (
        "ic_measure and research S0 read the membership universe for every corpus timeframe"
        if not problems
        else "; ".join(problems) + " (todo 609 blocker I1: the IC universe differs from the "
        "corpus universe)"
    )
    return rp.CheckResult("ic_universe_aligned", not problems, detail)


def rebuild_precondition_results(
    conn: Any, settings: Settings, includes_intraday: bool, disk: Mapping[str, int]
) -> list[Any]:
    """Every D-32 rebuild precondition (services/rebuild_preconditions.py run_all) on the live
    inputs; raises RebuildPreconditionFailure naming every failure."""
    from services import rebuild_preconditions as rp
    from services.backfill_feature_factory import filter_etf_contracts, get_target_timeframes
    from services.corpus_universe import corpus_universe

    cfg = load_config_service_sync(conn)
    tfs = get_target_timeframes(cfg)
    symbols = sorted({c.symbol for c in filter_etf_contracts(corpus_universe(conn), None)})
    intraday_symbols = sorted(
        {c.symbol for c in filter_etf_contracts(corpus_universe(conn, intraday=True), None)}
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
    ic_universe = check_ic_universe_aligned()
    try:
        results = rp.run_all(
            bar_scan=(
                rp.fetch_bar_verdict_inputs(conn, intraday_symbols, tfs)
                if includes_intraday
                else None
            ),
            empty_history_spans=(
                rp.fetch_empty_history_spans(conn, tfs) if includes_intraday else []
            ),
            grid_marker_present=grid,
            grid_marker_detail="",
            d2_scan=rp.fetch_d2_inputs(conn, symbols, held=rp.fetch_held_verdicts(conn)),
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
    except rp.RebuildPreconditionFailure as failure:
        raise rp.RebuildPreconditionFailure([*failure.results, ic_universe]) from None
    if not ic_universe.ok:
        raise rp.RebuildPreconditionFailure([*results, ic_universe])
    return [*results, ic_universe]


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
    planned_units: Callable[
        ..., tuple[list[Any], set[str]]
    ]  # (settings, conn, horizon, timeframes)
    symbol_chunks: Callable[[str], list[tuple[str, ...]]]  # by timeframe: the tier for intraday
    history_bars: Callable[[datetime], Mapping[str, int]]  # symbol -> tradeable 1d bars before it
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
    member_months: Callable[[], Mapping[str, tuple[int, bool]]]  # symbol -> (months, ever in tier)
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


def run_scope(run: CorpusRun) -> str:
    """The scope the run records (`--data-gate-scope` at --new-run): it picks the chain, the
    timeframes and the data gate. A run that records none, or an unknown one, refuses."""
    scope = run.measured.get(DATA_GATE_SCOPE_KEY)
    if scope not in DATA_GATE_SCOPES:
        raise StepRefused(
            f"run {run.run_id} records no valid scope {scope!r}; "
            f"create the run with --data-gate-scope {{{','.join(DATA_GATE_SCOPES)}}}"
        )
    return str(scope)


_SELF_COMPLETED = object()  # a handler that completed its own step (data_gate's transaction)


class CorpusRerun:
    # The pilot's tf scope. The scalars are the source of truth (round 10): a scope change
    # or a test override touches them, and PILOT_TFS derives for the set-semantics consumers
    # (column screen, unit list, compression measures, G6 expected_tfs). The staging reads
    # the named scalars, so no tuple order can silently swap the daily stage and the hour
    # probe.
    PILOT_DAILY_TF = "1d"
    PILOT_HOURLY_TF = "1h"
    PILOT_TFS = (PILOT_DAILY_TF, PILOT_HOURLY_TF)

    @property
    def pilot_tfs(self) -> tuple[str, ...]:
        """The tfs this run's pilot computes: 1d alone at scope `1d`, 1d and 1h at scope `all`."""
        return (self.PILOT_DAILY_TF,) if self.scope == SCOPE_1D else self.PILOT_TFS

    def __init__(self, run: CorpusRun, store: RunStore, deps: Deps, apr: CorpusRerunApr):
        self.run = run
        self.store = store
        self.deps = deps
        self.apr = apr
        self.scope = run_scope(run)
        self.steps = build_steps(run.spans, self.scope)
        self.by_name = {step.name: step for step in self.steps}
        self.handlers = self._step_handlers()
        unhandled = sorted({step.kind for step in self.steps} - set(self.handlers))
        if unhandled:  # a step kind added to the DAG without a handler fails at construction
            raise ValueError(f"step kind(s) without a handler: {unhandled}")

    @property
    def run_tfs(self) -> list[str]:
        """The timeframes this run computes and judges: 1d alone at scope `1d`, the APR target
        set at scope `all`. Every step reads its tfs here, so a `1d` run never counts, plans or
        measures an intraday unit."""
        return [DAILY_TF] if self.scope == SCOPE_1D else self.apr_tfs()

    def _step_handlers(self) -> dict[str, Callable[[Step], Any]]:
        """The one table from a step kind to the method that runs it (never a name lookup, so a
        helper cannot be mistaken for a step and a mistyped kind fails at construction)."""
        return {
            DATA_GATE: self._step_data_gate,
            PIN_GATE: self._step_pin_gate,
            PILOT: self._step_pilot,
            STAGE_1D: self._step_stage_1d,
            SPAN: self._step_span,
            FEATURE_COMPLETE: self._step_feature_complete,
            IC_MEASURE: self._step_ic_measure,
            D19_BOUND: self._step_d19_bound,
            CANARY_STEP: self._step_canary,
        }

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
        if step.kind == SPAN or (step.kind in INTRADAY_STEP_KINDS and self.scope == SCOPE_ALL):
            self._require_intraday_verdict(step)
        self.store.begin(self.run.run_id, name)
        _logger.info("corpus_rerun.step_started", step=name, run_id=self.run.run_id)
        started = self.deps.monotonic()
        try:
            summary = self.handlers[step.kind](step)
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

    def _require_intraday_verdict(self, step: Step) -> None:
        """Refuse an intraday step unless the stored data_gate verdict was judged over scope
        `all`; a 1d-only verdict, or one recorded without a scope, never unlocks 5m compute."""
        verdict = self.store.step(self.run.run_id, DATA_GATE)
        scope = verdict.summary.get("scope") if verdict is not None else None
        if scope != SCOPE_ALL:
            raise StepRefused(
                f"step {step.name} refused: it computes intraday features and the data_gate "
                f"verdict of run {self.run.run_id} was judged over scope {scope!r}, not "
                f"{SCOPE_ALL!r}"
            )

    def _step_data_gate(self, step: Step) -> Any:
        result = self.deps.run_data_gate(
            self.deps.conn,
            self.deps.settings,
            self.apr,
            horizon=self.run.horizon,
            scope=self.scope,
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
                timer_is_quiet(enabled, active),
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
    def _tf_of_step(step: Step) -> str:
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
        tf = self._tf_of_step(step)
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
        if upcoming.kind == SPAN:
            tfs: tuple[str, ...] = INTRADAY_ORDER
        else:
            tfs = (DAILY_TF, *INTRADAY_ORDER) if self.scope == SCOPE_ALL else (DAILY_TF,)
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
            intraday = upcoming.kind != STAGE_1D and self.scope == SCOPE_ALL
            results = self.deps.preconditions(intraday, disk)
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
        timeframes = kwargs.get("timeframes")
        if self.scope == SCOPE_1D and (not timeframes or set(timeframes) != {DAILY_TF}):
            # No path of a `1d` run reaches an intraday unit, whatever the caller asks.
            raise StepRefused(
                f"run {self.run.run_id} has scope {SCOPE_1D!r}: its stages compute {DAILY_TF} "
                f"only, not {timeframes!r}"
            )
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
        # The 1d pilot sample is a rule (ledger 2026-11-22d, services/corpus_pilot_sample.py): the
        # names are computed as whole chunks, so the unit identities stay the full run's and
        # stage_1d adopts them. Refused here, before any compute, when too few members qualify.
        try:
            chunks = d.symbol_chunks(self.PILOT_DAILY_TF)
            universe = {symbol for chunk in chunks for symbol in chunk}
            bars = {s: n for s, n in d.history_bars(self.run.horizon).items() if s in universe}
            sample = pilot_rule.pilot_sample(bars, self.run.run_id)
            sample_chunks = pilot_rule.sample_chunk_indices(sample, chunks)
        except (pilot_rule.PilotSampleShort, ValueError) as error:
            raise StepFailed(f"pilot sample: {error}", {"pin_checks": pins}) from error
        daily = self._stage(timeframes=[self.PILOT_DAILY_TF], chunk_indices=sample_chunks)
        t1 = d.monotonic()
        hourly = self._pilot_hourly_unit() if self.scope == SCOPE_ALL else None
        t2 = d.monotonic()
        load_after = d.db_load()
        summary: dict[str, Any] = {
            "pin_checks": pins,
            "stage_1d_sample": daily,
            "pilot_sample": {
                "names": len(sample),
                "chunks": sample_chunks,
                "min_bars": pilot_rule.PILOT_MIN_BARS,
                "min_judged_names": pilot_rule.PILOT_MIN_JUDGED_NAMES,
            },
            "proven_start_disclosure": self._proven_start_disclosure(),
        }
        problems = self.stage_problems(daily)
        if self.scope == SCOPE_ALL:
            summary["s1_1h_unit"] = hourly
            if hourly is None or not hourly["units_total"]:
                problems.append("no 1h unit of symbol chunk 0 inside span 1")
            else:
                problems += self.stage_problems(hourly)
        if not daily["units_total"]:
            problems.append("the pilot sample's chunks have no 1d unit")
        if problems:
            raise StepFailed("pilot units: " + "; ".join(problems), summary)

        # 1d screens the sample; an intraday timeframe the 5m-tier names of chunk 0, so the screen
        # and the compute gate never name a (symbol, tf) the stage did not compute.
        chunk0_by_tf = {
            tf: tuple(sample) if tf == self.PILOT_DAILY_TF else d.symbol_chunks(tf)[0]
            for tf in self.pilot_tfs
        }
        # the screen counts stored rows: the sample floor in bars less the rows the rebuild skips
        daily_floor = [
            "--min-name-rows",
            str(pilot_rule.min_stored_rows(int(d.apr_value(_FIRST_ROW_KEY)))),
            "--min-judged-names",
            str(pilot_rule.PILOT_MIN_JUDGED_NAMES),
        ]
        # G6 in the pilot too: a NULL-share fault shows in the pilot hour, not after days
        # One screen per timeframe over the names that timeframe computed (all of chunk 0 for 1d).
        screens = [
            [d.python, str(COLUMN_SCREEN), "--null-gate", "--tf", tf]
            + (daily_floor if tf == self.PILOT_DAILY_TF else [])
            + [arg for symbol in chunk0_by_tf[tf] for arg in ("--symbol", symbol)]
            for tf in self.pilot_tfs
        ]
        units = [f"{s}:{tf}" for tf in self.pilot_tfs for s in chunk0_by_tf[tf]]
        gates = {
            "G1-G3": _combined(d.run_command(argv, d.worktree) for argv in screens),
            "G4-G5": d.run_command(
                [d.python, str(PILOT_COMPUTE_GATE), "--units", *units], d.worktree
            ),
        }
        summary["gates"] = {
            name: {"returncode": rc, "output": out} for name, (rc, out) in gates.items()
        }

        # The stages measured: 1d always, the 1h unit only at scope `all` (a `1d` run measures,
        # extrapolates and re-projects stage_1d alone; its intraday terms are not judged).
        stages = [daily] if hourly is None else [daily, hourly]
        measured: dict[str, Any] = {
            "pilot_bytes_per_row_1d": daily["bytes_per_row_max"],
            "pilot_stored_per_spool": max(s["stored_per_spool_max"] for s in stages),
            "pilot_seconds_1d_chunk": round((t1 - t0) / len(sample_chunks), 1),
        }
        counts = self._counts()
        every = (datetime(1970, 1, 1, tzinfo=UTC), datetime(9999, 1, 1, tzinfo=UTC))
        n_chunks = len(counts.chunks()) or 1
        per_chunk = (t1 - t0) / len(sample_chunks)
        measured["extrapolated_seconds"] = {"stage_1d": round(per_chunk * n_chunks, 0)}
        if hourly is not None:
            hourly_rows = max(hourly["rows_loaded"], 1)
            measured["pilot_bytes_per_row_intraday"] = hourly["bytes_per_row_max"]
            measured["pilot_seconds_1h_unit"] = round(t2 - t1, 1)
            measured["extrapolated_seconds"] |= {
                tf: round((t2 - t1) / hourly_rows * counts.rows(*every, (tf,)), 0)
                for tf in INTRADAY_ORDER
            }
        # The real compressed-to-uncompressed ratio of the pilot's rows (the 6.0 seed is the
        # plan-only preview's fallback); the smaller of the 1d and 1h ratios is the conservative
        # one for every later projection.
        compression = {tf: d.measure_compression(chunk0_by_tf[tf], tf) for tf in self.pilot_tfs}
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
            [k for stage in stages for k in stage["scope_batch_keys"]], list(self.pilot_tfs)
        )
        summary["gates"]["G6-objects"] = objects
        failed_gates = [name for name, (rc, _) in gates.items() if rc != 0]
        if objects["failing"]:
            failed_gates.append("G6-objects")
        if failed_gates:
            raise StepFailed(f"pilot gates failed: {', '.join(failed_gates)}", summary)
        larger = max(
            measured["pilot_bytes_per_row_1d"], measured.get("pilot_bytes_per_row_intraday", 0.0)
        )
        inputs = self._inputs(
            bytes_per_row=larger, compression_ratio=measured[COMPRESSION_RATIO_MEASURED]
        )
        peaks = project(self.run.spans, counts, inputs)
        summary["reprojection"] = [p.as_record() for p in peaks]
        over = overflowing(peaks, inputs)
        if over:
            remedy = (
                "spans (spans are immutable: start a new run, which plans more spans)"
                if self.run.spans
                else "stage_1d peak (a 1d run has no spans: free disk, then start a new run)"
            )
            raise StepFailed(
                f"the pilot's measured bytes per row and compression ratio overflow the run's "
                f"{remedy}:\n" + format_peaks(peaks, inputs.limit_bytes),
                summary,
            )
        return summary

    def _pilot_hourly_unit(self) -> dict[str, Any] | None:
        """One 1h unit of symbol chunk 0 in the first Jan-1 aligned year of span 1 that holds
        one (scope `all` only); s1.1h later skips it as completed."""
        span_start, span_end = self.run.spans[0]
        hourly: dict[str, Any] | None = None
        year = span_start.year
        while datetime(year, 1, 1, tzinfo=UTC) < span_end:
            bounds = (datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC))
            hourly = self._stage(timeframes=[self.PILOT_HOURLY_TF], span=bounds, chunk_indices=[0])
            if hourly["units_total"]:
                break
            year += 1
        return hourly

    def _proven_start_disclosure(self) -> dict[str, Any]:
        """Owner disclosure (ledger 2026-11-21b): the names whose compute start is pushed past
        their last membership month by the proven start's coverage rule, from the stored data
        gate verdict's list and `universe_membership` (read only)."""
        from services.corpus_rerun_data_gate import proven_start_disclosure

        verdict = self.store.step(self.run.run_id, DATA_GATE)
        names = (verdict.summary if verdict is not None else {}).get(
            "names_member_before_proven_start", []
        )
        return proven_start_disclosure(names, self.deps.member_months())

    # -- feature_complete ---------------------------------------------------------

    def _step_feature_complete(self, step: Step) -> dict[str, Any]:
        d, run_id = self.deps, self.run.run_id
        tfs = self.run_tfs
        specs, blind = d.planned_units(
            d.settings, d.conn, self.run.horizon, tfs if self.scope == SCOPE_1D else None
        )
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
            for part in ("stage_1d_sample", "s1_1h_unit"):
                blind |= set((summary.get(part) or {}).get("digest_blind_symbols") or ())
        screens = {
            tf: d.run_command([d.python, str(COLUMN_SCREEN), "--null-gate", "--tf", tf], d.worktree)
            for tf in tfs
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
        objects = self._object_gate(keys, tfs)
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
        if self.scope == SCOPE_1D:  # ic_measure's default is every tf of its horizons APR
            argv += [arg for tf in self.run_tfs for arg in ("--tf", tf)]
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
        # Scope `all` judges every tf of the horizons APR (ic_measure's default); `1d` only 1d.
        only = {DAILY_TF} if self.scope == SCOPE_1D else None
        horizons = {
            tf: {int(h) for h in hs}
            for tf, hs in self._json_apr(_IC_HORIZONS_KEY).items()
            if only is None or tf in only
        }
        adopted, problems = [], []
        if only and only - set(horizons):  # a scope tf without horizons would check nothing
            problems.append(f"{sorted(only - set(horizons))} has no horizons in {_IC_HORIZONS_KEY}")
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
        summary["pooled_lookaheads"] = {
            tf: sorted(v) for tf, v in present.items() if only is None or tf in only
        }
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
        count, first = self.store.rows_reaching(
            oos_start, self.run_tfs if self.scope == SCOPE_1D else None
        )
        summary = {"oos_start": oos_start.isoformat(), "rows_reaching": count, "first": first}
        if count:
            raise StepFailed(f"{count} {_IC_TABLE} rows reach oos_start (D-19)", summary)
        return summary

    def _step_canary(self, step: Step) -> dict[str, Any]:
        d = self.deps
        argv = [d.python, str(CANARY), "--run-id", self.run.run_id]
        if self.scope == SCOPE_1D:  # the canary's default is every tf of the target APR
            argv += [arg for tf in self.run_tfs for arg in ("--tf", tf)]
        rc, out = d.run_command(argv, d.worktree)
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
    from services.backfill_feature_factory import build_feature_factory_config, rebuild_code_key

    cfg = load_config_service_sync(conn)
    horizons = cfg.get_sync(_IC_HORIZONS_KEY)
    horizons = json.loads(horizons) if isinstance(horizons, str) else horizons
    keys = pinned_apr_keys(horizons or {})
    values = {key: cfg.get_sync(key) for key in keys}
    missing = sorted(k for k, v in values.items() if v is None)
    return {
        "code_key": rebuild_code_key(),
        "apr_hash": apr_hash(values, build_feature_factory_config(cfg)),
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
        member_months=lambda: gate.fetch_member_months(conn),
        symbol_chunks=lambda tf: factory.symbol_chunks(settings, conn, tf),
        history_bars=lambda horizon: pilot_rule.fetch_history_bars(conn, horizon),
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


def plan_run(conn: Any, settings: Settings, horizon: datetime, scope: str) -> Plan:
    """The span plan --new-run records: counts, free space, max_wal_size, the chunk interval. A
    `1d` run counts the 1d timeframe only and plans no span (the disk plan is stage_1d's term)."""
    from services import backfill_feature_factory as factory

    if scope not in DATA_GATE_SCOPES:
        raise ValueError(f"run scope {scope!r} is not one of {DATA_GATE_SCOPES}")
    cfg = load_config_service_sync(conn)
    apr = load_corpus_rerun_apr(cfg)
    ctx = factory._stage_context(settings, conn, None, None)
    tfs = [DAILY_TF] if scope == SCOPE_1D else ctx.all_timeframes
    counts = fetch_row_counts(conn, ctx.chunks, ctx.starts, horizon, tfs, ctx.intraday)
    stored = stored_row_counts(
        conn,
        settings,
        horizon,
        ctx.chunks,
        ctx.intraday,
        timeframes=tfs if scope == SCOPE_1D else None,
    )
    inputs = BudgetInputs(
        free_bytes_at_launch=factory.database_free_bytes(cfg),
        max_disk_fraction=apr.max_disk_fraction,
        bytes_per_row=float(apr.bytes_per_row_uncompressed),
        compression_ratio=apr.compression_ratio,
        stored_bytes_per_spool_byte=apr.stored_bytes_per_spool_byte,
        wal_bytes=factory.max_wal_bytes(conn),
        chunk_interval=chunk_interval(conn),
    )
    if scope == SCOPE_1D:
        plan = plan_daily_only(counts, inputs, stored=stored)
    else:
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
    print(
        f"{len(plan.spans)} spans: " + ", ".join(f"[{s:%Y}, {e:%Y})" for s, e in plan.spans)
        if plan.spans
        else "no spans (scope 1d: stage_1d only)"
    )
    print(format_peaks(plan.peaks, plan.inputs.limit_bytes))


def _data_gate_verdict(conn: Any, settings: Settings, horizon: datetime, scope: str) -> None:
    from services.corpus_rerun_data_gate import run_data_gate

    apr = load_corpus_rerun_apr(load_config_service_sync(conn))
    result = run_data_gate(conn, settings, apr, horizon=horizon, scope=scope)
    print(
        f"data_gate: {'PASS' if result.ok else 'FAIL'} (scope {result.scope}); names {result.names_checked} "
        f"(5m tier {result.intraday_names}); "
        f"failing name-years {len(result.failing_name_years)}; without a proven start "
        f"{len(result.names_without_proven_start)}; 5m-term failing name-years not gating "
        f"{len(result.failing_5m_not_gating)}; 1d residual name-years (disclosed) "
        f"{len(result.residual_1d_name_years)}; held name-years {len(result.held_name_years)}; "
        f"members before their proven start {len(result.names_member_before_proven_start)}"
    )
    for era, counts in result.eras.items():
        print(
            f"  {era}: names {counts.names}, at depth {counts.names_at_depth}, partial "
            f"{counts.names_partial}, none {counts.names_none}"
        )


def new_run(conn: Any, settings: Settings, horizon: datetime, commit: str, scope: str) -> str:
    """Plan the spans, create the pinned worktree and record the run; returns the run id."""
    plan = plan_run(conn, settings, horizon, scope)
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
            DATA_GATE_SCOPE_KEY: scope,
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
    mode.add_argument(
        "--quiesce",
        action="store_true",
        help="disable and stop the blocking timers, record the prior set under logs/",
    )
    mode.add_argument(
        "--release", action="store_true", help="restore the set --quiesce recorded, then remove it"
    )
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
    parser.add_argument(
        "--data-gate-scope",
        choices=DATA_GATE_SCOPES,
        help="with --new-run (required), plan-only too: `1d` gates on the 1d term alone and "
        "never unlocks the intraday steps; `all` gates on 1d and 5m. Recorded in the run",
    )
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--step", help="with --run-id: run this one step")
    which.add_argument("--through", help="with --run-id: run every step up to and including this")
    args = parser.parse_args(argv)
    if args.run_id and not (args.step or args.through):
        parser.error("--run-id needs --step or --through")
    if args.new_run and not args.data_gate_scope:
        parser.error("--new-run needs --data-gate-scope (1d or all)")
    if args.data_gate_scope and not args.new_run:
        parser.error("--data-gate-scope applies to --new-run only (a run records its own)")
    return args


def _quiesce_command(args: argparse.Namespace, conn: Any) -> int:
    from services import corpus_rerun_quiesce as q
    from services import rebuild_preconditions as rp

    deps = q.QuiesceDeps(
        query=systemctl,
        change=q.real_change,
        no_live_run=lambda: rp.check_no_live_run(rp.fetch_process_lines(), ""),
    )
    path = q.state_path(main_logs_dir())
    try:
        if args.quiesce:
            cfg = load_config_service_sync(conn)
            apr, wait = load_corpus_rerun_apr(cfg), load_quiesce_apr(cfg)
            q.quiesce(
                apr.blocking_timers,
                deps,
                path,
                wait_seconds=wait.wait_seconds,
                poll_seconds=wait.poll_seconds,
            )
            print(f"quiesced {len(apr.blocking_timers)} timers; the prior set is in {path}")
        else:
            restored = q.release(deps, path)
            print(f"released: {restored}" if restored else "nothing recorded; nothing to release")
    except q.QuiesceError as error:
        print(f"STOPPED: {error}", file=sys.stderr)
        return 1
    return 0


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
        if args.quiesce or args.release:
            return _quiesce_command(args, conn)
        if args.new_run:
            from services.backfill_feature_factory import default_data_horizon

            horizon = (
                datetime.strptime(args.horizon, "%Y-%m-%d").replace(tzinfo=UTC)
                if args.horizon
                else default_data_horizon()
            )
            if args.plan_only:
                try:
                    _print_plan(plan_run(conn, settings, horizon, args.data_gate_scope))
                except SpanPlanRefused as refused:
                    print(f"REFUSED: {refused}")
                _data_gate_verdict(conn, settings, horizon, args.data_gate_scope)
                return 0
            try:
                new_run(conn, settings, horizon, args.commit, args.data_gate_scope)
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
        try:
            runner = CorpusRerun(
                run, store, real_deps(settings, conn, run_worktree(run.run_id)), apr
            )
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
