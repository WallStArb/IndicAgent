"""Masked-slot baseline for the intraday bar store (todo 462, plan 185-12).

A masked slot is a coarse-timeframe slot (15m by default) whose stored row is a synthetic fill
while the tradeable 5m bars over the same slot carry real volume: the coarse table says nothing
traded when something did. The rewrite in plan 185-12 deletes synthetic fills and does not
archive them, so this count can only be taken before it runs; afterwards it must read zero for
every derived symbol.

Read-only. Per year it reports the synthetic rows, the masked slots, the symbols involved and the
5m volume hidden; with --whole-year-min it also lists the symbols whose slots in that year are
masked in bulk (the 2026-09-29 measurement found 13 names with 6,464 slots each in 2025).

The 15m grid aligns with the 09:30 open, so the join on `date_bin` is exact. A 1h reading is not
comparable (the provider's 1h grid has a 09:30 half-hour bar), so 1h is refused here.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import psycopg

from src.config.settings import Settings

_BIN_MINUTES = {"15m": 15}
_FIRST_YEAR = 2006

_MASKED_BY_YEAR_SQL = """
WITH fine AS (
    SELECT symbol,
           date_bin(%(bin)s::interval, "timestamp", '2000-01-01 00:00+00') AS slot,
           sum(volume) AS fine_volume
    FROM market_data_ohlcv_tradeable
    WHERE timeframe = '5m' AND "timestamp" >= %(start)s AND "timestamp" < %(end)s
    GROUP BY 1, 2
)
SELECT
    (SELECT count(*) FROM market_data_ohlcv
      WHERE timeframe = %(coarse)s AND source = 'synthetic_fill'
        AND "timestamp" >= %(start)s AND "timestamp" < %(end)s) AS synthetic_rows,
    count(*) AS masked_slots,
    count(DISTINCT m.symbol) AS symbols,
    COALESCE(sum(fine.fine_volume), 0) AS hidden_volume
FROM market_data_ohlcv m
JOIN fine ON fine.symbol = m.symbol AND fine.slot = m."timestamp"
WHERE m.timeframe = %(coarse)s AND m.source = 'synthetic_fill'
  AND m."timestamp" >= %(start)s AND m."timestamp" < %(end)s
"""

_WHOLE_YEAR_SQL = """
WITH fine AS (
    SELECT symbol,
           date_bin(%(bin)s::interval, "timestamp", '2000-01-01 00:00+00') AS slot
    FROM market_data_ohlcv_tradeable
    WHERE timeframe = '5m' AND "timestamp" >= %(start)s AND "timestamp" < %(end)s
    GROUP BY 1, 2
)
SELECT m.symbol, count(*) AS masked_slots
FROM market_data_ohlcv m
JOIN fine ON fine.symbol = m.symbol AND fine.slot = m."timestamp"
WHERE m.timeframe = %(coarse)s AND m.source = 'synthetic_fill'
  AND m."timestamp" >= %(start)s AND m."timestamp" < %(end)s
GROUP BY 1
HAVING count(*) >= %(min_slots)s
ORDER BY 2 DESC, 1
"""


def _params(coarse: str, year: int) -> dict[str, Any]:
    if coarse not in _BIN_MINUTES:
        raise ValueError(f"baseline supports {sorted(_BIN_MINUTES)}, not {coarse!r}")
    return {
        "coarse": coarse,
        "bin": f"{_BIN_MINUTES[coarse]} minutes",
        "start": f"{year}-01-01",
        "end": f"{year + 1}-01-01",
    }


def masked_by_year(conn: Any, coarse: str, years: Sequence[int]) -> list[dict[str, Any]]:
    """One row per year: synthetic rows, masked slots, symbols involved, hidden 5m volume."""
    rows: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        for year in years:
            cur.execute(_MASKED_BY_YEAR_SQL, _params(coarse, year))
            synthetic_rows, masked_slots, symbols, hidden_volume = cur.fetchone()
            rows.append(
                {
                    "year": year,
                    "synthetic_rows": int(synthetic_rows),
                    "masked_slots": int(masked_slots),
                    "symbols": int(symbols),
                    "hidden_volume": int(hidden_volume),
                }
            )
    return rows


def whole_year_masked(conn: Any, coarse: str, year: int, min_slots: int) -> list[tuple[str, int]]:
    """Symbols with at least `min_slots` masked slots in `year`, most masked first."""
    with conn.cursor() as cur:
        cur.execute(_WHOLE_YEAR_SQL, {**_params(coarse, year), "min_slots": min_slots})
        return [(str(symbol), int(slots)) for symbol, slots in cur.fetchall()]


def totals(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    return {
        "masked_slots": sum(r["masked_slots"] for r in rows),
        "hidden_volume": sum(r["hidden_volume"] for r in rows),
        "years_with_masked_slots": sum(1 for r in rows if r["masked_slots"] > 0),
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--timeframe", default="15m", help="coarse timeframe (15m only)")
    parser.add_argument("--first-year", type=int, default=_FIRST_YEAR)
    parser.add_argument("--last-year", type=int, required=True)
    parser.add_argument(
        "--whole-year-min",
        type=int,
        default=None,
        help="also list symbols with at least this many masked slots in --whole-year",
    )
    parser.add_argument("--whole-year", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if (args.whole_year_min is None) != (args.whole_year is None):
        print("--whole-year and --whole-year-min go together", file=sys.stderr)
        return 2
    settings = Settings()
    years = range(args.first_year, args.last_year + 1)
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        rows = masked_by_year(conn, args.timeframe, list(years))
        result: dict[str, Any] = {"timeframe": args.timeframe, "by_year": rows}
        result["totals"] = totals(rows)
        if args.whole_year is not None:
            result["whole_year"] = {
                "year": args.whole_year,
                "min_slots": args.whole_year_min,
                "symbols": whole_year_masked(
                    conn, args.timeframe, args.whole_year, args.whole_year_min
                ),
            }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
