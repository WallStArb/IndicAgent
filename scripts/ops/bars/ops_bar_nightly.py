"""Nightly bar capture leaf (todo 521 T4): vendor-native, scratch-free, one engine.

For every active instrument, pulls the recent tail straight from the vendor's
HistoryProvider leaf and writes it through the load engine -- no scratch, no
campaign: request rows land via the D1 sink, 5m authors canonically
(``load_series``, which archives non-authored rows per todo 528 R1), and 1d is
raw-capture only (``archive_rows``; the engine's writer fence refuses 1d, so a
vendor daily can never author -- IBKR owns 1d).

The vendor is a CLI choice dispatched through the ``history_leaf`` factory and
the HistoryProvider protocol; a new capture vendor is one leaf plus one registry
entry, nothing here changes. Dry run is the default: without --apply this plans
and prints, writing nothing -- but the leaf still runs against the vendor API,
so a dry run costs vendor requests by design: the nightly's real work is the
ask.

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

from services.bar_load import (
    LoadPolicy,
    archive_frame_to_tuples,
    archive_rows,
    load_series,
)
from services.ohlcv_ingress_contract import read_params
from services.ohlcv_observation_writer import ObservationSink, new_fetch_run_id
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
            params = read_params(cur)
        universe = args.symbols or [
            instrument.symbol for instrument in get_active_contracts(settings, dimension="backfill")
        ]
        sink = ObservationSink(
            conn, caller=CALLER_SINK.format(vendor=args.vendor), source=args.vendor
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
            _run(leaf, conn, sink, policy_5m, params, universe, start, end, args.apply)
        )
    finally:
        conn.close()

    print(
        f"{'APPLIED' if args.apply else 'PLANNED'}: {summary['authored']} 5m rows authored, "
        f"{summary['raw_1d']} 1d rows archived raw, {summary['errors']} errors"
    )
    return 1 if summary["errors"] else 0


async def _run(leaf, conn, sink, policy_5m, params, universe, start, end, write: bool) -> dict:
    budget = FetchBudget(deadline=datetime.now(UTC) + timedelta(minutes=30), max_requests=500)
    await leaf.connect()
    summary = {"authored": 0, "raw_1d": 0, "errors": 0}
    try:
        for symbol in universe:
            try:
                for timeframe, load_canonical in (("5m", True), ("1d", False)):
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
                    frame = _bars_frame(page.bars)
                    if load_canonical:
                        applied, _, _ = load_series(
                            conn, policy_5m, symbol, frame, params=params, write=write
                        )
                        summary["authored"] += applied
                    else:
                        rows = archive_frame_to_tuples(
                            frame, symbol, source=policy_5m.vendor, timeframe="1d"
                        )
                        if write and rows:
                            summary["raw_1d"] += archive_rows(
                                conn, rows, caller=CALLER_1D.format(vendor=policy_5m.vendor)
                            )
            except Exception as error:  # noqa: BLE001 - one name fails, the night continues
                summary["errors"] += 1
                print(f"{symbol}: ERROR {type(error).__name__}: {error}", flush=True)
            sink.flush()
    finally:
        await leaf.close()
    return summary


if __name__ == "__main__":
    sys.exit(main())
