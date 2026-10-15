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

from services.bar_load import LoadPolicy, load_series, load_status
from services.ohlcv_ingress_contract import read_raw_params
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

    total = new = unchanged = flagged = unselected = 0

    # autocommit: persist_chunk_atomically demands an IDLE connection so its
    # per-chunk conn.transaction() owns BEGIN/COMMIT (psycopg's `with conn:`
    # would hold an open transaction and demote those to savepoints).
    conn = psycopg.connect(get_settings().database_url, autocommit=True)
    try:
        with conn.cursor() as cur:
            params = read_raw_params(cur)

        for symbol in symbols:
            frame = artifacts.get(symbol)
            if frame is None:
                print(f"{symbol}: no artifact, skipping", flush=True)
                continue
            result = load_series(conn, policy, symbol, frame, params=params, write=args.apply)
            total += result.n_offered
            new += result.n_new + result.n_changed
            unchanged += result.n_unchanged
            flagged += result.n_flagged_series
            unselected += result.n_unselected
            if args.apply:
                print(
                    f"{symbol}: offered {result.n_offered} ({result.n_new} new, "
                    f"{result.n_changed} changed, {result.n_unchanged} unchanged, "
                    f"{result.n_flagged_series} flagged, {result.n_unselected} unselected)",
                    flush=True,
                )
            else:
                print(f"{symbol}: {result.n_offered} to offer", flush=True)

    finally:
        conn.close()

    mode = load_status(apply=args.apply, unselected=unselected)
    print(
        f"{mode}: {total} rows offered, {new} written, {unchanged} unchanged, "
        f"{flagged} restatement-flagged series, {unselected} unselected"
    )
    return 1 if unselected else 0


if __name__ == "__main__":
    sys.exit(main())
