"""Vendor-generic campaign loader CLI (todo 521 successor shell).

Thin shell over the shared load engine (``services/bar_load.py``):
resolves the (vendor, timeframe) seam in
``src/intelligence.bars.vendor_ingress``, plans or applies every artifact
the seam reads, and prints per-symbol counts in the campaign log format.
Every integrity rule lives in the engine; this file holds no write logic
and no vendor knowledge. The vendor-named shell it replaced
(``ops_alpaca_5m_load.py``) was deleted at the 190-06 cutover; this is the
one campaign loader.

Dry run is the default: without --apply this plans and prints, writing
nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from services.bar_load import LoadPolicy, load_series
from services.ohlcv_ingress_contract import read_params
from src.config.settings import get_settings
from src.intelligence.bars.vendor_ingress import vendor_ingress


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", required=True, help="vendor source label (e.g. alpaca)")
    parser.add_argument("--timeframe", required=True, help="raw timeframe (e.g. 5m)")
    parser.add_argument(
        "--artifacts-dir", type=Path, default=None, help="default: the seam's artifact dir"
    )
    parser.add_argument(
        "--symbols", nargs="*", help="subset; default every artifact the seam reads"
    )
    parser.add_argument("--apply", action="store_true", help="write; default plans and prints")
    args = parser.parse_args()

    ingress = vendor_ingress(args.vendor, args.timeframe)
    policy = LoadPolicy(
        vendor=ingress.source,
        timeframe=ingress.timeframe,
        caller=f"{ingress.source}-{ingress.timeframe}-load",
    )
    artifact_dir = args.artifacts_dir or ingress.artifact_dir
    artifacts = ingress.read_artifacts(artifact_dir, symbols=args.symbols)
    symbols = args.symbols or sorted(artifacts)

    total = skipped_stored = dropped_extended = 0

    # autocommit: persist_chunk_atomically demands an IDLE connection so its
    # per-chunk conn.transaction() owns BEGIN/COMMIT (psycopg's `with conn:`
    # would hold an open transaction and demote those to savepoints).
    conn = psycopg.connect(get_settings().database_url, autocommit=True)
    try:
        with conn.cursor() as cur:
            params = read_params(cur)

        for symbol in symbols:
            frame = artifacts.get(symbol)
            if frame is None:
                print(f"{symbol}: no artifact, skipping", flush=True)
                continue
            rows, skipped, dropped = load_series(
                conn, policy, symbol, frame, params=params, write=args.apply
            )
            skipped_stored += skipped
            dropped_extended += dropped
            total += rows
            if args.apply:
                print(
                    f"{symbol}: applied {rows} ({skipped} stored, {dropped} extended)",
                    flush=True,
                )
            else:
                print(f"{symbol}: {rows} new ({skipped} stored, {dropped} extended)", flush=True)

    finally:
        conn.close()

    mode = "APPLIED" if args.apply else "PLANNED"
    print(
        f"{mode}: {total} rows, {skipped_stored} stored-held "
        f"{'archived' if args.apply else 'to archive'}, "
        f"{dropped_extended} extended {'archived' if args.apply else 'to archive'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
