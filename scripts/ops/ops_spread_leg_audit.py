#!/usr/bin/env python3
"""spread_leg tag audit (todo 678): every `instrument_tags` row tagged `spread_leg` names, in its
evidence `pair` key (a symbol or a list of symbols), instruments that exist, and every pair is
reciprocal. Read-only on the tags; writes one `integrity_monitor` row per run (monitor_type
`spread_leg_audit`, metric `problems`, threshold 0) and prints the problems. Exit 1 on any problem.

This was a unit test reading the live database (tests/unit/test_spread_leg_pair_validity.py); its
result depended on data, not code, so it moved here. The checks are pure and unit-tested in
tests/unit/scripts/test_ops_spread_leg_audit.py.

Usage: .venv/bin/python -m scripts.ops.ops_spread_leg_audit [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402

from src.config.settings import get_settings  # noqa: E402
from src.core.integrity_monitor import emit_integrity_fact_sync  # noqa: E402

MONITOR_TYPE = "spread_leg_audit"


def pairs_of(evidence: Mapping | None) -> list[str]:
    """The evidence `pair` value as a list of symbols; [] when it is missing."""
    pair = (evidence or {}).get("pair")
    if pair is None:
        return []
    return list(pair) if isinstance(pair, list) else [pair]


def spread_leg_problems(
    rows: Sequence[tuple[str, Mapping | None]], symbols: frozenset[str]
) -> list[str]:
    """Every duplicate current row, missing pair, pair naming an unknown symbol and non-reciprocal
    pair, sorted. `rows` are the current (symbol, evidence) rows; a symbol with two of them is a
    problem, never collapsed to one."""
    counts = Counter(symbol for symbol, _ in rows)
    problems = [f"{s}: {n} current spread_leg rows" for s, n in counts.items() if n > 1]
    partners = {symbol: pairs_of(evidence) for symbol, evidence in rows}
    for symbol, pair_list in partners.items():
        if not pair_list:
            problems.append(f"{symbol}: no evidence pair")
        for partner in pair_list:
            if partner not in symbols:
                problems.append(f"{symbol}->{partner}: no such instrument")
            if partner not in partners:
                problems.append(f"{symbol}->{partner}: partner has no spread_leg row")
            elif symbol not in partners[partner]:
                problems.append(f"{symbol}->{partner}: {partner} does not name {symbol} back")
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print only, write no row")
    args = parser.parse_args(argv)
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # current rows only: ITR is point in time, a reclassify closes valid_to and inserts
            cur.execute(
                "SELECT symbol, evidence FROM instrument_tags WHERE tag = 'spread_leg' "
                "AND (valid_to IS NULL OR valid_to > now())"
            )
            rows = cur.fetchall()
            cur.execute("SELECT symbol FROM instruments")
            symbols = frozenset(r[0] for r in cur.fetchall())
        problems = spread_leg_problems(rows, symbols)
        print(f"spread_leg rows {len(rows)}, problems {len(problems)}")
        for line in problems:
            print(f"  {line}")
        if not args.dry_run:
            emit_integrity_fact_sync(
                conn,
                MONITOR_TYPE,
                None,
                "problems",
                float(len(problems)),
                0.0,
                not problems,
                datetime.now(UTC),
                commit=True,
            )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
