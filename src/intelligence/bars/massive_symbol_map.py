"""Which Massive ticker string is which instrument on a given session (admission design section 6).

Pure Ring 1: spans, session dates and a presence function in, verdicts out. The spans are the
evidenced `ticker_event` rows (Option A: a ticker's rows load only inside an evidenced span of an
instrument); the identity writer fills them and lists what it refused in a gap list.

Event dates can lag the string actually served (AGCO is served as AGCO in 2008 files while the
chain says AG until 2009-05-05), so a span is judged by EDGE PRESENCE before it loads: its ticker
string must appear in the served files at the first and the last archive session inside the span.
A span that fails is TRIMMED to the first and last session where the string is actually present
(never extended past the evidenced span) and loaded over that sub-window; the trimmed sessions are
reported as gap days and the incumbent keeps them. A span with no present session is not loaded.
Interior absences are reported, not trimmed. A different string is never loaded to fill a gap.
The count of sessions inside a window that carry the string is reported, never a tunable.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

REASON_NO_SESSIONS = "no_archive_session_in_span"
REASON_FIRST_ABSENT = "ticker_absent_at_first_session"
REASON_LAST_ABSENT = "ticker_absent_at_last_session"
REASON_BOTH_ABSENT = "ticker_absent_at_first_and_last_session"
REASON_NEVER_PRESENT = "ticker_never_present_in_span"


@dataclass(frozen=True)
class TickerSpan:
    """One evidenced ticker_event: `ticker` is the instrument `symbol` on [valid_from, valid_to)."""

    ticker_event_id: str
    symbol: str
    ticker: str
    valid_from: date
    valid_to: date | None  # exclusive; None is open-ended

    def covers(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day < self.valid_to)


@dataclass(frozen=True)
class SpanVerdict:
    span: TickerSpan
    reason: str | None  # None: both edges present; else the failed edge (the span is trimmed)
    first_session: date | None
    last_session: date | None
    n_window_sessions: int  # archive sessions of the span inside the load window
    n_window_present: int  # of those, sessions whose file carries the ticker string
    trimmed: TickerSpan | None = None  # the evidenced sub-span to load; None: nothing to load
    trimmed_days: tuple[
        date, ...
    ] = ()  # span sessions outside `trimmed`: gap days, incumbent keeps

    @property
    def loadable(self) -> bool:
        return self.trimmed is not None


def judge_span(
    span: TickerSpan,
    archive_sessions: Sequence[date],
    present_on: Callable[[date], Collection[str]],
    window: tuple[date, date] | None = None,
) -> SpanVerdict:
    """Trim `span` to its first and last present session; count presence over `window` (inclusive
    dates; the whole span when None). `archive_sessions` is the sorted list of every session the
    archive holds; `present_on(day)` the ticker strings served that session."""
    inside = [d for d in archive_sessions if span.covers(d)]
    if not inside:
        return SpanVerdict(span, REASON_NO_SESSIONS, None, None, 0, 0)
    first, last = inside[0], inside[-1]
    present = [d for d in inside if span.ticker in present_on(d)]
    in_window = [d for d in inside if window is None or window[0] <= d <= window[1]]
    if not present:
        return SpanVerdict(span, REASON_NEVER_PRESENT, first, last, len(in_window), 0)
    present_set = set(present)
    n_present = sum(d in present_set for d in in_window)
    first_ok, last_ok = present[0] == first, present[-1] == last
    reason = (
        None
        if first_ok and last_ok
        else (
            REASON_BOTH_ABSENT
            if not first_ok and not last_ok
            else REASON_FIRST_ABSENT if not first_ok else REASON_LAST_ABSENT
        )
    )
    valid_to = span.valid_to if last_ok else present[-1] + timedelta(days=1)
    trimmed = TickerSpan(span.ticker_event_id, span.symbol, span.ticker, present[0], valid_to)
    gap = tuple(d for d in inside if not trimmed.covers(d))
    return SpanVerdict(span, reason, first, last, len(in_window), n_present, trimmed, gap)


def tickers_on(spans: Iterable[TickerSpan], day: date) -> dict[str, TickerSpan]:
    """The file ticker string to span map of one session, from loadable spans. Two spans for one
    string on one day would load a ticker as two instruments: ValueError (the table's exclusion
    constraint forbids it, so this is a tripwire, not a case)."""
    mapping: dict[str, TickerSpan] = {}
    for span in spans:
        if span.covers(day):
            if span.ticker in mapping:
                raise ValueError(f"ticker {span.ticker!r} maps to two instruments on {day}")
            mapping[span.ticker] = span
    return mapping


def unaccounted_instruments(
    active_symbols: Iterable[str], spans: Iterable[TickerSpan], gap_symbols: Collection[str]
) -> list[str]:
    """Active instruments with neither a span nor a gap-list row: the loader fails loudly on any,
    because an instrument the identity map neither resolved nor refused is a silent hole."""
    resolved = {span.symbol for span in spans}
    return sorted(s for s in set(active_symbols) if s not in resolved and s not in gap_symbols)
