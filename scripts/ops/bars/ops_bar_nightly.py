"""Nightly bar capture leaf (todo 521 T4): vendor-native, scratch-free, one engine.

For every active instrument, pulls the recent tail straight from the vendor's
HistoryProvider leaf and writes it through the load engine -- no scratch, no
campaign: request rows land via the D1 sink, 5m is offered to ohlcv_raw
(``load_series``; selection decides canonical), and 1d is raw capture only
(``load_frame`` without coverage; the engine's writer fence refuses a 1d
policy, so a vendor daily can never author -- IBKR owns 1d).

The vendor is a CLI choice dispatched through the ``history_leaf`` factory and
the HistoryProvider protocol; a new capture vendor is one leaf plus one registry
entry, nothing here changes. Dry run is the default: without --apply this plans
and prints, writing nothing -- but the leaf still runs against the vendor API,
so a dry run costs vendor requests by design: the nightly's real work is the
ask.

Complete bars only (second review of 191-07, finding 5): every page the leaf answers is split by
the vendor-agnostic rule (src/intelligence/bars/complete_bars.py) against the time the window was
asked (a lower bound on the answer) and the window's end. A bar still forming, or a session's
closing bar answered before the settle delay, is not offered to raw; its values go onto the
window's last request row (ohlcv_request.partial_bars) and the next night asks it again.

Known v1 shape: request rows flush per symbol from the sink (not the per-chunk
atomic persist the fetcher uses), so a crash between bars and requests can
leave a request whose bars a rerun re-asks; coverage is the truth, so resume
tolerates it. Tightening to the atomic helper is the follow-up when the
nightly joins the unified fetcher's loop.

Frozen-out by the 2026-10-10 pull hold: nothing schedules this until the owner
reopens capture; the script exists so the reopen is a systemctl line, not a
build.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

import pandas as pd
import psycopg

from services.bar_load import LoadPolicy, load_frame, load_series, load_status
from services.complete_bar_gate import keep_complete, read_settle
from services.ohlcv_ingress_contract import read_raw_params
from services.ohlcv_request_writer import RequestSink, new_fetch_run_id
from src.config.settings import get_active_contracts, get_settings
from src.providers import history_leaf
from src.providers.base import FetchBudget, HistoryRequest

CALLER_SINK = "{vendor}-nightly"
CALLER_5M = "{vendor}-nightly-5m"
CALLER_1D = "{vendor}-nightly-1d-raw"


def _apr_int(conn, key: str, default: int) -> int:
    """One sync APR read for the leaf's window knobs (config_state is the store)."""
    with conn.cursor() as cur:
        cur.execute("SELECT config_value FROM config_state WHERE config_key = %s", (key,))
        row = cur.fetchone()
    return int(row[0]) if row else default


def _bars_frame(bars) -> pd.DataFrame:
    """Provider bars -> the engine's canonical frame (t, o, h, l, c, v)."""
    return pd.DataFrame(
        {
            "t": [b.timestamp for b in bars],
            "o": [b.open for b in bars],
            "h": [b.high for b in bars],
            "l": [b.low for b in bars],
            "c": [b.close for b in bars],
            "v": [b.volume for b in bars],
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", default="alpaca", help="capture vendor (default alpaca)")
    parser.add_argument("--days", type=int, default=None, help="window; default the APR key")
    parser.add_argument("--symbols", nargs="*", help="subset; default every active instrument")
    parser.add_argument("--apply", action="store_true", help="write; default plans and prints")
    args = parser.parse_args()

    settings = get_settings()
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        window_days = args.days or _apr_int(conn, "infra.alpaca.nightly_window_days", 5)
        end = datetime.now(UTC)
        start = end - timedelta(days=window_days)
        with conn.cursor() as cur:
            params = read_raw_params(cur)
            settle = read_settle(cur)
        universe = args.symbols or [
            instrument.symbol for instrument in get_active_contracts(settings, dimension="backfill")
        ]
        sink = _NightlySink(
            RequestSink(conn, caller=CALLER_SINK.format(vendor=args.vendor), source=args.vendor)
        )
        policy_5m = LoadPolicy(
            vendor=args.vendor,
            timeframe="5m",
            caller=CALLER_5M.format(vendor=args.vendor),
        )
        leaf = history_leaf(
            args.vendor,
            settings,
            rate_limit_max_requests=_apr_int(conn, "infra.alpaca.rate_limit_max_requests", 190),
            on_request=sink.on_request,
            fetch_run_id=new_fetch_run_id(),
        )
        summary = asyncio.run(
            _run(leaf, conn, sink, policy_5m, params, settle, universe, start, end, args.apply)
        )
    finally:
        conn.close()

    print(summary_line(summary, apply=args.apply))
    return exit_code(summary)


class _NightlySink:
    """The request sink plus the id of the last request the leaf reported, so a window's held
    back partial bars land on the request that answered its newest page."""

    def __init__(self, sink: RequestSink) -> None:
        self._sink = sink
        self.last_request_id: str | None = None
        self.last_answered_at: datetime | None = None

    def on_request(self, record) -> None:
        self._sink.on_request(record)
        self.last_request_id = record.request_id
        self.last_answered_at = record.answered_at

    def note_partial(self, partial_text: str) -> None:
        if self.last_request_id is None:
            raise RuntimeError("partial bars with no request row to record them on")
        self._sink.note_partial(self.last_request_id, partial_text)

    def flush(self) -> int:
        return self._sink.flush()


def summary_line(summary: dict, *, apply: bool) -> str:
    status = load_status(
        apply=apply,
        unselected=summary["unselected"],
        basis_flagged=summary.get("basis_flagged", 0),
    )
    return (
        f"{status}: "
        f"{summary['authored']} 5m rows offered to raw, {summary['raw_1d']} 1d rows offered to "
        f"raw, {summary['errors']} errors, {summary['flagged']} restatement-flagged series "
        f"({summary.get('basis_flagged', 0)} basis-change), "
        f"{summary.get('superseded', 0)} offers superseded by a newer serve, "
        f"{summary['unselected']} unselected slots, "
        f"{summary.get('partial', 0)} incomplete bars held back"
    )


def exit_code(summary: dict) -> int:
    """Non-zero for an error, an unselected slot (rows that landed in raw with no canonical
    winner are not a clean night) or a basis-change restatement flag (the write landed, D-191-N,
    but the night is partial until the flag is reviewed; fourth review of 191-07, finding 2). A
    share-only flag is reported, never a failure."""
    return 1 if summary["errors"] or summary["unselected"] or summary.get("basis_flagged") else 0


async def _run(
    leaf, conn, sink, policy_5m, params, settle, universe, start, end, write: bool
) -> dict:
    budget = FetchBudget(deadline=datetime.now(UTC) + timedelta(minutes=30), max_requests=500)
    await leaf.connect()
    summary = {
        "authored": 0,
        "raw_1d": 0,
        "errors": 0,
        "flagged": 0,
        "basis_flagged": 0,
        "superseded": 0,
        "unselected": 0,
        "partial": 0,
    }
    try:
        for symbol in universe:
            try:
                for timeframe, load_canonical in (("5m", True), ("1d", False)):
                    asked_at = datetime.now(UTC)
                    sink.last_answered_at = None
                    page = await leaf.fetch_ohlcv(
                        HistoryRequest(
                            symbol=symbol,
                            timeframe=timeframe,
                            start=start,
                            end=end,
                            adjustment="split",
                            rth_only=load_canonical,
                        ),
                        budget,
                    )
                    # served_at: the leaf's answer time for this window (its last request),
                    # else the time the page came back; never the write time
                    answered_at = sink.last_answered_at or datetime.now(UTC)
                    complete, partial, partial_text = keep_complete(
                        page.bars,
                        timeframe,
                        answered_at=asked_at,
                        request_end=end,
                        settle=settle,
                        symbol=symbol,
                        caller=policy_5m.caller,
                    )
                    if partial_text is not None:
                        sink.note_partial(partial_text)
                        summary["partial"] += len(partial)
                    frame = _bars_frame(complete)
                    if load_canonical:
                        result = load_series(
                            conn,
                            policy_5m,
                            symbol,
                            frame,
                            params=params,
                            write=write,
                            answered_at=answered_at,
                        )
                        summary["authored"] += result.n_offered
                        summary["flagged"] += result.n_flagged_series
                        summary["basis_flagged"] += result.n_basis_flagged
                        summary["superseded"] += result.n_superseded
                        summary["unselected"] += result.n_unselected
                    elif write and len(frame):
                        result = load_frame(
                            conn,
                            symbol,
                            frame,
                            vendor=policy_5m.vendor,
                            timeframe="1d",
                            caller=CALLER_1D.format(vendor=policy_5m.vendor),
                            write=True,
                            answered_at=answered_at,
                            coverage=False,
                            params=params,
                        )
                        summary["raw_1d"] += result.n_offered
                        summary["flagged"] += result.n_flagged_series
                        summary["basis_flagged"] += result.n_basis_flagged
                        summary["superseded"] += result.n_superseded
            except Exception as error:  # noqa: BLE001 - one name fails, the night continues
                summary["errors"] += 1
                print(f"{symbol}: ERROR {type(error).__name__}: {error}", flush=True)
            sink.flush()
    finally:
        await leaf.close()
    return summary


if __name__ == "__main__":
    sys.exit(main())
