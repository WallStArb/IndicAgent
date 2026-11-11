"""Split-adjusted basis for Massive winners: raw (unadjusted) in, canonical (adjusted) out.

Design: docs/plans/2026-11-10-massive-admission-db-design.md section 5. Raw stores Massive bars as
served; canonical holds split-adjusted prices, so selection rescales a Massive winner by the
recorded splits and gives it the canonical kind `sip_flat_adj`. Pure Ring 1: arrays and
dataclasses in, the same out, no database. Which split rows are passed (the `recorded_at` horizon,
the announcement-time rule) is the caller's contract (`splits_known_at`); this module applies the
arithmetic.

The arithmetic is the daily rule's (d2-v5 `split_scale`, and the lineage view it must stay
bit-exact with): a split's `effective_date` is the last session on the old scale, so every bar
dated on or before it is divided by `factor`; several splits multiply left to right in
effective-date order and the bar is divided once by the product. Volume is a share count and is
multiplied by the same scale, rounded half up (`floor(x + 0.5)`) so it stays an integer. The
session date of a stamp is its America/New_York calendar date.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime

from src.intelligence.bars.selection import SESSION_TZ, Candidate, session_date
from src.intelligence.bars.vendor_kind import (
    KIND_MASSIVE_1D,
    KIND_MASSIVE_5M,
    KIND_MASSIVE_CANONICAL,
    VENDOR_MASSIVE,
)

#: Raw (vendor, kind) pairs served unadjusted, which selection rescales into the canonical kind.
_UNADJUSTED_RAW_KINDS = frozenset(
    {(VENDOR_MASSIVE, KIND_MASSIVE_5M), (VENDOR_MASSIVE, KIND_MASSIVE_1D)}
)


@dataclass(frozen=True)
class SplitFactor:
    """One recorded split: the last session on the old scale, and the factor old prices divide by
    (10.0 for a 10:1 forward split, 0.1 for a 1:10 reverse split)."""

    effective_date: date
    factor: float


@dataclass(frozen=True)
class SplitRow:
    """A corporate_action_current split row as read: the factor, when it was recorded, and
    whether it records the market's split (corporate_actions.is_market_split): an incumbent
    route correction (a todo 592 operator row) never rescales an unadjusted series."""

    effective_date: date
    factor: float
    recorded_at: datetime
    market_fact: bool


def splits_known_at(rows: Iterable[SplitRow], horizon: datetime) -> list[SplitFactor]:
    """The splits a selection run pinned at `horizon` may apply. A row counts when it was
    recorded by the horizon (the corporate_action table is append-only, so the same horizon
    always selects the same rows) and its effective_date is not after the horizon's New York
    date: a split not yet executed at the horizon must not rescale history, because the real
    prices at the horizon are still pre-split. Only market splits count: raw Massive is served
    unadjusted, so the factor is the market's split, and a row correcting one incumbent's
    mis-scaled route (PATK x0.4 fixes IBKR) would rescale a series that never carried the error.
    No declaration date exists in the data, so a rebuild is an as-of-horizon snapshot (design
    section 5, limitation)."""
    if horizon.tzinfo is None:
        raise ValueError("horizon must be timezone-aware")
    last_executed = horizon.astimezone(SESSION_TZ).date()
    return [
        SplitFactor(row.effective_date, row.factor)
        for row in rows
        if row.market_fact and row.recorded_at <= horizon and row.effective_date <= last_executed
    ]


def needs_canonicalization(winners: Iterable[Candidate]) -> bool:
    """True when any winner is an unadjusted Massive row (so the splits must be read)."""
    return any((c.vendor, c.kind) in _UNADJUSTED_RAW_KINDS for c in winners)


def scales_for_sessions(days: Iterable[date], splits: Sequence[SplitFactor]) -> dict[date, float]:
    """The cumulative factor dividing the prices of each session date (1.0 when no split covers it).
    Splits multiply onto 1.0 in effective-date order, the order the lineage view uses."""
    ordered = sorted(splits, key=lambda split: split.effective_date)
    scales: dict[date, float] = {}
    for day in set(days):
        scale = 1.0
        for split in ordered:
            if day <= split.effective_date:
                scale *= split.factor
        scales[day] = scale
    return scales


def rescale_volume(volume: int | None, scale: float) -> int | None:
    """A share count on the adjusted basis, rounded half up; None stays None."""
    return None if volume is None else int(math.floor(volume * scale + 0.5))


def canonicalize_winners(
    winners: Iterable[Candidate], splits_by_symbol: Mapping[str, Sequence[SplitFactor]]
) -> list[Candidate]:
    """Selection winners with every unadjusted Massive row rescaled to the split-adjusted basis
    and given the canonical kind; every other winner is returned as is. A symbol missing from
    `splits_by_symbol` has no recorded split (scale 1.0), which still changes the kind."""
    held = list(winners)
    days_by_symbol: dict[str, set[date]] = {}
    for c in held:
        if (c.vendor, c.kind) in _UNADJUSTED_RAW_KINDS:
            days_by_symbol.setdefault(c.symbol, set()).add(session_date(c.timestamp))
    scales = {
        symbol: scales_for_sessions(days, splits_by_symbol.get(symbol, ()))
        for symbol, days in days_by_symbol.items()
    }
    out: list[Candidate] = []
    for c in held:
        if (c.vendor, c.kind) not in _UNADJUSTED_RAW_KINDS:
            out.append(c)
            continue
        scale = scales[c.symbol][session_date(c.timestamp)]
        out.append(
            replace(
                c,
                kind=KIND_MASSIVE_CANONICAL,
                open=c.open / scale,
                high=c.high / scale,
                low=c.low / scale,
                close=c.close / scale,
                volume=rescale_volume(c.volume, scale),
            )
        )
    return out
