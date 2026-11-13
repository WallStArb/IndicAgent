"""Expected delta of the Massive switch without IBKR, and every slot it loses, classified (todo 600
step 7; runbook docs/operations/massive-step7-runbook.md, A2 and D1).

Read-only (a read-only session; temp nothing, write nothing). Run it against the live selection
BEFORE the drop. Per (timeframe, UTC month) of canonical ``market_data_ohlcv`` it full-joins the
canonical slots with Massive's raw slots (5m ``sip_flat_agg`` by stamp, 1d ``sip_flat`` by
session date) and counts, under the switch policy (``ops_massive_policy_plan``: Massive before the
archive end, Alpaca from it, no fallback, nothing before Massive's first file):

- before, before_ibkr, before_alpaca: canonical rows now
- pre_start: canonical rows before 2003-09-10 (they leave: no source)
- massive: Massive raw slots in [2003-09-10, archive end) (they become canonical)
- moved_alpaca, moved_ibkr: canonical slots in that span that Massive also holds (vendor changes)
- gained: Massive slots canonical lacks today
- lost_alpaca, lost_ibkr: canonical slots in that span Massive lacks (they leave; classified)
- gap_alpaca: Alpaca slots inside a gap-list span from 2016-01-04 (the plan's Alpaca gap rows
  keep them, byte-identical); gap_other: other slots there (they leave: no fallback)
- after_end_alpaca: Alpaca slots from the archive end (byte-identical after the rebuild)
- after_end_other: other slots from the archive end (they leave: no fallback)
- expected_after = massive + gap_alpaca + after_end_alpaca

The card compare (runbook D1) must show exactly ``expected_after`` rows per (timeframe, month)
after the rebuild. 1m (IBKR only) leaves whole by ruling; the runbook counts it with one query.

Every lost slot is classified (``classify_loss``), in this order: ``gap_list`` (an identity gap
span covers it: unplaced, no source by design), ``after_listing_end`` (after the name's recorded
last session), ``zero_volume`` (the incumbent bar has zero or unknown volume: a non-trade
placeholder the tradeable view drops anyway), ``no_ticker_span`` (no Massive ticker span of the
name covers the date: a mapping hole, to be fixed, not an accepted loss), ``unexplained``. 5m
losses are one row per (name, session, vendor, volume class) with the slot count.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from scripts.ops.bars.ops_massive_policy_plan import (  # noqa: E402
    ALPACA_FIRST_DAY,
    DEFAULT_MANIFEST,
    GapRow,
    archive_end_of,
    read_gap_list,
)
from src.config.settings import get_settings  # noqa: E402
from src.intelligence.bars.ticker_entity_map import MASSIVE_ARCHIVE_START  # noqa: E402

MASSIVE_KIND = {"5m": "sip_flat_agg", "1d": "sip_flat"}
CAUSES = ("gap_list", "after_listing_end", "zero_volume", "no_ticker_span", "unexplained")
DELTA_FIELDS = (
    "timeframe",
    "month",
    "before",
    "before_ibkr",
    "before_alpaca",
    "pre_start",
    "massive",
    "moved_alpaca",
    "moved_ibkr",
    "gained",
    "lost_alpaca",
    "lost_ibkr",
    "gap_alpaca",
    "gap_other",
    "after_end_alpaca",
    "after_end_other",
    "expected_after",
)
LOSS_FIELDS = ("timeframe", "symbol", "session", "vendor", "zero_volume", "slots", "cause")

#: One grouped row of the month join: (symbol, session date, canonical vendor or None, zero or
#: unknown canonical volume, in canonical, in Massive raw, slot count).
_JOIN_SQL = """
WITH c AS (
    SELECT symbol, {c_key} AS k, {c_day} AS d, vendor, coalesce(volume, 0) = 0 AS zero
    FROM market_data_ohlcv
    WHERE timeframe = %(tf)s AND "timestamp" >= %(lo)s AND "timestamp" < %(hi)s
), m AS (
    SELECT symbol, {m_key} AS k, {m_day} AS d
    FROM ohlcv_raw
    WHERE timeframe = %(tf)s AND vendor = 'massive' AND kind = %(kind)s
      AND "timestamp" >= %(raw_lo)s AND "timestamp" < %(raw_hi)s
)
SELECT coalesce(c.symbol, m.symbol), coalesce(c.d, m.d), c.vendor, coalesce(c.zero, false),
       c.symbol IS NOT NULL, m.symbol IS NOT NULL, count(*)
FROM c FULL JOIN m ON c.symbol = m.symbol AND c.k = m.k
WHERE coalesce(c.d, m.d) >= %(lo_day)s AND coalesce(c.d, m.d) < %(hi_day)s
GROUP BY 1, 2, 3, 4, 5, 6
"""
_NY = "AT TIME ZONE 'America/New_York'"
_RAW_DAY = f'("timestamp" {_NY})::date'  # a raw bar's session date
_KEYS = {
    # 5m: the bar stamp on both sides; 1d: canonical is stamped at the UTC date, raw at New York
    # midnight, so the key is the session date
    "5m": {"c_key": '"timestamp"', "c_day": f'("timestamp" {_NY})::date', "m_key": '"timestamp"'},
    "1d": {
        "c_key": "(\"timestamp\" AT TIME ZONE 'UTC')::date",
        "c_day": "(\"timestamp\" AT TIME ZONE 'UTC')::date",
        "m_key": f'("timestamp" {_NY})::date',
    },
}
_SPANS_SQL = """
SELECT symbol, valid_from, valid_to FROM ticker_event_current
WHERE vendor = 'massive' AND retired_at IS NULL
"""
_LISTING_END_SQL = "SELECT symbol, last_session FROM listing_end_current"
_MONTHS_SQL = """
SELECT DISTINCT date_trunc('month', "timestamp" AT TIME ZONE 'UTC')::date
FROM market_data_ohlcv WHERE timeframe = %s ORDER BY 1
"""


@dataclass(frozen=True)
class Group:
    symbol: str
    day: date
    vendor: str | None
    zero: bool
    in_canonical: bool
    in_massive: bool
    n: int


@dataclass(frozen=True)
class Identity:
    """The facts a lost slot is classified by."""

    gaps: Mapping[str, Sequence[GapRow]]
    spans: Mapping[str, Sequence[tuple[date, date | None]]]
    listing_end: Mapping[str, date]

    def gap_covers(self, symbol: str, day: date) -> bool:
        return any(
            (g.valid_from is None or g.valid_from <= day)
            and (g.valid_to is None or day < g.valid_to)
            for g in self.gaps.get(symbol, ())
        )

    def span_covers(self, symbol: str, day: date) -> bool:
        return any(a <= day and (b is None or day < b) for a, b in self.spans.get(symbol, ()))


def classify_loss(identity: Identity, symbol: str, day: date, zero: bool) -> str:
    """The cause of one lost slot (module docstring order)."""
    if identity.gap_covers(symbol, day):
        return "gap_list"
    end = identity.listing_end.get(symbol)
    if end is not None and day > end:
        return "after_listing_end"
    if zero:
        return "zero_volume"
    if not identity.span_covers(symbol, day):
        return "no_ticker_span"
    return "unexplained"


def tally(
    groups: Iterable[Group], timeframe: str, month: date, archive_end: date, identity: Identity
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The delta row of one (timeframe, month) and its lost-slot rows."""
    row: dict[str, Any] = dict.fromkeys(DELTA_FIELDS, 0)
    row.update(timeframe=timeframe, month=month.isoformat())
    losses: list[dict[str, Any]] = []
    for g in groups:
        if g.in_canonical:
            row["before"] += g.n
            if g.vendor in ("ibkr", "alpaca"):
                row[f"before_{g.vendor}"] += g.n
        if g.day < MASSIVE_ARCHIVE_START:
            row["pre_start"] += g.n if g.in_canonical else 0
            continue
        if g.day >= archive_end:
            if g.in_canonical:
                key = "after_end_alpaca" if g.vendor == "alpaca" else "after_end_other"
                row[key] += g.n
            continue
        if g.day >= ALPACA_FIRST_DAY and identity.gap_covers(g.symbol, g.day):
            # an Alpaca gap row: Massive holds nothing here (the name is unplaced)
            if g.in_canonical:
                row["gap_alpaca" if g.vendor == "alpaca" else "gap_other"] += g.n
            continue
        if g.in_massive:
            row["massive"] += g.n
            if not g.in_canonical:
                row["gained"] += g.n
            elif g.vendor in ("ibkr", "alpaca"):
                row[f"moved_{g.vendor}"] += g.n
            continue
        if g.vendor not in ("ibkr", "alpaca"):
            raise ValueError(f"{timeframe} {g.symbol} {g.day}: canonical vendor {g.vendor!r}")
        row[f"lost_{g.vendor}"] += g.n
        losses.append(
            {
                "timeframe": timeframe,
                "symbol": g.symbol,
                "session": g.day.isoformat(),
                "vendor": g.vendor,
                "zero_volume": g.zero,
                "slots": g.n,
                "cause": classify_loss(identity, g.symbol, g.day, g.zero),
            }
        )
    row["expected_after"] = row["massive"] + row["gap_alpaca"] + row["after_end_alpaca"]
    return row, losses


def month_bounds(month: date) -> tuple[datetime, datetime]:
    nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return (
        datetime(month.year, month.month, 1, tzinfo=UTC),
        datetime(nxt.year, nxt.month, 1, tzinfo=UTC),
    )


def read_identity(conn: Any, gaps: Sequence[GapRow]) -> Identity:
    by_gap: dict[str, list[GapRow]] = defaultdict(list)
    for g in gaps:
        by_gap[g.symbol].append(g)
    spans: dict[str, list[tuple[date, date | None]]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(_SPANS_SQL)
        for symbol, start, end in cur.fetchall():
            spans[symbol].append((start, end))
        cur.execute(_LISTING_END_SQL)
        listing_end = dict(cur.fetchall())
    return Identity(dict(by_gap), dict(spans), listing_end)


def month_groups(conn: Any, timeframe: str, month: date) -> list[Group]:
    lo, hi = month_bounds(month)
    # 1d raw is stamped at New York midnight: read one day either side, keep the month's sessions
    pad = timedelta(days=1 if timeframe == "1d" else 0)
    sql = _JOIN_SQL.format(**_KEYS[timeframe], m_day=_RAW_DAY)
    params = {
        "tf": timeframe,
        "kind": MASSIVE_KIND[timeframe],
        "lo": lo,
        "hi": hi,
        "raw_lo": lo - pad,
        "raw_hi": hi + pad,
        "lo_day": lo.date(),
        "hi_day": hi.date(),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [Group(*r) for r in cur.fetchall()]


def summarize(losses: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    """Per timeframe and cause: slots, name-sessions and names."""
    slots: Counter[tuple[str, str]] = Counter()
    sessions: Counter[tuple[str, str]] = Counter()
    names: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in losses:
        key = (r["timeframe"], r["cause"])
        slots[key] += r["slots"]
        sessions[key] += 1
        names[key].add(r["symbol"])
    out: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)
    for tf, cause in sorted(slots):
        out[tf][cause] = {
            "slots": slots[(tf, cause)],
            "name_sessions": sessions[(tf, cause)],
            "names": len(names[(tf, cause)]),
        }
    return dict(out)


def _write_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeframes", nargs="+", default=["1d", "5m"], choices=sorted(_KEYS))
    parser.add_argument("--gap-list", required=True, help="the pinned identity gap_list.csv")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    args = parser.parse_args(argv)
    archive_end = archive_end_of(Path(args.manifest).read_bytes())
    args.out.mkdir(parents=True, exist_ok=True)
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    deltas: list[dict[str, Any]] = []
    losses: list[dict[str, Any]] = []
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
        identity = read_identity(conn, read_gap_list(Path(args.gap_list)))
        for tf in args.timeframes:
            with conn.cursor() as cur:
                cur.execute(_MONTHS_SQL, (tf,))
                months = [r[0] for r in cur.fetchall()]
            last = date(archive_end.year, archive_end.month, 1)
            months = sorted(set(months) | {last})
            for month in months:
                row, lost = tally(month_groups(conn, tf, month), tf, month, archive_end, identity)
                deltas.append(row)
                losses += lost
                print(
                    f"{tf} {month}: before {row['before']}, after {row['expected_after']}",
                    flush=True,
                )
    _write_csv(args.out / "switch_delta.csv", DELTA_FIELDS, deltas)
    _write_csv(args.out / "switch_losses.csv", LOSS_FIELDS, losses)
    totals = {
        tf: {f: sum(r[f] for r in deltas if r["timeframe"] == tf) for f in DELTA_FIELDS[2:]}
        for tf in args.timeframes
    }
    summary = {
        "archive_end": archive_end.isoformat(),
        "gap_list": args.gap_list,
        "totals": totals,
        "losses": summarize(losses),
    }
    (args.out / "switch_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
