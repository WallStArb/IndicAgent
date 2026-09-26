#!/usr/bin/env python3
"""
universe_expansion_holdings_draw.py -- seeded cap-stratified draw from an iShares holdings export

Draws `alpha.universe.r2k_sample_size` symbols (or --size) from an iShares holdings export,
the index's own membership (IWM for the Russell 2000, IVV for the S&P 500): exclude every symbol already in `instruments`,
then take Phase 174's cap-bucket-stratified sample (`stratified_sample()`, seed and bucket
count from APR). A mechanical draw rather than a hand-picked one, so no prior about where
signal lives enters the universe. Download the export with
universe_expansion_fetch_iwv_holdings.py --url <IWM holdings CSV URL>; the file format is the
same as IWV's.

--min-price drops names priced below it in the holdings file (penny stocks, escrow lines),
before bucketing. --skip-top N drops the N largest names by index position value first. Run on an IWV (Russell
3000) export with --skip-top 1000 it approximates the Russell 2000 by rank; the 2026-09-26
expansion onboarded one draw each way (config/universe/).

The draw is from current index members only, so it carries survivorship bias (todo 376).

Read-only: writes the drawn list and its provenance to --out. Onboarding happens through
universe_expansion_onboard_manifest.py once each drawn name is classified.

Usage:
    .venv/bin/python scripts/infrastructure/universe_expansion_holdings_draw.py \\
        --holdings config/universe/iwm_holdings_2026_09_23.csv --out config/universe/r2k_draw_2026_09_26.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd  # noqa: E402

from scripts.infrastructure.universe_expansion_fetch_iwv_holdings import (  # noqa: E402
    HEADER_ROW_INDEX,
    _parse_money,
    parse_holdings,
)
from scripts.infrastructure.universe_expansion_stratified_sourcing import (  # noqa: E402
    _fetch_apr,
    _sha256_of,
    exclude_set_sha256,
    stratified_sample,
)
from src.config.settings import Settings  # noqa: E402


def holdings_prices(path: Path) -> dict[str, float]:
    """Ticker -> last price from an iShares holdings export (parse_holdings keeps a narrower
    contract and drops the Price column)."""
    frame = pd.read_csv(path, skiprows=HEADER_ROW_INDEX, dtype=str)
    return {
        str(t).strip(): price
        for t, raw in zip(frame["Ticker"], frame["Price"], strict=True)
        if (price := _parse_money(raw)) is not None
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seeded cap-stratified draw from iShares holdings."
    )
    parser.add_argument("--holdings", type=Path, required=True, help="iShares holdings CSV.")
    parser.add_argument(
        "--skip-top",
        type=int,
        default=0,
        help="Drop this many largest names first (1000 on an IWV export approximates the R2K).",
    )
    parser.add_argument("--out", type=Path, required=True, help="Drawn-list CSV to write.")
    parser.add_argument(
        "--size",
        type=int,
        default=0,
        help="Draw size; defaults to alpha.universe.r2k_sample_size.",
    )
    parser.add_argument(
        "--min-price",
        type=float,
        default=0.0,
        help="Drop names whose holdings-file price is below this before drawing.",
    )
    args = parser.parse_args(argv)

    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        seed = _fetch_apr(cur, "alpha.universe.stratified_sample_random_state", 42)
        bucket_count = _fetch_apr(cur, "alpha.universe.cap_bucket_count", 10)
        target_size = _fetch_apr(cur, "alpha.universe.r2k_sample_size", 0)
        cur.execute("SELECT symbol FROM instruments")
        exclude = {row[0] for row in cur.fetchall()}
    if args.size > 0:
        target_size = args.size
    if target_size <= 0:
        print("FAILED: alpha.universe.r2k_sample_size is unset (migration 369).", file=sys.stderr)
        return 1

    population = parse_holdings(args.holdings)
    if args.skip_top:
        population = (
            population.sort_values("index_position_value", ascending=False, kind="mergesort")
            .iloc[args.skip_top :]
            .reset_index(drop=True)
        )
    if args.min_price > 0:
        prices = holdings_prices(args.holdings)
        population = population.loc[
            population["symbol"].map(prices).fillna(0.0) >= args.min_price
        ].reset_index(drop=True)
    sample = stratified_sample(
        population, target_size=target_size, bucket_count=bucket_count, seed=seed, exclude=exclude
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(args.out, index=False)
    provenance = {
        "holdings_file": str(args.holdings),
        "holdings_sha256": _sha256_of(args.holdings),
        "min_price": args.min_price,
        "skip_top": args.skip_top,
        "n_population": len(population),
        "stratified_sample_random_state": seed,
        "cap_bucket_count": bucket_count,
        "sample_size": target_size,
        "n_excluded": len(exclude),
        "exclude_set_sha256": exclude_set_sha256(exclude),
        "n_drawn": len(sample),
    }
    args.out.with_suffix(".provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
