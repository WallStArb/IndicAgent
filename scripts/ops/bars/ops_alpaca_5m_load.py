"""Alpaca 5m campaign loader CLI (todo 521, T2).

Thin shell over the shared load engine (`services/bar_load.py`): walks the
puller's scratch parquet, plans or applies each name under the Alpaca 5m
policy, and prints per-name counts. Every integrity rule lives in the engine;
this file holds no write logic. The T4 nightly leaf calls the same engine
from its own daemon shell.

Dry run is the default: without --apply this plans and prints, writing
nothing. Provenance and the row-level-observation gap are documented in the
engine module and the canonical-truth-registry's Alpaca row.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import psycopg

from services.bar_load import LoadPolicy, load_series
from services.ohlcv_ingress_contract import read_params
from src.config.settings import get_settings

POLICY = LoadPolicy(vendor="alpaca", timeframe="5m", caller="alpaca-5m-load")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-dir", type=Path, default=Path("data/scratch/alpaca-pilot/depth"))
    parser.add_argument("--symbols", nargs="*", help="subset; default every parquet in the dir")
    parser.add_argument("--apply", action="store_true", help="write; default plans and prints")
    args = parser.parse_args()

    symbols = args.symbols or sorted(
        p.name.split("_")[0] for p in args.scratch_dir.glob("*_5Min.parquet")
    )
    planned_total = applied_total = skipped_stored = dropped_extended = 0

    with psycopg.connect(get_settings().database_url) as conn:
        with conn.cursor() as cur:
            params = read_params(cur)

        for symbol in symbols:
            path = args.scratch_dir / f"{symbol}_5Min.parquet"
            if not path.exists():
                print(f"{symbol}: no parquet, skipping", flush=True)
                continue
            frame = pd.read_parquet(path)
            frame["t"] = pd.to_datetime(frame["t"], utc=True).dt.floor("5min")
            planned, skipped, dropped = load_series(
                conn, POLICY, symbol, frame, params=params, write=args.apply
            )
            skipped_stored += skipped
            dropped_extended += dropped
            if args.apply:
                applied_total += planned
                print(
                    f"{symbol}: applied {planned} ({skipped} stored, {dropped} extended)",
                    flush=True,
                )
            else:
                planned_total += planned
                print(f"{symbol}: {planned} new ({skipped} stored, {dropped} extended)", flush=True)

    mode = "APPLIED" if args.apply else "PLANNED"
    total = applied_total if args.apply else planned_total
    print(
        f"{mode}: {total} rows, {skipped_stored} stored-held dropped, "
        f"{dropped_extended} extended dropped"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
