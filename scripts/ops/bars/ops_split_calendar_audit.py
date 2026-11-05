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
    A spin-off a calendar writes as a clean ratio is an explicit exclusion on the operator's list
    (config/corporate_actions/spin_off_exclusions.csv: excluded_spin_off, no row; it belongs to the
    dividend/total-return layer). No automatic veto: volume and new-listing witnesses were
    measured and rejected (2026-11-04: a co-listing within a week occurs on 69% of sessions).
    Then every raw series with an observation before the date is measured on its own: its close
    over Yahoo's adjusted close, medians over threshold.split_calendar.route_sessions sessions on each side inside
    the neighbouring calendar events, steps by -log ratio (unadjusted, the row names it in
    unadjusted_routes and the rule rescales it), 0 (adjusted) or anything else (conflict). A
    split with a conflicting or unmeasurable series gets no row (route_conflict): the scale is
    measured per series, never assumed across a vendor seam. Every event is written with its
    verdict and evidence.
--quarantine-unconfirmed CSV [--commit]: quarantine the first new-scale canonical bar of every
    candidate left unconfirmed (excluded_spin_off, route_conflict, conflict) under bar_quality_flag rule
    unconfirmed_split, and every bar of config/corporate_actions/operator_bad_bars.csv under rule
    operator_bad_bar, through bar_scrub.write_flags; dry run unless --commit.
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
from collections.abc import Collection, Mapping, Sequence
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
ROUTE_SESSIONS_KEY = "threshold.split_calendar.route_sessions"
# Operator-maintained spin-offs a calendar writes as clean split ratios (todo 587 Decision point
# 2): never a split row; they belong to the dividend/total-return layer.
SPIN_OFF_EXCLUSIONS = project_root / "config" / "corporate_actions" / "spin_off_exclusions.csv"
# Operator-listed bad bars (todo 587 point 6; the planned operator_bad_bar quarantine): a calendar
# conflict whose step bracket holds one is that bar, not an unconfirmed split.
OPERATOR_BAD_BARS = project_root / "config" / "corporate_actions" / "operator_bad_bars.csv"
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
SELECT r.vendor, r.kind, (r."timestamp" AT TIME ZONE s.zone)::date AS bar_date, r.close
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


# One raw series of a name: (session date, close) in date order.
RawSeries = Sequence[tuple[date, float]]


def series_key(series: tuple[str, str]) -> str:
    return f"{series[0]}/{series[1]}"


@dataclass(frozen=True)
class CalendarEvent:
    """One calendar split event judged against canonical (one line of the audit CSV)."""

    symbol: str
    calendar_date: date
    calendar_factor: float
    # judge_calendar_split's verdict, "unmeasured", or for a confirmed price step: route_conflict
    # (a series conflicts or cannot be measured) or excluded_spin_off (the operator's list)
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
    if any(effective < d < day for d, _ in series):
        return None
    before = [c / calendar_close[d] for d, c in series if lo <= d < day and d in calendar_close]
    after = [c / calendar_close[d] for d, c in series if day <= d < hi and d in calendar_close]
    if not before or not after:
        return None
    return round(math.log(statistics.median(after[:n]) / statistics.median(before[-n:])), 6)


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


def _final_verdict(
    symbol: str,
    calendar_date: date,
    canonical_series: str,
    route_steps: Mapping[str, float | None],
    ratio: float,
    rel_tol: float,
    excluded: Collection[tuple[str, date]],
) -> tuple[str, list[str] | None]:
    """A price-confirmed split's final verdict and its unadjusted series: an operator-listed
    spin-off is excluded; otherwise every series must read unadjusted or adjusted, canonical's own
    unadjusted. Pure; confirmed_rows re-runs it on the recorded numbers."""
    unadjusted = _unadjusted(route_steps, ratio, rel_tol)
    if (symbol, calendar_date) in excluded:
        return "excluded_spin_off", unadjusted
    if unadjusted is None or canonical_series not in unadjusted:
        return "route_conflict", unadjusted
    return "confirmed", unadjusted


def judge_events(
    symbol: str,
    canonical: Sequence[tuple[date, float, str, str]],
    calendar: Sequence[tuple[date, float, float]],
    raw: Mapping[tuple[str, str], RawSeries],
    rule: SplitRatioRule,
    rel_tol: float,
    route_sessions: int,
    excluded: Collection[tuple[str, date]] = (),
) -> list[CalendarEvent]:
    """Every calendar split event of one name, judged. Pure. excluded is the operator's spin-off
    list as (symbol, calendar date)."""
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
        if verdict in ("confirmed", "adjusted"):
            assert ratio is not None
            i = bisect_left(event_days, day)
            span = (
                event_days[i - 1] if i else date.min,
                event_days[i + 1] if i + 1 < len(event_days) else date.max,
            )
            route_steps = {
                series_key(series): _route_step(rows, y_close, day, effective, span, route_sessions)
                for series, rows in sorted(raw.items())
                if rows and rows[0][0] < day
            }
            if verdict == "confirmed":
                own = _RAW_SERIES_OF.get((vendor, kind))
                verdict, unadjusted = _final_verdict(
                    symbol,
                    day,
                    series_key(own) if own else "",
                    route_steps,
                    ratio,
                    rel_tol,
                    excluded,
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
            )
        )
    return events


def operator_list(path: Path) -> dict[tuple[str, date], str]:
    """An operator list (the spin-off exclusions, the bad bars): (symbol, date) -> reason. Every
    line needs a reason and its evidence; a malformed or duplicated line raises."""
    out: dict[tuple[str, date], str] = {}
    with path.open() as fh:
        for line in csv.DictReader(fh):
            key = (line["symbol"], date.fromisoformat(line["date"]))
            if not line["reason"].strip() or not line["evidence"].strip() or key in out:
                raise ValueError(f"{path.name} {key}: needs one line with reason and evidence")
            out[key] = line["reason"]
    return out


@dataclass(frozen=True)
class AuditParams:
    """The audit's APR (raises KeyError on a missing key: migrations 461, 567 and 571 seed them)."""

    rule: SplitRatioRule
    rel_tol: float
    route_sessions: int

    @classmethod
    def from_apr(cls, values: Mapping[str, Any]) -> AuditParams:
        return cls(
            split_rule_from_apr(values),
            float(values[REL_TOL_KEY]),
            int(values[ROUTE_SESSIONS_KEY]),
        )


def _apr(conn: Any) -> AuditParams:
    with conn.cursor() as cur:
        cur.execute(_APR_SQL, ([*SPLIT_RULE_KEYS, REL_TOL_KEY, ROUTE_SESSIONS_KEY],))
        return AuditParams.from_apr(dict(cur.fetchall()))


def _raw_series(conn: Any, symbol: str) -> dict[tuple[str, str], list[tuple[date, float]]]:
    vendors, kinds = zip(*_RESCALABLE, strict=True)
    zones = [RAW_DAILY_SESSION_ZONE[series] for series in _RESCALABLE]
    raw: dict[tuple[str, str], list[tuple[date, float]]] = {}
    for vendor, kind, day, close in conn.execute(
        _RAW_SQL, (list(vendors), list(kinds), zones, symbol)
    ):
        raw.setdefault((vendor, kind), []).append((day, float(close)))
    return raw


def audit(settings: Settings, symbols: Sequence[str] | None, out: Path) -> dict[str, int]:
    """Read-only: every calendar event of every name into `out`; returns counts per verdict."""
    counts: dict[str, int] = {}
    excluded = operator_list(SPIN_OFF_EXCLUSIONS)
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
            for event in judge_events(
                symbol,
                canonical,
                calendar,
                _raw_series(conn, symbol),
                params.rule,
                params.rel_tol,
                params.route_sessions,
                excluded,
            ):
                writer.writerow({**asdict(event), "error": ""})
                counts[event.verdict] = counts.get(event.verdict, 0) + 1
    return counts


def _route(key: str) -> dict[str, str]:
    vendor, kind = key.split("/")
    return {"vendor": vendor, "kind": kind}


def confirmed_rows(
    path: Path, params: AuditParams, excluded: Collection[tuple[str, date]] | None = None
) -> list[dict[str, Any]]:
    """The audit CSV's confirmed lines as corporate_action rows (factor = old/new-scale price).

    Each line is re-judged from its recorded steps under the current APR and the current spin-off
    list, every series' scale included (a hand-edited file, or one from another tolerance, cannot
    write what the current rule would not confirm), so the parameters in detail are the ones that confirmed it,
    beside the file's sha256. detail.unadjusted_routes is the list the daily rule rescales."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if excluded is None:
        excluded = operator_list(SPIN_OFF_EXCLUSIONS)
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
            verdict, unadjusted = _final_verdict(
                line["symbol"],
                date.fromisoformat(line["calendar_date"]),
                series_key(own) if own else "",
                route_steps,
                ratio,
                params.rel_tol,
                excluded,
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
                        "audit_file": path.name,
                        "audit_sha256": digest,
                        "rule": asdict(params.rule),
                        "rel_tol": params.rel_tol,
                        "route_sessions": params.route_sessions,
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


# The loud flag of every calendar split left unconfirmed (lead ruling 2026-11-04): its first
# new-scale canonical bar is quarantined (the rule is in threshold.bar_scrub.quarantine_rules,
# migration 571), so no one-day fabricated return reaches research. Multi-day returns and rolling
# kernels still span the break: open item on todo 587's review list.
UNCONFIRMED_RULE = "unconfirmed_split"
# The operator's listed bad bars (operator_bad_bars.csv) are quarantined in the same step.
BAD_BAR_RULE = "operator_bad_bar"
UNCONFIRMED_RULE_VERSION = "split-calendar-audit"
_UNCONFIRMED_VERDICTS = frozenset({"excluded_spin_off", "route_conflict", "conflict"})
_UNCONFIRMED_FIELDS = ("open", "high", "low", "close")
_FIRST_NEW_SCALE_SQL = """
SELECT min("timestamp") FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND volume > 0
  AND "timestamp" >= (($2::date + 1)::timestamp AT TIME ZONE 'UTC')
"""
_QUARANTINE_RULES_SQL = "SELECT config_value FROM config_state WHERE config_key = 'threshold.bar_scrub.quarantine_rules'"
_FLAGGED_SQL = "SELECT DISTINCT symbol FROM bar_quality_flag WHERE timeframe = '1d' AND rule = $1"
_BAR_SQL = """
SELECT "timestamp" FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND "timestamp" = ($2::date::timestamp AT TIME ZONE 'UTC')
"""


def unconfirmed_candidates(
    path: Path, bad_bars: Collection[tuple[str, date]] | None = None
) -> list[dict[str, Any]]:
    """The audit CSV's measured split candidates left without a row (the review list): an
    excluded spin-off, a series conflict, or a price step at a different ratio. A conflict whose
    step bracket (effective_date to the calendar date) holds an operator-listed bad bar is that
    bar, not an unconfirmed split, and is left out. Each carries what the flag records."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if bad_bars is None:
        bad_bars = operator_list(OPERATOR_BAD_BARS)

    def is_bad_bar(line: dict[str, str]) -> bool:
        lo, hi = (date.fromisoformat(line[k]) for k in ("effective_date", "calendar_date"))
        return line["verdict"] == "conflict" and any(
            symbol == line["symbol"] and lo <= day <= hi for symbol, day in bad_bars
        )

    with path.open() as fh:
        return [
            {
                "symbol": line["symbol"],
                "effective_date": date.fromisoformat(line["effective_date"]),
                "detail": {
                    "calendar_date": line["calendar_date"],
                    "calendar_factor": float(line["calendar_factor"]),
                    "verdict": line["verdict"],
                    "canonical_step": float(line["canonical_step"]),
                    "audit_file": path.name,
                    "audit_sha256": digest,
                    "todo": 587,
                },
            }
            for line in csv.DictReader(fh)
            if line["verdict"] in _UNCONFIRMED_VERDICTS and not is_bad_bar(line)
        ]


async def quarantine_unconfirmed(conn: Any, path: Path, *, commit: bool) -> int:
    """One transaction, one scrub batch, through bar_scrub.write_flags; rolled back unless commit:
    - unconfirmed_split on the first traded canonical bar after each unconfirmed candidate's
      effective_date (the raw table, so a re-run finds the same bar once it is quarantined);
    - operator_bad_bar on every bar of operator_bad_bars.csv.
    Each rule is this tool's alone, so it is replaced globally (a name flagged today but absent
    from the files is cleared) and a re-run writes the same rows. Refuses unless both rules
    quarantine (APR list), and when a candidate has no bar after its date or a listed bad bar is
    not stored."""
    from services.bar_derivation_batch import close_batch, open_batch
    from services.bar_scrub import FlagRow, write_flags

    rules = json.loads(await conn.fetchval(_QUARANTINE_RULES_SQL) or "[]")
    for rule in (UNCONFIRMED_RULE, BAD_BAR_RULE):
        if rule not in rules:
            raise ValueError(f"{rule!r} is not in threshold.bar_scrub.quarantine_rules")
    tx = conn.transaction()
    await tx.start()
    try:
        flags: dict[tuple[str, str], list[FlagRow]] = {}
        for rule in (UNCONFIRMED_RULE, BAD_BAR_RULE):
            for r in await conn.fetch(_FLAGGED_SQL, rule):
                flags[(rule, r["symbol"])] = []

        def add(rule: str, symbol: str, stamp: Any, detail: dict[str, Any]) -> None:
            flags.setdefault((rule, symbol), []).append(
                FlagRow(stamp, rule, UNCONFIRMED_RULE_VERSION, _UNCONFIRMED_FIELDS, True, detail)
            )

        for c in unconfirmed_candidates(path):
            stamp = await conn.fetchval(_FIRST_NEW_SCALE_SQL, c["symbol"], c["effective_date"])
            if stamp is None:
                raise ValueError(f"{c['symbol']} has no canonical bar after {c['effective_date']}")
            add(UNCONFIRMED_RULE, c["symbol"], stamp, c["detail"])
        for (symbol, day), reason in sorted(operator_list(OPERATOR_BAD_BARS).items()):
            stamp = await conn.fetchval(_BAR_SQL, symbol, day)
            if stamp is None:
                raise ValueError(f"listed bad bar {symbol} {day} is not a stored 1d bar")
            add(BAD_BAR_RULE, symbol, stamp, {"reason": reason, "list": OPERATOR_BAD_BARS.name})
        batch_id = await open_batch(
            conn,
            stage="scrub",
            rule_version=UNCONFIRMED_RULE_VERSION,
            apr_snapshot={"threshold.bar_scrub.quarantine_rules": [UNCONFIRMED_RULE, BAD_BAR_RULE]},
            n_symbols=len({symbol for _, symbol in flags}),
            detail={"source": "ops_split_calendar_audit --quarantine-unconfirmed", "todo": 587},
        )
        written = 0
        for (rule, symbol), rows in sorted(flags.items()):
            written += await write_flags(
                conn,
                tf="1d",
                symbol=symbol,
                rules_evaluated=frozenset({rule}),
                flags=rows,
                start=None,
                end=None,
                batch_id=batch_id,
            )
        await close_batch(conn, batch_id, status="completed", detail={"quarantined": written})
    except BaseException:
        await tx.rollback()
        raise
    if commit:
        await tx.commit()
    else:
        await tx.rollback()
    print(f"{'quarantined' if commit else 'dry run, would quarantine'} {written} bars")
    return written


async def _quarantine(settings: Settings, path: Path, *, commit: bool) -> int:
    import asyncpg

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        await quarantine_unconfirmed(conn, path, commit=commit)
    finally:
        await conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true", help="judge the calendar into --out")
    mode.add_argument("--apply", type=Path, metavar="CSV", help="write an audit's confirmed rows")
    mode.add_argument(
        "--quarantine-unconfirmed",
        type=Path,
        metavar="CSV",
        help="quarantine every unconfirmed candidate's first new-scale bar (unconfirmed_split) "
        "and every listed bad bar (operator_bad_bar)",
    )
    parser.add_argument("--out", type=Path, help="--audit: the CSV to write")
    parser.add_argument("--symbols", nargs="*", default=None)
    add_write_mode_args(
        parser,
        dry_run="--apply/--quarantine-unconfirmed: report what would be written (default)",
        commit="--apply/--quarantine-unconfirmed: write",
    )
    args = parser.parse_args(argv)
    settings = Settings()
    if args.audit:
        if args.out is None:
            raise SystemExit("--audit needs --out")
        print(audit(settings, args.symbols, args.out))
        return 0
    if args.quarantine_unconfirmed:
        return asyncio.run(_quarantine(settings, args.quarantine_unconfirmed, commit=args.commit))
    return apply(settings, args.apply, commit=args.commit)


if __name__ == "__main__":
    sys.exit(main())
