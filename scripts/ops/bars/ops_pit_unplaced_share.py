"""The unplaced share of liquid rows, by year and served type (todo 609, preregistration amendment
2026-11-13: "the survivorship residual, the unplaced share of rows meeting the rule, by year and
type, is measured after the capture and recorded before membership is built").

Read-only. A row is one ticker on one session of the Massive day files as served; it meets the
rule when its same-session dollar volume (close times volume) is at or above the membership
floor, and it is placed when a live ``ticker_event`` span of that ticker covers the session (the
installed pit map plus the stage 1 map). The type is the one the month-end snapshot serves for
the ticker (active list first, then inactive), ``none`` when no snapshot names it. No return is
read: the measure uses the close level, the volume and the dates only.

    .venv/bin/python -m scripts.ops.bars.ops_pit_unplaced_share --out OUT.csv

Run after the pit install (so the spans exist) and before ``universe_membership`` is built; show
the table to the owner (``members_tier`` gate 5 reads it).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path

import psycopg

from src.config.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
# Preregistered liquidity floor to enter (2026-11-13), a research-design constant, not an APR key.
MEMBERSHIP_FLOOR_USD = 1_000_000.0

Spans = Mapping[str, Sequence[tuple[date, date | None]]]


def covered(
    spans: Spans, ticker: str, day: date, starts: Mapping[str, list[date]] | None = None
) -> bool:
    """True when one span ``[start, end)`` of the ticker holds the day (end None is open).
    ``starts`` (ticker -> sorted span starts) avoids rebuilding the list on every call."""
    rows = spans.get(ticker)
    if not rows:
        return False
    keys = starts[ticker] if starts is not None else [s for s, _ in rows]
    i = bisect_right(keys, day) - 1
    return i >= 0 and (rows[i][1] is None or day < rows[i][1])


def tally(
    days: Iterable[tuple[date, Iterable[tuple[str, float]]]],
    spans: Spans,
    type_of: Mapping[tuple[str, int, int], str],
    floor: float = MEMBERSHIP_FLOOR_USD,
) -> Counter[tuple[int, str, bool]]:
    """Rows meeting the floor per (year, type, placed). ``days`` yields a session and its
    ``(ticker, dollar volume)`` pairs; ``type_of`` maps (ticker, year, month) to a served type."""
    out: Counter[tuple[int, str, bool]] = Counter()
    starts = {ticker: [s for s, _ in rows] for ticker, rows in spans.items()}
    for day, rows in days:
        year, month = day.year, day.month
        for ticker, dollars in rows:
            if dollars >= floor:
                kind = type_of.get((ticker, year, month), "none")
                out[(year, kind, covered(spans, ticker, day, starts))] += 1
    return out


def report_rows(counts: Counter[tuple[int, str, bool]]) -> list[dict[str, object]]:
    keys = sorted({(y, t) for y, t, _ in counts})
    rows = []
    for year, kind in keys:
        placed, unplaced = counts[(year, kind, True)], counts[(year, kind, False)]
        total = placed + unplaced
        rows.append(
            {"year": year, "type": kind, "rows_meeting_floor": total, "placed": placed,
             "unplaced": unplaced, "unplaced_share": round(unplaced / total, 6) if total else 0.0}
        )  # fmt: skip
    return rows


def served_types(snapshot_dir: Path) -> dict[tuple[str, int, int], str]:
    """(ticker, year, month) -> type from the month-end lists, active before inactive."""
    out: dict[tuple[str, int, int], str] = {}
    for path in sorted(snapshot_dir.glob("*.json.gz")):
        stamp, _, rest = path.name.partition("%40")
        kind = rest.split("__")[0]
        day = date.fromisoformat(stamp)
        with gzip.open(path, "rt") as handle:
            body = json.load(handle)
        for r in body.get("results", []):
            key = (r.get("ticker", ""), day.year, day.month)
            if r.get("type") and (kind == "active" or key not in out):
                out[key] = r["type"]
    return out


def day_rows(path: Path) -> Iterable[tuple[str, float]]:
    with gzip.open(path, "rt", newline="") as handle:
        for r in csv.DictReader(handle):
            yield r["ticker"], float(r["close"]) * float(r["volume"])


def live_spans(dsn: str) -> dict[str, list[tuple[date, date | None]]]:
    sql = "SELECT ticker, valid_from, valid_to FROM ticker_event_current WHERE vendor = 'massive'"
    spans: dict[str, list[tuple[date, date | None]]] = {}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)
        for ticker, start, end in cur:
            spans.setdefault(ticker, []).append((start, end))
    for rows in spans.values():
        rows.sort(key=lambda r: r[0])
    return spans


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=REPO_ROOT / "data" / "massive")
    parser.add_argument("--snapshots", default=None, help="pit_snapshots capture date directory")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        print(f"REFUSING: {args.out} exists; evidence is never overwritten", file=sys.stderr)
        return 2
    root = args.data_root
    snap_dir = root / "reference" / "pit_snapshots"
    captures = sorted(p for p in snap_dir.iterdir() if p.is_dir())
    if not captures:
        print(f"REFUSING: no pit snapshot capture under {snap_dir}", file=sys.stderr)
        return 2
    chosen = snap_dir / args.snapshots if args.snapshots else captures[-1]
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    spans = live_spans(dsn)
    types = served_types(chosen)
    files = sorted((root / "files" / "day_aggs_v1").rglob("*.csv.gz"))

    def days() -> Iterable[tuple[date, Iterable[tuple[str, float]]]]:
        for f in files:
            yield date.fromisoformat(f.name.removesuffix(".csv.gz")), day_rows(f)

    rows = report_rows(tally(days(), spans, types))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} (year, type) rows written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
