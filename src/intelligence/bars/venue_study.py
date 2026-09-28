"""D3 listing-venue validation study statistics (D-17).

Before venue bars may enter canonical derivation, a study on at least 30 names
with known listing venues across NYSE, Nasdaq and NYSE Arca must show (a) the
listing venue has the most volume on nearly every day and (b) only its closes
match SMART's. The thresholds, name-selection rule, seed, windows and verdict
rule are pre-registered in config/bars/venue_study_preregistration.json and
committed before any study fetch; this module only computes the statistics and
judges them against whatever mapping it is handed, so the numbers and the code
cannot be tuned to data the study has already seen.

Semantics fixed here (the pre-registration names the numbers, this docstring
the rules):
- "Most volume" is per SMART day: the listing venue's volume that day is
  strictly greater than every other route's volume that day. A day the listing
  venue is missing, or carries a NULL or non-finite volume, counts as not-max;
  days other routes are missing simply remove them from the comparison. The
  denominator is always the name's full SMART day count: nothing is dropped.
- A close matches when |venue - smart| <= max(close_tolerance_abs,
  close_tolerance_rel * |smart|). Missing venue days count as not-matched.
- Criterion b needs the listing venue's match share at or above its floor and
  every other route's share at or below non_listing_match_share_max.
- The study verdict (passed = criterion_a_pass and criterion_b_pass) applies to
  a structurally valid study: fewer names than selection.min_names, or fewer
  than min_per_venue on any selected venue, fails the study outright with a
  reason.

Listing venues arrive as IBKR primaryExchange values; ISLAND is Nasdaq's
routing code, so NASDAQ is normalized to ISLAND exactly as
src/providers/ibkr.py's _VENUE_ALIASES does (the alias table is mirrored here
because this module is pure and must not import the provider).

Pure: dicts and the pre-registration mapping in, verdicts out; no database, no
IBKR, no I/O.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Mirror of src/providers/ibkr.py _VENUE_ALIASES: a contract's primaryExchange
# reads NASDAQ while ISLAND is the routing code.
_VENUE_ALIASES: dict[str, str] = {"NASDAQ": "ISLAND"}


@dataclass(frozen=True)
class NameEvaluation:
    """One name's statistics over the study window.

    listing_max_volume_share is the share of the name's SMART days on which the
    listing venue had the most volume; close_match_share_by_venue maps every
    route in the input (plus the listing venue at 0.0 when wholly absent) to
    its share of days matching SMART's close.
    """

    symbol: str
    listing_venue: str
    n_days: int
    listing_max_volume_share: float
    close_match_share_by_venue: dict[str, float]
    passes_volume: bool
    passes_close: bool


@dataclass(frozen=True)
class VenueStudyResult:
    """The whole study's verdict for one timeframe."""

    timeframe: str
    names: tuple[NameEvaluation, ...]
    n_names_by_venue: dict[str, int]
    criterion_a_pass: bool
    criterion_b_pass: bool
    passed: bool
    reasons: tuple[str, ...]


def _valid_volume(value: Any) -> bool:
    return (
        value is not None and isinstance(value, (int, float)) and math.isfinite(value) and value > 0
    )


def _close_matches(venue_close: Any, smart_close: float, criterion_b: Mapping[str, float]) -> bool:
    if not isinstance(venue_close, (int, float)) or not math.isfinite(venue_close):
        return False
    tolerance = max(
        criterion_b["close_tolerance_abs"],
        criterion_b["close_tolerance_rel"] * abs(smart_close),
    )
    return abs(venue_close - smart_close) <= tolerance


def evaluate_name(
    symbol: str,
    listing_venue: str,
    smart_close: dict[Any, float],
    venue_bars: dict[str, dict[Any, tuple[float, float]]],
    prereg: Mapping[str, Any],
) -> NameEvaluation:
    """One name's venue statistics against the pre-registered thresholds.

    smart_close maps the study window's days (date or datetime keys, the same
    key type the fetch harness keyed venue_bars with) to SMART closes;
    venue_bars maps each venue route to day -> (close, volume).
    """
    venue = _VENUE_ALIASES.get(listing_venue, listing_venue)
    criterion_a = prereg["criterion_a"]
    criterion_b = prereg["criterion_b"]
    n_days = len(smart_close)
    listing_bars = venue_bars.get(venue, {})

    matches: dict[str, int] = {route: 0 for route in venue_bars}
    matches.setdefault(venue, 0)
    max_volume_days = 0
    for day, smart in smart_close.items():
        listing_bar = listing_bars.get(day)
        listing_volume = listing_bar[1] if listing_bar is not None else None
        if _valid_volume(listing_volume):
            other_volumes = [
                bar[1]
                for route, series in venue_bars.items()
                if route != venue
                for bar in (series.get(day),)
                if bar is not None and _valid_volume(bar[1])
            ]
            if listing_volume > max(other_volumes, default=0.0):
                max_volume_days += 1
        for route, series in venue_bars.items():
            bar = series.get(day)
            if bar is not None and _close_matches(bar[0], smart, criterion_b):
                matches[route] += 1

    def share(route: str) -> float:
        return matches.get(route, 0) / n_days if n_days else 0.0

    listing_match_share = share(venue)
    passes_volume = (
        max_volume_days / n_days >= criterion_a["listing_max_volume_share_per_name"]
        if n_days
        else False
    )
    passes_close = (
        n_days > 0
        and listing_match_share >= criterion_b["listing_match_share_per_name"]
        and all(
            share(route) <= criterion_b["non_listing_match_share_max"]
            for route in venue_bars
            if route != venue
        )
    )
    return NameEvaluation(
        symbol=symbol,
        listing_venue=venue,
        n_days=n_days,
        listing_max_volume_share=max_volume_days / n_days if n_days else 0.0,
        close_match_share_by_venue={route: share(route) for route in matches},
        passes_volume=passes_volume,
        passes_close=passes_close,
    )


def evaluate_study(
    evaluations: Sequence[NameEvaluation],
    prereg: Mapping[str, Any],
    timeframe: str,
) -> VenueStudyResult:
    """The study verdict over every name's evaluation (pre-registered rule).

    Structural gates first (min_names overall, min_per_venue on every selected
    venue): a structurally invalid study fails with reasons regardless of the
    criteria shares.
    """
    selection = prereg["selection"]
    names = tuple(evaluations)
    n_names_by_venue: dict[str, int] = {}
    for evaluation in names:
        n_names_by_venue[evaluation.listing_venue] = (
            n_names_by_venue.get(evaluation.listing_venue, 0) + 1
        )

    reasons: list[str] = []
    structurally_valid = True
    if len(names) < selection["min_names"]:
        structurally_valid = False
        reasons.append(
            f"selection: {len(names)} names evaluated, min_names is {selection['min_names']}"
        )
    for venue in selection["listing_venues"]:
        count = n_names_by_venue.get(venue, 0)
        if count < selection["min_per_venue"]:
            structurally_valid = False
            reasons.append(
                f"selection: {venue} has {count} names, min_per_venue is "
                f"{selection['min_per_venue']}"
            )

    total = len(names)
    share_a = sum(evaluation.passes_volume for evaluation in names) / total if total else 0.0
    share_b = sum(evaluation.passes_close for evaluation in names) / total if total else 0.0
    criterion_a_pass = share_a >= prereg["criterion_a"]["share_of_names_passing"]
    criterion_b_pass = share_b >= prereg["criterion_b"]["share_of_names_passing"]
    if not criterion_a_pass:
        reasons.append(
            f"criterion_a: {share_a:.3f} of names pass, need "
            f"{prereg['criterion_a']['share_of_names_passing']}"
        )
    if not criterion_b_pass:
        reasons.append(
            f"criterion_b: {share_b:.3f} of names pass, need "
            f"{prereg['criterion_b']['share_of_names_passing']}"
        )
    return VenueStudyResult(
        timeframe=timeframe,
        names=names,
        n_names_by_venue=n_names_by_venue,
        criterion_a_pass=criterion_a_pass,
        criterion_b_pass=criterion_b_pass,
        passed=structurally_valid and criterion_a_pass and criterion_b_pass,
        reasons=tuple(reasons),
    )
