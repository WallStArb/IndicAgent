"""Canonical bar selection from raw rows by policy, a pure function (phase 191 plan 02).

Design: docs/plans/2026-10-12-unified-raw-bar-table-design.md (Canonical section). For each
(symbol, timeframe, timestamp) the canonical row is the one the highest-ranked vendor holds in
`ohlcv_raw`; within a vendor the kind with the lowest CVR `bar_kind` sort_order wins. The ranking
comes from `bar_source_policy` (the symbol-specific row covering the slot date beats the
timeframe default, then primary_source, then fallback_source).

Selection is a function of the raw rows and the policy only, never of write order: shuffling the
candidates cannot change the result. A missing policy row raises (a slot without a policy fails
loud, as the daily rule does). A slot no ranked vendor holds yields nothing (missing is NaN, no
fill). Rows of vendor `derived` and kind `smart_adjusted` are never selected.

Two rules added at the selection gate (plan 191-07, review of plans 04 and 05):
- Session. A kind that is defined as regular-hours (`sip_rth`, D-191-A) is a candidate only on
  the regular trading hours grid (open inclusive, close exclusive, 5 minute step from the NYSE
  open, early closes included). Raw keeps every bar a vendor served, Alpaca's extended-hours bars
  among them (kind `sip_rth` also holds pre- and post-market stamps); such a stamp is never a
  candidate, so extended-hours bars cannot enter canonical 5m or the 15m/1h derivation that reads
  it. The rule is by kind, not by vendor-blind calendar: IBKR answers an RTH request with its own
  session (bars to 16:00 ET on early-close days, a 14:30 UTC open on 2006-12-27 where the calendar
  says 14:32) and canonical holds exactly those, so a calendar filter on every vendor would drop
  real canonical rows.
- Dates. A policy span is matched by the NYSE session date (America/New_York calendar date of the
  stamp), not the UTC date: a post-close stamp after 00:00 UTC belongs to the session it closes.

Session-level fallback (second review of plan 191-07, finding 3). A fallback never fills single
slots of a session the primary served: vendors differ in what they count (Alpaca SIP volume runs
1.1 to 2x IBKR's on the same bar), so a session spliced from two vendors puts a step into every
volume feature and the 15m/1h derivation (52 of 57 series on 2026-10-09, Alpaca mornings and IBKR
afternoons). Per (symbol, timeframe, session date) the session's slots are those any ranked vendor
holds; a vendor is complete when it holds all of them. The session is taken whole from the first
ranked vendor that is complete. When none is, it is taken from the vendor holding the most of
them (ties by rank) and the slots only another vendor holds are left out (`dropped`: the writer
retracts a canonical row there, missing is NaN). Every session not taken from the primary is
recorded in `SelectionOutcome.choices`, as is a session whose chosen vendor holds fewer slots than
the calendar's regular-hours grid.

Pure Ring 1: no database access, no services imports.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.vendor_kind import VENDOR_DERIVED

NEVER_SELECTED_KINDS = frozenset({"smart_adjusted"})

# Timeframes with a regular-hours session grid, with the step in minutes, and the raw kinds
# defined as regular-hours only (the others are the vendor's own answer to an RTH request).
RTH_GRID_STEP_MINUTES: dict[str, int] = {"5m": 5}
SESSION_BOUND_KINDS = frozenset({"sip_rth"})
SESSION_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class PolicyRow:
    """A bar_source_policy row (symbol None is the timeframe default)."""

    timeframe: str
    symbol: str | None
    valid_from: date
    valid_to: date | None
    primary_source: str
    fallback_source: str | None

    def covers(self, slot_date: date) -> bool:
        return self.valid_from <= slot_date and (self.valid_to is None or slot_date < self.valid_to)


@dataclass(frozen=True)
class Candidate:
    """One vendor-served row of ohlcv_raw."""

    timestamp: datetime
    symbol: str
    timeframe: str
    vendor: str
    kind: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None


@lru_cache(maxsize=16)
def rth_grid_stamps(timeframe: str, first_year: int, last_year: int) -> frozenset[datetime]:
    """Every regular-hours stamp of `timeframe` for the NYSE sessions of [first_year, last_year].

    Open inclusive, close exclusive: a 16:00 ET close gives 09:30..15:55 (78 five minute stamps),
    a 13:00 ET early close gives 09:30..12:55. Bounds come from the calendar, never a count.
    """
    step = timedelta(minutes=RTH_GRID_STEP_MINUTES[timeframe])
    stamps: set[datetime] = set()
    for open_ts, close_ts in nyse_sessions(
        date(first_year, 1, 1), date(last_year, 12, 31)
    ).values():
        stamp = open_ts
        while stamp < close_ts:
            stamps.add(stamp.astimezone(UTC))
            stamp += step
    return frozenset(stamps)


def partition_session(
    candidates: Iterable[Candidate],
) -> tuple[list[Candidate], list[Candidate]]:
    """(on-grid, off-grid) candidates. Only session-bound kinds (`sip_rth`) at a timeframe with a
    session grid are tested; every other candidate is on-grid."""
    held = list(candidates)
    years: dict[str, list[int]] = {}
    for c in held:
        if c.timeframe in RTH_GRID_STEP_MINUTES and c.kind in SESSION_BOUND_KINDS:
            y = c.timestamp.astimezone(UTC).year
            span = years.setdefault(c.timeframe, [y, y])
            span[0], span[1] = min(span[0], y), max(span[1], y)
    # One calendar year of slack each side: a stamp near a year boundary may belong to the
    # neighbouring year's session in New York time.
    grids = {tf: rth_grid_stamps(tf, lo - 1, hi + 1) for tf, (lo, hi) in years.items()}
    on_grid: list[Candidate] = []
    off_grid: list[Candidate] = []
    for c in held:
        grid = grids.get(c.timeframe) if c.kind in SESSION_BOUND_KINDS else None
        (off_grid if grid is not None and c.timestamp not in grid else on_grid).append(c)
    return on_grid, off_grid


def session_date(timestamp: datetime) -> date:
    """The NYSE session date of a stamp: its America/New_York calendar date."""
    return timestamp.astimezone(SESSION_TZ).date()


def rank_vendors(
    policy_rows: Iterable[PolicyRow], symbol: str, timeframe: str, slot_date: date
) -> list[str]:
    """Vendors in selection order for a slot; LookupError when no policy row covers it."""
    covering = [p for p in policy_rows if p.timeframe == timeframe and p.covers(slot_date)]
    for scope in (symbol, None):
        scoped = [p for p in covering if p.symbol == scope]
        if len(scoped) > 1:
            raise ValueError(
                f"{len(scoped)} bar_source_policy rows cover {symbol} {timeframe} {slot_date}"
            )
        if scoped:
            row = scoped[0]
            return [row.primary_source] + ([row.fallback_source] if row.fallback_source else [])
    raise LookupError(f"no bar_source_policy row covers {symbol} {timeframe} {slot_date}")


def select_slot(
    candidates: Iterable[Candidate], ranking: Sequence[str], kind_order: Mapping[str, int]
) -> Candidate | None:
    """The winning candidate of one slot, or None when no ranked vendor holds it."""
    eligible = [
        c
        for c in candidates
        if c.vendor != VENDOR_DERIVED and c.kind not in NEVER_SELECTED_KINDS and c.vendor in ranking
    ]
    for vendor in ranking:
        held = [c for c in eligible if c.vendor == vendor]
        if held:
            unknown = sorted({c.kind for c in held} - kind_order.keys())
            if unknown:
                raise KeyError(f"kind(s) {unknown} have no CVR bar_kind sort_order")
            return min(held, key=lambda c: (kind_order[c.kind], c.kind))
    return None


@lru_cache(maxsize=64)
def grid_by_session(timeframe: str, year: int) -> dict[date, frozenset[datetime]]:
    """Session date -> its regular-hours grid stamps, for the sessions of `year`."""
    out: dict[date, set[datetime]] = defaultdict(set)
    for stamp in rth_grid_stamps(timeframe, year, year):
        out[session_date(stamp)].add(stamp)
    return {day: frozenset(stamps) for day, stamps in out.items()}


def session_grid(timeframe: str, day: date) -> frozenset[datetime] | None:
    """The calendar's regular-hours stamps of session `day`; None for a timeframe without a
    session grid or a date that is no NYSE session."""
    if timeframe not in RTH_GRID_STEP_MINUTES:
        return None
    return grid_by_session(timeframe, day.year).get(day)


@dataclass(frozen=True)
class SessionChoice:
    """A session not taken whole from its primary vendor, or taken whole but holding fewer
    slots than the calendar's grid (module docstring; third review of plan 191-07, finding 4).
    Persisted in bar_session_choice by services/bar_selection.py."""

    symbol: str
    timeframe: str
    session: date
    ranking: tuple[str, ...]
    vendor: str  # the vendor the session was taken from
    complete: bool  # False: no ranked vendor held every slot; the others' slots were dropped
    n_slots: int  # the session's slots (held by any ranked vendor)
    n_vendor_slots: int  # of those, the chosen vendor's
    n_grid_slots: int | None = None  # the calendar's regular-hours slots (None: no grid)
    n_vendor_grid_slots: int | None = None  # of those, the chosen vendor's
    dropped: tuple[datetime, ...] = ()  # slots another vendor held that the session left out
    # the ranked-first vendor's regular-hours slots: 0 says the primary held nothing that
    # session (a fallback by absence), more says it held part (a fallback by shortfall)
    n_primary_grid_slots: int | None = None

    @property
    def fallback(self) -> bool:
        return self.vendor != self.ranking[0]

    @property
    def partial(self) -> bool:
        """The chosen vendor holds fewer regular-hours slots than the calendar has."""
        return self.n_grid_slots is not None and (self.n_vendor_grid_slots or 0) < self.n_grid_slots


@dataclass(frozen=True)
class SelectionOutcome:
    """The result of selecting a candidate set: winners plus the counts a loader must report."""

    winners: list[Candidate]
    n_slots: int  # on-grid slots with at least one candidate
    n_unselected: int  # of those, slots no ranked vendor holds (nothing is written for them)
    n_off_grid: int  # candidates dropped by the session rule
    # slots of a session another ranked vendor held but the chosen vendor did not (no complete
    # vendor): no winner, and the writer retracts a canonical row there
    dropped: tuple[tuple[str, str, datetime], ...] = ()
    # sessions not taken whole from the primary, or holding fewer slots than the calendar grid
    choices: tuple[SessionChoice, ...] = ()
    sessions: tuple[date, ...] = ()  # every session date selected (the choices' scope)


def select_slots(
    candidates: Iterable[Candidate],
    policy_rows: Sequence[PolicyRow],
    kind_order: Mapping[str, int],
) -> SelectionOutcome:
    """Select the winner of every on-grid slot present in `candidates`, one vendor per session
    (module docstring), with the counts."""
    on_grid, off_grid = partition_session(candidates)
    sessions: dict[tuple[str, str, date], dict[datetime, list[Candidate]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for c in on_grid:
        sessions[(c.symbol, c.timeframe, session_date(c.timestamp))][c.timestamp].append(c)
    scopes: dict[tuple[str, str], list[PolicyRow]] = {}
    winners: list[Candidate] = []
    dropped: list[tuple[str, str, datetime]] = []
    choices: list[SessionChoice] = []
    n_slots = n_unselected = 0
    for (symbol, timeframe, day), slots in sorted(sessions.items()):
        scoped = scopes.get((symbol, timeframe))
        if scoped is None:
            # the table holds a row per decision of every series; rank over this one's only
            scoped = scopes[(symbol, timeframe)] = [
                p for p in policy_rows if p.timeframe == timeframe and p.symbol in (None, symbol)
            ]
        ranking = rank_vendors(scoped, symbol, timeframe, day)
        n_slots += len(slots)
        # per slot, each ranked vendor's best candidate
        by_vendor: dict[str, dict[datetime, Candidate]] = {v: {} for v in ranking}
        for ts, here in slots.items():
            for vendor in ranking:
                best = select_slot(here, [vendor], kind_order)
                if best is not None:
                    by_vendor[vendor][ts] = best
        session_slots = set().union(*(set(v) for v in by_vendor.values()))
        n_unselected += len(slots) - len(session_slots)
        if not session_slots:
            continue
        # Completeness is judged on the calendar's regular-hours slots where the timeframe has a
        # grid: a vendor's after-close bar (IBKR SPY 16:00 to 16:10 ET) is no slot another
        # vendor owes, so it never makes a regular-hours vendor incomplete (third review, low).
        grid = session_grid(timeframe, day)
        judged = session_slots & grid if grid is not None else session_slots
        complete = [v for v in ranking if judged <= set(by_vendor[v])]
        if complete:
            chosen = complete[0]
        else:
            most = max(len(judged & set(by_vendor[v])) for v in ranking)
            chosen = next(v for v in ranking if len(judged & set(by_vendor[v])) == most)
        left_out = tuple(ts for ts in sorted(session_slots) if ts not in by_vendor[chosen])
        choice = SessionChoice(
            symbol,
            timeframe,
            day,
            tuple(ranking),
            chosen,
            bool(complete),
            len(session_slots),
            len(by_vendor[chosen]),
            None if grid is None else len(grid),
            None if grid is None else len(grid & set(by_vendor[chosen])),
            left_out,
            None if grid is None else len(grid & set(by_vendor[ranking[0]])),
        )
        if choice.fallback or not choice.complete or choice.partial:
            choices.append(choice)
        for ts in sorted(session_slots):
            if ts not in by_vendor[chosen]:
                dropped.append((symbol, timeframe, ts))
                continue
            winners.append(by_vendor[chosen][ts])
    return SelectionOutcome(
        winners,
        n_slots,
        n_unselected,
        len(off_grid),
        tuple(dropped),
        tuple(choices),
        tuple(sorted({day for (_s, _t, day) in sessions})),
    )


def select_all(
    candidates: Iterable[Candidate],
    policy_rows: Sequence[PolicyRow],
    kind_order: Mapping[str, int],
) -> list[Candidate]:
    """The winner of every on-grid slot present in `candidates`, sorted by (symbol, timeframe, timestamp)."""
    return select_slots(candidates, policy_rows, kind_order).winners
