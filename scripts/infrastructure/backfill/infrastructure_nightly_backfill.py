#!/usr/bin/env python3
"""
infrastructure_nightly_backfill.py — nightly incremental OHLCV backfill

Ranks every compute-eligible instrument by staleness and delegates the whole list to
infrastructure_run_historical_pipeline.py in one nightly run. Gap detection stays
entirely in the delegate script (detect_gaps) -- this wrapper only ranks candidates
and dispatches; it never decides what data is actually missing.

Bug fixed 2026-09-16: this originally ranked candidates by 1h row count and hard-filtered
to `WHERE row_count < completeness_threshold` (150,000) -- a symbol's total row count only
grows, so any symbol that ever crossed that threshold became PERMANENTLY invisible to this
job, forever, no matter how stale its most recent bar got. Verified live that 168 of 273
active instruments -- the entire mature single-name/ETF book, everything ic_engine trains
on -- had silently stopped receiving any update the moment they individually crossed
150,000 1h rows, the bulk of them frozen since 2026-08-10 while the systemd service logged
`status=success` every single night (the ~20-40 still-incomplete symbols below the
threshold kept it busy and green). Fixed by ranking on the actual staleness signal
(MAX(timestamp) ascending) instead of a proxy (row count) with a hard cutoff.

Second bug fixed 2026-09-22 (todo 382): the 2026-09-16 fix above was necessary but not
sufficient -- it left a `LIMIT batch_size` (default 20) on *candidate selection* itself,
which throttles the wrong resource. `detect_gaps()` is a near-zero-cost no-op on any
symbol that's already current; the actual rate-limited resource is IBKR historical-fetch
volume (`_hist_limiter_for()` in `src/providers/ibkr.py`: a self-paced sliding window at
`infra.ibkr.rate_limit_max_requests`, or per timeframe where
`infra.ibkr.rate_limit_max_requests_by_tf` sets one), not "number of symbols examined per night." With 233 compute-eligible
symbols and batch_size=20, the design mathematically guaranteed a permanent ~12-day
(`ceil(233/20)`) staleness sawtooth once caught up, by construction, regardless of how many
more nights passed -- verified live 2026-09-18: 151/233 symbols (65%) frozen at the original
2026-08-10/12 freeze, 37+ days stale, `status=success` logged every night throughout. Fixed
by deleting the cap entirely: every compute-eligible symbol is dispatched every night,
staliest first, and `fetch_historical_bars()`'s own pre-emptive rate limiter is what
actually bounds how much gets done in one run -- it sleeps (never aborts) when approaching
the 55/10min ceiling, so a bad night with a real backlog naturally spends the budget on
fewer symbols before running long, and a normal night covers everyone because most symbols
cost ~0 real requests.

Concurrency, fixed 2026-09-28 (phase 185 plan 09, D-29): the old pgrep skip is gone.
Overlapping runs are serialized by the ibkr_history_stream lease instead: every leg runs
the delegate at `--lease-tier priority` with a wait bound from APR
(infra.ibkr_history_lease.nightly_wait_minutes), so a long bulk backfill can no longer
silently cost the daily bars a night -- the nightly waits, and a leg that waits past its
bound fails loudly: status failed_lease_timeout, an integrity fact
(nightly_lease_timeout), and a nonzero exit. Delegate exit code 3 (EXIT_LEASE_TIMEOUT in
infrastructure_run_historical_pipeline.py) is that signal.

Ranking heuristic note: _select_stalest's MAX(timestamp) is still a proxy, not the
delegate's own more accurate _reorder_contracts_by_gap() (which nets each symbol's shortfall
against its own proven-depth ceiling and can find gaps earlier in a symbol's history even
when its most recent bar is current). Reusing that logic directly was considered and
deliberately deferred -- it isn't currently exposed as an importable, gaps-returning
function, and refactoring it for reuse is out of scope for this change. Tracked as follow-up
in todo 274's spirit; file a dedicated todo before scaling this heuristic further. Harmless
in the meantime: whatever this picks, the delegate's detect_gaps() is the real correctness
check and no-ops instantly on anything already covered.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

import psycopg
import structlog

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (  # noqa: E402
    EXIT_LEASE_TIMEOUT,
    connect_db,
)
from scripts.ops.bars.ops_grid_lane_guard import write_exclude_file  # noqa: E402
from src.config.settings import Settings, dimension_where_clause  # noqa: E402
from src.core.integrity_monitor import emit_integrity_fact_sync  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402
from src.observability.otel import OTelInitError, init_otel_providers  # noqa: E402

_logger = structlog.get_logger(__name__)

_JOB = "nightly-backfill"
_NIGHTLY_CLIENT_ID = 45  # dedicated lane; ibkr.py auto-rotates on Error 326 collision
_DELEGATE_SCRIPT = (Path(__file__).parent / "infrastructure_run_historical_pipeline.py").resolve()
from scripts.infrastructure.backfill._derivation_stage import (  # noqa: E402
    run_derivation_stage,
)

# The lane guard's exclude file for the grid stage (symbols a running backfill
# lane is writing are not derived mid-lane). Recreated fresh each run.
_GRID_EXCLUDE_FILE = Path(tempfile.gettempdir()) / "indicagent-nightly-grid-exclude-symbols.txt"
_NIGHTLY_LEASE_WAIT_KEY = "infra.ibkr_history_lease.nightly_wait_minutes"
_NIGHTLY_LEASE_WAIT_FALLBACK_MINUTES = 60  # migration 380 APR seed


def _load_lease_wait_minutes(conn: psycopg.Connection) -> int:
    """How long a nightly leg may wait on the ibkr_history_stream lease before
    failing (D-29), from APR. The fallback is the migration 380 seed."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT config_value FROM config_state WHERE config_key = %s",
                (_NIGHTLY_LEASE_WAIT_KEY,),
            )
            row = cur.fetchone()
        if row and row[0] is not None:
            return int(float(row[0]))
    except Exception as error:
        _logger.warning("nightly_backfill.lease_wait_lookup_failed", error=str(error))
    return _NIGHTLY_LEASE_WAIT_FALLBACK_MINUTES


def _emit_lease_timeout_fact(leg_name: str, settings: Settings) -> None:
    """One integrity fact per lease-timed-out leg. Never raises (the helper it
    calls guards); a leg that waited its whole bound and still did not get the
    stream is exactly the silent-staleness failure this plan exists to end."""
    try:
        conn = connect_db(settings)
        try:
            emit_integrity_fact_sync(
                conn,
                "nightly_backfill",
                f"leg:{leg_name}",
                "nightly_lease_timeout",
                1.0,
                0.0,
                False,
                None,
            )
        finally:
            conn.close()
    except Exception as error:  # noqa: BLE001 - the fact is observability, never fatal
        _logger.warning("nightly_backfill.lease_timeout_fact_failed", error=str(error))


class _Leg(NamedTuple):
    """One nightly dispatch: a disjoint slice of the eligible universe and how to fetch it."""

    name: str
    where_clause: str  # predicate over `instruments i`, from dimension_where_clause()
    ranking_tf: str  # timeframe whose latest bar orders the leg, staliest first
    delegate_args: tuple[str, ...]  # extra args for the historical pipeline


# The legs partition every eligible symbol; each symbol is fetched by exactly one leg.
#
# compute: the governed compute universe at the full timeframe stack. Scoped to
#   compute_eligible, not bare is_active: is_active alone also sweeps up onboarded-but-
#   not-promoted symbols like Phase 174's D-09 pilot cohort, whose zero 1h rows would rank
#   them "staliest" and silently pull full-stack history for symbols kept 1d-only for
#   exactly that cost reason. Ranked on 1h, a cheap proxy for "how far along is this
#   symbol" (see module docstring).
# compute_1d_only: compute_eligible_1d symbols outside the compute universe, fetched at 1d
#   only. They are excluded from the first leg by design, so without this leg their series
#   silently stops while dimension="compute_1d" keeps returning them (174 review WR-02).
_LEGS: tuple[_Leg, ...] = (
    _Leg("compute", dimension_where_clause("compute", "i"), "1h", ()),
    _Leg(
        "compute_1d_only",
        f"{dimension_where_clause('compute_1d', 'i')} AND i.compute_eligible = false",
        "1d",
        ("--dimension", "compute_1d", "--timeframes", "1d"),
    ),
)


def _select_stalest(conn: psycopg.Connection, leg: _Leg) -> list[str]:
    """Return every symbol in `leg`, staliest `leg.ranking_tf` bar first.

    No count cap (todo 382, fixed 2026-09-22) -- every eligible symbol is a candidate
    every night, ranked by how old its most recent bar is (NULLs -- never backfilled at
    all -- sort first via the epoch fallback), and ALL of them are dispatched to the
    delegate in staleness order. See module docstring for the full incident writeup
    (both this bug and its 2026-09-16 predecessor). The latest bar is looked up per
    candidate symbol (LATERAL, index-driven), so a leg costs its own size, not a
    whole-table GROUP BY per leg; ordering verified identical to the GROUP BY form.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT i.symbol
            FROM instruments i
            LEFT JOIN LATERAL (
                SELECT MAX(m.timestamp) AS latest_bar
                FROM market_data_ohlcv m
                WHERE m.symbol = i.symbol AND m.timeframe = %s
            ) latest ON true
            WHERE {leg.where_clause}
            ORDER BY COALESCE(latest.latest_bar, '1970-01-01'::timestamptz) ASC, i.symbol ASC
            """,
            (leg.ranking_tf,),
        )
        return [row[0] for row in cur.fetchall()]


def _run_delegate(symbols: list[str], extra_args: tuple[str, ...]) -> int:
    """Run the historical pipeline for `symbols` on the nightly client lane; return its rc."""
    result = subprocess.run(
        [
            sys.executable,
            str(_DELEGATE_SCRIPT),
            "--symbols",
            ",".join(symbols),
            "--client-id",
            str(_NIGHTLY_CLIENT_ID),
            *extra_args,
        ],
        cwd=str(project_root),
        env={**os.environ, "PYTHONPATH": str(project_root)},
    )
    return result.returncode


def _prepare_grid_stage() -> Path:
    """Write the lane guard's exclude file for the grid stage; raise RuntimeError
    when a grid-timeframe lane runs without --symbols (the stage must not start
    scoped only by hope)."""
    write_exclude_file(_GRID_EXCLUDE_FILE)
    return _GRID_EXCLUDE_FILE


def _run_derivation_stage(stage: str, *extra_args: str) -> int:
    """Run bar_derivation's `stage` with --changed-only --apply (shared runner,
    _derivation_stage.py holds the cwd/PYTHONPATH convention once)."""
    return run_derivation_stage(stage, "--changed-only", "--apply", *extra_args)


def _run_daily_stage() -> int:
    """Derive the 1d grid rows for every symbol whose inputs changed (plan
    185-18 task 1b).

    The legs' 1d fetches capture into D1 and store no bar, so the nightly
    derives the daily grid itself. Serialized before the grid stage so the
    two derivation writers never overlap (the grid stage reads only 5m
    inputs; the order is convention, not a data dependency). --changed-only
    means a clean night costs a change probe per symbol. No lane guard
    file: the derivation owns its own changed-set scoping.
    """
    return _run_derivation_stage("daily")


def _run_grid_stage(exclude_file: Path) -> int:
    """Derive the 15m/1h grid for every symbol whose 5m changed (plan 12).

    The legs fetch 1h/15m into ohlcv_intraday_raw_archive now, so symbols whose
    5m arrived late (todo 449) get their derived rows from this stage, with the
    lane guard's file keeping running lanes' symbols out. --changed-only means
    a clean night costs a digest comparison per symbol, not a rewrite.
    """
    return _run_derivation_stage("grid", "--exclude-symbols-file", str(exclude_file))


def _finish(status: str, message: str, returncode: int = 0) -> int:
    """Log, print, emit job_completed_total, flush OTel, and return the process exit code."""
    if status == "success":
        _logger.info(f"nightly_backfill.{status}")
    else:
        _logger.error(f"nightly_backfill.{status}")
    print(message)
    JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
    flush_and_shutdown_metrics()
    return returncode


def main() -> int:
    setup_service_logging("logs/infrastructure_nightly_backfill.log")
    settings = Settings()

    conn = connect_db(settings)
    try:
        batches = [(leg, _select_stalest(conn, leg)) for leg in _LEGS]
        lease_wait_minutes = _load_lease_wait_minutes(conn)
    finally:
        conn.close()

    if not any(symbols for _leg, symbols in batches):
        return _finish(
            "nothing_to_do",
            "No active instruments found -- nothing to do tonight.",
        )

    # D-29: legs take the ibkr_history_stream lease at priority tier and wait on
    # it (bounded by APR) instead of the nightly skipping when a backfill runs.
    lease_args = ("--lease-tier", "priority", "--lease-wait-minutes", str(lease_wait_minutes))

    returncodes: list[int] = []
    lease_timeout_legs: list[str] = []
    for leg, symbols in batches:
        if not symbols:
            continue
        print(f"Nightly backfill ({leg.name}): {len(symbols)} symbols -- {', '.join(symbols)}")
        _logger.info(
            "nightly_backfill.batch_selected", leg=leg.name, symbols=symbols, n_symbols=len(symbols)
        )
        returncode = _run_delegate(symbols, leg.delegate_args + lease_args)
        returncodes.append(returncode)
        if returncode == EXIT_LEASE_TIMEOUT:
            lease_timeout_legs.append(leg.name)
            _emit_lease_timeout_fact(leg.name, settings)

    # Plan 185-18 task 1b: the legs' 1d answers landed in D1; the daily stage
    # derives the 1d grid for every symbol whose inputs changed. Runs before
    # the grid stage, same no-skip reasoning: derived rows are exactly what a
    # shortened fetch night still needs.
    returncodes.append(_run_daily_stage())

    # Plan 12: the legs' 1h/15m landed in the archive as raw observations; the
    # grid stage derives 15m/1h from 5m for every symbol whose inputs changed.
    # No skip path: it also runs after a leg that ended failed_lease_timeout
    # (derived rows are exactly what a shortened fetch night still needs).
    try:
        exclude_file = _prepare_grid_stage()
    except RuntimeError as error:
        return _finish("failed", f"Grid stage not started: {error}", returncode=1)
    returncodes.append(_run_grid_stage(exclude_file))
    exclude_file.unlink(missing_ok=True)

    returncode = next((rc for rc in returncodes if rc != 0), 0)
    if lease_timeout_legs:
        status = "failed_lease_timeout"
    else:
        status = "success" if returncode == 0 else "failed"
    message = f"Nightly backfill delegate(s) finished: returncodes={returncodes}"
    if lease_timeout_legs:
        message += f" (lease timeout in leg(s): {', '.join(lease_timeout_legs)})"
    return _finish(
        status,
        message,
        returncode=returncode,
    )


if __name__ == "__main__":
    try:
        init_otel_providers(_JOB)
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    sys.exit(main())
