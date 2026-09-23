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
volume (`_hist_rate_limiter` in `src/providers/ibkr.py`, a hard 55 req/10min self-paced
sliding window), not "number of symbols examined per night." With 233 compute-eligible
symbols and batch_size=20, the design mathematically guaranteed a permanent ~12-day
(`ceil(233/20)`) staleness sawtooth once caught up, by construction, regardless of how many
more nights passed -- verified live 2026-09-18: 151/233 symbols (65%) frozen at the original
2026-08-10/12 freeze, 37+ days stale, `status=success` logged every night throughout. Fixed
by deleting the cap entirely: every compute-eligible symbol is dispatched every night,
staliest first, and `fetch_historical_bars()`'s own pre-emptive rate limiter is what
actually bounds how much gets done in one run -- it sleeps (never aborts) when approaching
the 55/10min ceiling, so a bad night with a real backlog naturally spends the budget on
fewer symbols before running long, and a normal night covers everyone because most symbols
cost ~0 real requests. `_is_another_backfill_running()` below already guards against
overlapping runs regardless of how long any single night's run takes.

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
from pathlib import Path
from typing import NamedTuple

import psycopg
import structlog

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (  # noqa: E402
    connect_db,
)
from src.config.settings import Settings, dimension_where_clause  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402
from src.observability.otel import OTelInitError, init_otel_providers  # noqa: E402

_logger = structlog.get_logger(__name__)

_JOB = "nightly-backfill"
_NIGHTLY_CLIENT_ID = 45  # dedicated lane; ibkr.py auto-rotates on Error 326 collision
_DELEGATE_SCRIPT = (Path(__file__).parent / "infrastructure_run_historical_pipeline.py").resolve()


def _is_another_backfill_running() -> bool:
    """True if any infrastructure_run_historical_pipeline.py process is already active.

    Avoids two backfill processes contending for the same IBKR rate-limit budget and
    potentially double-fetching the same symbols -- a real risk this session already
    hit once with an unrelated one-off sprint still in flight.
    """
    result = subprocess.run(
        ["pgrep", "-f", _DELEGATE_SCRIPT.name],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


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


def _finish(status: str, message: str, returncode: int = 0) -> int:
    """Log, print, emit job_completed_total, flush OTel, and return the process exit code."""
    _logger.info(f"nightly_backfill.{status}")
    print(message)
    JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
    flush_and_shutdown_metrics()
    return returncode


def main() -> int:
    setup_service_logging("logs/infrastructure_nightly_backfill.log")
    settings = Settings()

    if _is_another_backfill_running():
        return _finish(
            "skipped_concurrent_run",
            "Another historical-backfill process is already running -- skipping tonight.",
        )

    conn = connect_db(settings)
    try:
        batches = [(leg, _select_stalest(conn, leg)) for leg in _LEGS]
    finally:
        conn.close()

    if not any(symbols for _leg, symbols in batches):
        return _finish(
            "nothing_to_do",
            "No active instruments found -- nothing to do tonight.",
        )

    returncodes: list[int] = []
    for leg, symbols in batches:
        if not symbols:
            continue
        print(f"Nightly backfill ({leg.name}): {len(symbols)} symbols -- {', '.join(symbols)}")
        _logger.info(
            "nightly_backfill.batch_selected", leg=leg.name, symbols=symbols, n_symbols=len(symbols)
        )
        returncodes.append(_run_delegate(symbols, leg.delegate_args))

    returncode = next((rc for rc in returncodes if rc != 0), 0)
    status = "success" if returncode == 0 else "failed"
    return _finish(
        status,
        f"Nightly backfill delegate(s) finished: returncodes={returncodes}",
        returncode=returncode,
    )


if __name__ == "__main__":
    try:
        init_otel_providers(_JOB)
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    sys.exit(main())
