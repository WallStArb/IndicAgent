"""One-shot audit of every universe member's canonical 1d history (todo 647). Read-only.

The members are every distinct symbol of universe_membership, active or not (the stage 2 dead
names are the point of the universe). Structural findings fail the gate (exit 1): no canonical
1d bar, an OHLC invariant or non-positive price, a split recorded after the name's newest 1d
digest (re-derive it with a scoped bar_derivation run, todo 646). Bar density (bars over NYSE
sessions in the span) is written per member beside the same measure over the active names and is
not a pass/fail threshold.

Outputs in --out: summary.json, findings.csv, coverage.csv (per-name bar density).

    .venv/bin/python -m scripts.ops.bars.ops_member_history_audit --out <dir>
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from src.config.settings import Settings, get_settings  # noqa: E402
from src.intelligence.bars.member_history import (  # noqa: E402
    MemberStats,
    audit_members,
    bar_density,
    coverage_quantiles,
)
from src.intelligence.bars.sessions import nyse_sessions  # noqa: E402

_CHUNK = 2000
_QUANTILES = (0.01, 0.05, 0.25, 0.5)
_MEMBERS_SQL = "SELECT DISTINCT symbol FROM universe_membership"
_ACTIVE_SQL = "SELECT symbol FROM instruments WHERE is_active"
# The price columns are NOT NULL in market_data_ohlcv, so the filters below never meet a NULL.
_STATS_SQL = """
SELECT symbol, count(*),
       (min("timestamp") AT TIME ZONE 'UTC')::date, (max("timestamp") AT TIME ZONE 'UTC')::date,
       count(*) FILTER (WHERE high < greatest(open, low, close) OR low > least(open, high, close)),
       count(*) FILTER (WHERE least(open, high, low, close) <= 0)
FROM market_data_ohlcv_tradeable
WHERE timeframe = '1d' AND symbol = ANY(%(s)s)
GROUP BY symbol
"""
# The split-currency rule of universe_membership_writer._STALE_SPLITS_SQL (a test pins the two
# equal): a corporate action recorded after the name's newest 1d digest (or no digest at all)
# leaves canonical stale.
_STALE_SQL = """
SELECT ca.symbol, max(ca.recorded_at) AS latest_action, d.computed_at AS latest_digest
FROM corporate_action ca
LEFT JOIN (
    SELECT symbol, max(computed_at) AS computed_at
    FROM bar_content_digest WHERE timeframe = '1d' AND symbol = ANY(%(s)s) GROUP BY symbol
) d ON d.symbol = ca.symbol
WHERE ca.symbol = ANY(%(s)s)
GROUP BY ca.symbol, d.computed_at
HAVING d.computed_at IS NULL OR max(ca.recorded_at) > d.computed_at
ORDER BY ca.symbol
"""


def _rows(conn: psycopg.Connection, sql: str, symbols: list[str]) -> Iterator[tuple]:
    for lo in range(0, len(symbols), _CHUNK):
        yield from conn.execute(sql, {"s": symbols[lo : lo + _CHUNK]})


def read_stats(conn: psycopg.Connection, symbols: list[str]) -> dict[str, MemberStats]:
    return {row[0]: MemberStats(*row) for row in _rows(conn, _STATS_SQL, symbols)}


def read_stale(conn: psycopg.Connection, symbols: list[str]) -> dict[str, str]:
    return {
        sym: f"split recorded {action}, 1d digest {digest}"
        for sym, action, digest in _rows(conn, _STALE_SQL, symbols)
    }


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def run(settings: Settings, out: Path) -> int:
    t0 = time.monotonic()
    with psycopg.connect(settings.database_url) as conn:
        members = [r[0] for r in conn.execute(_MEMBERS_SQL)]
        active = [r[0] for r in conn.execute(_ACTIVE_SQL)]
        stats = read_stats(conn, sorted(set(members) | set(active)))
        stale = read_stale(conn, members)
    today = datetime.now(UTC).date()
    calendar = sorted(nyse_sessions(min((r.first for r in stats.values()), default=today), today))
    density = {s: bar_density(row, calendar) for s, row in stats.items()}
    findings = audit_members(members, stats, stale)
    member_set = set(members)
    quant = {
        name: coverage_quantiles([density[s] for s in group if s in density], _QUANTILES)
        for name, group in (("members", members), ("active", active))
    }
    out.mkdir(parents=True, exist_ok=True)
    write_csv(
        out / "findings.csv",
        ["symbol", "check", "detail"],
        [[f.symbol, f.check, f.detail] for f in findings],
    )
    write_csv(
        out / "coverage.csv",
        ["symbol", "member", "bars", "first", "last", "density"],
        [
            [s, s in member_set, stats[s].bars, stats[s].first, stats[s].last, f"{c:.6f}"]
            for s, c in sorted(density.items())
        ],
    )
    summary = {
        "members": len(members),
        "active": len(active),
        "findings_by_check": dict(Counter(f.check for f in findings)),
        "coverage_quantiles": quant,
        "elapsed_s": round(time.monotonic() - t0, 1),
        "passed": not findings,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return int(bool(findings))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    return run(get_settings(), parser.parse_args(argv).out)


if __name__ == "__main__":
    sys.exit(main())
