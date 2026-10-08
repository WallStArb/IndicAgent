"""Corporate-action records from seams and disputed dividend dates (D-21, D-23).

infer_split decides whether a seam is a split: only a factor that snaps to a
rational p/q with p, q <= 50 becomes a corporate action, so a drift-shaped or
news-shaped ratio that slipped past the seam detector as a tight band still
cannot masquerade as a 1.73-for-1 split. A seam that does not snap stays
unexplained (None) for the audit to report.

The disputed-date rule handles the 1-5 day ex-date disagreements between the
IBKR-derived and Yahoo dividend sources (26 events on 18 names, measured
2026-09-26). The conservative choice is neither keeping both rows (one dividend
counted twice) nor rolling the symbol back: each near-miss pair becomes one
record whose span marks every return crossing it unknown. The span extends one
session below first_date because a return entered at the session before the
earliest possible ex-date already spans the event: the drop lands between that
session's close and the next open.

The pair shape (ibkr_date, yahoo_date) is the same shape
services/dividend_event_writer.py's Reconciliation.near_misses produces, so the
D5 writer can feed this function directly.

Pure: values in, records out; no database, no config service, no I/O.
ratio_snap_tol is a keyword argument supplied by the caller from APR (plan 22
seeds threshold.seam.ratio_snap_tol); there is no default here.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from src.intelligence.bars.seams import Seam

# The largest numerator or denominator a plausible split ratio carries
# (interface bound from plan 185-07, definitional: it separates real corporate
# actions from arbitrary rationals, it is not an operator tunable).
_MAX_SPLIT_TERMS = 50


@dataclass(frozen=True)
class SplitInference:
    """One seam explained as a split or reverse split.

    effective_date is the seam's end (the last day on the old scale), factor the
    snapped rational p/q (2.0 = 2-for-1, 0.125 = 1-for-8) and evidence_days the
    run length that carried the constant ratio.
    """

    effective_date: date
    factor: float
    kind: Literal["split", "reverse_split"]
    evidence_days: int


def infer_split(seam: Seam, *, ratio_snap_tol: float) -> SplitInference | None:
    """The split a seam explains, or None when its factor snaps to no rational.

    Searches p/q over 1 <= p, q <= 50 for the closest rational to seam.factor
    (ties broken toward the smaller denominator) and accepts it when the gap is
    within ratio_snap_tol. A snap to 1 is refused: a ratio that close to 1 is
    not a split, and the seam stays unexplained.
    """
    best_p = best_q = 1
    best_diff = float("inf")
    for q in range(1, _MAX_SPLIT_TERMS + 1):
        p = min(_MAX_SPLIT_TERMS, max(1, round(seam.factor * q)))
        diff = abs(seam.factor - p / q)
        if diff < best_diff:
            best_diff, best_p, best_q = diff, p, q
    if best_p == best_q or best_diff > ratio_snap_tol:
        return None
    return SplitInference(
        effective_date=seam.end,
        factor=best_p / best_q,
        kind="split" if best_p > best_q else "reverse_split",
        evidence_days=seam.n_days,
    )


@dataclass(frozen=True)
class SplitRatioRule:
    """What counts as a split ratio (plan 185-51, todo 515; APR infra.backfill.split_ratio_*,
    migration 461).

    infer_split's snap (p, q <= 50) separates a constant seam from noise, but 39/7 snaps too:
    CTVA's spin-off rescale of 2026-10-08 was recorded as a split. Real splits are small integer
    ratios (2:1, 3:2, 4:1, 1:3, 1:20), so a recognised ratio also caps the smaller term.
    """

    max_numerator: int
    max_denominator: int
    rel_tol: float


def recognised_split_ratio(factor: float, rule: SplitRatioRule) -> float | None:
    """The split ratio a measured stored/fresh factor is, or None when it is no split ratio.

    Accepted when factor or 1/factor is within rule.rel_tol (relative) of p/q with
    1 <= q <= rule.max_denominator, p <= rule.max_numerator and p != q (a ratio of 1 is no
    split). The smallest denominator wins, and the exact ratio is returned in the factor's own
    orientation (1/3 for a 1-for-3 reverse split, 1.5 for 3-for-2).

    A rescale that happens to land on a small ratio still passes (Tradier's CTVA factor 6.665 is
    0.025 % from 20/3): the rule bounds the false-split rate, it does not identify spin-offs.
    """
    if not (math.isfinite(factor) and factor > 0):
        raise ValueError(f"factor must be positive and finite, got {factor!r}")
    if rule.max_numerator < 2 or rule.max_denominator < 1 or not 0 < rule.rel_tol < 1:
        raise ValueError(f"unusable split ratio rule {rule!r}")
    for q in range(1, rule.max_denominator + 1):
        for ratio, inverted in ((factor, False), (1.0 / factor, True)):
            p = round(ratio * q)
            if p < 1 or p > rule.max_numerator or p == q:
                continue
            if abs(ratio * q / p - 1.0) <= rule.rel_tol:
                return q / p if inverted else p / q
    return None


@dataclass(frozen=True)
class DisputedDate:
    """One dividend reported by both sources with disagreeing ex-dates.

    first_date/last_date are the ordered span (inclusive); dates_by_source maps
    each source name to the ex-date it reported.
    """

    symbol: str
    first_date: date
    last_date: date
    dates_by_source: dict[str, date]


def disputed_dates(
    symbol: str,
    near_misses: Sequence[tuple[date, date]],
    sources: tuple[str, str] = ("ibkr_adjusted_last_ratio", "yahoo"),
) -> list[DisputedDate]:
    """One DisputedDate per near-miss pair, sorted by first_date.

    near_misses are (ibkr ex-date, yahoo ex-date) pairs as reconcile() emits
    them; sources names them for dates_by_source. Raises ValueError on a
    same-date pair (that is a match, not a dispute) or on malformed sources.
    """
    if len(sources) != 2 or sources[0] == sources[1]:
        raise ValueError(f"disputed dates need two distinct source names, got {sources}")
    records: list[DisputedDate] = []
    for ibkr_day, other_day in near_misses:
        if ibkr_day == other_day:
            raise ValueError(
                f"same date {ibkr_day} from both sources is a match, not a disputed date"
            )
        records.append(
            DisputedDate(
                symbol=symbol,
                first_date=min(ibkr_day, other_day),
                last_date=max(ibkr_day, other_day),
                dates_by_source={sources[0]: ibkr_day, sources[1]: other_day},
            )
        )
    records.sort(key=lambda record: (record.first_date, record.last_date))
    return records


def unknown_return_mask(
    session_dates: np.ndarray,
    entry_idx: np.ndarray,
    exit_idx: np.ndarray,
    disputes: Sequence[DisputedDate],
) -> np.ndarray:
    """Boolean mask over returns: True where the return's session span crosses a dispute.

    A return crosses a dispute when its [entry, exit] session span intersects
    the disputed span [first_date - 1 session, last_date]. session_dates is the
    symbol's session calendar (strictly ascending date or datetime objects,
    datetime64 arrays accepted); entry_idx/exit_idx index into it.

    Raises ValueError on mismatched return-array lengths, an unsorted calendar,
    or out-of-bounds indices: a wrong calendar would silently mark the wrong
    returns, which is worse than failing loudly.
    """
    calendar = np.asarray(session_dates)
    sessions = calendar.tolist()
    n = len(sessions)
    if any(sessions[i] >= sessions[i + 1] for i in range(n - 1)):
        raise ValueError("session_dates must be strictly ascending")
    entry = np.asarray(entry_idx)
    exit_ = np.asarray(exit_idx)
    if entry.ndim != 1 or exit_.ndim != 1 or entry.size != exit_.size:
        raise ValueError(
            f"entry/exit arrays must be 1-D of one length, got {entry.size}, {exit_.size}"
        )
    if entry.size and (
        int(entry.min()) < 0
        or int(entry.max()) >= n
        or int(exit_.min()) < 0
        or int(exit_.max()) >= n
    ):
        raise ValueError(f"return indices out of bounds for {n} sessions")

    mask = np.zeros(entry.size, dtype=bool)
    for dispute in disputes:
        hi = bisect_right(sessions, dispute.last_date) - 1
        if hi < 0:
            continue  # the whole dispute predates the calendar
        lo = bisect_left(sessions, dispute.first_date) - 1
        mask |= (entry <= hi) & (exit_ >= lo)
    return mask
