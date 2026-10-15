"""ops_session_choice_backfill.py - record the session choices of existing canonical series.

Third review of plan 191-07, finding 4; migration 480. `services/bar_selection.py` keeps
bar_session_choice current for every session it selects from now on; this one-time pass records
the choices of the sessions it selected before the table existed. Per series, under the series'
selection lock: read its raw rows, run the same session selection
(`select_slots`), and write the choices through `record_session_choices`, the table's sole
writer. Nothing else is written: canonical and raw are not touched (the selection gate proves
canonical equals the selection separately). One transaction per series. Dry run by default.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from scripts.ops.bars import ops_selection_gate as gate  # noqa: E402
from services.bar_selection import record_session_choices  # noqa: E402
from services.ohlcv_ingress_contract import read_raw_params  # noqa: E402
from src.intelligence.bars.selection import select_slots  # noqa: E402

_SERIES_SQL = (
    "SELECT symbol FROM instruments ORDER BY 1"  # a series with no raw rows writes nothing
)
_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeframe", default="5m", choices=sorted(gate.DIRECT_TIMEFRAMES))
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args(argv)
    import asyncio

    _batch, timeout_s, _match_s = asyncio.run(gate._read_apr())
    conn = gate.open_connection(timeout_s)
    totals: Counter = Counter()
    try:
        with conn.cursor() as cur:
            params = read_raw_params(cur)
            if args.symbols:
                symbols = args.symbols
            else:
                cur.execute(_SERIES_SQL)
                symbols = [r[0] for r in cur.fetchall()]
        conn.rollback()
        for n, symbol in enumerate(symbols, 1):
            with conn.cursor() as cur:
                cur.execute(_LOCK_SQL, (f"bar_selection|{symbol}|{args.timeframe}",))
                candidates = gate.read_candidates(cur, symbol, args.timeframe)
                outcome = select_slots(candidates, params.policy_rows, params.kind_order)
                totals["series"] += 1
                totals["sessions"] += len(outcome.sessions)
                totals["choices"] += len(outcome.choices)
                totals["fallback"] += sum(c.fallback for c in outcome.choices)
                totals["incomplete"] += sum(not c.complete for c in outcome.choices)
                totals["partial"] += sum(c.partial for c in outcome.choices)
                if args.apply:
                    record_session_choices(
                        cur, symbol, args.timeframe, outcome.sessions, outcome.choices
                    )
            if args.apply:
                conn.commit()
            else:
                conn.rollback()
            if n % 50 == 0 or n == len(symbols):
                print(f"{n}/{len(symbols)} {symbol} {dict(totals)}", flush=True)
    finally:
        conn.close()
    print(("applied " if args.apply else "dry run ") + str(dict(totals)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
