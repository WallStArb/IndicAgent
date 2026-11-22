"""Massive cash dividends: capture records to per-name events and a coverage claim.

Pure: records and ticker spans in, events, drop counts and coverage out; no database, no I/O.
The writer is services/dividend_event_writer.py (source ``massive``); the rule and its
measurement are in docs/plans/2026-11-21-massive-dividend-coverage-rule.md.

Mapping. A record carries a ticker, never an identity, and tickers are reused across
companies (a bare ticker join adds 97,465 wrong pairs on the 2026-11-10 capture). A record
belongs to the symbol whose Massive ticker span ``[valid_from, valid_to)`` holds its ex-date
(``ticker_event_current``); the spans of one ticker never overlap, so no record maps to two
names. A record outside every span is unmapped and counted.

Events. Per (symbol, ex-date): exact repeats of one amount collapse (Massive serves the same
dividend under several record ids), and distinct amounts sum (a regular and a special dividend
on one ex-date). A date is dropped, and becomes a hole in the coverage, when any record on it
is not in USD (two currencies cannot be summed, and a claim of "covered, no dividend" there
would be false), has no positive finite cash amount, or restates one dividend with a different
amount (same type and pay date, amounts within RESTATEMENT_REL_TOLERANCE: summing would double
it, and neither amount is known right). Records with an ex-date after the
capture date are dropped: the reader of a capture taken on that date cannot know them.

Coverage (the claim that a date with no event had no dividend). Absence of events means no
dividends only where Massive demonstrably tracked the name, so the claim is built from the
name's own cadence:

- a name with no events gets no claim (old DuPont has none at all);
- the claim starts at the first ex-date (no claim before it) and ends ``tail_intervals``
  payment intervals after the last one, capped at ``tail_cap_days``, the capture date and the
  end of the name's last ticker span;
- the payment interval is the median gap between consecutive distinct ex-dates; a name with
  one ex-date claims that date only;
- a gap longer than ``gap_intervals`` intervals is a hole (Massive lost the name for a while:
  WELL 2010-2022, STX 2008-2014); a single missed payment doubles the interval, so any
  ``gap_intervals`` below 2 catches it;
- days outside every ticker span of the name (no record could map there) and dropped
  ex-dates are holes.

``tail_intervals`` below 1 keeps the claim from reaching the next expected payment: a name
whose final dividend Massive lost is then unknown after its last listed one, not wrongly
covered. The constants are definitions of the rule, pre-registered in the dated design note,
not operator tunables.
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from src.intelligence.bars.massive_symbol_map import TickerSpan

SOURCE = "massive"
USD = "USD"
# Names the coverage rule below (constants and logic); a change is a new id and a new claim.
RULE_ID = "massive-dividend-coverage-v1"

# Drop reasons (counted per record, never silent).
DROP_AFTER_CAPTURE = "after_capture"
DROP_NON_USD = "non_usd"
DROP_BAD_AMOUNT = "bad_amount"
DROP_UNMAPPED = "unmapped"
DROP_NO_PREV_CLOSE = "no_prev_close"
DROP_CONFLICTING = "conflicting_amounts"

# Two records of one ex-date with the same distribution type and pay date whose amounts differ
# by at most this share of the larger are one dividend restated, not two to sum (66 such dates
# among mapped USD dates of the 2026-11-10 capture, e.g. GOL 2007-09-28 0.10693 vs 0.10785):
# the date is dropped.
# A rule definition (design note section 2), not a tunable.
RESTATEMENT_REL_TOLERANCE = 0.10

# Hole reasons (dividend_event_coverage_gap.reasons, migration 608).
GAP_CADENCE = "cadence_gap"
GAP_SPAN = "span_gap"
GAP_DROPPED = "dropped_ex_date"

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class CoverageRule:
    """The pre-registered coverage constants (design note 2026-11-21, section 3)."""

    tail_intervals: float = 0.75
    tail_cap_days: int = 400
    gap_intervals: float = 1.5

    def __post_init__(self) -> None:
        if not 0 <= self.tail_intervals < 1:
            raise ValueError(
                "tail_intervals must be in [0, 1): the tail may not reach the next payment"
            )
        if not 1 < self.gap_intervals < 2:
            raise ValueError("gap_intervals must be in (1, 2): one missed payment must be a hole")
        if self.tail_cap_days < 0:
            raise ValueError("tail_cap_days must be non-negative")


RULE = CoverageRule()


@dataclass(frozen=True)
class DividendRecord:
    """One Massive dividend record with its capture lineage."""

    record_id: str
    ticker: str
    ex_date: date
    cash_amount: float | None
    currency: str | None
    distribution_type: str | None
    declared_on: date | None
    page: int
    pay_date: str | None = None  # as served; compared only for equality (restatements)


@dataclass(frozen=True)
class MassiveEvent:
    """One stored event: the summed distinct cash amounts of a (symbol, ex-date)."""

    symbol: str
    ex_date: date
    amount: float
    declared_on: date | None  # earliest declaration date among its records, None if unknown
    record_ids: tuple[str, ...]  # sorted
    pages: tuple[int, ...]  # sorted, distinct


@dataclass(frozen=True)
class Hole:
    """Days [gap_from, gap_to] (inclusive) inside a claim that stay unknown, and why."""

    gap_from: date
    gap_to: date
    reasons: tuple[str, ...]  # sorted, distinct GAP_* codes


@dataclass(frozen=True)
class Coverage:
    """The claim for one symbol: covered on [covered_from, covered_to] minus the holes."""

    covered_from: date
    covered_to: date
    holes: tuple[Hole, ...]  # sorted, disjoint, inside the span

    def covers(self, day: date) -> bool:
        return self.covered_from <= day <= self.covered_to and not any(
            h.gap_from <= day <= h.gap_to for h in self.holes
        )


@dataclass
class Collapsed:
    """collapse_events output: events by symbol, every ex-date Massive reported for the
    symbol (stored or dropped, before the capture date), and the dropped dates."""

    events: dict[str, list[MassiveEvent]] = field(default_factory=dict)
    reported_dates: dict[str, set[date]] = field(default_factory=dict)
    dropped_dates: dict[str, set[date]] = field(default_factory=dict)
    drops: Counter = field(default_factory=Counter)


def _iso_date(value: Any, what: str, record_id: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"record {record_id}: bad {what} {value!r}") from error


def parse_page(body: Mapping[str, Any], page: int) -> list[DividendRecord]:
    """The records of one captured page. Raises ValueError on a malformed page or record (a
    capture that does not parse is refused, never skipped)."""
    results = body.get("results")
    if body.get("status") != "OK" or not isinstance(results, list):
        raise ValueError(f"page {page}: status {body.get('status')!r}, no results list")
    out = []
    for raw in results:
        record_id = raw.get("id")
        ticker = raw.get("ticker")
        if (
            not isinstance(record_id, str)
            or not record_id
            or not isinstance(ticker, str)
            or not ticker
        ):
            raise ValueError(f"page {page}: record without id or ticker: {raw!r}")
        declared = raw.get("declaration_date")
        amount = raw.get("cash_amount")
        out.append(
            DividendRecord(
                record_id=record_id,
                ticker=ticker,
                ex_date=_iso_date(raw.get("ex_dividend_date"), "ex_dividend_date", record_id),
                cash_amount=float(amount) if isinstance(amount, int | float) else None,
                currency=raw.get("currency"),
                distribution_type=raw.get("distribution_type"),
                declared_on=(
                    _iso_date(declared, "declaration_date", record_id) if declared else None
                ),
                page=page,
                pay_date=raw.get("pay_date"),
            )
        )
    return out


class SpanIndex:
    """Ticker spans by ticker, for the point-in-time record-to-symbol mapping."""

    def __init__(self, spans: Iterable[TickerSpan]) -> None:
        by_ticker: dict[str, list[TickerSpan]] = defaultdict(list)
        self.by_symbol: dict[str, list[TickerSpan]] = defaultdict(list)
        for span in spans:
            by_ticker[span.ticker].append(span)
            self.by_symbol[span.symbol].append(span)
        self._starts: dict[str, list[date]] = {}
        self._spans: dict[str, list[TickerSpan]] = {}
        for ticker, rows in by_ticker.items():
            rows.sort(key=lambda s: s.valid_from)
            for a, b in zip(rows, rows[1:], strict=False):
                if a.valid_to is None or a.valid_to > b.valid_from:
                    raise ValueError(f"ticker {ticker}: overlapping spans {a} and {b}")
            self._spans[ticker] = rows
            self._starts[ticker] = [s.valid_from for s in rows]
        for rows in self.by_symbol.values():
            rows.sort(key=lambda s: s.valid_from)

    def symbol_of(self, ticker: str, day: date) -> str | None:
        """The symbol whose span of `ticker` holds `day`, or None."""
        starts = self._starts.get(ticker)
        if not starts:
            return None
        i = bisect_right(starts, day) - 1
        if i < 0:
            return None
        span = self._spans[ticker][i]
        return span.symbol if span.covers(day) else None


def collapse_events(
    records: Iterable[DividendRecord], spans: SpanIndex, capture_date: date
) -> Collapsed:
    """Map records to symbols and collapse them to one event per (symbol, ex-date). Drops are
    counted per record by reason; a date with any non-USD or bad-amount record is dropped
    whole. Deterministic: the result does not depend on record order."""
    out = Collapsed()
    by_key: dict[tuple[str, date], list[DividendRecord]] = defaultdict(list)
    for rec in records:
        if rec.ex_date > capture_date:
            out.drops[DROP_AFTER_CAPTURE] += 1
            continue
        symbol = spans.symbol_of(rec.ticker, rec.ex_date)
        if symbol is None:
            out.drops[DROP_UNMAPPED] += 1
            continue
        by_key[(symbol, rec.ex_date)].append(rec)
    for (symbol, ex_date), recs in sorted(by_key.items()):
        out.reported_dates.setdefault(symbol, set()).add(ex_date)
        reason = None
        if any(r.currency != USD for r in recs):
            reason = DROP_NON_USD
        elif any(
            r.cash_amount is None or not math.isfinite(r.cash_amount) or r.cash_amount <= 0
            for r in recs
        ):
            reason = DROP_BAD_AMOUNT
        elif _restated(recs):
            reason = DROP_CONFLICTING
        if reason is not None:
            out.drops[reason] += len(recs)
            out.dropped_dates.setdefault(symbol, set()).add(ex_date)
            continue
        amounts = sorted({_amount(r) for r in recs})  # exact repeats collapse
        declared = [r.declared_on for r in recs if r.declared_on is not None]
        out.events.setdefault(symbol, []).append(
            MassiveEvent(
                symbol=symbol,
                ex_date=ex_date,
                amount=math.fsum(amounts),
                declared_on=min(declared) if declared else None,
                record_ids=tuple(sorted(r.record_id for r in recs)),
                pages=tuple(sorted({r.page for r in recs})),
            )
        )
    return out


def _amount(rec: DividendRecord) -> float:
    """The record's cash amount; a missing one was dropped before any amount is read, so a None
    here is a bug and fails loudly."""
    if rec.cash_amount is None:
        raise ValueError(f"dividend record {rec.record_id} has no cash amount")
    return rec.cash_amount


def _restated(recs: Sequence[DividendRecord]) -> bool:
    """True when two records of one ex-date cannot be told apart as one dividend or two: same
    distribution type and pay date with amounts within RESTATEMENT_REL_TOLERANCE (one dividend
    restated; summing doubles it), or the same amount paid on different dates (two payments;
    collapsing the repeat halves them, e.g. BGB 2024-12-23 paid 2024-12-31 and 2025-01-31)."""
    for i, a in enumerate(recs):
        for b in recs[i + 1 :]:
            x, y = _amount(a), _amount(b)
            if x == y and a.pay_date != b.pay_date:
                return True
            if (
                x != y
                and a.distribution_type == b.distribution_type
                and a.pay_date == b.pay_date
                and abs(x - y) <= RESTATEMENT_REL_TOLERANCE * max(x, y)
            ):
                return True
    return False


def payment_interval(ex_dates: Sequence[date]) -> float | None:
    """Median days between consecutive distinct ex-dates; None with fewer than two."""
    days = sorted(set(ex_dates))
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False)]
    return float(statistics.median(gaps)) if gaps else None


def _merge(holes: Iterable[Hole]) -> list[Hole]:
    """Sorted, disjoint holes: overlapping or adjacent ones join and keep every reason."""
    merged: list[Hole] = []
    for hole in sorted(holes, key=lambda h: (h.gap_from, h.gap_to)):
        prev = merged[-1] if merged else None
        if prev is not None and hole.gap_from <= prev.gap_to + _ONE_DAY:
            merged[-1] = Hole(
                prev.gap_from,
                max(prev.gap_to, hole.gap_to),
                tuple(sorted(set(prev.reasons) | set(hole.reasons))),
            )
        else:
            merged.append(hole)
    return merged


def coverage(
    reported: Iterable[date],
    dropped: Iterable[date],
    spans: Sequence[TickerSpan],
    capture_date: date,
    rule: CoverageRule = RULE,
) -> Coverage | None:
    """The coverage claim for one symbol from every ex-date Massive reported for it (stored or
    dropped, none after the capture date) and its ticker spans; None when it reported none."""
    days = sorted(set(reported))
    if not days:
        return None
    if days[-1] > capture_date:
        raise ValueError(f"ex-date {days[-1]} after the capture date {capture_date}")
    if not spans:
        raise ValueError("reported ex-dates without a ticker span")
    interval = payment_interval(days)
    first, last = days[0], days[-1]
    ordered = sorted(spans, key=lambda s: s.valid_from)
    end_ref = ordered[-1].valid_to
    # The span end is exclusive: its last mapped day is the day before.
    span_end = end_ref - _ONE_DAY if end_ref is not None else capture_date
    covered_to = last
    if interval is not None:
        tail = min(rule.tail_intervals * interval, float(rule.tail_cap_days))
        covered_to = max(last, min(last + timedelta(days=math.floor(tail)), capture_date, span_end))
    holes: list[Hole] = []
    if interval is not None:
        limit = rule.gap_intervals * interval
        holes += [
            Hole(a + _ONE_DAY, b - _ONE_DAY, (GAP_CADENCE,))
            for a, b in zip(days, days[1:], strict=False)
            if (b - a).days > limit
        ]
    for a, b in zip(ordered, ordered[1:], strict=False):
        if a.valid_to is None or a.valid_to > b.valid_from:
            raise ValueError(f"{a.symbol}: overlapping ticker spans {a} and {b}")
        if b.valid_from > a.valid_to:
            holes.append(Hole(a.valid_to, b.valid_from - _ONE_DAY, (GAP_SPAN,)))
    holes += [Hole(d, d, (GAP_DROPPED,)) for d in dropped]
    clipped = tuple(
        Hole(max(h.gap_from, first), min(h.gap_to, covered_to), h.reasons)
        for h in _merge(holes)
        if h.gap_to >= first and h.gap_from <= covered_to
    )
    return Coverage(first, covered_to, clipped)
