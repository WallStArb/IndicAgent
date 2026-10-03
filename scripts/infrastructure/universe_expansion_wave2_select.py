#!/usr/bin/env python3
"""
universe_expansion_wave2_select.py -- stage 2 (select) for the 2026-10-03 single-name wave

Rule, fixed before any bar of a selected name is fetched; inputs are facts of the selection
date only (index membership, holdings weight rank, sector, instruments table):

  r3k_top500_fill      Russell 3000 ranks 1-500 by holdings market value, not held
  r3k_501_1000         ranks 501-1000, not held (index band taken whole)
  r3k_utilities_depth  Utilities at rank 1001+, not held (the whole sector)
  r3k_depth_draw       Energy, Materials, Communication at rank 1001+: seeded, cap-stratified
                       draw of --depth-size names per sector (seed and bucket count from APR)

Names already held, and a second share class of an issuer already held or selected (same name
after stripping CLASS/SERIES suffixes), are excluded. No history, return or price screen.

    .venv/bin/python scripts/infrastructure/universe_expansion_wave2_select.py \
        --holdings config/universe/iwv_holdings_2026_09_14.csv \
        --out config/universe/wave2_selection_2026_10_03.csv
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd
import psycopg

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.universe_expansion_fetch_iwv_holdings import (  # noqa: E402
    HEADER_ROW_INDEX,
    _parse_money,
)
from scripts.infrastructure.universe_expansion_stratified_sourcing import (  # noqa: E402
    _fetch_apr,
    _sha256_of,
    stratified_sample,
)
from src.config.settings import Settings  # noqa: E402

_DEPTH_SECTORS = ("Energy", "Materials", "Communication")
_CLASS_SUFFIX = re.compile(r"\s+(CLASS|SERIES)\s+[A-Z0-9]+\s*$|\s+COM\s*$|\s+ADR\s*$")


def _issuer_key(name: str) -> str:
    return _CLASS_SUFFIX.sub("", str(name).upper().strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--holdings", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depth-size", type=int, default=25, help="Draw size per depth sector.")
    args = parser.parse_args(argv)

    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        seed = _fetch_apr(cur, "alpha.universe.stratified_sample_random_state", 42)
        bucket_count = _fetch_apr(cur, "alpha.universe.cap_bucket_count", 10)
        cur.execute("SELECT symbol FROM instruments")
        held = {row[0] for row in cur.fetchall()}

    frame = pd.read_csv(args.holdings, skiprows=HEADER_ROW_INDEX, dtype=str)
    frame = frame.loc[frame["Asset Class"] == "Equity"].copy()
    frame["index_position_value"] = frame["Market Value"].map(_parse_money)
    frame = frame.dropna(subset=["index_position_value"])
    frame = frame.sort_values("index_position_value", ascending=False, kind="mergesort")
    frame = frame.reset_index(drop=True)
    frame["rank"] = frame.index + 1
    frame["ibkr_symbol"] = frame["Ticker"].str.strip()
    # instruments spells a share class with a dot (BRK.B); the holdings file and IBKR use a space.
    frame["symbol"] = frame["ibkr_symbol"].str.replace(" ", ".", regex=False)
    frame["issuer_key"] = frame["Name"].map(_issuer_key)

    held_issuers = set(frame.loc[frame["symbol"].isin(held), "issuer_key"])
    open_frame = frame.loc[~frame["symbol"].isin(held) & ~frame["issuer_key"].isin(held_issuers)]

    picks: list[pd.DataFrame] = []
    for cohort, mask in (
        ("r3k_top500_fill", open_frame["rank"] <= 500),
        ("r3k_501_1000", open_frame["rank"].between(501, 1000)),
        (
            "r3k_utilities_depth",
            (open_frame["rank"] > 1000) & (open_frame["Sector"] == "Utilities"),
        ),
    ):
        picks.append(open_frame.loc[mask].assign(cohort=cohort))

    depth = open_frame.loc[open_frame["rank"] > 1000]
    for sector in _DEPTH_SECTORS:
        population = depth.loc[depth["Sector"] == sector].rename(columns={"Name": "name"})
        drawn = stratified_sample(
            population[["symbol", "name", "index_position_value"]].reset_index(drop=True),
            target_size=args.depth_size,
            bucket_count=bucket_count,
            seed=seed,
            exclude=set(),
        )
        picks.append(
            depth.loc[depth["symbol"].isin(drawn["symbol"])].assign(cohort="r3k_depth_draw")
        )

    selected = pd.concat(picks)
    # One row per issuer: a second class picked by another cohort loses to the earlier cohort.
    selected = selected.drop_duplicates("issuer_key", keep="first")
    out = selected[["symbol", "Name", "Sector", "rank", "cohort", "ibkr_symbol"]].rename(
        columns={"Name": "name", "Sector": "sector"}
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    provenance = {
        "holdings_file": str(args.holdings),
        "holdings_sha256": _sha256_of(args.holdings),
        "stratified_sample_random_state": seed,
        "cap_bucket_count": bucket_count,
        "depth_size_per_sector": args.depth_size,
        "held_at_selection": len(held),
        "selected": len(out),
        "by_cohort": out["cohort"].value_counts().to_dict(),
    }
    args.out.with_suffix(".provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
