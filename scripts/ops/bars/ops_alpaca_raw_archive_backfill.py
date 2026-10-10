"""Alpaca raw-archive backfill: recover the rows the loader dropped (todo 528).

One-time pass over the 521 scratch parquets: every served bar that canonical
authoring did not store (extended-hours rows, and RTH rows another source
already held under first-writer-stays) is archived raw with source 'alpaca'
through the single-writer contract (`services/intraday_raw_archive
.insert_fetched_archive_rows`). Authored rows are not double-stored: their
canonical row in `market_data_ohlcv` is the persisted copy. Nothing is
dropped from this point on; the completeness identity is
served = authored + archived (this script) + vendor-refused.

Requires migration 468 (source in the archive key) to be applied. Dry run is
the default: without --apply this plans and prints, writing nothing.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import psycopg

from services.bar_load import (
    filter_frame_to_grid,
    grid_stamps_utc,
    session_grid,
    stored_range_stamps,
)
from services.intraday_raw_archive import insert_fetched_archive_rows
from services.ohlcv_ingress_contract import read_params
from src.config.settings import get_settings
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.vendor_ingress import vendor_ingress

CALLER = "alpaca-raw-archive-backfill"


def non_authored_rows(frame: pd.DataFrame, symbol: str, conn) -> tuple[list[tuple], int, int]:
    """Split one canonical frame into archive rows and counts.

    Returns (rows, n_extended, n_stored_held): the extended-hours rows and the
    RTH rows another source authored, as archive 10-tuples. Pure over its
    inputs apart from the one stored-range read.
    """
    days = set(frame["t"].dt.date.unique())
    grid = session_grid(nyse_sessions(min(days), max(days)), days)
    utc_stamps = grid_stamps_utc(grid)
    in_grid = filter_frame_to_grid(frame, utc_stamps)
    n_extended = len(frame) - len(in_grid)
    start, end = in_grid["t"].min().to_pydatetime(), in_grid["t"].max().to_pydatetime()
    with conn.cursor() as cur:
        stored = stored_range_stamps(cur, symbol, "5m", start, end)
    held = in_grid.loc[in_grid["t"].isin(stored)]
    rows = [
        (
            ts.to_pydatetime(),
            symbol,
            "5m",
            float(o),
            float(h),
            float(low),
            float(c),
            int(v),
            "alpaca",
            None,
        )
        for ts, o, h, low, c, v in zip(
            held["t"], held["o"], held["h"], held["l"], held["c"], held["v"], strict=True
        )
    ]
    return rows, n_extended, len(held)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols", nargs="*", help="subset; default every artifact the seam reads"
    )
    parser.add_argument("--apply", action="store_true", help="write; default plans and prints")
    args = parser.parse_args()

    ingress = vendor_ingress("alpaca", "5m")
    artifacts = ingress.read_artifacts(ingress.artifact_dir)
    symbols = args.symbols or sorted(artifacts)

    conn = psycopg.connect(get_settings().database_url, autocommit=True)
    total_rows = total_extended = total_held = 0
    try:
        with conn.cursor() as cur:
            read_params(cur)
        for symbol in symbols:
            frame = artifacts.get(symbol)
            if frame is None:
                print(f"{symbol}: no artifact, skipping", flush=True)
                continue
            rows, n_extended, n_held = non_authored_rows(frame, symbol, conn)
            total_extended += n_extended
            total_held += n_held
            if args.apply and rows:
                applied = 0
                batch = 50_000
                for i in range(0, len(rows), batch):
                    chunk = rows[i : i + batch]
                    with conn.transaction():
                        with conn.cursor() as cur:
                            applied += insert_fetched_archive_rows(cur, chunk, caller=CALLER)
                    print(f"{symbol}: archived {applied}/{len(rows)}", end="\r", flush=True)
                total_rows += applied
                print(f"{symbol}: archived {applied} ({n_held} stored-held, {n_extended} extended)")
            else:
                print(
                    f"{symbol}: {len(rows)} archive rows ({n_held} stored-held, {n_extended} extended)"
                )
    finally:
        conn.close()

    mode = "ARCHIVED" if args.apply else "PLANNED"
    print(
        f"{mode}: {total_rows} rows archived, {total_held} stored-held, {total_extended} extended"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
