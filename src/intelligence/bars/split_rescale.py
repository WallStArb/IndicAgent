"""Split-adjusted basis for Massive winners: raw (unadjusted) in, canonical (adjusted) out.

Design: docs/plans/2026-11-10-massive-admission-db-design.md section 5. Raw stores Massive bars as
served; canonical holds split-adjusted prices, so selection rescales a Massive winner by the
recorded splits and gives it the canonical kind `sip_flat_adj`. Pure Ring 1: arrays and
dataclasses in, the same out, no database. Which split rows are passed (the `recorded_at` horizon,
the announcement-time rule) is the caller's contract; this module only applies the arithmetic.

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
from datetime import date

from src.intelligence.bars.selection import Candidate, session_date
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
