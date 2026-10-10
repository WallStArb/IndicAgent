"""Alpaca raw-archive backfill: recover the rows the loader dropped (todo 528).

One-time pass over the 521 scratch parquets: every served bar that canonical
authoring did not store (extended-hours rows, and RTH rows another source
already held under first-writer-stays) is archived raw with source 'alpaca'.
Classification and the archive write are the engine's own: `split_series`
defines non-authored once and `archive_rows` owns the chunk loop, so this
script holds no write logic and no second definition of the split. Authored
rows are not double-stored: their canonical row in `market_data_ohlcv` is the
persisted copy. The completeness identity is
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
    archive_frame_to_tuples,
    archive_rows,
    split_series,
)
from src.config.settings import get_settings
from src.intelligence.bars.vendor_ingress import vendor_ingress

CALLER = "alpaca-raw-archive-backfill"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols", nargs="*", help="subset; default every artifact the seam reads"
    )
    parser.add_argument("--apply", action="store_true", help="write; default plans and prints")
    args = parser.parse_args()

    ingress = vendor_ingress("alpaca", "5m")
    artifacts = ingress.read_artifacts(ingress.artifact_dir, symbols=args.symbols)

    conn = psycopg.connect(get_settings().database_url, autocommit=True)
    total_rows = total_extended = total_held = 0
    try:
        for symbol in sorted(artifacts):
            _, held, extended = split_series(conn, symbol, ingress.timeframe, artifacts[symbol])
            total_extended += len(extended)
            total_held += len(held)
            rows = archive_frame_to_tuples(
                pd.concat([held, extended], ignore_index=True),
                symbol,
                source=ingress.source,
                timeframe=ingress.timeframe,
            )
            if args.apply and rows:
                archived = archive_rows(conn, rows, caller=CALLER)
                total_rows += archived
                print(
                    f"{symbol}: archived {archived} ({len(held)} stored-held, {len(extended)} extended)",
                    flush=True,
                )
            else:
                print(
                    f"{symbol}: {len(rows)} archive rows "
                    f"({len(held)} stored-held, {len(extended)} extended)",
                    flush=True,
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
