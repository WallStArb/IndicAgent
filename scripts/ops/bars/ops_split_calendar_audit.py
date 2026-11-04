"""Recover the splits canonical 1d carries unadjusted, from an external split calendar (todo 587).

Canonical 1d must be split-adjusted (services/dividend_event_writer.py's basis; the panel builds on
it), but IBKR smart_trades 1d before 2016 misses about half of its splits (measured 2026-11-04).
This tool finds them from the calendar, never from jumps (a 3:2 or 5:4 split sits under any jump
threshold), and records each confirmed one as a corporate_action row, inferred_by calendar_audit
(migration 567, its own single-writer segment). Raw is never touched; applying the factor is the
daily rule's job (d2-v5), and the rows land in the same landing as that rule (todo 587, Order).

Two steps, with the evidence a reviewed, committed file between them:

--audit --out CSV [--symbols ...]: read-only. Per name, Yahoo's daily split-adjusted closes and
    split events (src/providers/yahoo.py), canonical 1d (the tradeable view) and the raw 1d series
    canonical is served from (daily_rule.RESCALABLE_SERIES). A split is confirmed by:
    1. the calendar: a recognised split ratio (APR infra.backfill.split_ratio_*, which refuses the
       spin-offs Yahoo writes as fractional splits) on its date;
    2. the price step: canonical steps by -log ratio across the date beyond Yahoo's adjusted step,
       Yahoo's adjusted close continuous (judge_calendar_split, threshold.split_continuity.rel_tol).
    The share count can only veto (lead ruling 2026-11-04): on canonical's raw series, the log
    volume step across the date over each window of threshold.split_calendar.volume_windows
    (truncated at the neighbouring calendar events), in units of log ratio, median over the
    measurable windows (share_count_stat). Below threshold.split_calendar.volume_veto_below the
    count robustly did not move (a spin-off or stock distribution): volume_veto, no row, review.
    Unmeasurable or ambiguous evidence never vetoes; the statistic is recorded either way.
    Then every raw series with an observation before the date is measured on its own: its close
    over Yahoo's adjusted close, medians over the shortest volume window's sessions on each side inside
    the neighbouring calendar events, steps by -log ratio (unadjusted, the row names it in
    unadjusted_routes and the rule rescales it), 0 (adjusted) or anything else (conflict). A
    split with a conflicting or unmeasurable series gets no row (route_conflict): the scale is
    measured per series, never assumed across a vendor seam. Every event is written with its
    verdict and evidence.
--apply CSV [--commit]: re-judge each confirmed line under the current APR and insert it unless
    the name already has any corporate_action row (current, superseded or void) within a week of
    the date; one transaction under bar_derivation_writer. Dry run unless --commit.

effective_date is the last day on the old scale (migration 400's definition).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import statistics
import sys
import time
from bisect import bisect_left
from collections.abc import Mapping, Sequence
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
    scale_step,
    share_count_stat,
    share_count_vetoes,
)
from src.intelligence.bars.daily_rule import (  # noqa: E402
    FALLBACK_PAIR,
    PRIMARY_PAIR,
    RAW_DAILY_SESSION_ZONE,
    RESCALABLE_SERIES,
    VENDOR_ALPACA,
    VENDOR_IBKR,
)
from src.providers.yahoo import fetch_daily_close_and_splits  # noqa: E402

REL_TOL_KEY = "threshold.split_continuity.rel_tol"
VOLUME_WINDOWS_KEY = "threshold.split_calendar.volume_windows"
VOLUME_VETO_KEY = "threshold.split_calendar.volume_veto_below"
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
SELECT ("timestamp" AT TIME ZONE 'UTC')::date, close, vendor, kind FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = '1d' AND close > 0 ORDER BY timestamp
"""
# The rescalable raw series as the daily read reads them (bar_derivation._SELECT_DAILY_RAW_SQL):
# session-dated in each series' zone, test callers' requests left out.
_RAW_SQL = """
SELECT r.vendor, r.kind, (r."timestamp" AT TIME ZONE s.zone)::date AS bar_date, r.close, r.volume
FROM ohlcv_raw r
JOIN unnest(%s::text[], %s::text[], %s::text[]) AS s(vendor, kind, zone)
  ON s.vendor = r.vendor AND s.kind = r.kind
LEFT JOIN ohlcv_request q ON q.request_id = r.request_id
WHERE r.symbol = %s AND r.timeframe = '1d' AND r.close > 0
  AND (q.caller IS NULL OR q.caller NOT LIKE 'test-%%')
ORDER BY bar_date
"""
_RESCALABLE = sorted(RESCALABLE_SERIES)
# The raw series each canonical (vendor, kind) is served from (canonical_bar_lineage's mapping).
_RAW_SERIES_OF = {
    PRIMARY_PAIR[VENDOR_IBKR]: (VENDOR_IBKR, "smart_trades"),
    FALLBACK_PAIR: (VENDOR_IBKR, "smart_trades"),
    PRIMARY_PAIR[VENDOR_ALPACA]: (VENDOR_ALPACA, "sip_rth"),
}
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
class Witness:
    """The share-count witness's APR (threshold.split_calendar.*, migration 571): the session
    windows the volume step is measured over (the shortest also bounds the per-series price
    medians) and the statistic below which it vetoes."""

    windows: tuple[int, ...]
    veto_below: float

    @property
    def price_sessions(self) -> int:
        return min(self.windows)


# One raw series of a name: (session date, close, volume) in date order.
RawSeries = Sequence[tuple[date, float, int | None]]


def series_key(series: tuple[str, str]) -> str:
    return f"{series[0]}/{series[1]}"


@dataclass(frozen=True)
class CalendarEvent:
    """One calendar split event judged against canonical (one line of the audit CSV)."""

    symbol: str
    calendar_date: date
    calendar_factor: float
    # judge_calendar_split's verdict, "unmeasured", or for a confirmed price step whose other
    # witnesses fail: route_conflict, volume_veto
    verdict: str
    ratio: float | None = None
    effective_date: date | None = None  # canonical's last session on the old scale
    canonical_step: float | None = None
    calendar_adjusted_step: float | None = None
    canonical_vendor: str | None = None  # the canonical bar before the step
    canonical_kind: str | None = None
    # Confirmed and adjusted events only. JSON {"vendor/kind": log step of the series' close over
    # Yahoo's across the date, or null when the series has observations before the date but
    # cannot be measured}
    route_steps: str | None = None
    # ";"-joined vendor/kind of the series measured unadjusted (what a row's detail records; on
    # an adjusted event, a series still unadjusted for a split canonical is adjusted for)
    unadjusted_routes: str | None = None
    # Confirmed price steps only, on canonical's series: share_count_stat (empty = unmeasured)
    # and the measured windows' log volume steps, a JSON list in the order of witness.windows
    # (unmeasurable windows left out)
    volume_stat: float | None = None
    volume_windows: str | None = None


def _bracket(days: Sequence[date], on: date) -> tuple[int, int] | None:
    """Indices (last session before `on`, first on or after it), or None when not measurable."""
    after = bisect_left(days, on)
    if after == 0 or after == len(days):
        return None
    if (days[after] - on).days > _MAX_DAYS_AFTER or (on - days[after - 1]).days > _MAX_DAYS_BEFORE:
        return None
    return after - 1, after


# Steps are recorded to six decimals and judged as recorded, so --apply re-judges the same numbers.
def _route_step(
    series: RawSeries,
    calendar_close: Mapping[date, float],
    day: date,
    effective: date,
    span: tuple[date, date],
    n: int,
) -> float | None:
    """log(close / calendar close) after the date minus before it, medians over the series' n
    sessions nearest the date on each side inside span (between the neighbouring calendar events,
    so no other event's factor enters). None when a side is empty, or when the series has a bar
    after effective_date and before the date (the rule rescales on or before effective_date only,
    so that bar would keep the old scale)."""
    lo, hi = span
    if any(effective < d < day for d, _, _ in series):
        return None
    before = [
        (d, c / calendar_close[d]) for d, c, _ in series if lo <= d < day and d in calendar_close
    ]
    after = [c / calendar_close[d] for d, c, _ in series if day <= d < hi and d in calendar_close]
    if not before or not after:
        return None
    step = math.log(statistics.median(after[:n]) / statistics.median(r for _, r in before[-n:]))
    return round(step, 6)


def _volume_steps(
    series: RawSeries, day: date, span: tuple[date, date], windows: Sequence[int]
) -> list[float]:
    """log(median volume after / median before) per window with n traded sessions on each side
    inside span (truncated at the neighbouring calendar events); an unmeasurable window is left
    out."""
    lo, hi = span
    before = [v for d, _, v in series if lo <= d < day and v]
    after = [v for d, _, v in series if day <= d < hi and v]
    return [
        math.log(statistics.median(after[:n]) / statistics.median(before[-n:]))
        for n in windows
        if len(before) >= n and len(after) >= n
    ]


def _unadjusted(
    route_steps: Mapping[str, float | None], ratio: float, rel_tol: float
) -> list[str] | None:
    """The series measured unadjusted, or None when any series is unmeasured or conflicts."""
    readings = {
        key: None if step is None else scale_step(step, ratio, rel_tol)
        for key, step in route_steps.items()
    }
    if any(r is None or r == "conflict" for r in readings.values()):
        return None
    return sorted(key for key, r in readings.items() if r == "unadjusted")


def _witnessed(
    canonical_series: str,
    route_steps: Mapping[str, float | None],
    volume_stat: float | None,
    witness: Witness,
    ratio: float,
    rel_tol: float,
) -> tuple[str, list[str] | None]:
    """A price-confirmed split's final verdict from the per-series scales and the share-count
    veto, and its unadjusted series. Pure; confirmed_rows re-runs it on the recorded numbers."""
    unadjusted = _unadjusted(route_steps, ratio, rel_tol)
    if unadjusted is None or canonical_series not in unadjusted:
        return "route_conflict", unadjusted
    if share_count_vetoes(volume_stat, witness.veto_below):
        return "volume_veto", unadjusted
    return "confirmed", unadjusted


def judge_events(
    symbol: str,
    canonical: Sequence[tuple[date, float, str, str]],
    calendar: Sequence[tuple[date, float, float]],
    raw: Mapping[tuple[str, str], RawSeries],
    rule: SplitRatioRule,
    rel_tol: float,
    witness: Witness,
) -> list[CalendarEvent]:
    """Every calendar split event of one name, judged. Pure."""
    c_days = [row[0] for row in canonical]
    # yfinance can emit an action row with no price: steps use priced rows only.
    priced = [row for row in calendar if math.isfinite(row[1]) and row[1] > 0]
    y_days = [row[0] for row in priced]
    y_close = {row[0]: row[1] for row in priced}
    event_days = sorted(day for day, _c, f in calendar if math.isfinite(f) and f not in (0.0, 1.0))
    events: list[CalendarEvent] = []
    for day, _close, factor in calendar:
        if not math.isfinite(factor) or factor in (0.0, 1.0):
            continue
        c, y = _bracket(c_days, day), _bracket(y_days, day)
        if c is None or y is None:
            events.append(CalendarEvent(symbol, day, factor, "unmeasured"))
            continue
        c_step = math.log(canonical[c[1]][1] / canonical[c[0]][1])
        y_step = math.log(priced[y[1]][1] / priced[y[0]][1])
        verdict, ratio = judge_calendar_split(factor, c_step, y_step, rule, rel_tol)
        effective, _, vendor, kind = canonical[c[0]]
        route_steps: dict[str, float | None] | None = None
        unadjusted: list[str] | None = None
        volume_stat = volume_windows = None
        if verdict in ("confirmed", "adjusted"):
            i = bisect_left(event_days, day)
            span = (
                event_days[i - 1] if i else date.min,
                event_days[i + 1] if i + 1 < len(event_days) else date.max,
            )
            route_steps = {
                series_key(series): _route_step(
                    rows, y_close, day, effective, span, witness.price_sessions
                )
                for series, rows in sorted(raw.items())
                if rows and rows[0][0] < day
            }
            assert ratio is not None
            if verdict == "confirmed":
                own = _RAW_SERIES_OF.get((vendor, kind))
                steps = _volume_steps(raw.get(own, ()), day, span, witness.windows)
                stat = share_count_stat(steps, ratio)
                volume_stat = None if stat is None else round(stat, 6)
                volume_windows = json.dumps([round(x, 6) for x in steps])
                verdict, unadjusted = _witnessed(
                    series_key(own) if own else "",
                    route_steps,
                    volume_stat,
                    witness,
                    ratio,
                    rel_tol,
                )
            else:
                unadjusted = _unadjusted(route_steps, ratio, rel_tol)
        events.append(
            CalendarEvent(
                symbol,
                day,
                factor,
                verdict,
                ratio,
                effective,
                round(c_step, 6),
                round(y_step, 6),
                vendor,
                kind,
                None if route_steps is None else json.dumps(route_steps, sort_keys=True),
                None if unadjusted is None else ";".join(unadjusted),
                volume_stat,
                volume_windows,
            )
        )
    return events


@dataclass(frozen=True)
class AuditParams:
    """The audit's APR (raises KeyError on a missing key: migrations 461, 567 and 571 seed them)."""

    rule: SplitRatioRule
    rel_tol: float
    witness: Witness

    @classmethod
    def from_apr(cls, values: Mapping[str, Any]) -> AuditParams:
        return cls(
            split_rule_from_apr(values),
            float(values[REL_TOL_KEY]),
            Witness(
                tuple(int(n) for n in json.loads(values[VOLUME_WINDOWS_KEY])),
                float(values[VOLUME_VETO_KEY]),
            ),
        )


def _apr(conn: Any) -> AuditParams:
    with conn.cursor() as cur:
        cur.execute(
            _APR_SQL, ([*SPLIT_RULE_KEYS, REL_TOL_KEY, VOLUME_WINDOWS_KEY, VOLUME_VETO_KEY],)
        )
        return AuditParams.from_apr(dict(cur.fetchall()))


def _raw_series(
    conn: Any, symbol: str
) -> dict[tuple[str, str], list[tuple[date, float, int | None]]]:
    vendors, kinds = zip(*_RESCALABLE, strict=True)
    zones = [RAW_DAILY_SESSION_ZONE[series] for series in _RESCALABLE]
    raw: dict[tuple[str, str], list[tuple[date, float, int | None]]] = {}
    for vendor, kind, day, close, volume in conn.execute(
        _RAW_SQL, (list(vendors), list(kinds), zones, symbol)
    ):
        raw.setdefault((vendor, kind), []).append((day, float(close), volume))
    return raw


def audit(settings: Settings, symbols: Sequence[str] | None, out: Path) -> dict[str, int]:
    """Read-only: every calendar event of every name into `out`; returns counts per verdict."""
    counts: dict[str, int] = {}
    with psycopg.connect(settings.database_url) as conn, out.open("w", newline="") as fh:
        params = _apr(conn)
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
            raw = _raw_series(conn, symbol)
            for event in judge_events(
                symbol, canonical, calendar, raw, params.rule, params.rel_tol, params.witness
            ):
                writer.writerow({**asdict(event), "error": ""})
                counts[event.verdict] = counts.get(event.verdict, 0) + 1
    return counts


def _route(key: str) -> dict[str, str]:
    vendor, kind = key.split("/")
    return {"vendor": vendor, "kind": kind}


def confirmed_rows(path: Path, params: AuditParams) -> list[dict[str, Any]]:
    """The audit CSV's confirmed lines as corporate_action rows (factor = old/new-scale price).

    Each line is re-judged from its recorded steps under the current APR, all three witnesses and
    every series' scale (a hand-edited file, or one from another tolerance, cannot write what the
    current rule would not confirm), so the parameters in detail are the ones that confirmed it,
    beside the file's sha256. detail.unadjusted_routes is the list the daily rule rescales."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = []
    with path.open() as fh:
        for line in csv.DictReader(fh):
            if line["verdict"] != "confirmed":
                continue
            where = f"{line['symbol']} {line['calendar_date']}"
            verdict, ratio = judge_calendar_split(
                float(line["calendar_factor"]),
                float(line["canonical_step"]),
                float(line["calendar_adjusted_step"]),
                params.rule,
                params.rel_tol,
            )
            if verdict != "confirmed" or not math.isclose(ratio or 0.0, float(line["ratio"])):
                raise ValueError(f"{where}: {verdict} under the current APR")
            assert ratio is not None
            route_steps = json.loads(line["route_steps"])
            own = _RAW_SERIES_OF.get((line["canonical_vendor"], line["canonical_kind"]))
            volume_stat = float(line["volume_stat"]) if line["volume_stat"] else None
            verdict, unadjusted = _witnessed(
                series_key(own) if own else "",
                route_steps,
                volume_stat,
                params.witness,
                ratio,
                params.rel_tol,
            )
            if verdict != "confirmed" or ";".join(unadjusted or ()) != line["unadjusted_routes"]:
                raise ValueError(f"{where}: {verdict} ({unadjusted}) under the current APR")
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
                        "canonical_route": {
                            "vendor": line["canonical_vendor"],
                            "kind": line["canonical_kind"],
                        },
                        "route_steps": route_steps,
                        "unadjusted_routes": [_route(key) for key in unadjusted or ()],
                        "volume": "unmeasured" if volume_stat is None else volume_stat,
                        "volume_windows": json.loads(line["volume_windows"] or "[]"),
                        "audit_file": path.name,
                        "audit_sha256": digest,
                        "rule": asdict(params.rule),
                        "rel_tol": params.rel_tol,
                        "witness": asdict(params.witness),
                        "todo": 587,
                    },
                }
            )
    return rows


def apply(settings: Settings, path: Path, *, commit: bool) -> int:
    """One transaction: every confirmed row whose event is undecided; rolled back unless commit."""
    with psycopg.connect(settings.database_url) as conn:
        rows = confirmed_rows(path, _apr(conn))
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
