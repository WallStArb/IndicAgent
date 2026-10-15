"""Restatement detector: what a vendor's re-serve changed, reported, never blocking (D-191-N).

Owner decision 2026-10-14 (docs/plans/2026-10-12-unified-raw-bar-table-design.md, D-191-N): a
vendor's own re-serve always overwrites its raw value last-wins and the old value is logged as a
revision, so every overwrite is recoverable. Nothing is refused and nothing is held. What the
refusal guarded against, a vendor silently changing the basis of its history, is detected here
and reported loudly instead:

- `share`: changed rows over the vendor's stored rows of the offered keys;
- `price_ratio`: many changed bars whose new prices are one near-constant multiple of the old
  ones (a split or dividend adjustment, a currency or precision change applied to history);
- `time_shift`: many changed bars whose new values equal the stored values one bar earlier or
  later (a vendor shifting its stamps).

Pure functions over the offered and stored values; the thresholds come from APR
(`threshold.bar_integrity.restatement_*`, migration 481) through the caller.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

Values = tuple  # (open, high, low, close, volume)

SIGNATURE_SHARE = "share"
SIGNATURE_PRICE_RATIO = "price_ratio"
SIGNATURE_TIME_SHIFT = "time_shift"


@dataclass(frozen=True)
class DetectorParams:
    """APR thresholds of the restatement detector (migration 481)."""

    flag_share: float  # flag a load whose changed share of stored rows exceeds this
    flag_min_stored: int  # ... over at least this many stored rows
    signature_min_bars: int  # a signature needs at least this many changed bars
    ratio_tolerance: float  # largest relative spread of the price ratios around their median
    shift_min_share: float  # share of changed bars equal to a neighbour's stored value


@dataclass(frozen=True)
class Restatement:
    n_stored: int
    n_changed: int
    share: float
    signatures: tuple[str, ...]
    ratio: float | None = None  # the median new/old price ratio when price_ratio fired
    shift_bars: int | None = None  # -1 or +1 when time_shift fired

    @property
    def flagged(self) -> bool:
        return bool(self.signatures)

    def detail(self) -> str:
        parts = [f"changed {self.n_changed} / stored {self.n_stored} = {self.share:.4f}"]
        if self.ratio is not None:
            parts.append(f"price ratio {self.ratio:.6f}")
        if self.shift_bars is not None:
            parts.append(f"time shift {self.shift_bars:+d} bar")
        return "; ".join(parts) + f"; signatures {list(self.signatures)}"


def _price_ratios(new: Values, old: Values) -> list[float]:
    return [n / o for n, o in zip(new[:4], old[:4], strict=True) if o not in (None, 0) and n]


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
    ratio = shift = None
    if len(changed) >= params.signature_min_bars:
        ratios = [r for ts in changed for r in _price_ratios(offered[ts], stored[ts])]
        if ratios:
            median = statistics.median(ratios)
            spread = max(abs(r / median - 1.0) for r in ratios)
            if spread <= params.ratio_tolerance and abs(median - 1.0) > params.ratio_tolerance:
                signatures.append(SIGNATURE_PRICE_RATIO)
                ratio = median
        for step in (-1, 1):
            hits = sum(1 for ts in changed if stored.get(ts + step * bar) == offered[ts])
            if hits / len(changed) >= params.shift_min_share:
                signatures.append(SIGNATURE_TIME_SHIFT)
                shift = step
                break
    return Restatement(n_stored, len(changed), share, tuple(signatures), ratio, shift)
