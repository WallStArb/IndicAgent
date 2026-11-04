"""Recover the splits canonical 1d carries unadjusted, from an external split calendar (todo 587).

Canonical 1d must be split-adjusted (services/dividend_event_writer.py's basis; the panel builds on
it), but IBKR smart_trades 1d before 2016 misses about half of its splits (measured 2026-11-04).
This tool finds them from the calendar, never from jumps (a 3:2 or 5:4 split sits under any jump
threshold), and records each confirmed one as a corporate_action row, inferred_by calendar_audit
(migration 567, its own single-writer segment). Raw is never touched; applying the factor is the
daily rule's job, and the rows land in the same landing as that rule (todo 587, Order): under
today's rule a split row makes every pre-split observation stale.

Two steps, with the evidence a reviewed, committed file between them:

--audit --out CSV [--symbols ...]: read-only. Per name, Yahoo's daily split-adjusted closes and
    split events (src/providers/yahoo.py) and canonical 1d (the tradeable view). Each event is
    judged by corporate_actions.judge_calendar_split: a recognised split ratio (APR
    infra.backfill.split_ratio_*, which refuses the spin-offs Yahoo writes as fractional splits),
    canonical stepping by -log ratio across the date, Yahoo's adjusted close not stepping (APR
    threshold.split_continuity.rel_tol). Every event is written with its verdict and evidence.
--apply CSV [--commit]: re-judge each confirmed line's ratio under the current APR and insert it
    unless the name already has any corporate_action row (current, superseded or void) within a
    week of the date; one transaction under bar_derivation_writer. Dry run unless --commit.

effective_date is the last day on the old scale (migration 400's definition).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import sys
import time
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from scripts.infrastructure._write_mode_args import add_write_mode_args  # noqa: E402
from scripts.ops.bars.ops_split_detect import SPLIT_RULE_KEYS, split_rule_from_apr  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.corporate_actions import (  # noqa: E402
    SplitRatioRule,
    judge_calendar_split,
)
from src.providers.yahoo import fetch_daily_close_and_splits  # noqa: E402

REL_TOL_KEY = "threshold.split_continuity.rel_tol"
_WRITER_ROLE = "bar_derivation_writer"
# "Across the date" means sessions this close to the calendar date; a split with no session
# nearby (a hole, a listing that starts after it) is unmeasured. Definitional, not tunables.
_MAX_DAYS_AFTER = 5
_MAX_DAYS_BEFORE = 7
# Any row of the name within this many days, current, superseded or void, means the event is
# already decided (an overlap or seam row a session apart, an operator's void): never a second row.
_SAME_EVENT_DAYS = 7
# A read-only audit's patience with Yahoo's rate limit; a name still failing is a fetch_error line.
_FETCH_ATTEMPTS = 3
_FETCH_RETRY_S = 5.0

_CANONICAL_SQL = """
SELECT timestamp::date, close, vendor, kind FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = '1d' AND close > 0 ORDER BY timestamp
"""
_ACTIVE_SQL = "SELECT symbol FROM instruments WHERE is_active ORDER BY symbol"
_APR_SQL = "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)"
_EXISTING_SQL = """
SELECT action_type, effective_date, factor, inferred_by FROM corporate_action
WHERE symbol = %s AND effective_date BETWEEN %s::date - %s AND %s::date + %s
"""
_INSERT_SQL = """
INSERT INTO corporate_action
    (symbol, action_type, effective_date, factor, inferred_by, evidence_request_ids, detail)
VALUES (%s, %s, %s, %s, 'calendar_audit', '{}'::uuid[], %s::jsonb)
"""


@dataclass(frozen=True)
class CalendarEvent:
    """One calendar split event judged against canonical (one line of the audit CSV)."""

    symbol: str
    calendar_date: date
    calendar_factor: float
    effective_date: date | None  # canonical's last session on the old scale
    canonical_step: float | None
    calendar_adjusted_step: float | None
    unadjusted_vendor: str | None  # the canonical bar before the step: the span measured
    unadjusted_kind: str | None
    verdict: str  # judge_calendar_split's verdict, or "unmeasured"
    ratio: float | None


def _bracket(days: Sequence[date], on: date) -> tuple[int, int] | None:
    """Indices (last session before `on`, first on or after it), or None when not measurable."""
    after = bisect_left(days, on)
    if after == 0 or after == len(days):
        return None
    if (days[after] - on).days > _MAX_DAYS_AFTER or (on - days[after - 1]).days > _MAX_DAYS_BEFORE:
        return None
    return after - 1, after


def judge_events(
    symbol: str,
    canonical: Sequence[tuple[date, float, str, str]],
    calendar: Sequence[tuple[date, float, float]],
    rule: SplitRatioRule,
    rel_tol: float,
) -> list[CalendarEvent]:
    """Every calendar split event of one name, judged. Pure."""
    c_days = [row[0] for row in canonical]
    # yfinance can emit an action row with no price: steps use priced rows only.
    priced = [row for row in calendar if math.isfinite(row[1]) and row[1] > 0]
    y_days = [row[0] for row in priced]
    events: list[CalendarEvent] = []
    for day, _close, factor in calendar:
        if not math.isfinite(factor) or factor in (0.0, 1.0):
            continue
        c, y = _bracket(c_days, day), _bracket(y_days, day)
        if c is None or y is None:
            events.append(
                CalendarEvent(symbol, day, factor, None, None, None, None, None, "unmeasured", None)
            )
            continue
        c_step = math.log(canonical[c[1]][1] / canonical[c[0]][1])
        y_step = math.log(priced[y[1]][1] / priced[y[0]][1])
        verdict, ratio = judge_calendar_split(factor, c_step, y_step, rule, rel_tol)
        _, _, vendor, kind = canonical[c[0]]
        events.append(
            CalendarEvent(
                symbol,
                day,
                factor,
                c_days[c[0]],
                round(c_step, 6),
                round(y_step, 6),
                vendor,
                kind,
                verdict,
                ratio,
            )
        )
    return events


def _apr(conn: Any) -> tuple[SplitRatioRule, float]:
    with conn.cursor() as cur:
        cur.execute(_APR_SQL, ([*SPLIT_RULE_KEYS, REL_TOL_KEY],))
        values = dict(cur.fetchall())
    return split_rule_from_apr(values), float(values[REL_TOL_KEY])


def audit(settings: Settings, symbols: Sequence[str] | None, out: Path) -> dict[str, int]:
    """Read-only: every calendar event of every name into `out`; returns counts per verdict."""
    counts: dict[str, int] = {}
    with psycopg.connect(settings.database_url) as conn, out.open("w", newline="") as fh:
        rule, rel_tol = _apr(conn)
        names = list(symbols) if symbols else [r[0] for r in conn.execute(_ACTIVE_SQL)]
        writer = csv.DictWriter(fh, fieldnames=[*CalendarEvent.__dataclass_fields__, "error"])
        writer.writeheader()
        for symbol in names:
            for attempt in range(_FETCH_ATTEMPTS):
                calendar, error = asyncio.run(fetch_daily_close_and_splits(symbol))
                if error is None:
                    break
                time.sleep(_FETCH_RETRY_S * (attempt + 1))
            if error is not None:
                writer.writerow({"symbol": symbol, "verdict": "fetch_error", "error": error})
                counts["fetch_error"] = counts.get("fetch_error", 0) + 1
                continue
            canonical = [
                (d, float(c), v, k) for d, c, v, k in conn.execute(_CANONICAL_SQL, (symbol,))
            ]
            for event in judge_events(symbol, canonical, calendar, rule, rel_tol):
                writer.writerow({**asdict(event), "error": ""})
                counts[event.verdict] = counts.get(event.verdict, 0) + 1
    return counts


def confirmed_rows(path: Path, rule: SplitRatioRule, rel_tol: float) -> list[dict[str, Any]]:
    """The audit CSV's confirmed lines as corporate_action rows (factor = old/new-scale price).

    Each line is re-judged from its recorded steps under the current APR (a hand-edited file, or one
    from another tolerance, cannot write what the current rule would not confirm), so the rule and
    rel_tol in detail are the ones that confirmed it, beside the file's sha256."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = []
    with path.open() as fh:
        for line in csv.DictReader(fh):
            if line["verdict"] != "confirmed":
                continue
            verdict, ratio = judge_calendar_split(
                float(line["calendar_factor"]),
                float(line["canonical_step"]),
                float(line["calendar_adjusted_step"]),
                rule,
                rel_tol,
            )
            if verdict != "confirmed" or not math.isclose(ratio or 0.0, float(line["ratio"])):
                raise ValueError(
                    f"{line['symbol']} {line['calendar_date']}: {verdict} under the current APR"
                )
            rows.append(
                {
                    "symbol": line["symbol"],
                    "action_type": "split" if ratio > 1 else "reverse_split",
                    "effective_date": date.fromisoformat(line["effective_date"]),
                    "factor": ratio,
                    "detail": {
                        "calendar": "yahoo",
                        "calendar_date": line["calendar_date"],
                        "calendar_factor": float(line["calendar_factor"]),
                        "canonical_step": float(line["canonical_step"]),
                        "calendar_adjusted_step": float(line["calendar_adjusted_step"]),
                        "unadjusted_span": {
                            "vendor": line["unadjusted_vendor"],
                            "kind": line["unadjusted_kind"],
                        },
                        "audit_file": path.name,
                        "audit_sha256": digest,
                        "rule": asdict(rule),
                        "rel_tol": rel_tol,
                        "todo": 587,
                    },
                }
            )
    return rows


def apply(settings: Settings, path: Path, *, commit: bool) -> int:
    """One transaction: every confirmed row whose event is undecided; rolled back unless commit."""
    with psycopg.connect(settings.database_url) as conn:
        rule, rel_tol = _apr(conn)
        rows = confirmed_rows(path, rule, rel_tol)
        cur = conn.cursor()
        cur.execute(f"SET LOCAL ROLE {_WRITER_ROLE}")
        written = 0
        for row in rows:
            day, window = row["effective_date"], _SAME_EVENT_DAYS
            cur.execute(_EXISTING_SQL, (row["symbol"], day, window, day, window))
            existing = cur.fetchall()
            if existing:
                print(f"skipped {row['symbol']} {day} x{row['factor']}: decided by {existing}")
                continue
            cur.execute(
                _INSERT_SQL,
                (
                    row["symbol"],
                    row["action_type"],
                    day,
                    row["factor"],
                    json.dumps(row["detail"], sort_keys=True),
                ),
            )
            written += 1
        if commit:
            conn.commit()
        else:
            conn.rollback()
    print(
        f"{'wrote' if commit else 'dry run, would write'} {written} of {len(rows)} confirmed rows"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true", help="judge the calendar into --out")
    mode.add_argument("--apply", type=Path, metavar="CSV", help="write an audit's confirmed rows")
    parser.add_argument("--out", type=Path, help="--audit: the CSV to write")
    parser.add_argument("--symbols", nargs="*", default=None)
    add_write_mode_args(
        parser, dry_run="--apply: report what would be written (default)", commit="--apply: write"
    )
    args = parser.parse_args(argv)
    settings = Settings()
    if args.audit:
        if args.out is None:
            raise SystemExit("--audit needs --out")
        print(audit(settings, args.symbols, args.out))
        return 0
    return apply(settings, args.apply, commit=args.commit)


if __name__ == "__main__":
    sys.exit(main())
