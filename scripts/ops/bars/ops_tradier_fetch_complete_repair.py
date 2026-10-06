#!/usr/bin/env python3
"""One-time repair: set 1d fetch_complete for names Tradier owns that never got the flag.

The compute_1d promotion predicate (COMPUTE_READY_1D_PREDICATE_SQL) requires
backfill_status.fetch_complete for tf '1d'. Only the IBKR history pipeline set it until the
Tradier loader learned to (it marks every accepted load since this change), so the names loaded
from Tradier before then hold at promotion with real bars. This script runs the flag's one
writer, mark_fetch_complete (infrastructure_run_historical_pipeline.py), for every active equity
with an accepted Tradier load (TRADIER_OWNED_SQL), stored tradeable 1d bars and no 1d
fetch_complete. The writer's EXISTS guard still refuses a name with no bars at or after its
earliest accepted load's requested start; such a name stays unmarked and shows in the after count.

Default is a dry run that prints the counts and the names; --apply writes, in one transaction.

Usage:
  python scripts/ops/bars/ops_tradier_fetch_complete_repair.py [--apply]
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (  # noqa: E402
    mark_fetch_complete,
)
from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import (  # noqa: E402
    TRADIER_OWNED_SQL,
)
from src.config.settings import get_settings  # noqa: E402

_ACTIVE_EQUITY = "i.is_active AND i.contract_details->>'asset_class' = 'equity'"
_NO_FLAG = (
    "NOT EXISTS (SELECT 1 FROM backfill_status b "
    "WHERE b.symbol = i.symbol AND b.tf = '1d' AND b.fetch_complete)"
)
_HAS_BARS = (
    "EXISTS (SELECT 1 FROM market_data_ohlcv_tradeable m "
    "WHERE m.symbol = i.symbol AND m.timeframe = '1d')"
)

# The repair set: name and the requested start of its earliest accepted load (the writer's since).
CANDIDATES_SQL = f"""
SELECT i.symbol,
       (SELECT min(l.requested_start) FROM ohlcv_load l
        WHERE l.symbol = i.symbol AND l.timeframe = '1d' AND l.outcome = 'loaded') AS since
FROM instruments i
WHERE {_ACTIVE_EQUITY}
  AND {TRADIER_OWNED_SQL.format(col="i.symbol")}
  AND {_NO_FLAG}
  AND {_HAS_BARS}
ORDER BY i.symbol
"""

COUNTS_SQL = f"""
SELECT count(*) FILTER (WHERE NOT {_NO_FLAG}) AS flagged,
       count(*) FILTER (WHERE {TRADIER_OWNED_SQL.format(col="i.symbol")} AND {_NO_FLAG}
                        AND {_HAS_BARS}) AS owned_unflagged_with_bars,
       count(*) FILTER (WHERE {TRADIER_OWNED_SQL.format(col="i.symbol")} AND {_NO_FLAG}
                        AND NOT {_HAS_BARS}) AS owned_unflagged_no_bars
FROM instruments i
WHERE {_ACTIVE_EQUITY}
"""


def counts(conn: Any) -> dict[str, int]:
    """Active-equity 1d fetch_complete counts: flagged, and Tradier-owned unflagged by bars."""
    with conn.cursor() as cur:
        cur.execute(COUNTS_SQL)
        flagged, with_bars, no_bars = cur.fetchone()
    return {
        "flagged": flagged,
        "owned_unflagged_with_bars": with_bars,
        "owned_unflagged_no_bars": no_bars,
    }


def candidates(conn: Any) -> list[tuple[str, date]]:
    with conn.cursor() as cur:
        cur.execute(CANDIDATES_SQL)
        return [(symbol, since) for symbol, since in cur.fetchall()]


def repair(conn: Any, names: list[tuple[str, date]]) -> int:
    """Run the one writer for each name; returns the number of names passed to it."""
    for symbol, since in names:
        mark_fetch_complete(
            conn, symbol, "1d", datetime(since.year, since.month, since.day, tzinfo=UTC)
        )
    return len(names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args(argv)
    with psycopg.connect(get_settings().database_url) as conn:
        before = counts(conn)
        names = candidates(conn)
        print(f"before: {before}")
        print(f"candidates: {len(names)}: {' '.join(s for s, _ in names)}")
        if not args.apply:
            print("dry run: nothing written (pass --apply)")
            return 0
        n = repair(conn, names)
        conn.commit()
        print(f"marked: {n}")
        print(f"after: {counts(conn)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
