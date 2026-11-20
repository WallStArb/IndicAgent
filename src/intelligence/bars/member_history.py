"""Structural audit of a universe member's canonical 1d history (todo 647).

The stage 2 universe holds every dead name so research is free of survivorship bias; their bars
are static, so they are audited once, before counted compute, not nightly. Pure functions over
per-name aggregates: the caller reads the database. A finding fails the gate; bar density
is measured and disclosed, never a pass/fail threshold (calibrate it on the distribution first).
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from src.intelligence.bars.integrity_checks import INFO_PROVEN_START, proven_start
from src.intelligence.bars.verdict_gate import MONITOR_TYPE

# The structural checks, one name each (the gate's failure reasons).
NO_BARS = "no_canonical_1d_bar"
OHLC_INVARIANT = "ohlc_invariant"
NON_POSITIVE_PRICE = "non_positive_price"
STALE_SPLITS = "split_not_current"


@dataclass(frozen=True)
class MemberStats:
    """One member's canonical 1d aggregates (market_data_ohlcv_tradeable)."""

    symbol: str
    bars: int
    first: date
    last: date
    ohlc_bad: int  # bars with high < max(open, low, close) or low > min(open, high, close)
    non_positive: int  # bars with any price <= 0


@dataclass(frozen=True)
class Finding:
    symbol: str
    check: str
    detail: str


def bar_density(stats: MemberStats, calendar: Sequence[date]) -> float:
    """Canonical 1d bars over the sorted NYSE `calendar` sessions between the name's first and
    last bar. Not integrity_checks.session_coverage: answered-empty dates are not credited here,
    so a halted name reads lower. A span with no session reads 1.0. Measured, never a gate."""
    sessions = bisect_right(calendar, stats.last) - bisect_left(calendar, stats.first)
    return 1.0 if sessions <= 0 else min(1.0, stats.bars / sessions)


def audit_members(
    members: Collection[str],
    stats: Mapping[str, MemberStats],
    stale_splits: Mapping[str, str],
) -> list[Finding]:
    """The failing checks over every member, sorted by symbol then check. `stale_splits` maps a
    symbol to the evidence that a split was recorded after its newest 1d digest (the caller's
    query); a member absent from `stats` has no canonical 1d bar (the GROUP BY yields no empty
    row)."""
    findings: list[Finding] = []
    for symbol in sorted(members):
        row = stats.get(symbol)
        if row is None:
            findings.append(Finding(symbol, NO_BARS, "no row in market_data_ohlcv_tradeable (1d)"))
        else:
            if row.ohlc_bad:
                findings.append(Finding(symbol, OHLC_INVARIANT, f"{row.ohlc_bad} bar(s)"))
            if row.non_positive:
                findings.append(Finding(symbol, NON_POSITIVE_PRICE, f"{row.non_positive} bar(s)"))
        if (evidence := stale_splits.get(symbol)) is not None:
            findings.append(Finding(symbol, STALE_SPLITS, evidence))
    return findings


def coverage_quantiles(values: Sequence[float], points: Sequence[float]) -> dict[str, float]:
    """Nearest-rank quantiles of the per-name coverage (the disclosure next to the findings)."""
    ordered = sorted(values)
    if not ordered:
        return {}
    last = len(ordered) - 1
    return {
        f"p{round(p * 100):02d}": ordered[min(last, max(0, math.ceil(p * len(ordered)) - 1))]
        for p in points
    }


def member_proven_start(
    stats: MemberStats,
    calendar: Sequence[date],
    stored_dates: Collection[date],
    empty_spans: Sequence[tuple[date, date]],
    min_coverage: float,
    *,
    era_start: date,
) -> date | None:
    """A member's proven start (design D4, todo 532) over its own span: the sessions of the sorted
    NYSE `calendar` from max(first canonical 1d bar, `era_start`) to its last bar. The 1d verdict
    run ends the span at the calendar's last session, which a dead name never reaches (its start
    is None by construction); here the span ends at the name's own last bar. Answered sessions are
    the stored bars and the sessions inside an answered-empty span; a missing session is never
    credited (no_fill), and only bars up to the last bar are read (point_in_time). The rule is
    integrity_checks.proven_start, the 1d verdict's own; None when the span holds no session or
    its last session is unanswered."""
    first = max(stats.first, era_start)
    span = calendar[bisect_left(calendar, first) : bisect_right(calendar, stats.last)]
    answered = set(stored_dates).intersection(span)
    answered.update(s for s in span if any(a <= s <= b for a, b in empty_spans))
    return proven_start(span, answered, min_coverage)


def proven_start_fact(
    symbol: str, start: date | None, training_window_end: datetime
) -> tuple[str, str, str, float, None, bool, datetime]:
    """The `proven_start_1d` integrity_monitor fact of one name, the tuple the shared batch writer
    (src.core.integrity_monitor.emit_integrity_facts_async) takes. The shape the 1d verdict run
    writes (services.bar_reconciliation_audit): a name with no start is a failing fact (value 0),
    so the reader (backfill_feature_factory.proven_starts) refuses it."""
    return (
        MONITOR_TYPE,
        f"{symbol}|1d",
        INFO_PROVEN_START,
        float(start.toordinal()) if start else 0.0,
        None,
        start is not None,
        training_window_end,
    )
