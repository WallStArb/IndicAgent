"""D-27 step 2: re-ask the 1d heads of late-starting names and inventory the moved ones.

A late name is a 1d name whose first ibkr_named bar falls after 2006-11-01. The
pipeline re-asks the old window under verify-only (SMART, then every venue in
infra.ibkr.venue_fallback.exchanges) and every answer lands in ohlcv_request /
ohlcv_observation (D-16). This script only orchestrates and classifies from those
stored answers; it never stores venue bars (D-17, plan 13 verdict).

Each late name ends with one disposition, from D1 alone (D-20):
  moved                 venue bars exist before the name's SMART head
  verified_empty        SMART and every expected venue other than the name's primary
                        answered no_data for the oldest window
  reached_window_start  the SMART head is at or before the oldest request window start
  unresolved            anything else (timeout, failure, a venue not asked); never counted as empty

Discipline: campaign preflight on client id 49 (D-30); the pipeline subprocess holds the
ibkr_history_stream lease at priority tier (D-29). Refusal or a lease timeout exits
cleanly; reruns skip names D1 already resolves (unless --force).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import psycopg
import structlog

from scripts.ops.bars._campaign import CampaignRefused, preflight
from src.config.settings import Settings
from src.core.integrity_monitor import emit_integrity_fact_sync
from src.providers.base import VENUE_ROUTE_ALIASES

_logger = structlog.get_logger(__name__)

Disposition = Literal["moved", "verified_empty", "unresolved", "reached_window_start"]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PIPELINE = (
    _REPO_ROOT
    / "scripts"
    / "infrastructure"
    / "backfill"
    / ("infrastructure_run_historical_pipeline.py")
)
_CLIENT_ID = 49
_LEASE_TIMEOUT_EXIT = 3
_REFUSED_EXIT = 3
_LATE_CUTOFF = "2006-11-01"
_MONITOR_TYPE = "bar_head_rerun"
_APR_CLIENT_IDS = "infra.bar_campaign.client_ids"
_APR_VENUES = "infra.ibkr.venue_fallback.exchanges"
_SMART = "SMART"
# Only IBKR answers judge an IBKR head (185-28): a Tradier answer (route TRADIER, source
# tradier) is a different vendor's consolidated history, not a former IBKR listing venue.
_IBKR_SOURCE = "ibkr"
_CLEAN_OUTCOMES = {"bars", "no_data"}
_RUN_ID_RE = re.compile(r"fetch_run_id:\s*([0-9a-f-]{36})")


@dataclass(frozen=True)
class HeadRequest:
    route: str
    outcome: str
    window_start: date | None
    window_end: date
    first_bar: date | None
    answered_at: datetime
    primary_exchange: str | None = None


# --- pure pieces -----------------------------------------------------------------


def _latest_per_route(requests: Sequence[HeadRequest]) -> dict[str, HeadRequest]:
    """Latest answer per route; on an exact tie an unclean outcome wins (fail closed)."""
    best: dict[str, HeadRequest] = {}
    for req in requests:
        current = best.get(req.route)
        key = (req.answered_at, req.outcome not in _CLEAN_OUTCOMES)
        if current is None or key > (current.answered_at, current.outcome not in _CLEAN_OUTCOMES):
            best[req.route] = req
    return best


def classify_head(
    requests: Sequence[HeadRequest],
    smart_head: date | None,
    expected_venues: Sequence[str],
) -> Disposition:
    """Disposition of one late name from its stored TRADES requests (D-20)."""
    if not requests:
        return "unresolved"
    venue_bars = [
        r
        for r in requests
        if r.route != _SMART
        and r.outcome == "bars"
        and r.first_bar is not None
        and (smart_head is None or r.first_bar < smart_head)
    ]
    if venue_bars:
        return "moved"
    smart = [r for r in requests if r.route == _SMART]
    starts = [r.window_start for r in smart if r.window_start is not None]
    if smart_head is not None and starts and smart_head <= min(starts):
        return "reached_window_start"
    if not smart or not starts:
        return "unresolved"
    oldest_start = min(starts)
    oldest_end = min(r.window_end for r in smart if r.window_start == oldest_start)
    overlapping = [
        r
        for r in requests
        if (r.window_start is None or r.window_start <= oldest_end) and r.window_end >= oldest_start
    ]
    latest = _latest_per_route(overlapping)
    # The provider never asks the current primary venue (SMART routes there), and the
    # empty-history reconcile does not require it either (185-28): judge by the primary
    # recorded on the latest SMART answer for the oldest window.
    smart_latest = latest.get(_SMART)
    primary = smart_latest.primary_exchange if smart_latest is not None else None
    needed = (_SMART, *(v for v in expected_venues if VENUE_ROUTE_ALIASES.get(v, v) != primary))
    if all(route in latest and latest[route].outcome == "no_data" for route in needed):
        return "verified_empty"
    return "unresolved"


def pending_symbols(
    late: Sequence[str], dispositions: Mapping[str, Disposition], *, force: bool
) -> list[str]:
    """Names still to ask: everything under --force, else those D1 does not resolve."""
    if force:
        return list(late)
    return [s for s in late if dispositions.get(s, "unresolved") == "unresolved"]


def run_with_refusal(check: Callable[[], None]) -> None:
    """Run the preflight; a refusal prints and exits non-zero rather than proceeding."""
    try:
        check()
    except CampaignRefused as error:
        print(f"REFUSED: {error}")
        sys.exit(_REFUSED_EXIT)


# --- D1 reads --------------------------------------------------------------------


def _late_names(conn: Any) -> dict[str, date]:
    """Late 1d names mapped to their SMART head (first ibkr_named 1d bar)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.symbol, MIN(m."timestamp")::date
            FROM market_data_ohlcv_tradeable m
            JOIN instruments i USING (symbol)
            WHERE m.timeframe = '1d' AND m.source = 'ibkr_named'
              AND i.compute_eligible_1d = true
            GROUP BY m.symbol
            HAVING MIN(m."timestamp") > %s
            ORDER BY m.symbol
            """,
            (_LATE_CUTOFF,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def _load_requests(conn: Any, symbols: Sequence[str]) -> dict[str, list[HeadRequest]]:
    out: dict[str, list[HeadRequest]] = {s: [] for s in symbols}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.symbol, r.route, r.outcome, r.window_start, r.window_end,
                   (SELECT MIN(o.bar_date) FROM ohlcv_observation o
                     WHERE o.request_id = r.request_id),
                   r.answered_at, r.source, r.primary_exchange
            FROM ohlcv_request r
            WHERE r.timeframe = '1d' AND r.what_to_show = 'TRADES'
              AND r.symbol = ANY(%s) AND r.outcome <> 'legacy_import'
              AND r.route <> 'LEGACY_IMPORT'
            """,
            (list(symbols),),
        )
        for sym, route, outcome, ws, we, first_bar, answered, source, primary in cur.fetchall():
            if source != _IBKR_SOURCE or route == "TRADIER":
                continue
            out[sym].append(
                HeadRequest(
                    route=route,
                    outcome=outcome,
                    window_start=ws.astimezone(UTC).date() if ws else None,
                    window_end=we.astimezone(UTC).date(),
                    first_bar=first_bar,
                    answered_at=answered,
                    primary_exchange=primary,
                )
            )
    return out


def _load_apr(conn: Any) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
            ([_APR_CLIENT_IDS, _APR_VENUES],),
        )
        return {k: v for k, v in cur.fetchall()}


def _classify_all(
    conn: Any, late: Mapping[str, date], venues: Sequence[str]
) -> dict[str, Disposition]:
    requests = _load_requests(conn, list(late))
    return {s: classify_head(requests[s], late[s], venues) for s in late}


# --- pipeline --------------------------------------------------------------------


def _run_chunk(symbols: Sequence[str]) -> tuple[int, list[str]]:
    """One pipeline invocation; returns (exit code, fetch_run_ids seen)."""
    proc = subprocess.Popen(
        [
            sys.executable,
            str(_PIPELINE),
            "--symbols",
            ",".join(symbols),
            "--timeframes",
            "1d",
            "--dimension",
            "compute_1d",
            "--client-id",
            str(_CLIENT_ID),
            "--lease-tier",
            "priority",
        ],
        cwd=_REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    run_ids: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
        match = _RUN_ID_RE.search(line)
        if match:
            run_ids.append(match.group(1))
    return proc.wait(), run_ids


# --- report ----------------------------------------------------------------------


def _moved_detail(conn: Any, moved: Sequence[str]) -> dict[str, list[tuple[str, date, date]]]:
    detail: dict[str, list[tuple[str, date, date]]] = {s: [] for s in moved}
    if not moved:
        return detail
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, route, MIN(bar_date), MAX(bar_date)
            FROM ohlcv_observation
            WHERE symbol = ANY(%s) AND timeframe = '1d' AND what_to_show = 'TRADES'
              AND source = 'ibkr' AND route NOT IN ('SMART', 'LEGACY_IMPORT', 'TRADIER')
            GROUP BY symbol, route ORDER BY symbol, route
            """,
            (list(moved),),
        )
        for sym, route, first, last in cur.fetchall():
            detail[sym].append((route, first, last))
    return detail


def _outcome_counts(conn: Any, run_ids: Sequence[str]) -> dict[str, Counter[str]]:
    """Request outcome counts, and the failed-request error codes, over the run ids."""
    counts: dict[str, Counter[str]] = {"outcome": Counter(), "failed": Counter()}
    if not run_ids:
        return counts
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT outcome, COALESCE(error_code::text, '-'), COUNT(*)
            FROM ohlcv_request WHERE fetch_run_id = ANY(%s::uuid[])
            GROUP BY 1, 2
            """,
            (list(run_ids),),
        )
        for outcome, code, n in cur.fetchall():
            counts["outcome"][outcome] += n
            if outcome in ("failed", "timeout"):
                counts["failed"][f"{outcome} (error {code})"] += n
    return counts


def render_report(
    dispositions: Mapping[str, Disposition],
    late: Mapping[str, date],
    moved_detail: Mapping[str, Sequence[tuple[str, date, date]]],
    run_ids: Sequence[str],
    counts: Mapping[str, Counter[str]],
    pre_move_view_count: int,
    today: date,
) -> str:
    tally = Counter(dispositions.values())
    lines = [
        "# Moved-name inventory",
        "",
        "Author: phase 185 plan 14 (ops_head_rerun.py)",
        "Informed by: D1 ohlcv_request / ohlcv_observation (D-16), D-20, D-27 step 2, "
        "plan 13 verdict (venue bars stay stored and unused)",
        "",
        f"Generated {today.isoformat()}. Late names are 1d names whose first ibkr_named bar "
        f"falls after {_LATE_CUTOFF}: {len(late)} counted at run time. Dispositions come "
        "from stored D1 answers only; unresolved is never counted as empty.",
        "",
        "## Counts",
        "",
        "| Disposition | Names |",
        "| --- | --- |",
    ]
    for name in ("moved", "verified_empty", "reached_window_start", "unresolved"):
        lines.append(f"| {name} | {tally.get(name, 0)} |")
    lines += [
        f"| total | {len(dispositions)} |",
        "",
        f"Distinct symbols with pre_move in ohlcv_venue_head among late names: "
        f"{pre_move_view_count} (moved count above: {tally.get('moved', 0)}).",
        "",
        "## Requests of this run",
        "",
        "Fetch run ids: " + (", ".join(run_ids) if run_ids else "none this invocation"),
        "",
        "| Outcome | Requests |",
        "| --- | --- |",
    ]
    for outcome, n in sorted(counts["outcome"].items()):
        lines.append(f"| {outcome} | {n} |")
    lines += ["", "Failed-request outcomes seen: "]
    lines[-1] += (
        ", ".join(f"{k}: {n}" for k, n in sorted(counts["failed"].items()))
        if counts["failed"]
        else "none"
    )
    lines += [
        "",
        "## Every late name",
        "",
        "| Symbol | SMART head | Disposition | Venue spans (first to last venue bar) |",
        "| --- | --- | --- | --- |",
    ]
    for sym in sorted(dispositions):
        spans = "; ".join(f"{v} {a} to {b}" for v, a, b in moved_detail.get(sym, ()))
        lines.append(f"| {sym} | {late[sym]} | {dispositions[sym]} | {spans} |")
    return "\n".join(lines) + "\n"


def _emit_facts(settings: Settings, tally: Mapping[str, int], total: int) -> None:
    """One integrity_monitor fact per disposition count, on a fresh connection."""
    now = datetime.now(UTC)
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        for name in ("moved", "verified_empty", "reached_window_start", "unresolved"):
            emit_integrity_fact_sync(
                conn,
                _MONITOR_TYPE,
                None,
                f"late_names_{name}",
                float(tally.get(name, 0)),
                float(total),
                name != "unresolved" or tally.get(name, 0) == 0,
                now,
                commit=False,
            )


# --- main ------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--report", type=Path, default=None, help="write the markdown report here")
    parser.add_argument("--force", action="store_true", help="re-ask names D1 already resolves")
    parser.add_argument("--chunk-size", type=int, default=25, help="symbols per pipeline call")
    parser.add_argument("--report-only", action="store_true", help="classify and report, no fetch")
    parser.add_argument(
        "--run-id", action="append", default=[], help="fetch_run_id to include in the report"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = Settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        apr = _load_apr(conn)
        late = _late_names(conn)
        venues = json.loads(apr.get(_APR_VENUES, "[]"))
        before = _classify_all(conn, late, venues)
    print(f"late names: {len(late)}; venues: {venues}")
    print(f"already resolved in D1: {sum(d != 'unresolved' for d in before.values())}")

    run_ids: list[str] = list(args.run_id)
    todo: list[str] = []
    if not args.report_only:
        run_with_refusal(lambda: preflight(client_id=_CLIENT_ID, apr=apr))
        todo = pending_symbols(list(late), before, force=args.force)
        print(f"to ask: {len(todo)}")

    exit_code = 0
    for i in range(0, len(todo), args.chunk_size):
        chunk = todo[i : i + args.chunk_size]
        print(f"--- chunk {i // args.chunk_size + 1}: {len(chunk)} names ---")
        rc, ids = _run_chunk(chunk)
        run_ids.extend(ids)
        if rc == _LEASE_TIMEOUT_EXIT:
            print("lease timeout: stopping cleanly; rerun resumes (resolved names skipped)")
            exit_code = _LEASE_TIMEOUT_EXIT
            break
        if rc != 0:
            print(f"pipeline exited {rc}: stopping; rerun resumes")
            exit_code = rc
            break

    # Fresh connection: the fetch can outlast the server's idle-session timeout.
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        after = _classify_all(conn, late, venues)
        moved = sorted(s for s, d in after.items() if d == "moved")
        detail = _moved_detail(conn, moved)
        counts = _outcome_counts(conn, run_ids)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT symbol) FROM ohlcv_venue_head "
                "WHERE pre_move AND symbol = ANY(%s)",
                (list(late),),
            )
            pre_move = int(cur.fetchone()[0])
    tally = Counter(after.values())
    print("dispositions:", dict(tally))
    report = render_report(after, late, detail, run_ids, counts, pre_move, datetime.now(UTC).date())
    if args.report is not None:
        args.report.write_text(report)
        print(f"report written: {args.report}")
    if not args.report_only and exit_code == 0:
        _emit_facts(settings, tally, len(after))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
