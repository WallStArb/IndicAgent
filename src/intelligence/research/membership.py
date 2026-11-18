"""Point-in-time membership as one boolean mask over the panel (todo 609 blocker I1).

Features compute on every name ever a member and prices stay unmasked; only the IC cross-section
is gated, by `member[session, symbol]`. A decision built at month-end t is effective for the
sessions strictly after t (a decision made on t's close never sits in t's own cross-section).
Pure functions over arrays; the reader lives in snapshot.py.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence

import numpy as np

# A name is in the core panel when it is a member at this share or more of the built month-ends
# (prereg 2026-11-13 stage 2 amendment: 90 percent). A design constant of the preregistered
# panel definition, not a tunable.
CORE_SHARE = 0.9


def covered_through(as_of: dt.date) -> dt.date:
    """The last session date a ledger built through `as_of` covers: the end of the next month."""
    first = as_of.replace(day=1)
    after = (first + dt.timedelta(days=62)).replace(day=1)  # first of the month after next
    return after - dt.timedelta(days=1)


def member_mask(
    sessions: np.ndarray,
    symbols: Sequence[str],
    members_by_as_of: Mapping[dt.date, frozenset[str]],
) -> np.ndarray:
    """bool [n_sessions, n_symbols]: True where the symbol is a member for that session.

    `sessions` are datetime64[D] session dates, ascending. `members_by_as_of` holds one entry
    per built month-end (an empty set is a built month with no member). Session d reads the latest
    built as_of strictly before d; a session on or before the first as_of is all False; a
    session past the month after the last as_of raises (no extrapolation past the ledger).
    """
    if not members_by_as_of:
        raise ValueError("member_mask: the membership ledger is empty")
    as_ofs = sorted(members_by_as_of)
    ledger_days = np.array(as_ofs, dtype="datetime64[D]")
    covered_to = np.datetime64(covered_through(as_ofs[-1]), "D")
    if sessions.size and sessions.max() > covered_to:
        raise ValueError(
            f"membership is built through {as_ofs[-1]} (covers sessions to {covered_to}); "
            f"the panel has sessions to {sessions.max()}"
        )
    column = {symbol: j for j, symbol in enumerate(symbols)}
    month_rows = np.zeros((len(as_ofs), len(symbols)), dtype=bool)
    for i, as_of in enumerate(as_ofs):
        for symbol in members_by_as_of[as_of]:
            if symbol in column:
                month_rows[i, column[symbol]] = True
    # Index of the latest as_of strictly before each session; -1 before the first.
    slot = np.searchsorted(ledger_days, sessions, side="left") - 1
    mask = month_rows[np.maximum(slot, 0)]
    mask[slot < 0] = False
    return mask


def core_symbols(
    members_by_as_of: Mapping[dt.date, frozenset[str]], *, share: float = CORE_SHARE
) -> frozenset[str]:
    """The names that are members at `share` or more of the built month-ends."""
    if not members_by_as_of:
        raise ValueError("core_symbols: the membership ledger is empty")
    months = len(members_by_as_of)
    counts: dict[str, int] = {}
    for members in members_by_as_of.values():
        for symbol in members:
            counts[symbol] = counts.get(symbol, 0) + 1
    return frozenset(s for s, c in counts.items() if c >= share * months)


def apply_member_mask(array: np.ndarray, member: np.ndarray, bars_per_session: int) -> np.ndarray:
    """`array` [n_rows, m] with NaN where the (session, symbol) is not a member.

    `member` is [n_sessions, m]; each session's mask repeats over its `bars_per_session` rows.
    Missing is NaN, never filled (no_fill): a non-member cell gives no value downstream.
    """
    if array.shape[0] != member.shape[0] * bars_per_session or array.shape[1:] != member.shape[1:]:
        raise ValueError(f"member mask {member.shape} does not fit array {array.shape}")
    rows = np.repeat(member, bars_per_session, axis=0)
    return np.where(rows, array, np.nan)


def seen_member_mask(member: np.ndarray) -> np.ndarray:
    """bool [n_sessions, m]: True from a name's first membership session onward, member or not.

    S1 is fitted on the names in this mask at each date and no others, so no name enters a
    date's market mean, clustering or principal components because of a membership that begins
    later (point_in_time: selection on future liquidity). A name that has left the membership
    stays in: its exit is known at the exit, and its returns after it are facts at t.
    """
    return np.maximum.accumulate(member, axis=0)


def apply_seen_prices(
    open_: np.ndarray, close: np.ndarray, seen: np.ndarray, bars_per_session: int
) -> tuple[np.ndarray, np.ndarray]:
    """`open_` and `close` with NaN before each name's first membership session.

    The only panel handed to S1 (residual bar returns and forward target): its return at row t is
    NaN for a name not yet seen as a member at t, so the name is out of every cross-sectional
    statistic of that date without any change to S1. Costs an entrant its pre-entry residual
    history inside member windows (they warm from first membership), a disclosed design choice.
    """
    return (
        apply_member_mask(open_, seen, bars_per_session),
        apply_member_mask(close, seen, bars_per_session),
    )


def cold_start_share_by_year(
    member: np.ndarray, years: np.ndarray, memory_sessions: int
) -> dict[int, float]:
    """Per calendar year, the share of member-days whose residual window is not yet warm because
    of entry: fewer than `memory_sessions` sessions since the name's first membership.

    The price of the seen-names rule (apply_seen_prices): an entrant's residual history starts at
    first membership. Measured at the membership build and shown to the owner with the member
    counts; a large share is answered by a counted amendment, never by a quiet change.
    `years` is the calendar year of each session, [n_sessions].
    """
    if memory_sessions < 1:
        raise ValueError(f"memory_sessions must be at least 1, got {memory_sessions}")
    n = member.shape[0]
    if years.shape != (n,):
        raise ValueError(f"years has shape {years.shape}, expected {(n,)}")
    first = np.where(member.any(axis=0), np.argmax(member, axis=0), n)
    cold = member & ((np.arange(n)[:, None] - first[None, :]) < memory_sessions)
    out: dict[int, float] = {}
    for year in np.unique(years).tolist():
        rows = years == year
        days = int(member[rows].sum())
        if days:
            out[int(year)] = float(cold[rows].sum()) / days
    return out
