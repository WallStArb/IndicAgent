"""Re-record stale bar_session_choice rows through the selection writer (todo 611).

A choice row written before migration 484 and 480's grid counters carries n_vendor_grid_slots = 0
and n_primary_grid_slots = 0 beside a positive n_grid_slots; the selection gate counts each as
`session_choices_unrecorded`. The one writer of the table is services/bar_selection.py, so the
repair re-selects each affected session through `select_and_write`, whose upsert rewrites only a
row that differs. Canonical is a pure function of raw, so a repair that would change a canonical
row is wrong: the run aborts and rolls back (dry run by default; --apply commits).

    python -m scripts.ops.bars.ops_rerecord_session_choices                # dry run
    python -m scripts.ops.bars.ops_rerecord_session_choices --apply
    python -m scripts.ops.bars.ops_rerecord_session_choices --symbols A AAPL --timeframes 5m
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import psycopg  # noqa: E402

from services.bar_selection import select_and_write  # noqa: E402
from services.ohlcv_ingress_contract import read_raw_params  # noqa: E402
from src.config.settings import get_settings  # noqa: E402

_STALE_SQL = (
    "SELECT symbol, timeframe, session_date FROM bar_session_choice "
    "WHERE n_grid_slots > 0 AND n_vendor_grid_slots = 0 AND n_primary_grid_slots = 0 "
    "AND timeframe = ANY(%s) AND (%s::text[] IS NULL OR symbol = ANY(%s)) "
    "ORDER BY timeframe, symbol, session_date"
)
_DIRECT_TIMEFRAMES = ("1m", "5m", "4h")


def _day_window(session: date) -> tuple[datetime, datetime]:
    """UTC bounds that cover one NYSE session; select_and_write widens them to whole sessions."""
    start = datetime.combine(session, time(12, 0), tzinfo=UTC)
    return start, start + timedelta(hours=12)


def stale_sessions(
    conn: psycopg.Connection, timeframes: list[str], symbols: list[str] | None
) -> dict[tuple[str, str], list[date]]:
    with conn.cursor() as cur:
        cur.execute(_STALE_SQL, (timeframes, symbols, symbols))
        found: dict[tuple[str, str], list[date]] = defaultdict(list)
        for symbol, timeframe, session in cur.fetchall():
            found[(symbol, timeframe)].append(session)
    return dict(found)


def rerecord(conn: psycopg.Connection, found: dict[tuple[str, str], list[date]]) -> int:
    """Re-select every stale session; returns the rows the writer changed (must be 0)."""
    with conn.cursor() as cur:
        params = read_raw_params(cur)
    changed = 0
    for (symbol, timeframe), sessions in sorted(found.items()):
        for session in sessions:
            start, end = _day_window(session)
            result = select_and_write(
                conn,
                symbols=[symbol],
                timeframe=timeframe,
                start=start,
                end=end,
                policy_rows=None,
                kind_order=params.kind_order,
                batch_rows=params.write.batch_rows,
            )
            changed += result.new + result.changed
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeframes", nargs="+", default=list(_DIRECT_TIMEFRAMES))
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--apply", action="store_true", help="commit (default: roll back)")
    args = parser.parse_args()
    bad = sorted(set(args.timeframes) - set(_DIRECT_TIMEFRAMES))
    if bad:
        parser.error(f"direct timeframes only: {_DIRECT_TIMEFRAMES}; got {bad}")
    symbols = [s.upper() for s in args.symbols] if args.symbols else None
    conn = psycopg.connect(get_settings().database_url)
    try:
        found = stale_sessions(conn, args.timeframes, symbols)
        n_sessions = sum(len(v) for v in found.values())
        print(f"stale choice rows: {n_sessions} over {len(found)} series", flush=True)
        if not n_sessions:
            return 0
        changed = rerecord(conn, found)
        if changed:
            conn.rollback()
            print(f"ABORT: the writer would change {changed} canonical rows; rolled back")
            return 1
        if not args.apply:
            conn.rollback()
            print("dry run: rolled back (rerun with --apply)")
            return 0
        conn.commit()
        # The detector is a candidate filter: a session whose slots are all off the calendar grid
        # legitimately records zero grid counters (XTN 2011-01-28), so a row can match after the
        # repair. The proof is the gate: ops_selection_gate --compare reports unrecorded == 0.
        print("applied; verify with ops_selection_gate --compare (session_choices_unrecorded)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
