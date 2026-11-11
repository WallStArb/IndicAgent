"""The step 7 canonical rebuild of the direct timeframes: span-major, chunk-aligned, resumable.

Design: docs/plans/2026-11-10-massive-admission-db-design.md section 8 step 7 (drop and one-pass
rebuild); runbook docs/operations/massive-step7-runbook.md, which owns the order (card, policy,
TRUNCATE, this, the daily and grid stages, checks). Canonical is a pure function of raw, policy
and the split horizon, so it is rebuilt by the one canonical writer (services.bar_selection
.select_and_write), never by a copy.

--preflight          read-only. The hard-abort preconditions re-run immediately before the
                     TRUNCATE: no foreign key references market_data_ohlcv; every canonical
                     timeframe has a raw source holding at least as many rows (1m: raw IBKR 1m
                     equals canonical 1m, the refinement review's F4; 4h holds none); the chunk
                     grid is the epoch-aligned dimension interval (the windows below rely on it);
                     no split row is dated after today (d2-v6 would rescale 1d by it, selection
                     would not rescale 5m); the compression settings and the quiet list
                     (QUIET_UNITS and QUIET_PROCESSES inactive, no other session touching
                     canonical); and the lineage gate: every latest red 1d lineage_missing or
                     canonical_recompute verdict (canonical rows raw cannot rebuild) has a
                     disposition in --dispositions and its rows are in the --card directory's
                     physical export (ops_canonical_summary_card). A clean preflight unschedules the table's compression policy
                     job (a window must not be compressed mid-fill). It writes the state file
                     the rebuild resumes
                     from, with the pinned horizon and the settings to re-check after.
--rebuild            for each chunk window [a, b) of the grid from --from to now, oldest first,
                     and each --timeframes (1m, 5m): every instrument through select_and_write
                     over the whole NYSE sessions of [a, b) (a session never straddles a UTC
                     midnight chunk edge, so a window touches one chunk), one commit per symbol,
                     the run's one horizon for every call; then, once every timeframe of the run
                     has filled the window, compress its chunk (one invocation for 5m and 1m).
                     Per window totals go to the JSONL report. It refuses a non-empty table on a
                     fresh state, a --from after a timeframe's first raw bar, and a quiet list
                     that is not quiet (re-checked on every resume); a selection that replaced,
                     found equal or retracted a stored row stops the run (the target was not
                     empty). Rerunning the same command resumes after the last committed
                     symbol. --reset refuses once any window was written.
--abort              reschedule the compression policy job the preflight unscheduled; every abort
                     path after a clean preflight runs it (the runbook names it in each rule).
--finish             reschedule the compression policy job the preflight unscheduled, run it to
                     recompress partial chunks (the daily and grid stages write into compressed
                     chunks after this), ANALYZE, and check the compression settings and grid
                     against the preflight record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from scripts.ops.bars.ops_canonical_summary_card import red_lineage  # noqa: E402
from scripts.ops.bars.ops_massive_load import disk_headroom_refusal  # noqa: E402
from services.bar_selection import DIRECT_TIMEFRAMES, select_and_write  # noqa: E402
from services.ohlcv_ingress_contract import read_raw_params  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.intelligence.bars.selection import SESSION_TZ  # noqa: E402

TABLE = "market_data_ohlcv"
# Units that write or read canonical bars and must be inactive for the TRUNCATE and the rebuild
# (design section 8 step 0, the refinement review's F14; the Alpaca nightly selects 5m into
# canonical through the load engine, so the runbook stops it too).
QUIET_UNITS = (
    "indicagent-bar-derivation-daily.timer",
    "indicagent-bar-derivation-grid.timer",
    "indicagent-bar-reconciliation-audit.timer",
    "indicagent-dividend-event-writer-yahoo.timer",
    "indicagent-regime-coverage-auditor.timer",
    "indicagent-alpaca-nightly.timer",
    "indicagent-ibkr-history-fetcher.timer",
    # it force-runs the compression job on an overdue chunk, which would compress the chunk the
    # rebuild is filling (the preflight also unschedules the job; --finish reschedules it)
    "indicagent-compression-auditor.service",
    "indicagent-bar-derivation-daily.service",
    "indicagent-bar-derivation-grid.service",
    "indicagent-bar-reconciliation-audit.service",
    "indicagent-alpaca-nightly.service",
    "indicagent-ibkr-history-fetcher.service",
)
# Hand-run writers and readers of canonical that no unit covers (the Massive load sweep among
# them): a process whose command line matches one of these must not be running.
QUIET_PROCESSES = (
    "ops_massive_load",
    "massive_sweep",
    "ops_selection_gate",
    "ops_source_policy",
    "ops_split_detect",
    "services.bar_derivation",
    "bar_reconciliation_audit",
    "ohlcv_history_fetcher",
    "ops_bar_nightly",
)
_FK_SQL = "SELECT conrelid::regclass::text FROM pg_constraint WHERE confrelid = %s::regclass"
_COMPRESSION_SQL = """
SELECT attname, segmentby_column_index, orderby_column_index, orderby_asc, orderby_nullsfirst
FROM timescaledb_information.compression_settings
WHERE hypertable_name = %s ORDER BY attname
"""
_INTERVAL_SQL = """
SELECT extract(epoch FROM time_interval)::bigint FROM timescaledb_information.dimensions
WHERE hypertable_name = %s AND dimension_type = 'Time'
"""
_CHUNKS_SQL = """
SELECT extract(epoch FROM range_start)::bigint, extract(epoch FROM range_end)::bigint
FROM timescaledb_information.chunks WHERE hypertable_name = %s ORDER BY range_start
"""
_CANONICAL_TF_SQL = f"SELECT timeframe, count(*) FROM {TABLE} GROUP BY 1"
_ANY_ROW_SQL = f"SELECT EXISTS (SELECT 1 FROM {TABLE})"
_RAW_TF_SQL = 'SELECT count(*), min("timestamp") FROM ohlcv_raw WHERE timeframe = %s'
# Every live policy row: a rebuild resumed under another policy would mix two selections in one
# table (stage 1 windows beside restored-policy windows), so the state pins this digest.
_POLICY_IDS_SQL = "SELECT policy_id::text FROM bar_source_policy_current ORDER BY 1"
_OTHER_SESSIONS_SQL = f"""
SELECT count(*) FROM pg_stat_activity
WHERE pid <> pg_backend_pid() AND state <> 'idle' AND query ILIKE '%%{TABLE}%%'
"""
_SCHEDULE_SQL = "SELECT alter_job(%s, scheduled => %s)"
_SYMBOLS_SQL = "SELECT symbol FROM instruments ORDER BY symbol"
# Splits not executed yet. Selection leaves them out of a 5m rescale (splits_known_at), but the
# d2-v6 daily rule divides Massive 1d by every market split dated on or after the bar, so one
# such row would put a name's 1d and 5m Massive history on different scales.
_FUTURE_SPLITS_SQL = """
SELECT symbol, effective_date::text FROM corporate_action_current
WHERE action_type IN ('split', 'reverse_split')
  AND effective_date > (now() AT TIME ZONE 'America/New_York')::date
ORDER BY 1, 2
"""
_COMPRESS_SQL = f"""
SELECT count(compress_chunk(c, if_not_compressed => true))
FROM show_chunks('{TABLE}', newer_than => %s::timestamptz, older_than => %s::timestamptz) c
"""
# The table's compression policy job: --finish runs it (it recompresses partial chunks, the
# way the raw loader recompresses ohlcv_raw), and its compress_after bounds what a window may
# compress early (the newest chunks stay uncompressed, as the policy keeps them).
_JOB_SQL = f"""
SELECT job_id, extract(epoch FROM (config->>'compress_after')::interval)::bigint
FROM timescaledb_information.jobs
WHERE hypertable_name = '{TABLE}' AND proc_name = 'policy_compression'
"""
_TOTAL_KEYS = (
    "new",
    "changed",
    "unchanged",
    "skipped_null_volume",
    "unselected",
    "off_grid",
    "sessions_fallback",
    "sessions_incomplete",
    "dropped",
    "excluded",
)


def chunk_windows(interval_s: int, first: date, until: datetime) -> list[tuple[datetime, datetime]]:
    """The epoch-aligned chunk ranges [a, b) covering `first` to `until` (TimescaleDB's own
    grid for a time dimension of `interval_s` seconds), oldest first."""
    start = int(datetime.combine(first, datetime.min.time(), UTC).timestamp())
    lo = start - start % interval_s
    out = []
    while lo < until.timestamp():
        out.append((datetime.fromtimestamp(lo, UTC), datetime.fromtimestamp(lo + interval_s, UTC)))
        lo += interval_s
    return out


def grid_misaligned(chunks: Iterable[tuple[int, int]], interval_s: int) -> list[tuple[int, int]]:
    """Existing chunk ranges that are not on the epoch-aligned grid (must be none)."""
    return [(a, b) for a, b in chunks if a % interval_s or b - a != interval_s]


def session_bounds(window: tuple[datetime, datetime]) -> tuple[datetime, datetime]:
    """The New York midnights of the window edges' UTC dates: whole sessions inside the chunk
    (select_and_write widens to session edges; a session's bars never cross 00:00 UTC)."""
    a, b = window
    return (
        datetime.combine(a.date(), datetime.min.time(), SESSION_TZ),
        datetime.combine(b.date(), datetime.min.time(), SESSION_TZ),
    )


def source_shortfalls(canonical: Mapping[str, int], raw: Mapping[str, int]) -> list[str]:
    """Canonical timeframes no raw source can rebuild. 15m and 1h derive from the rebuilt 5m;
    every other timeframe needs at least as many raw rows as canonical holds, and 1m exactly as
    many (one vendor, one row per slot: the refinement review's F4 measurement)."""
    out = []
    for tf, n in sorted(canonical.items()):
        have = raw.get(tf, 0)
        if tf not in ("15m", "1h") and (have != n if tf == "1m" else have < n):
            out.append(f"{tf}: canonical {n}, raw {have}")
    return out


def lineage_gate(
    red: Sequence[str], dispositions: Mapping[str, str], exported: Iterable[str]
) -> list[str]:
    """Failures of the lineage gate: a red `SYMBOL|1d|check` verdict with no written disposition,
    or a red name whose canonical 1d rows the card did not export (the TRUNCATE would lose them
    with no pre-image)."""
    failures = [f"red 1d verdict with no disposition: {v}" for v in red if not dispositions.get(v)]
    missing = sorted({v.split("|", 1)[0] for v in red} - set(exported))
    if missing:
        failures.append(f"red 1d lineage names missing from the card's export: {missing}")
    return failures


def read_card_lineage(card: Path) -> list[str]:
    """The names whose canonical 1d rows the card exported (card.json, red_lineage)."""
    meta = json.loads((card / "card.json").read_text())
    return list(meta.get("red_lineage", {}).get("exported_symbols", []))


def result_violation(result: Any, symbol: str, pending: str | None) -> str | None:
    """Why one symbol's selection into an empty target is wrong, or None. After TRUNCATE every
    winner is new: a replaced (`changed`), already-equal (`unchanged`) or retracted (`dropped`)
    row means the target was not empty. The one exception is the symbol a crash left pending
    (committed before its state was saved): its rows are already there, unchanged."""
    if result.changed or result.dropped:
        return f"{symbol}: changed {result.changed}, dropped {result.dropped}"
    if result.unchanged and symbol != pending:
        return f"{symbol}: unchanged {result.unchanged}"
    return None


def from_violations(start: date, raw_first: Mapping[str, str | None], timeframes: Iterable[str]):
    """Timeframes whose first raw bar (recorded by the preflight) is before --from: their earlier
    windows would never be rebuilt."""
    out = []
    for tf in timeframes:
        first = raw_first.get(tf)
        if first is not None and datetime.fromisoformat(first).date() < start:
            out.append(f"{tf}: first raw bar {first} is before --from {start}")
    return out


def has_written(state_data: Mapping[str, Any]) -> bool:
    """Whether a rebuild already wrote under this state (a window done or in flight)."""
    return any(state_data.get("done", {}).values()) or bool(state_data.get("inflight"))


def add_totals(into: dict[str, int], result: Any) -> None:
    for key in _TOTAL_KEYS:
        into[key] = into.get(key, 0) + int(getattr(result, key))


class State:
    """The rebuild's resume record: the pinned horizon, the preflight facts, per timeframe the
    windows done, and per window in progress ("<timeframe>|<window>") its last committed symbol
    and running totals."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
        self.data.setdefault("done", {})
        self.data.setdefault("inflight", {})

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True, default=str) + "\n")
        tmp.replace(self.path)

    @property
    def horizon(self) -> datetime:
        return datetime.fromisoformat(self.data["horizon"])

    def done(self, timeframe: str, window: str) -> bool:
        return window in self.data["done"].get(timeframe, [])

    def inflight(self, key: str) -> dict[str, Any]:
        """The window's resume entry: {"last": committed symbol, "pending": the symbol being
        committed (set before its commit), "totals": {...}}."""
        return self.data["inflight"].setdefault(key, {"last": None, "pending": None, "totals": {}})

    def finish(self, timeframe: str, window: str) -> None:
        self.data["done"].setdefault(timeframe, []).append(window)
        self.data["inflight"].pop(f"{timeframe}|{window}", None)
        self.save()


def compression_job(cur: Any) -> tuple[list[int] | None, str | None]:
    """([job_id, compress_after seconds], None) of TABLE's one compression policy job, or
    (None, why) when there is not exactly one."""
    cur.execute(_JOB_SQL)
    jobs = cur.fetchall()
    if len(jobs) != 1:
        return None, f"{len(jobs)} compression policy jobs on {TABLE}, not 1"
    return [int(v) for v in jobs[0]], None


def policy_digest(policy_ids: Iterable[str]) -> str:
    """The digest of a set of live policy_ids (order-free)."""
    return hashlib.sha256("\n".join(sorted(policy_ids)).encode()).hexdigest()


def read_policy_digest(cur: Any) -> str:
    cur.execute(_POLICY_IDS_SQL)
    return policy_digest(r[0] for r in cur.fetchall())


def read_layout(cur: Any) -> tuple[int, list[tuple[int, int]], list[list[Any]]]:
    """(chunk interval seconds, chunks off the epoch grid, compression settings) of TABLE."""
    cur.execute(_INTERVAL_SQL, (TABLE,))
    interval_s = int(cur.fetchone()[0])
    cur.execute(_CHUNKS_SQL, (TABLE,))
    misaligned = grid_misaligned(cur.fetchall(), interval_s)
    cur.execute(_COMPRESSION_SQL, (TABLE,))
    return interval_s, misaligned, [list(r) for r in cur.fetchall()]


def _dsn() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


def _unit_active(unit: str) -> bool:
    out = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
    return out.stdout.strip() in ("active", "activating", "reloading")


def _running(pattern: str) -> list[str]:
    """Python processes whose command line names `pattern` (a shell that merely mentions it in
    its own command text is not a writer)."""
    out = subprocess.run(["pgrep", "-af", pattern], capture_output=True, text=True)
    return [
        line
        for line in out.stdout.splitlines()
        if "python" in (line.split(maxsplit=2) + ["", ""])[1]
        and "ops_canonical_rebuild" not in line
    ]


def quiet_failures() -> list[str]:
    """The quiet list (QUIET_UNITS, QUIET_PROCESSES): what is still running."""
    failures = []
    if busy := [u for u in QUIET_UNITS if _unit_active(u)]:
        failures.append(f"units not quiet: {busy}")
    if procs := sorted({line for pattern in QUIET_PROCESSES for line in _running(pattern)}):
        failures.append(f"processes not quiet: {procs}")
    return failures


def run_preflight(args: argparse.Namespace) -> int:
    state = State(args.state)
    if args.reset and has_written(state.data):
        print("refused: --reset would re-pin the horizon of a rebuild that already wrote windows")
        return 2
    failures = quiet_failures()
    refusal = disk_headroom_refusal()
    if refusal:
        failures.append(f"disk: {refusal}")
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
        cur.execute(_FK_SQL, (TABLE,))
        if fks := [r[0] for r in cur.fetchall()]:
            failures.append(f"foreign keys reference {TABLE}: {fks}")
        interval_s, misaligned, compression = read_layout(cur)
        if misaligned:
            failures.append(f"chunks off the epoch grid: {misaligned[:5]}")
        job, why = compression_job(cur)
        if why:
            failures.append(why)
        cur.execute(_CANONICAL_TF_SQL)
        canonical = {tf: int(n) for tf, n in cur.fetchall()}
        raw, raw_first = {}, {}
        for tf in sorted(set(canonical) | DIRECT_TIMEFRAMES):
            cur.execute(_RAW_TF_SQL, (tf,))
            n, first = cur.fetchone()
            raw[tf], raw_first[tf] = int(n), first.isoformat() if first else None
        failures += source_shortfalls(canonical, raw)
        policy = read_policy_digest(cur)
        if has_written(state.data) and policy != state.data.get("policy_digest"):
            failures.append(
                "the live policy differs from the one this state's windows were selected under; "
                "start a fresh state file (after a TRUNCATE) instead of resuming"
            )
        cur.execute(_FUTURE_SPLITS_SQL)
        if future := cur.fetchall():
            failures.append(f"splits not executed yet (1d and 5m would disagree): {future[:10]}")
        red = red_lineage(cur)
        dispositions = json.loads(args.dispositions.read_text()) if args.dispositions else {}
        failures += lineage_gate(red, dispositions, read_card_lineage(args.card))
        cur.execute(_OTHER_SESSIONS_SQL)
        if n_other := int(cur.fetchone()[0]):
            failures.append(f"{n_other} other session(s) are running a statement on {TABLE}")
        conn.rollback()
    if "horizon" in state.data and not args.reset:
        horizon = state.data["horizon"]
    else:
        horizon = (args.horizon or datetime.now(UTC)).isoformat()
    state.data.update(
        {
            "horizon": horizon,
            "interval_s": interval_s,
            "compression": compression,
            "compression_job": job,
            "policy_digest": policy,
            "canonical_rows_before": canonical,
            "raw_rows": raw,
            "raw_first": raw_first,
            "red_lineage": {v: dispositions.get(v) for v in red},
            "preflight_at": datetime.now(UTC).isoformat(),
            "preflight_failures": failures,
        }
    )
    state.save()
    if not failures:
        # The policy job must not compress a chunk mid-fill; --finish reschedules and runs it.
        with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(_SCHEDULE_SQL, (state.data["compression_job"][0], False))
    print(json.dumps({k: state.data[k] for k in sorted(state.data) if k != "done"}, indent=2))
    print("PREFLIGHT " + ("FAIL: " + "; ".join(failures) if failures else "OK"))
    return 1 if failures else 0


def run_rebuild(args: argparse.Namespace) -> int:
    state = State(args.state)
    if "horizon" not in state.data or state.data.get("preflight_failures"):
        print("refused: no clean --preflight recorded in the state file")
        return 2
    if state.data.get("aborted_at", "") > state.data.get("preflight_at", ""):
        print("refused: --abort rescheduled the compression job since the last preflight; rerun it")
        return 2
    if refusals := quiet_failures() + from_violations(
        args.start, state.data.get("raw_first", {}), args.timeframes
    ):
        print("refused: " + "; ".join(refusals))
        return 2
    horizon = state.horizon
    now = datetime.now(UTC)
    windows = chunk_windows(state.data["interval_s"], args.start, now)
    compress_before = now - timedelta(seconds=state.data["compression_job"][1])
    report = args.state.with_suffix(".jsonl")
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            params = read_raw_params(cur)
            cur.execute(_ANY_ROW_SQL)
            if cur.fetchone()[0] and not has_written(state.data):
                print(f"refused: {TABLE} is not empty and no window of this state was written")
                return 2
            if read_policy_digest(cur) != state.data.get("policy_digest"):
                print("refused: the live policy is not the one the preflight recorded; rerun it")
                return 2
            cur.execute(_SYMBOLS_SQL)
            # Python order: resume skips `symbol <= last` in this same order (a collation that
            # sorts punctuation differently would otherwise skip a name silently)
            symbols = sorted(r[0] for r in cur.fetchall())
        conn.commit()
        for window in windows:
            key = window[0].date().isoformat()
            start, end = session_bounds(window)
            for timeframe in args.timeframes:
                if state.done(timeframe, key):
                    continue
                if refusal := disk_headroom_refusal():
                    print(f"STOP before {timeframe} {key}: disk {refusal}")
                    return 2
                entry = state.inflight(f"{timeframe}|{key}")
                last, pending, totals = entry["last"], entry.get("pending"), entry["totals"]
                started = datetime.now(UTC)
                for symbol in symbols:
                    if last is not None and symbol <= last:
                        continue
                    result = select_and_write(
                        conn,
                        symbols=[symbol],
                        timeframe=timeframe,
                        start=start,
                        end=end,
                        policy_rows=None,
                        kind_order=params.kind_order,
                        batch_rows=params.write.batch_rows,
                        horizon=horizon,
                    )
                    if why := result_violation(result, symbol, pending):
                        conn.rollback()
                        print(f"STOP {timeframe} {key}: {why}; the target was not empty")
                        return 1
                    entry["pending"] = symbol
                    state.save()
                    conn.commit()
                    add_totals(totals, result)
                    entry["last"], entry["pending"] = symbol, None
                    state.save()
                line = {
                    "timeframe": timeframe,
                    "window": [w.isoformat() for w in window],
                    "horizon": horizon.isoformat(),
                    "seconds": (datetime.now(UTC) - started).total_seconds(),
                    **totals,
                }
                with report.open("a") as handle:
                    handle.write(json.dumps(line, sort_keys=True) + "\n")
                print(json.dumps(line, sort_keys=True), flush=True)
                state.finish(timeframe, key)
            # Compress as we go, as the policy would, once every timeframe of the run has filled
            # the window: a chunk compressed before a later timeframe writes into it would be
            # decompressed again (the bloat this path exists to avoid).
            if window[1] <= compress_before:
                with conn.cursor() as cur:
                    cur.execute(_COMPRESS_SQL, window)
                conn.commit()
    print(f"REBUILD done: {len(windows)} windows x {list(args.timeframes)}; report {report}")
    return 0


def run_abort(args: argparse.Namespace) -> int:
    """Reschedule the compression policy job the preflight unscheduled; the step every abort rule
    of the runbook names after a clean preflight. The job is the state's, or looked up when the
    state never recorded one; the rebuild's state and rows are left as they are (resume stays
    possible after a new preflight)."""
    state = State(args.state)
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        recorded = state.data.get("compression_job")
        if recorded is None:
            recorded, why = compression_job(cur)
            if why:
                print(f"ABORT FAIL: {why}")
                return 1
        job = recorded[0]
        cur.execute(_SCHEDULE_SQL, (job, True))
    state.data["aborted_at"] = datetime.now(UTC).isoformat()
    state.save()
    print(f"ABORT: compression job {job} rescheduled")
    return 0


def run_finish(args: argparse.Namespace) -> int:
    state = State(args.state)
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
        cur.execute(_SCHEDULE_SQL, (state.data["compression_job"][0], True))
        cur.execute("CALL run_job(%s)", (state.data["compression_job"][0],))
        cur.execute(f"ANALYZE {TABLE}")
        interval_s, misaligned, compression = read_layout(cur)
    drift = []
    if compression != state.data.get("compression"):
        drift.append(f"compression settings {compression} != {state.data.get('compression')}")
    if interval_s != state.data.get("interval_s") or misaligned:
        drift.append(f"chunk grid moved: interval {interval_s}, misaligned {misaligned[:5]}")
    print(f"compression job {state.data['compression_job'][0]} run; ANALYZE done")
    print("FINISH " + ("FAIL: " + "; ".join(drift) if drift else "OK"))
    return 1 if drift else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--rebuild", action="store_true")
    mode.add_argument("--finish", action="store_true")
    mode.add_argument(
        "--abort", action="store_true", help="reschedule the compression job (every abort path)"
    )
    parser.add_argument("--state", type=Path, required=True, help="the resume record (JSON)")
    parser.add_argument(
        "--horizon",
        type=datetime.fromisoformat,
        default=None,
        help="--preflight: the split horizon to pin (timezone-aware ISO); default now",
    )
    parser.add_argument("--reset", action="store_true", help="--preflight: re-pin the horizon")
    parser.add_argument(
        "--card", type=Path, default=None, help="--preflight: the before-card directory (B1)"
    )
    parser.add_argument(
        "--dispositions",
        type=Path,
        default=None,
        help="--preflight: JSON {'SYMBOL|1d|check': 'disposition'} for every red lineage verdict",
    )
    parser.add_argument("--timeframes", nargs="+", default=["5m", "1m"])
    parser.add_argument(
        "--from",
        dest="start",
        type=date.fromisoformat,
        default=None,
        help="--rebuild: the first date the windows cover (the timeframe's first raw bar)",
    )
    args = parser.parse_args(argv)
    if bad := sorted(set(args.timeframes) - DIRECT_TIMEFRAMES):
        parser.error(f"--timeframes {bad}: only the direct timeframes are selected here")
    if args.horizon is not None and args.horizon.tzinfo is None:
        parser.error("--horizon must be timezone-aware")
    if args.preflight:
        if args.card is None:
            parser.error("--preflight needs --card (the before-card and its 1d export)")
        return run_preflight(args)
    if args.rebuild:
        if args.start is None:
            parser.error("--rebuild needs --from")
        return run_rebuild(args)
    if args.abort:
        return run_abort(args)
    return run_finish(args)


if __name__ == "__main__":
    sys.exit(main())
