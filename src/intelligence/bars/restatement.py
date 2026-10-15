"""Restatement detector: what a vendor's re-serve changed, reported, never blocking (D-191-N).

Owner decision 2026-10-14 (docs/plans/2026-10-12-unified-raw-bar-table-design.md, D-191-N): a
vendor's own re-serve always overwrites its raw value last-wins and the old value is logged as a
revision, so every overwrite is recoverable. Nothing is refused and nothing is held. What the
refusal guarded against, a vendor silently changing the basis of its history, is detected here
and reported loudly instead:

- `share`: changed rows over the vendor's stored rows of the offered keys. Informational: routine
  one-cent and late-print revisions reach it, so it never makes a run partial;
- `price_ratio`: most changed bars carry new prices that are one multiple of the old ones (a
  split or dividend adjustment, a currency change applied to history). Robust by construction
  (fourth review of 191-07, finding 3): the multiple is the median of every changed price's
  ratio, a bar agrees when each of its four prices sits within the relative tolerance plus the
  cent rounding of both values (one tick, scaled by the multiple) of that multiple, and the
  signature needs only an APR share of the changed bars to agree, so a few unrelated corrected
  bars in the same re-serve do not hide it;
- `volume_ratio`: the same test on volume (a unit change such as lots of 100 versus shares,
  which leaves every price equal), the integer rounding of one old unit allowed;
- `time_shift`: many changed bars whose new values equal the stored values one bar earlier or
  later (a vendor shifting its stamps).

`price_ratio`, `volume_ratio` and `time_shift` are basis-change signatures (`BASIS_SIGNATURES`):
a flag carrying one makes the run partial and stays on the review queue until a reviewer marks
it (scripts/ops/bars/ops_restatement_review.py). Every signature needs only
`signature_min_bars` changed bars, never `flag_min_stored`, so a one-session overlap is judged.

Pure functions over the offered and stored values; the thresholds come from APR
(`threshold.bar_integrity.restatement_*`, migrations 481 and 485) through the caller.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

Values = tuple  # (open, high, low, close, volume)

SIGNATURE_SHARE = "share"
SIGNATURE_PRICE_RATIO = "price_ratio"
SIGNATURE_VOLUME_RATIO = "volume_ratio"
SIGNATURE_TIME_SHIFT = "time_shift"
BASIS_SIGNATURES = frozenset({SIGNATURE_PRICE_RATIO, SIGNATURE_VOLUME_RATIO, SIGNATURE_TIME_SHIFT})


@dataclass(frozen=True)
class DetectorParams:
    """APR thresholds of the restatement detector (migrations 481 and 485)."""

    flag_share: float  # flag a load whose changed share of stored rows exceeds this
    flag_min_stored: int  # ... over at least this many stored rows (share signature only)
    signature_min_bars: int  # a basis signature needs at least this many changed bars
    ratio_tolerance: float  # relative distance of a price from the median multiple
    shift_min_share: float  # share of changed bars equal to a neighbour's stored value
    ratio_min_share: float = 0.8  # share of changed bars that must agree with the multiple
    ratio_min_move: float = 0.002  # the price multiple must differ from 1 by more than this
    price_tick: float = 0.01  # the price grid both answers are rounded to
    volume_tolerance: float = 0.01  # relative distance of a volume from the median multiple
    volume_min_move: float = 0.2  # the volume multiple must differ from 1 by more than this


@dataclass(frozen=True)
class Restatement:
    n_stored: int
    n_changed: int
    share: float
    signatures: tuple[str, ...]
    ratio: float | None = None  # the median new/old price multiple when price_ratio fired
    shift_bars: int | None = None  # -1 or +1 when time_shift fired
    volume_ratio: float | None = None  # the median new/old volume multiple when it fired

    @property
    def flagged(self) -> bool:
        return bool(self.signatures)

    @property
    def basis_change(self) -> bool:
        """A basis-change signature fired: the run is partial until the flag is reviewed."""
        return bool(BASIS_SIGNATURES.intersection(self.signatures))

    def detail(self) -> str:
        parts = [f"changed {self.n_changed} / stored {self.n_stored} = {self.share:.4f}"]
        if self.ratio is not None:
            parts.append(f"price ratio {self.ratio:.6f}")
        if self.volume_ratio is not None:
            parts.append(f"volume ratio {self.volume_ratio:.6f}")
        if self.shift_bars is not None:
            parts.append(f"time shift {self.shift_bars:+d} bar")
        return "; ".join(parts) + f"; signatures {list(self.signatures)}"


def _positive(value) -> bool:
    return value is not None and value > 0


def _price_multiple(changed: list[tuple[Values, Values]], params: DetectorParams) -> float | None:
    """The common new/old price multiple of the changed bars, or None when there is none."""
    pairs = [
        (new, old)
        for new, old in changed
        if all(_positive(p) for p in new[:4]) and all(_positive(p) for p in old[:4])
    ]
    if len(pairs) < params.signature_min_bars:
        return None
    multiple = statistics.median(n / o for new, old in pairs for n, o in zip(new[:4], old[:4]))
    typical_old = statistics.median(old[3] for _new, old in pairs)
    if abs(multiple - 1.0) <= params.ratio_min_move:
        return None
    if abs(multiple - 1.0) * typical_old <= 2 * params.price_tick:
        return None  # a move inside cent rounding is not a basis change
    rounding = params.price_tick * (1.0 + multiple) / 2.0

    def agrees(new: Values, old: Values) -> bool:
        return all(
            abs(n - o * multiple) <= params.ratio_tolerance * o * multiple + rounding
            for n, o in zip(new[:4], old[:4])
        )

    n_agree = sum(1 for new, old in pairs if agrees(new, old))
    return multiple if n_agree / len(pairs) >= params.ratio_min_share else None


def _volume_multiple(changed: list[tuple[Values, Values]], params: DetectorParams) -> float | None:
    """The common new/old volume multiple of the changed bars, or None when there is none."""
    pairs = [(new[4], old[4]) for new, old in changed if _positive(new[4]) and _positive(old[4])]
    if len(pairs) < params.signature_min_bars:
        return None
    multiple = statistics.median(n / o for n, o in pairs)
    if abs(multiple - 1.0) <= params.volume_min_move:
        return None
    rounding = max(multiple, 1.0)  # one unit of the coarser of the two volume grids
    n_agree = sum(
        1
        for n, o in pairs
        if abs(n - o * multiple) <= params.volume_tolerance * o * multiple + rounding
    )
    return multiple if n_agree / len(pairs) >= params.ratio_min_share else None


def detect(
    offered: Mapping[datetime, Values],
    stored: Mapping[datetime, Values],
    bar: timedelta,
    params: DetectorParams,
) -> Restatement:
    """Compare one series' offer with the vendor's stored values at the same keys (`stored`
    holds a value for every offered key the vendor had stored; others are new)."""
    changed = [ts for ts, v in offered.items() if ts in stored and stored[ts] != v]
    n_stored = sum(1 for ts in offered if ts in stored)
    share = len(changed) / n_stored if n_stored else 0.0
    signatures: list[str] = []
    if n_stored >= params.flag_min_stored and share > params.flag_share:
        signatures.append(SIGNATURE_SHARE)
    ratio = shift = volume = None
    if len(changed) >= params.signature_min_bars:
        pairs = [(offered[ts], stored[ts]) for ts in changed]
        ratio = _price_multiple(pairs, params)
        if ratio is not None:
            signatures.append(SIGNATURE_PRICE_RATIO)
        volume = _volume_multiple(pairs, params)
        if volume is not None:
            signatures.append(SIGNATURE_VOLUME_RATIO)
        for step in (-1, 1):
            hits = sum(1 for ts in changed if stored.get(ts + step * bar) == offered[ts])
            if hits / len(changed) >= params.shift_min_share:
                signatures.append(SIGNATURE_TIME_SHIFT)
                shift = step
                break
    return Restatement(n_stored, len(changed), share, tuple(signatures), ratio, shift, volume)
