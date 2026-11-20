"""One-shot audit of every universe member's canonical 1d history (todo 647). Read-only by default.

The members are every distinct symbol of universe_membership, active or not (the stage 2 dead
names are the point of the universe). Structural findings fail the gate (exit 1): no canonical
1d bar, an OHLC invariant or non-positive price, a split recorded after the name's newest 1d
digest (re-derive it with a scoped bar_derivation run, todo 646). Bar density (bars over NYSE
sessions in the span) is written per member beside the same measure over the active names and is
not a pass/fail threshold.

Every inactive member also gets its proven start over its own first-to-last canonical bar span
(the 1d verdict run judges only active names, so a dead name has no start and the corpus rerun
data gate refuses it; docs/plans/2026-11-20-member-proven-start.md). The starts are printed and
written to proven_starts.csv; answered sessions are the tradeable canonical 1d bars (volume > 0, the
gate's own 1d read and no_fill), so a zero-volume placeholder session is a hole here; --apply also writes them as `proven_start_1d` integrity_monitor
facts through the verdict run's batch writer (emit_integrity_facts_async). A name whose start is
None gets a failing fact and stays refused. Each --apply appends one fact per inactive member
(the reader takes the latest), so run it once, after any member-history reload. An active name is
never written here: the verdict run owns it.

Outputs in --out: summary.json, findings.csv, coverage.csv (per-name bar density),
proven_starts.csv.

    .venv/bin/python -m scripts.ops.bars.ops_member_history_audit --out <dir> [--apply]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402
import psycopg  # noqa: E402

from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import Settings, get_settings  # noqa: E402
from src.core.integrity_monitor import emit_integrity_facts_async  # noqa: E402
from src.core.market_calendar import get_market_calendar  # noqa: E402
from src.intelligence.bars.member_history import (  # noqa: E402
    MemberStats,
    audit_members,
    bar_density,
    coverage_quantiles,
    member_proven_start,
    proven_start_fact,
)
from src.intelligence.bars.sessions import nyse_sessions  # noqa: E402

_CHUNK = 2000
_QUANTILES = (0.01, 0.05, 0.25, 0.5)
_COVERAGE_KEY = "threshold.bar_integrity.session_coverage_min_1d"  # the verdict run's own key
_COVERAGE_DEFAULT = 0.999
_WRITE_CHUNK = 1000
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
_DATES_SQL = """
SELECT symbol, ("timestamp" AT TIME ZONE 'UTC')::date
FROM market_data_ohlcv_tradeable WHERE timeframe = '1d' AND symbol = ANY(%(s)s)
"""
# bar_reconciliation_audit._EMPTY_SESSIONS_SQL (a test pins the two equal): answered-empty spans.
_EMPTY_SQL = """
SELECT symbol, (verified_from AT TIME ZONE 'UTC')::date AS span_start,
       (empty_through AT TIME ZONE 'UTC')::date AS span_end
FROM ohlcv_empty_history WHERE timeframe = '1d' AND provider = 'ibkr'
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


def read_stored_dates(conn: psycopg.Connection, symbols: list[str]) -> dict[str, set[date]]:
    dates: dict[str, set[date]] = {s: set() for s in symbols}
    for symbol, day in _rows(conn, _DATES_SQL, symbols):
        dates[symbol].add(day)
    return dates


def read_empty_spans(conn: psycopg.Connection) -> dict[str, list[tuple[date, date]]]:
    spans: dict[str, list[tuple[date, date]]] = {}
    for symbol, start, end in conn.execute(_EMPTY_SQL):
        spans.setdefault(symbol, []).append((start, end))
    return spans


async def _read_coverage_min() -> float:
    config = ConfigService(get_settings().database_url)
    await config.initialize()
    try:
        return float(await config.get(_COVERAGE_KEY, _COVERAGE_DEFAULT))
    finally:
        await config.close()


async def _write_facts(settings: Settings, facts: list[tuple]) -> int:
    """The facts through the verdict run's batch writer; returns how many of them landed (the
    writer logs and swallows an insert failure, so the caller compares the count)."""
    conn = await asyncpg.connect(settings.database_url)
    started = datetime.now(UTC)
    try:
        for lo in range(0, len(facts), _WRITE_CHUNK):
            await emit_integrity_facts_async(conn, facts[lo : lo + _WRITE_CHUNK])
        return int(
            await conn.fetchval(
                "SELECT count(*) FROM integrity_monitor WHERE monitor_type = $1"
                " AND metric_name = $2 AND evaluated_at >= $3 AND subject = ANY($4::text[])",
                facts[0][0],
                facts[0][2],
                started,
                [f[1] for f in facts],
            )
        )
    finally:
        await conn.close()


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def run(settings: Settings, out: Path, *, apply: bool = False) -> int:
    t0 = time.monotonic()
    with psycopg.connect(settings.database_url) as conn:
        members = [r[0] for r in conn.execute(_MEMBERS_SQL)]
        active = [r[0] for r in conn.execute(_ACTIVE_SQL)]
        stats = read_stats(conn, sorted(set(members) | set(active)))
        stale = read_stale(conn, members)
        inactive = sorted(set(members) - set(active))
        inactive_stats = [s for s in inactive if s in stats]
        stored_dates = read_stored_dates(conn, inactive_stats)
        empty_spans = read_empty_spans(conn)
    coverage_min = asyncio.run(_read_coverage_min())
    now = datetime.now(UTC)
    today = now.date()
    calendar = sorted(nyse_sessions(min((r.first for r in stats.values()), default=today), today))
    density = {s: bar_density(row, calendar) for s, row in stats.items()}
    findings = audit_members(members, stats, stale)
    member_set = set(members)
    quant = {
        name: coverage_quantiles([density[s] for s in group if s in density], _QUANTILES)
        for name, group in (("members", members), ("active", active))
    }
    era_start = get_market_calendar().first_session("NYSE")
    starts = {
        s: member_proven_start(
            stats[s],
            calendar,
            stored_dates[s],
            empty_spans.get(s, ()),
            coverage_min,
            era_start=era_start,
        )
        for s in inactive_stats
    }
    shifts = [(start - stats[s].first).days for s, start in starts.items() if start is not None]
    start_summary = {
        "inactive_members": len(inactive),
        "inactive_with_bars": len(inactive_stats),
        "with_start": len(shifts),
        "without_start": len(starts) - len(shifts),
        "start_shift_days_quantiles": coverage_quantiles(shifts, (0.5, 0.9, 0.99)),
        "coverage_min": coverage_min,
        "applied": apply,
    }
    if apply and starts:
        twe = datetime.combine(today, datetime.min.time(), UTC)
        facts = [proven_start_fact(s, start, twe) for s, start in sorted(starts.items())]
        written = asyncio.run(_write_facts(settings, facts))
        if written < len(facts):
            raise RuntimeError(f"proven_start_1d: wrote {written} of {len(facts)} facts")
        start_summary["facts_written"] = written
    out.mkdir(parents=True, exist_ok=True)
    write_csv(
        out / "proven_starts.csv",
        ["symbol", "first", "last", "proven_start"],
        [[s, stats[s].first, stats[s].last, start or ""] for s, start in sorted(starts.items())],
    )
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
        "proven_starts": start_summary,
        "elapsed_s": round(time.monotonic() - t0, 1),
        "passed": not findings,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return int(bool(findings))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the inactive members' proven_start_1d facts to integrity_monitor",
    )
    args = parser.parse_args(argv)
    return run(get_settings(), args.out, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
