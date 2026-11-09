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
--apply-rows CSV [--commit]: insert the operator rows file (todo 592) as corporate_action rows,
    same transaction and same existing-row guard. The calendar itself cannot confirm these: the
    vendor restated its history at its own date or depth (FBIZ, IJR, NVDA, PATK, WST), or the
    split witness is another raw series rather than Yahoo's calendar (UHAL). Each line carries
    the measured factor, the rescaled series, the day's real move, and its evidence; the rule
    (d2-v5) rescales it exactly as a confirmed split. Dry run unless --commit.
--sweep --out CSV [--rows-out CSV] [--symbols ...]: read-only (todo 592, the class emerged).
    Every lone break of canonical 1d - a |ln step| over the sweep threshold on a day when at
    most the sweep's name cap steps, so market-wide crash days stay out - classified by the
    per-series method that decided the ten landed cases: Yahoo's adjusted close is the
    continuity witness (it carries real moves, never split rescales), and every rescalable raw
    series is measured on its own across the break. Verdicts: single_bar_reversal (next session
    reverses the step; the odd bar quarantines via operator_bad_bars.csv), real_move (Yahoo
    adjusted carries the step; left alone), junction_rescale (canonical switches serving series
    and the pre series sits off correct by a constant factor; a rescale row), inseries_rescale
    (the serving tape itself switches scale at the break, a calendar event nearby: the FBIZ
    class; a rescale row), unrecorded_split (the tape switches scale with no calendar record -
    the jump side is dominated by unrecorded reverse splits; a rescale row), reported (anything
    the witnesses do not decide: no fix without vendor agreement). --rows-out writes the
    operator-rows lines for the three row verdicts; the worker reviews and lands them through
    --apply-rows.

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
from collections.abc import Callable, Collection, Mapping, Sequence
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
    rescale_routes,
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


def _fetch_calendar(symbol: str) -> tuple[list[tuple[date, float, float]], str | None]:
    """Yahoo's daily closes and split events, retried against its rate limit; (calendar, error)."""
    for attempt in range(_FETCH_ATTEMPTS):
        calendar, error = asyncio.run(fetch_daily_close_and_splits(symbol))
        if error is None:
            return calendar, None
        time.sleep(_FETCH_RETRY_S * (attempt + 1))
    return calendar, error


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
            calendar, error = _fetch_calendar(symbol)
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


# The operator rows file's columns (todo 592): every column required, every line its own evidence.
OPERATOR_ROWS_COLUMNS = (
    "symbol",
    "effective_date",
    "factor",
    "unadjusted_routes",
    "calendar_adjusted_step",
    "reason",
    "evidence",
)


# The factor plausibility bound (corporate_actions._MAX_SPLIT_TERMS's interface bound): a
# recorded factor outside it is a hand-edit typo, not a measured vendor scale.
_OPERATOR_ROWS_MAX_FACTOR = 50.0


def operator_rows(path: Path) -> list[dict[str, Any]]:
    """The operator rows file as corporate_action rows (todo 592): the rows the calendar cannot
    confirm, measured by hand per the audit's per-series method and decided by the lead.

    factor is the recorded old-scale/new-scale price the daily rule divides by, so a vendor whose
    series sits at half the correct level records 0.5 (the rule doubles it) and an unadjusted
    2:1 records 2.0; a measured factor need be no clean ratio (PATK's 2.5 is the vendor's exact
    scale), so the only bound is the split-ratio interface bound. effective_date is the last day
    on the old scale of the recorded series (migration 400). unadjusted_routes is the
    ';'-joined rescalable series the rule rescales on or before it (RESCALABLE_SERIES; at least
    one, each named once, the rule raises without). calendar_adjusted_step is the day's real
    move at the effective date (Yahoo's adjusted close, or the witnessing series' own continuous
    step), what D7 judges the date against. detail carries all of it, the reason, the evidence,
    and the file's sha256. The symbol is stripped; every rejection names its line."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rows: list[dict[str, Any]] = []
    decided: set[tuple[str, date]] = set()
    with path.open() as fh:
        for line in csv.DictReader(fh):
            empty = [c for c in OPERATOR_ROWS_COLUMNS if not (line.get(c) or "").strip()]
            if empty:
                raise ValueError(f"{path.name}: {empty} missing on a line")
            symbol, day = line["symbol"].strip(), date.fromisoformat(line["effective_date"])
            where = f"{symbol} {day}"
            factor = float(line["factor"])
            if not (
                math.isfinite(factor)
                and 1.0 / _OPERATOR_ROWS_MAX_FACTOR <= factor <= _OPERATOR_ROWS_MAX_FACTOR
                and factor != 1
            ):
                raise ValueError(f"{where}: unusable factor {factor!r}")
            step = float(line["calendar_adjusted_step"])
            if not math.isfinite(step):
                raise ValueError(f"{where}: unusable calendar_adjusted_step {step!r}")
            routes = []
            for key in line["unadjusted_routes"].split(";"):
                try:
                    route = _route(key.strip())
                except ValueError:
                    raise ValueError(f"{where}: malformed route {key.strip()!r}") from None
                # Raises on a series the rule cannot rescale.
                rescale_routes(route["vendor"], route["kind"])
                if route in routes:
                    raise ValueError(f"{where}: {key.strip()} named twice")
                routes.append(route)
            if (symbol, day) in decided:
                raise ValueError(f"{where}: decided twice in {path.name}")
            decided.add((symbol, day))
            rows.append(
                {
                    "symbol": symbol,
                    "action_type": "split" if factor > 1 else "reverse_split",
                    "effective_date": day,
                    "factor": factor,
                    "detail": {
                        "unadjusted_routes": routes,
                        "calendar_adjusted_step": step,
                        "reason": line["reason"].strip(),
                        "evidence": line["evidence"].strip(),
                        "rows_file": path.name,
                        "rows_sha256": digest,
                        "todo": 592,
                    },
                }
            )
    return rows


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


def _apply_decided(
    settings: Settings, build_rows: Callable[[Any], Sequence[dict[str, Any]]], *, commit: bool
) -> int:
    """One connection, one transaction: build_rows reads what it needs on the same connection,
    every decided row whose event is undecided is inserted, and the transaction rolls back
    unless commit."""
    with psycopg.connect(settings.database_url) as conn:
        rows = build_rows(conn)
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
    print(f"{'wrote' if commit else 'dry run, would write'} {written} of {len(rows)} decided rows")
    return 0


def apply(settings: Settings, path: Path, *, commit: bool) -> int:
    """One transaction: every confirmed row whose event is undecided; rolled back unless commit."""
    return _apply_decided(settings, lambda conn: confirmed_rows(path, _apr(conn)), commit=commit)


# Unlike --apply's re-judgment, nothing in the file itself proves the named series really carries
# the span: a route named at the wrong vendor (or a date before either vendor's first bar) would
# land cleanly and rescale nothing. Every recorded route must have raw observations on or before
# the effective date, in the series' own session zone.
_ROUTE_SERVED_SQL = """
SELECT EXISTS (
  SELECT 1 FROM ohlcv_raw
  WHERE symbol = %s AND vendor = %s AND kind = %s AND timeframe = '1d'
    AND ("timestamp" AT TIME ZONE %s)::date <= %s
)
"""


def _routes_served(conn: Any, rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """rows, after refusing any recorded route with no raw observations on or before its row's
    effective date (a silent no-op row would leave the span unadjusted)."""
    with conn.cursor() as cur:
        for row in rows:
            for route in row["detail"]["unadjusted_routes"]:
                cur.execute(
                    _ROUTE_SERVED_SQL,
                    (
                        row["symbol"],
                        route["vendor"],
                        route["kind"],
                        RAW_DAILY_SESSION_ZONE[(route["vendor"], route["kind"])],
                        row["effective_date"],
                    ),
                )
                if cur.fetchone() != (True,):
                    raise ValueError(
                        f"{row['symbol']} {row['effective_date']}: no raw 1d observations of "
                        f"{route['vendor']}/{route['kind']} on or before it"
                    )
    return rows


def apply_rows(settings: Settings, path: Path, *, commit: bool) -> int:
    """One transaction: the operator rows file's rows whose event is undecided (todo 592),
    every recorded route checked to carry the span; rolled back unless commit."""
    return _apply_decided(
        settings, lambda conn: _routes_served(conn, operator_rows(path)), commit=commit
    )


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


# ---------------- The lone-break sweep (todo 592: the class emerged) ----------------
#
# Definitional cut, measured in the todo's triage: a lone break is a step beyond this size on a
# day when at most this many names step - crash days move the whole market, scale errors move
# one name. A break is a scale event when it exceeds Yahoo's adjusted move by the scale
# tolerance (Yahoo adjusted carries real moves and never split rescales), and a calendar event
# this close to the break still explains an in-series adjustment switch (FBIZ: vendor anchored
# 2015-08-31's 2:1 twelve days early). Not tunables; changing one changes the classified
# corpus, so the sweep CSV records them.
_SWEEP_BREAK_STEP = 0.4
_SWEEP_MAX_LONE_NAMES = 20
_SWEEP_SCALE_TOL = 0.1
_SWEEP_CALENDAR_WINDOW = 30

# One pass over tradeable 1d: every step with its serving routes, then the days few names step.
_SWEEP_STEPS_SQL = """
WITH steps AS (
    SELECT symbol, ("timestamp" AT TIME ZONE 'UTC')::date AS d, close, vendor, kind,
           ln(close / lag(close) OVER (PARTITION BY symbol ORDER BY "timestamp")) AS step,
           lag(vendor) OVER (PARTITION BY symbol ORDER BY "timestamp") AS pv,
           lag(kind) OVER (PARTITION BY symbol ORDER BY "timestamp") AS pk
    FROM market_data_ohlcv_tradeable
    WHERE timeframe = '1d' AND close > 0
),
big AS (
    SELECT * FROM steps WHERE step IS NOT NULL AND abs(step) > %s
)
SELECT symbol, d, round(step::numeric, 6), pv, pk, vendor, kind FROM big
WHERE d IN (SELECT d FROM big GROUP BY d HAVING count(DISTINCT symbol) <= %s)
ORDER BY symbol, d
"""

# Verdicts that carry a rescale row (junction_rescale, inseries_rescale, unrecorded_split).
_SWEEP_ROW_VERDICTS = frozenset({"junction_rescale", "inseries_rescale", "unrecorded_split"})


@dataclass(frozen=True)
class SweepBreak:
    """One lone canonical break, classified (one line of the sweep CSV)."""

    symbol: str
    break_date: date
    step: float
    verdict: str
    next_step: float | None = None
    yahoo_step: float | None = None
    series_switch: bool = False
    route_before: str | None = None
    route_after: str | None = None
    factor: float | None = None
    effective_date: date | None = None
    unadjusted_route: str | None = None
    nearest_calendar: str | None = None
    # JSON {"vendor/kind": [median close before, median close after, ln step]}, every rescalable
    # series with an observation inside the break's span
    route_steps: str | None = None
    # JSON {"vendor/kind": [series/Yahoo median before, series/Yahoo median after]} for the
    # routes on each side of the break
    k_levels: str | None = None
    evidence: str | None = None


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _series_sides(
    series: RawSeries, y_close: Mapping[date, float], span: tuple[date, date], day: date, n: int
) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    """((median own close before, median own/Yahoo before), (after, after)): the series' n
    sessions nearest the break on each side inside span. A None level marks an empty side."""
    lo, hi = span
    own_b, k_b, own_a, k_a = [], [], [], []
    for d, close in series:
        if lo <= d < day:
            own_b.append(close)
            if d in y_close:
                k_b.append(close / y_close[d])
        elif day <= d < hi:
            own_a.append(close)
            if d in y_close:
                k_a.append(close / y_close[d])
    return (
        (_median(own_b[-n:]), _median(k_b[-n:])),
        (_median(own_a[:n]), _median(k_a[:n])),
    )


def _nearest_calendar(
    calendar: Sequence[tuple[date, float, float]], day: date
) -> tuple[date, float] | None:
    """The nearest split event of Yahoo's calendar within the sweep's window, or None."""
    best: tuple[date, float] | None = None
    for d, _close, factor in calendar:
        if (
            math.isfinite(factor)
            and factor not in (0.0, 1.0)
            and abs((d - day).days) <= _SWEEP_CALENDAR_WINDOW
        ):
            if best is None or abs(d - day) < abs(best[0] - day):
                best = (d, factor)
    return best


def classify_breaks(
    symbol: str,
    canonical: Sequence[tuple[date, float, str, str]],
    calendar: Sequence[tuple[date, float, float]],
    raw: Mapping[tuple[str, str], RawSeries],
    breaks: Sequence[tuple[date, float, str, str, str, str]],
    route_sessions: int,
) -> list[SweepBreak]:
    """Every lone break of one name, classified by the per-series method. Pure.

    breaks rows are (date, step, prev vendor, prev kind, vendor, kind) as the corpus pass
    reads them; the span around each break is bounded by the name's neighbouring breaks so a
    second scale event never enters a median. No fix is decided without a witness: everything
    the evidence leaves ambiguous is reported."""
    days = [row[0] for row in canonical]
    closes = {row[0]: row[1] for row in canonical}
    priced = [row for row in calendar if math.isfinite(row[1]) and row[1] > 0]
    y_close = {row[0]: row[1] for row in priced}
    y_days = [row[0] for row in priced]
    break_days = [row[0] for row in breaks]
    out: list[SweepBreak] = []
    for i, (day, step, pv, pk, vendor, kind) in enumerate(breaks):
        idx = bisect_left(days, day)
        next_step = (
            None
            if idx + 1 >= len(days)
            else round(math.log(closes[days[idx + 1]] / closes[day]), 6)
        )
        base = dict(next_step=next_step, route_before=f"{pv}/{pk}", route_after=f"{vendor}/{kind}")
        # (1) The MVBF/UHAL class: the next session reverses the step, so the break bar is a
        # one-bar scale error whose quarantine is operator_bad_bars.csv.
        if next_step is not None and abs(step + next_step) <= _SWEEP_SCALE_TOL:
            out.append(
                SweepBreak(
                    symbol,
                    day,
                    step,
                    "single_bar_reversal",
                    evidence=f"canonical steps {step:+.3f} then {next_step:+.3f} the next session "
                    f"({days[idx + 1]}): a one-bar scale error, the break bar quarantines",
                    **base,
                )
            )
            continue
        # (2) Yahoo's adjusted close is the continuity witness.
        y = _bracket(y_days, day)
        yahoo_step = None if y is None else round(math.log(priced[y[1]][1] / priced[y[0]][1]), 6)
        base["yahoo_step"] = yahoo_step
        if yahoo_step is None:
            out.append(
                SweepBreak(
                    symbol,
                    day,
                    step,
                    "reported",
                    evidence="Yahoo's adjusted close cannot be bracketed across the break",
                    **base,
                )
            )
            continue
        scale = step - yahoo_step
        span = (
            break_days[i - 1] if i else date.min,
            break_days[i + 1] if i + 1 < len(break_days) else date.max,
        )
        measured: dict[str, list[float | None]] = {}
        k_levels: dict[str, list[float | None]] = {}
        lo, hi = span
        for (rv, rk), rows in sorted(raw.items()):
            if not any(lo <= d < hi for d, _c in rows):
                continue
            (own_b, k_b), (own_a, k_a) = _series_sides(rows, y_close, span, day, route_sessions)
            step_own = None if own_b is None or own_a is None else round(math.log(own_a / own_b), 6)
            measured[series_key((rv, rk))] = [own_b, own_a, step_own]
            k_levels[series_key((rv, rk))] = [k_b, k_a]
        base["route_steps"] = json.dumps(measured, sort_keys=True)
        base["k_levels"] = json.dumps(k_levels, sort_keys=True)
        routes_json = "; ".join(f"{k}: {v[0]}/{v[1]} step {v[2]}" for k, v in measured.items())
        nearest = _nearest_calendar(calendar, day)
        base["nearest_calendar"] = None if nearest is None else f"{nearest[0]} x{nearest[1]}"
        # (3) Yahoo adjusted carries the step: a real move, left alone.
        if abs(scale) <= _SWEEP_SCALE_TOL:
            out.append(
                SweepBreak(
                    symbol,
                    day,
                    step,
                    "real_move",
                    evidence=f"Yahoo adjusted steps {yahoo_step:+.3f} against canonical "
                    f"{step:+.3f}: a real move; {routes_json}",
                    **base,
                )
            )
            continue
        # (4) A scale event. Which series serves each side decides the class.
        own_before = _RAW_SERIES_OF.get((pv, pk))
        own_after = _RAW_SERIES_OF.get((vendor, kind))
        base["series_switch"] = own_before != own_after
        if own_before != own_after:
            # A junction: the two serving series' levels against Yahoo decide which side is off.
            k_b = (
                None
                if own_before is None
                else k_levels.get(series_key(own_before), [None, None])[0]
            )
            k_a = (
                None if own_after is None else k_levels.get(series_key(own_after), [None, None])[1]
            )
            if k_b is None or k_a is None or k_b <= 0 or k_a <= 0:
                out.append(
                    _reported(
                        symbol,
                        day,
                        step,
                        "a serving series has no measured level " "against Yahoo at the junction",
                        base,
                    )
                )
                continue
            pre_off, post_ok = (
                abs(math.log(k_b) + scale) <= _SWEEP_SCALE_TOL,
                abs(math.log(k_a)) <= _SWEEP_SCALE_TOL,
            )
            post_off, pre_ok = (
                abs(math.log(k_a) - scale) <= _SWEEP_SCALE_TOL,
                abs(math.log(k_b)) <= _SWEEP_SCALE_TOL,
            )
            if pre_off and post_ok and own_before is not None:
                out.append(
                    SweepBreak(
                        symbol,
                        day,
                        step,
                        "junction_rescale",
                        unadjusted_route=series_key(own_before),
                        factor=round(k_b, 6),
                        effective_date=days[idx - 1] if idx else None,
                        evidence=f"canonical switches {series_key(own_before) if own_before else 'unrouted'} -> "
                        f"{series_key(own_after) if own_after else 'unrouted'} at the break; the pre series sits at "
                        f"{k_b:.4g} of Yahoo-adjusted (post {k_a:.4g}); Yahoo steps {yahoo_step:+.3f}; {routes_json}",
                        **base,
                    )
                )
            elif post_off and pre_ok:
                out.append(
                    _reported(
                        symbol,
                        day,
                        step,
                        "the POST side of the junction is off "
                        f"scale (pre {k_b:.4g}, post {k_a:.4g} of Yahoo): a prefix rescale cannot "
                        "express it",
                        base,
                    )
                )
            else:
                out.append(
                    _reported(
                        symbol,
                        day,
                        step,
                        f"junction levels do not decide "
                        f"(pre {k_b:.4g}, post {k_a:.4g} of Yahoo)",
                        base,
                    )
                )
            continue
        if own_after is None:
            out.append(
                _reported(
                    symbol, day, step, "the serving route is not a rescalable " "series", base
                )
            )
            continue
        # (5) No switch: the serving tape itself. It either switches scale at the break (the
        # FBIZ in-series class with a calendar event nearby, else an unrecorded split - the
        # jump side is dominated by unrecorded reverse splits) or it does not carry the step.
        step_own = measured.get(series_key(own_after), [None, None, None])[2]
        if step_own is None:
            out.append(
                _reported(
                    symbol,
                    day,
                    step,
                    "the serving series has no measured level " "on both sides of the break",
                    base,
                )
            )
            continue
        if abs(step_own - scale) <= _SWEEP_SCALE_TOL:
            verdict = "inseries_rescale" if nearest is not None else "unrecorded_split"
            out.append(
                SweepBreak(
                    symbol,
                    day,
                    step,
                    verdict,
                    unadjusted_route=series_key(own_after),
                    factor=round(math.exp(-step_own), 6),
                    effective_date=days[idx - 1] if idx else None,
                    evidence=f"the serving tape {series_key(own_after)} steps {step_own:+.3f} at the "
                    f"break while Yahoo adjusted moves {yahoo_step:+.3f}"
                    + (
                        f"; calendar event {nearest[0]} x{nearest[1]} nearby"
                        if nearest
                        else "; no calendar event within the window"
                    )
                    + f"; factor {math.exp(-step_own):.6g}; {routes_json}",
                    **base,
                )
            )
            continue
        out.append(
            _reported(
                symbol,
                day,
                step,
                f"the serving tape steps {step_own:+.3f} against the canonical scale {scale:+.3f} "
                "(neither flat nor the break: a witness the method cannot decide)",
                base,
            )
        )
    return out


def _reported(symbol: str, day: date, step: float, why: str, base: Mapping[str, Any]) -> SweepBreak:
    return SweepBreak(symbol, day, step, "reported", evidence=why, **base)


def sweep(
    settings: Settings, out: Path, rows_out: Path | None, symbols: Sequence[str] | None
) -> dict[str, int]:
    """Read-only: every lone break classified into --out, the rescale rows of the row verdicts
    into --rows-out. Returns verdict counts."""
    counts: dict[str, int] = {}
    with psycopg.connect(settings.database_url) as conn:
        params = _apr(conn)
        lone: dict[str, list[tuple[date, float, str, str, str, str]]] = {}
        for symbol, day, step, pv, pk, vendor, kind in conn.execute(
            _SWEEP_STEPS_SQL, (_SWEEP_BREAK_STEP, _SWEEP_MAX_LONE_NAMES)
        ):
            lone.setdefault(symbol, []).append((day, float(step), pv, pk, vendor, kind))
        names = list(symbols) if symbols is not None else sorted(lone)
        with (
            out.open("w", newline="") as fh,
            (
                rows_out.open("w", newline="") if rows_out else open("/dev/null", "w", newline="")
            ) as rfh,
        ):
            writer = csv.DictWriter(fh, fieldnames=[*SweepBreak.__dataclass_fields__])
            writer.writeheader()
            rows_writer = csv.DictWriter(rfh, fieldnames=OPERATOR_ROWS_COLUMNS)
            rows_writer.writeheader()
            for symbol in names:
                calendar, error = _fetch_calendar(symbol)
                if error is not None or symbol not in lone:
                    for day, step, pv, pk, vendor, kind in lone.get(symbol, ()):
                        event = SweepBreak(
                            symbol, day, step, "reported", evidence="Yahoo fetch failed"
                        )
                        writer.writerow(asdict(event))
                        counts["reported"] = counts.get("reported", 0) + 1
                    continue
                canonical = [
                    (d, float(c), v, k) for d, c, v, k in conn.execute(_CANONICAL_SQL, (symbol,))
                ]
                for event in classify_breaks(
                    symbol,
                    canonical,
                    calendar,
                    _raw_series(conn, symbol),
                    lone[symbol],
                    params.route_sessions,
                ):
                    writer.writerow(asdict(event))
                    counts[event.verdict] = counts.get(event.verdict, 0) + 1
                    if event.verdict in _SWEEP_ROW_VERDICTS:
                        rows_writer.writerow(
                            {
                                "symbol": event.symbol,
                                "effective_date": event.effective_date,
                                "factor": event.factor,
                                "unadjusted_routes": event.unadjusted_route,
                                "calendar_adjusted_step": event.yahoo_step,
                                "reason": f"{event.verdict} (todo 592 sweep; break "
                                f"{event.break_date} step {event.step:+.3f})",
                                "evidence": event.evidence,
                            }
                        )
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true", help="judge the calendar into --out")
    mode.add_argument(
        "--sweep",
        action="store_true",
        help="classify every lone canonical break into --out (todo 592); "
        "--rows-out writes the rescale rows of the row verdicts",
    )
    mode.add_argument("--apply", type=Path, metavar="CSV", help="write an audit's confirmed rows")
    mode.add_argument(
        "--apply-rows",
        type=Path,
        metavar="CSV",
        help="write the operator rows file (todo 592) as calendar_audit rows",
    )
    mode.add_argument(
        "--quarantine-unconfirmed",
        type=Path,
        metavar="CSV",
        help="quarantine every unconfirmed candidate's first new-scale bar (unconfirmed_split) "
        "and every listed bad bar (operator_bad_bar)",
    )
    parser.add_argument("--out", type=Path, help="--audit/--sweep: the CSV to write")
    parser.add_argument(
        "--rows-out",
        type=Path,
        help="--sweep: the operator-rows CSV the row verdicts write (optional)",
    )
    parser.add_argument("--symbols", nargs="*", default=None)
    add_write_mode_args(
        parser,
        dry_run="--apply/--apply-rows/--quarantine-unconfirmed: report what would be written "
        "(default)",
        commit="--apply/--apply-rows/--quarantine-unconfirmed: write",
    )
    args = parser.parse_args(argv)
    settings = Settings()
    if args.audit or args.sweep:
        if args.out is None:
            raise SystemExit("--audit/--sweep need --out")
        if args.sweep:
            print(sweep(settings, args.out, args.rows_out, args.symbols))
        else:
            print(audit(settings, args.symbols, args.out))
        return 0
    if args.apply_rows:
        return apply_rows(settings, args.apply_rows, commit=args.commit)
    if args.quarantine_unconfirmed:
        return asyncio.run(_quarantine(settings, args.quarantine_unconfirmed, commit=args.commit))
    return apply(settings, args.apply, commit=args.commit)


if __name__ == "__main__":
    sys.exit(main())
