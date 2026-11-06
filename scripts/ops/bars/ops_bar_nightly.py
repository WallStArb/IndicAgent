"""Nightly bar capture leaf (todo 521 T4): vendor-native, scratch-free, one engine.

For every active instrument, pulls the recent tail straight from the vendor's
HistoryProvider leaf and writes it through the load engine -- no scratch, no
campaign: each page's request row lands with its bars, 5m is offered to ohlcv_raw
(``load_series``; selection decides canonical), and 1d is raw capture only
(``load_frame``, which recomputes the vendor's 1d ledger bounds from raw; the
engine's writer fence refuses a 1d policy, so the nightly never authors a
daily). The ledger fetch status follows the request rows
(``_NightlySink.flush``).

The vendor is a CLI choice dispatched through the ``history_leaf`` factory and
the HistoryProvider protocol; a new capture vendor is one leaf plus one registry
entry, nothing here changes. For alpaca the tail is asked on the APR feed
(``infra.alpaca.data_feed``, sip since migration 513) and its rows carry that
feed's raw kind; a sip window ends ``infra.alpaca.sip_recent_lag_minutes``
before now because the free plan 403s a window reaching recent SIP data. Dry
run is the default: without --apply this plans
and prints, writing nothing -- but the leaf still runs against the vendor API,
so a dry run costs vendor requests by design: the nightly's real work is the
ask.

Complete bars only (second review of 191-07, finding 5): every page the leaf answers is split by
the vendor-agnostic rule (src/intelligence/bars/complete_bars.py) against the time the window was
asked (a lower bound on the answer) and the window's end. A bar still forming, or a session's
closing bar answered before the settle delay, is not offered to raw; its values go onto that
page's request row (ohlcv_request.partial_bars) and the next night asks it again.

Truthful ledger (todo 596, migration 581): each (symbol, timeframe) window is one ask. Every
answered page commits its request row (ask id, page index, terminal) in the same transaction as
that page's bars, a failed page's row is written after the symbol, and a dry run writes no
ledger row at all. A window the budget stopped before its terminal page is an incomplete ask
and fails the night (`unfinished`).

Frozen-out by the 2026-10-10 pull hold: nothing schedules this until the owner
reopens capture; the script exists so the reopen is a systemctl line, not a
build.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

import pandas as pd
import psycopg

from services.bar_load import LoadPolicy, LoadResult, load_frame, load_series, load_status
from services.complete_bar_gate import keep_complete, read_settle
from services.ohlcv_coverage_writer import fetch_status_for_outcome, record_fetch_outcome
from services.ohlcv_ingress_contract import read_raw_params
from services.ohlcv_request_writer import RequestSink, new_fetch_run_id
from src.config.settings import get_active_contracts, get_settings
from src.intelligence.bars.gap_plan import ANSWERED_OUTCOMES
from src.intelligence.bars.vendor_kind import ALPACA_RAW_ADJUSTMENT, alpaca_kind_for_feed
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


def _apr_str(conn, key: str, default: str) -> str:
    """The string sibling of _apr_int (the capture feed is a name, not a number)."""
    with conn.cursor() as cur:
        cur.execute("SELECT config_value FROM config_state WHERE config_key = %s", (key,))
        row = cur.fetchone()
    return row[0] if row else default


def request_end(now: datetime, data_feed: str | None, sip_lag_minutes: int) -> datetime:
    """The window end the nightly asks. Free-plan Alpaca 403s a feed=sip window ending within
    about 15 minutes of now (migration 513), so a sip window ends `sip_lag_minutes` earlier;
    every other feed and vendor ends at now."""
    if data_feed == "sip":
        return now - timedelta(minutes=sip_lag_minutes)
    return now


def _bars_frame(bars) -> pd.DataFrame:
    """Provider bars -> the engine's canonical frame (t, o, h, l, c, v). `t` is always a UTC
    datetime column, so an empty answer (a name the vendor no longer serves) loads zero rows."""
    return pd.DataFrame(
        {
            "t": pd.to_datetime([b.timestamp for b in bars], utc=True),
            "o": [b.open for b in bars],
            "h": [b.high for b in bars],
            "l": [b.low for b in bars],
            "c": [b.close for b in bars],
            "v": [b.volume for b in bars],
        }
    )


_TIMEFRAMES = ("5m", "1d")


def parse_timeframes(value: str | None) -> tuple[str, ...]:
    """The timeframes to ask, in nightly order: both by default; one for a history backfill
    (the 1d-only Alpaca history pull, 2026-10-27)."""
    if value is None:
        return _TIMEFRAMES
    asked = {part.strip() for part in value.split(",") if part.strip()}
    unknown = asked - set(_TIMEFRAMES)
    if unknown or not asked:
        raise ValueError(f"--timeframes takes a subset of {_TIMEFRAMES}, got {value!r}")
    return tuple(tf for tf in _TIMEFRAMES if tf in asked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", default="alpaca", help="capture vendor (default alpaca)")
    parser.add_argument("--days", type=int, default=None, help="window; default the APR key")
    parser.add_argument("--symbols", nargs="*", help="subset; default every active instrument")
    parser.add_argument(
        "--timeframes", default=None, help="comma-separated subset of 5m,1d; default both"
    )
    parser.add_argument("--apply", action="store_true", help="write; default plans and prints")
    args = parser.parse_args()
    timeframes = parse_timeframes(args.timeframes)

    settings = get_settings()
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        window_days = args.days or _apr_int(conn, "infra.alpaca.nightly_window_days", 5)
        # Alpaca only: the feed the tail is asked on (APR, migrations 511 and 513) and the raw
        # kind that basis is written under; a sip window ends before the recent-SIP horizon.
        data_feed = (
            _apr_str(conn, "infra.alpaca.data_feed", "sip") if args.vendor == "alpaca" else None
        )
        end = request_end(
            datetime.now(UTC),
            data_feed,
            _apr_int(conn, "infra.alpaca.sip_recent_lag_minutes", 20),
        )
        start = end - timedelta(days=window_days)
        with conn.cursor() as cur:
            params = read_raw_params(cur)
            settle = read_settle(cur)
        universe = args.symbols or [
            instrument.symbol for instrument in get_active_contracts(settings, dimension="backfill")
        ]
        sink = _NightlySink(
            RequestSink(conn, caller=CALLER_SINK.format(vendor=args.vendor), source=args.vendor),
            conn,
            provider=args.vendor,
        )
        policy_5m = LoadPolicy(
            vendor=args.vendor,
            timeframe="5m",
            caller=CALLER_5M.format(vendor=args.vendor),
            kind=alpaca_kind_for_feed(data_feed, ALPACA_RAW_ADJUSTMENT) if data_feed else None,
        )
        leaf_kwargs = {
            "rate_limit_max_requests": _apr_int(conn, "infra.alpaca.rate_limit_max_requests", 190),
            "on_request": sink.on_request,
            "on_page": sink.on_page,
            "fetch_run_id": new_fetch_run_id(),
        }
        if data_feed is not None:
            leaf_kwargs["data_feed"] = data_feed
        leaf = history_leaf(args.vendor, settings, **leaf_kwargs)
        summary = asyncio.run(
            _run(
                leaf,
                conn,
                sink,
                policy_5m,
                params,
                settle,
                universe,
                start,
                end,
                args.apply,
                FetchBudget(
                    deadline=datetime.now(UTC)
                    + timedelta(
                        minutes=_apr_int(conn, "infra.alpaca.nightly_deadline_minutes", 60)
                    ),
                    max_requests=_apr_int(conn, "infra.alpaca.nightly_max_requests", 4000),
                ),
                timeframes=timeframes,
            )
        )
    finally:
        conn.close()

    print(summary_line(summary, apply=args.apply))
    return exit_code(summary)


class _NightlySink:
    """The nightly's ledger: request rows from the leaf and the bars of each page it answered.

    Each answered page commits its ohlcv_request row together with that page's bars (todo 596:
    the row is then the proof its bars were stored) through the page store (`_PageStore`), the
    handler `on_page` routes to. A page's bars still forming are held back onto its own row
    (partial_bars). A failed or timed-out page has no bars; its row stays buffered and `flush`
    writes it. A dry run writes no ledger row: `flush` then discards the buffer. The ledger
    fetch status follows the request rows that were written: a failed page counts when it is
    reported, an answered page only once it is stored, and each written flush records the
    newest of them per series, the value a coverage rebuild reads from ohlcv_request."""

    def __init__(self, sink: RequestSink, conn, *, provider: str) -> None:
        self._sink = sink
        self._conn = conn
        self._provider = provider
        self._newest: dict[tuple[str, str], tuple[datetime, str]] = {}  # newest status per series
        self.store = None  # the _PageStore answered pages go to; _run sets it

    def on_request(self, record) -> None:
        self._sink.on_request(record)
        if record.outcome not in ANSWERED_OUTCOMES:
            self.stored(record)  # a failed page's row is all there is to store

    def on_page(self, record, bars) -> None:
        """Store one answered page. If storing fails, its answered row must never be written
        without its bars: the row is dropped from the buffer and a failed row for the same page
        takes its place (it is written with the symbol's flush), then the error propagates."""
        if self.store is None:
            raise RuntimeError("an answered page arrived with no page store set")
        try:
            self.store.load(record, bars, self)
        except Exception as error:
            self._sink.take_requests([record.request_id])
            self.on_request(
                type(record)(
                    **{
                        **vars(record),
                        "request_id": str(uuid.uuid4()),
                        "outcome": "failed",
                        "terminal": False,
                        "n_bars": 0,
                        "error_text": f"store failed: {type(error).__name__}: {error}"[:500],
                        "answered_at": datetime.now(UTC),
                    }
                )
            )
            raise

    def stored(self, record) -> None:
        """Count `record` toward its series' newest fetch status."""
        status = fetch_status_for_outcome(record.outcome)
        key = (record.symbol, record.timeframe)
        if status is not None and (
            key not in self._newest or record.answered_at >= self._newest[key][0]
        ):
            self._newest[key] = (record.answered_at, status)

    def note_partial(self, request_id, partial_text: str) -> None:
        self._sink.note_partial(request_id, partial_text)

    def take(self, request_id) -> list[tuple]:
        """The buffered row of one answered page, removed so it commits with the page's bars.
        Exactly one row, or it raises: bars must never commit without their ledger row."""
        rows = self._sink.take_requests([request_id])
        if len(rows) != 1:
            raise RuntimeError(f"request {request_id}: {len(rows)} buffered rows, expected 1")
        return rows

    def flush(self, *, write: bool) -> int:
        if not write:
            self._sink.discard()
            self._newest.clear()
            return 0
        n_requests = self._sink.flush()
        if self._sink.pending() == 0 and self._newest:
            with self._conn.transaction():
                with self._conn.cursor() as cur:
                    cur.execute("SET LOCAL ROLE bar_derivation_writer")
                    for (symbol, timeframe), (answered_at, status) in self._newest.items():
                        record_fetch_outcome(
                            cur, symbol, timeframe, status, answered_at, provider=self._provider
                        )
            self._newest.clear()
        return n_requests


_SUMMARY_KEYS = (
    "pages",
    "authored",
    "raw_1d",
    "new",
    "changed",
    "unchanged",
    "errors",
    "unfinished",
    "flagged",
    "basis_flagged",
    "superseded",
    "unselected",
    "excluded",
    "partial",
)


def summary_line(summary: dict, *, apply: bool) -> str:
    status = load_status(
        apply=apply, unselected=summary["unselected"], basis_flagged=summary["basis_flagged"]
    )
    return (
        f"{status}: {summary['pages']} pages, "
        f"{summary['authored']} 5m rows offered to raw, {summary['raw_1d']} 1d rows offered to "
        f"raw ({summary['new']} new, {summary['changed']} changed, "
        f"{summary['unchanged']} unchanged), {summary['errors']} errors, "
        f"{summary['unfinished']} windows unfinished, "
        f"{summary['flagged']} restatement-flagged series "
        f"({summary['basis_flagged']} basis-change), "
        f"{summary['superseded']} offers superseded by a newer serve, "
        f"{summary['unselected']} unselected slots, {summary['excluded']} excluded (never-selected "
        f"kinds), {summary['partial']} incomplete bars held back"
    )


def exit_code(summary: dict) -> int:
    """Non-zero for an error, a window the budget left unfinished (its ask is incomplete), an
    unselected slot (rows that landed in raw with no canonical winner are not a clean night) or
    a basis-change restatement flag (the write landed, D-191-N, but the night is partial until
    the flag is reviewed; fourth review of 191-07, finding 2). A share-only flag is reported,
    never a failure."""
    failed = (
        summary["errors"]
        or summary["unfinished"]
        or summary["unselected"]
        or summary["basis_flagged"]
    )
    return 1 if failed else 0


class _PageStore:
    """Stores one answered page: its complete bars offered with the page's own request row in
    one transaction (5m through the policy, 1d raw capture only); a dry run counts what it
    would offer and writes nothing. `asked_at` is when the current window was asked (_run sets
    it per window), the lower bound the complete-bar rule splits against."""

    def __init__(self, conn, policy_5m, params, settle, end, write: bool, summary: dict):
        self.conn = conn
        self.policy_5m = policy_5m
        self.params = params
        self.settle = settle
        self.end = end
        self.write = write
        self.summary = summary
        self.asked_at: datetime | None = None

    def load(self, record, bars, sink) -> None:
        summary, policy = self.summary, self.policy_5m
        complete, partial, partial_text = keep_complete(
            bars,
            record.timeframe,
            answered_at=self.asked_at,
            request_end=self.end,
            settle=self.settle,
            symbol=record.symbol,
            caller=policy.caller,
        )
        if partial_text is not None:
            sink.note_partial(record.request_id, partial_text)
        request_rows = sink.take(record.request_id)
        frame = _bars_frame(complete)
        if record.timeframe == "5m":
            result = load_series(
                self.conn,
                policy,
                record.symbol,
                frame,
                params=self.params,
                write=self.write,
                answered_at=record.answered_at,
                request_rows=request_rows,
            )
            summary["authored"] += result.n_offered
            summary["unselected"] += result.n_unselected
            summary["excluded"] += result.n_excluded
        elif self.write:
            result = load_frame(
                self.conn,
                record.symbol,
                frame,
                vendor=policy.vendor,
                timeframe="1d",
                caller=CALLER_1D.format(vendor=policy.vendor),
                write=True,
                answered_at=record.answered_at,
                params=self.params,
                kind=policy.kind,  # the 1d capture carries the feed's basis too
                request_rows=request_rows,
            )
            summary["raw_1d"] += result.n_offered
        else:
            result = LoadResult()
        sink.stored(record)
        summary["pages"] += 1
        summary["partial"] += len(partial)
        summary["new"] += result.n_new
        summary["changed"] += result.n_changed
        summary["unchanged"] += result.n_unchanged
        summary["flagged"] += result.n_flagged_series
        summary["basis_flagged"] += result.n_basis_flagged
        summary["superseded"] += result.n_superseded


async def _run(
    leaf,
    conn,
    sink,
    policy_5m,
    params,
    settle,
    universe,
    start,
    end,
    write: bool,
    budget,
    *,
    timeframes: tuple[str, ...] = _TIMEFRAMES,
) -> dict:
    """Ask each (symbol, timeframe) window once. The leaf hands every answered page to the
    sink's page store, which stores it with its ledger row; a window the budget stopped
    before its terminal page is counted unfinished (its ask is incomplete in the ledger)."""
    await leaf.connect()
    summary = dict.fromkeys(_SUMMARY_KEYS, 0)
    sink.store = _PageStore(conn, policy_5m, params, settle, end, write, summary)
    try:
        for symbol in universe:
            try:
                for timeframe in timeframes:
                    sink.store.asked_at = datetime.now(UTC)
                    page = await leaf.fetch_ohlcv(
                        HistoryRequest(
                            symbol=symbol,
                            timeframe=timeframe,
                            start=start,
                            end=end,
                            adjustment=ALPACA_RAW_ADJUSTMENT,
                            rth_only=timeframe == "5m",
                        ),
                        budget,
                    )
                    if page.next_window_start is not None:
                        summary["unfinished"] += 1
            except Exception as error:  # noqa: BLE001 - one name fails, the night continues
                summary["errors"] += 1
                print(f"{symbol}: ERROR {type(error).__name__}: {error}", flush=True)
            sink.flush(write=write)
    finally:
        await leaf.close()
    return summary


if __name__ == "__main__":
    sys.exit(main())
