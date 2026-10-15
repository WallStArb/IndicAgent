"""ops_restatement_review.py - the review queue of basis-change restatement flags (D-191-N).

A vendor's re-serve lands last-wins (D-191-N); the restatement detector
(src/intelligence/bars/restatement.py) records a flagged load in ohlcv_restatement_flag. A flag
with a basis-change signature (price_ratio, volume_ratio, time_shift) makes the fetcher, the
Alpaca nightly and ops_bar_load report a partial run, fails the selection gate (exit 3) and holds
the D7 gauge ohlcv_restatement_unreviewed_basis_flags above zero until a reviewer marks it here
(fourth review of plan 191-07, finding 2). Share-only flags are listed with --all and need no
review.

Modes:
  (default)            list the unreviewed basis-change flags; exit 1 when any exist
  --all                list every flag, reviewed or not
  --mark LOAD_ID ...   mark the named flags reviewed (dry run unless --apply); --by and --note
                       are required: the review names who decided and what (for example "split
                       2:1 effective 2026-10-01, canonical re-selected, derived re-derived")

The UPDATE lives in services/ohlcv_ingress_contract.py (`mark_reviewed`), the table's writer.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from services.ohlcv_ingress_contract import mark_reviewed, read_unreviewed_basis  # noqa: E402
from src.config.settings import get_settings  # noqa: E402

_ALL_SQL = (
    "SELECT load_id, symbol, timeframe, vendor, kind, n_stored, n_changed, share, signatures, "
    "detail, flagged_at, reviewed_at, reviewed_by, review_note FROM ohlcv_restatement_flag "
    "ORDER BY flagged_at, symbol, timeframe"
)


def format_flag(row: Sequence) -> str:
    load_id, symbol, timeframe, vendor, kind, n_stored, n_changed, share, signatures = row[:9]
    detail, flagged_at = row[9], row[10]
    line = (
        f"{load_id} {symbol} {timeframe} {vendor}/{kind} flagged {flagged_at:%Y-%m-%d %H:%M} "
        f"changed {n_changed}/{n_stored} ({share:.2%}) {list(signatures)}: {detail}"
    )
    if len(row) > 11 and row[11] is not None:
        line += f" | reviewed {row[11]:%Y-%m-%d} by {row[12]}: {row[13]}"
    return line


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--all", action="store_true", help="list every flag")
    parser.add_argument("--mark", nargs="+", type=uuid.UUID, metavar="LOAD_ID")
    parser.add_argument("--by", help="reviewer (required with --mark)")
    parser.add_argument("--note", help="what was decided (required with --mark)")
    parser.add_argument("--apply", action="store_true", help="write the review marks")
    args = parser.parse_args(argv)
    if args.mark and not (args.by and args.note):
        parser.error("--mark needs --by and --note")

    with psycopg.connect(get_settings().database_url) as conn, conn.cursor() as cur:
        if args.mark:
            marked = mark_reviewed(cur, args.mark, reviewed_by=args.by, note=args.note)
            if args.apply:
                conn.commit()
                print(f"marked {marked} of {len(args.mark)} flag(s) reviewed")
            else:
                conn.rollback()
                print(f"dry run: would mark {marked} of {len(args.mark)} flag(s) reviewed")
            return 0
        if args.all:
            cur.execute(_ALL_SQL)
            rows = cur.fetchall()
            for row in rows:
                print(format_flag(row))
            print(f"{len(rows)} flag(s)")
            return 0
        rows = read_unreviewed_basis(cur)
        for row in rows:
            print(format_flag(row))
        print(f"{len(rows)} unreviewed basis-change flag(s)")
        return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
