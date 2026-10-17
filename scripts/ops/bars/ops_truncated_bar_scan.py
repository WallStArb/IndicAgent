"""ops_truncated_bar_scan.py - find vendor 5m bars a request end truncated (read-only).

Third review of plan 191-07, low item (todo 535 item 19). An IBKR request that ended inside a 5m
bar stored the bar's first minutes only (TMUS 19:05; BLK and XTL 2026-10-09 14:10 hold a fifth of
Alpaca's volume, and canonical took them). Any reselect promotes such a bar wherever raw holds it,
so they must be found and re-served (the fetcher's --reserve-keys lane), never patched from
another vendor.

Rule, per series and NYSE session: for every regular-hours slot both vendors hold with volume,
r = IBKR volume / Alpaca volume; a bar is a candidate when r divided by the session's median r is
below APR `threshold.bar_integrity.truncated_bar_volume_ratio` (migration 483). The vendors'
volume levels differ by name and year (D-191-N item 6), which the session median absorbs. Each
candidate reports whether canonical holds it and whether a recorded IBKR request ended inside it.
Writes only the report (and, with --reserve-out, a reserve-keys file for the fetcher).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from scripts.ops.bars import ops_selection_gate as gate  # noqa: E402
from src.intelligence.bars.selection import session_date, session_grid  # noqa: E402

RATIO_KEY = "threshold.bar_integrity.truncated_bar_volume_ratio"
_BAR = timedelta(minutes=5)
_PAIRS_SQL = (
    'SELECT i."timestamp", i.volume, a.volume FROM ohlcv_raw i JOIN ohlcv_raw a '
    'ON a.symbol = i.symbol AND a.timeframe = i.timeframe AND a."timestamp" = i."timestamp" '
    "AND a.vendor = 'alpaca' WHERE i.symbol = %s AND i.timeframe = '5m' AND i.vendor = 'ibkr' "
    "AND i.volume > 0 AND a.volume > 0"
)
_CANON_SQL = (
    'SELECT "timestamp", vendor FROM market_data_ohlcv WHERE symbol = %s AND timeframe = %s '
    'AND "timestamp" = ANY(%s)'
)
_ENDS_SQL = (
    "SELECT window_end FROM ohlcv_request WHERE symbol = %s AND timeframe = '5m' "
    "AND source = 'ibkr' AND window_end = ANY(%s)"
)
_PAIRED_SYMBOLS_SQL = (
    "SELECT DISTINCT symbol FROM bar_source_policy WHERE timeframe = '5m' AND symbol IS NOT NULL"
)


def candidates(
    pairs: Sequence[tuple[datetime, int, int]], threshold: float
) -> list[dict[str, Any]]:
    """The truncated-bar candidates of one series (module docstring). Pure."""
    by_session: dict[Any, list[tuple[datetime, float]]] = defaultdict(list)
    for ts, ibkr, alpaca in pairs:
        day = session_date(ts)
        grid = session_grid("5m", day)
        if grid is not None and ts in grid:
            by_session[day].append((ts, ibkr / alpaca))
    out: list[dict[str, Any]] = []
    for day, rows in sorted(by_session.items()):
        median = statistics.median(r for _, r in rows)
        if median <= 0:
            continue
        for ts, r in rows:
            if r / median < threshold:
                out.append(
                    {"timestamp": ts.isoformat(), "session": day.isoformat(), "ratio": r / median}
                )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--reserve-out", default=None)
    args = parser.parse_args(argv)
    import asyncio

    _batch, timeout_s, _match = asyncio.run(gate._read_apr())
    conn = gate.open_connection(timeout_s)
    report: list[dict[str, Any]] = []
    try:
        with conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute("SELECT config_value FROM config_state WHERE config_key = %s", (RATIO_KEY,))
            row = cur.fetchone()
            if row is None:
                raise SystemExit(f"{RATIO_KEY} missing from config_state")
            threshold = float(row[0])
            if args.symbols:
                symbols = args.symbols
            else:
                cur.execute(_PAIRED_SYMBOLS_SQL)
                symbols = sorted(r[0] for r in cur.fetchall())
        for symbol in symbols:
            with conn.cursor() as cur:
                cur.execute(_PAIRS_SQL, (symbol,))
                found = candidates(cur.fetchall(), threshold)
                if found:
                    stamps = [datetime.fromisoformat(c["timestamp"]) for c in found]
                    cur.execute(_CANON_SQL, (symbol, "5m", stamps))
                    canon = {r[0]: r[1] for r in cur.fetchall()}
                    ends = []
                    for ts in stamps:
                        ends.extend(ts + timedelta(seconds=s) for s in range(1, 300))
                    cur.execute(_ENDS_SQL, (symbol, ends))
                    inside = {r[0] for r in cur.fetchall()}
                    for c, ts in zip(found, stamps, strict=True):
                        c["canonical"] = canon.get(ts)
                        c["request_ended_inside"] = any(ts < e < ts + _BAR for e in inside)
                        c["symbol"] = symbol
                    report.extend(found)
            conn.rollback()
            print(f"{symbol}: {len(found)}", flush=True)
    finally:
        conn.close()
    payload = {
        "meta": {"generated": datetime.now(UTC).isoformat(), "threshold": threshold},
        "n_candidates": len(report),
        "n_in_canonical": sum(1 for c in report if c["canonical"] == "ibkr"),
        "n_request_ended_inside": sum(1 for c in report if c["request_ended_inside"]),
        "candidates": report,
    }
    Path(args.out).write_text(json.dumps(payload, indent=1))
    if args.reserve_out:
        keys = [
            {
                "symbol": c["symbol"],
                "timeframe": "5m",
                "timestamp": c["timestamp"],
                "reason": "truncated IBKR bar (truncated-bar scan)",
            }
            for c in report
        ]
        Path(args.reserve_out).write_text(json.dumps({"reserve_keys": keys}, indent=1))
    print(
        json.dumps(
            {k: payload[k] for k in ("n_candidates", "n_in_canonical", "n_request_ended_inside")}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
