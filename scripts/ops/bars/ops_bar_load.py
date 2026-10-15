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

Each artifact is offered with its recorded fetch time (the seam's
``answered_at``), so raw stays last-wins by serve time: replaying an
artifact after the nightly re-served a key logs the older value as
superseded and leaves raw unchanged. A basis-change restatement flag makes
the run PARTIAL and exits 1, like an unselected slot.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import psycopg

from services.bar_load import LoadPolicy, load_series, load_status
from services.ohlcv_ingress_contract import read_raw_params
from src.config.settings import get_settings
from src.intelligence.bars.vendor_ingress import check_answered_at, vendor_ingress

# Largest plausible gap between an artifact's newest bar and its answer time (review of 191-08 M2).
_LAG_KEY = "infra.alpaca.artifact_max_answer_lag_hours"


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

    total = new = unchanged = flagged = basis = superseded = unselected = 0
    refused: list[str] = []

    # autocommit: persist_chunk_atomically demands an IDLE connection so its
    # per-chunk conn.transaction() owns BEGIN/COMMIT (psycopg's `with conn:`
    # would hold an open transaction and demote those to savepoints).
    conn = psycopg.connect(get_settings().database_url, autocommit=True)
    try:
        with conn.cursor() as cur:
            params = read_raw_params(cur)
            cur.execute("SELECT config_value FROM config_state WHERE config_key = %s", (_LAG_KEY,))
            row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"APR key {_LAG_KEY} is not set (migration 487 seeds it)")
        max_lag = timedelta(hours=float(row[0]))

        for symbol in symbols:
            frame = artifacts.get(symbol)
            if frame is None:
                print(f"{symbol}: no artifact, skipping", flush=True)
                continue
            # the artifact's recorded fetch time: an old artifact never overwrites a newer serve
            answered_at = ingress.answered_at(artifact_dir, symbol)
            try:
                check_answered_at(answered_at, frame, max_lag=max_lag, where=symbol)
            except ValueError as error:
                print(f"{symbol}: refused: {error}", flush=True)
                refused.append(symbol)
                continue
            result = load_series(
                conn,
                policy,
                symbol,
                frame,
                params=params,
                write=args.apply,
                answered_at=answered_at,
            )
            total += result.n_offered
            new += result.n_new + result.n_changed
            unchanged += result.n_unchanged
            flagged += result.n_flagged_series
            basis += result.n_basis_flagged
            superseded += result.n_superseded
            unselected += result.n_unselected
            if args.apply:
                print(
                    f"{symbol}: offered {result.n_offered} answered {answered_at.isoformat()} "
                    f"({result.n_new} new, {result.n_changed} changed, "
                    f"{result.n_unchanged} unchanged, {result.n_superseded} superseded, "
                    f"{result.n_flagged_series} flagged, {result.n_basis_flagged} basis-change, "
                    f"{result.n_unselected} unselected)",
                    flush=True,
                )
            else:
                print(f"{symbol}: {result.n_offered} to offer", flush=True)

    finally:
        conn.close()

    mode = load_status(apply=args.apply, unselected=unselected, basis_flagged=basis)
    print(
        f"{mode}: {total} rows offered, {new} written, {unchanged} unchanged, "
        f"{superseded} superseded by a newer serve, {flagged} restatement-flagged series "
        f"({basis} basis-change), {unselected} unselected"
    )
    if refused:
        print(f"refused {len(refused)} artifact(s) with an implausible answer time: {refused}")
    return 1 if unselected or basis or refused else 0


if __name__ == "__main__":
    sys.exit(main())
