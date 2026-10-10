"""Vendor-generic campaign loader CLI (todo 521 successor shell).

Thin shell over the shared load engine (``services/bar_load.py``):
resolves the (vendor, timeframe) seam in
``src/intelligence.bars.vendor_ingress``, plans or applies every artifact
the seam reads, and prints per-symbol counts in the campaign log format.
Every integrity rule lives in the engine; this file holds no write logic
and no vendor knowledge. Replaces the vendor-named
``ops_alpaca_5m_load.py`` shell at the 190-06 cutover; until then both
shells share the same engine and log format.

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
    artifacts = ingress.read_artifacts(artifact_dir)
    symbols = args.symbols or sorted(artifacts)

    planned_total = applied_total = skipped_stored = dropped_extended = 0

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
            planned, skipped, dropped = load_series(
                conn, policy, symbol, frame, params=params, write=args.apply
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

    finally:
        conn.close()

    mode = "APPLIED" if args.apply else "PLANNED"
    total = applied_total if args.apply else planned_total
    print(
        f"{mode}: {total} rows, {skipped_stored} stored-held dropped, "
        f"{dropped_extended} extended dropped"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
