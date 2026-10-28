"""A feature or kernel member's memory: the one place it is computed (184 RESEARCH Pattern 4).

A member reads its source column through the alignment, optionally smooths it on the fixed
menu (smoothing.py), and applies its own transform. The sessions a member's value at t can
read before t are

    ceil((source_memory_bars + max_age_rows) / source_bars_per_session)
        + smoothing_memory_sessions(smoothing_half_life)   (0 without smoothing)
        + slot_history_sessions

source_memory_bars is the source column's own reach on its own clock (the registry's
`feature_memory_bars` for a stored column, `kernel_source.kernel_member_memory_bars` for a
kernel; the caller passes the integer, so this module imports neither). max_age_rows is the
alignment's staleness bound, counted on the source grid. For an input member,
`slot_history_sessions` is the member transform's own additional reach over its aligned input,
on top of the source feature's memory; it never restates the source memory (184-REVIEWS
row 21).

The result is slot history in sessions and rows, nothing more. Every consumer reads the one
MemberMemory object (184-REVIEWS row 11): S0's warmup prefix is the max of `sessions` over the
book's members (warmup_prefix_sessions); S3's memory check declares `transform_rows`, the reach
of smoothing plus the member transform over the aligned input; and E17's L is
`timing.e17_memory` over `sessions` (through `book.book_memory`), which adds a daily target's
reach. Smoothing adds into slot history, never into L directly, and nothing here derives L.

Smoothing is defined on the daily clock only in this phase (RESEARCH A5), so a smoothed member
on a book with more than one bar per session is refused.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence

from src.intelligence.research.smoothing import smoothing_memory_sessions


@dataclasses.dataclass(frozen=True)
class MemberMemory:
    source_memory_bars: int  # the source column's reach, source bars
    max_age_rows: int  # the alignment's staleness bound, source rows
    smoothing_sessions: int  # the smoother's k_max, 0 without smoothing
    slot_history_sessions: int  # the member transform's reach over its aligned input
    book_bars_per_session: int
    sessions: int  # everything the member's value at t reads before t, in sessions
    rows: int  # `sessions` on the book clock

    @property
    def transform_rows(self) -> int:
        """Smoothing plus the member transform over the aligned input, on the book clock: the
        reach S3's memory check declares for the member's transform."""
        return (self.smoothing_sessions + self.slot_history_sessions) * self.book_bars_per_session


def _non_negative_int(name: str, value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return value


def feature_member_memory(
    *,
    source_memory_bars: int,
    source_bars_per_session: int,
    max_age_rows: int,
    smoothing_half_life: int | None,
    slot_history_sessions: int,
    book_bars_per_session: int,
) -> MemberMemory:
    _non_negative_int("source_memory_bars", source_memory_bars)
    _non_negative_int("source_bars_per_session", source_bars_per_session, minimum=1)
    _non_negative_int("max_age_rows", max_age_rows)
    _non_negative_int("slot_history_sessions", slot_history_sessions)
    _non_negative_int("book_bars_per_session", book_bars_per_session, minimum=1)
    smoothing = 0
    if smoothing_half_life is not None:
        if book_bars_per_session != 1:
            raise ValueError(
                f"smoothing is defined on a daily book clock only, got "
                f"{book_bars_per_session} bars per session"
            )
        smoothing = smoothing_memory_sessions(smoothing_half_life)
    source = math.ceil((source_memory_bars + max_age_rows) / source_bars_per_session)
    sessions = source + smoothing + slot_history_sessions
    return MemberMemory(
        source_memory_bars=source_memory_bars,
        max_age_rows=max_age_rows,
        smoothing_sessions=smoothing,
        slot_history_sessions=slot_history_sessions,
        book_bars_per_session=book_bars_per_session,
        sessions=sessions,
        rows=sessions * book_bars_per_session,
    )


def feature_member_memory_sessions(
    *,
    source_memory_bars: int,
    source_bars_per_session: int,
    max_age_rows: int,
    smoothing_half_life: int | None,
    slot_history_sessions: int,
    book_bars_per_session: int,
) -> int:
    return feature_member_memory(
        source_memory_bars=source_memory_bars,
        source_bars_per_session=source_bars_per_session,
        max_age_rows=max_age_rows,
        smoothing_half_life=smoothing_half_life,
        slot_history_sessions=slot_history_sessions,
        book_bars_per_session=book_bars_per_session,
    ).sessions


def feature_member_memory_rows(
    *,
    source_memory_bars: int,
    source_bars_per_session: int,
    max_age_rows: int,
    smoothing_half_life: int | None,
    slot_history_sessions: int,
    book_bars_per_session: int,
) -> int:
    return feature_member_memory(
        source_memory_bars=source_memory_bars,
        source_bars_per_session=source_bars_per_session,
        max_age_rows=max_age_rows,
        smoothing_half_life=smoothing_half_life,
        slot_history_sessions=slot_history_sessions,
        book_bars_per_session=book_bars_per_session,
    ).rows


def warmup_prefix_sessions(member_sessions: Sequence[int]) -> int:
    """S0's warmup prefix: the largest member memory in sessions, 0 for no members."""
    for i, value in enumerate(member_sessions):
        _non_negative_int(f"member_sessions[{i}]", value)
    return max(member_sessions, default=0)
