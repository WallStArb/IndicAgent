"""D3 venue-study statistics tests (D-17).

The study's thresholds live in the committed pre-registration
(config/bars/venue_study_preregistration.json); these tests load that file, so
the code and the pre-registered numbers cannot drift apart silently. Statistics
are pure: per-name share of days the listing venue has the most volume, and
per-venue share of days whose close matches SMART within tolerance, each judged
against the pre-registered criteria. Days missing from a venue count against
it, never dropped.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from src.intelligence.bars.venue_study import (
    NameEvaluation,
    evaluate_name,
    evaluate_study,
)
from tests.unit.bars._builders import random_walk_closes

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_PREREG = json.loads(
    (_REPO_ROOT / "config" / "bars" / "venue_study_preregistration.json").read_text()
)


def _smart_closes(n: int = 100, seed: int = 7) -> dict[date, float]:
    days = []
    day = date(2023, 1, 9)
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return dict(zip(days, random_walk_closes(n, 100.0, seed), strict=True))


def _venue_series(
    smart: dict[date, float],
    *,
    match_days: int,
    volume: float,
    off_scale: float = 1.05,
    missing_days: int = 0,
) -> dict[date, tuple[float, float]]:
    """Venue bars matching SMART closes on the first match_days days.

    Non-matching days carry closes off by off_scale (far beyond the tolerance
    for a 100-dollar name); the last missing_days days are absent entirely.
    volume is constant per day (the max-volume tests override it per name).
    """
    days = sorted(smart)
    drop = set(days[len(days) - missing_days :]) if missing_days else set()
    series: dict[date, tuple[float, float]] = {}
    for i, day in enumerate(days):
        if day in drop:
            continue
        close = smart[day] if i < match_days else smart[day] * off_scale
        series[day] = (round(close, 2), volume)
    return series


def test_passing_name_passes_both_criteria() -> None:
    smart = _smart_closes(100)
    # Listing venue: most volume on 97 of 100 days, closes matching on 99.
    listing = _venue_series(smart, match_days=99, volume=1_000_000)
    other = _venue_series(smart, match_days=10, volume=5_000)
    for day in sorted(smart)[3:6]:
        close, _ = other[day]
        other[day] = (close, 5_000_000)
    evaluation = evaluate_name("SPY", "NYSE", smart, {"NYSE": listing, "ARCA": other}, _PREREG)
    assert evaluation.listing_venue == "NYSE"
    assert evaluation.n_days == 100
    assert evaluation.listing_max_volume_share == 0.97
    assert evaluation.close_match_share_by_venue["NYSE"] == 0.99
    assert evaluation.close_match_share_by_venue["ARCA"] == 0.10
    assert evaluation.passes_volume is True
    # Other venues matching on 10 percent do not break criterion b (max 0.5).
    assert evaluation.passes_close is True


def test_non_listing_close_match_breaks_criterion_b() -> None:
    smart = _smart_closes(100)
    listing = _venue_series(smart, match_days=100, volume=1_000_000)
    other = _venue_series(smart, match_days=80, volume=5_000)
    evaluation = evaluate_name("XLU", "NYSE", smart, {"NYSE": listing, "ARCA": other}, _PREREG)
    assert evaluation.close_match_share_by_venue["ARCA"] == 0.80
    assert evaluation.passes_volume is True
    assert evaluation.passes_close is False


def test_missing_days_count_against_both_criteria() -> None:
    smart = _smart_closes(100)
    listing = _venue_series(smart, match_days=90, volume=1_000_000, missing_days=10)
    other = _venue_series(smart, match_days=80, volume=5_000, missing_days=20)
    evaluation = evaluate_name("KO", "NYSE", smart, {"NYSE": listing, "ARCA": other}, _PREREG)
    # The 10 absent listing days are not-max-volume and not-matched, never dropped.
    assert evaluation.listing_max_volume_share == 0.90
    assert evaluation.close_match_share_by_venue["NYSE"] == 0.90
    assert evaluation.passes_volume is False
    assert evaluation.passes_close is False


def test_venue_wholly_absent_from_bars_fails_outright() -> None:
    smart = _smart_closes(100)
    other = _venue_series(smart, match_days=0, volume=5_000)
    evaluation = evaluate_name("JPM", "ISLAND", smart, {"ARCA": other}, _PREREG)
    assert evaluation.close_match_share_by_venue["ISLAND"] == 0.0
    assert evaluation.listing_max_volume_share == 0.0
    assert evaluation.passes_volume is False
    assert evaluation.passes_close is False


def test_nasdaq_primary_exchange_resolves_to_island_route() -> None:
    smart = _smart_closes(100)
    island = _venue_series(smart, match_days=100, volume=1_000_000)
    other = _venue_series(smart, match_days=0, volume=5_000)
    evaluation = evaluate_name("AAPL", "NASDAQ", smart, {"ISLAND": island, "ARCA": other}, _PREREG)
    # primaryExchange reads NASDAQ; the routing code is ISLAND (ibkr.py alias).
    assert evaluation.listing_venue == "ISLAND"
    assert evaluation.passes_volume is True
    assert evaluation.passes_close is True


def _name(symbol: str, venue: str, *, volume: bool, close: bool) -> NameEvaluation:
    return NameEvaluation(
        symbol=symbol,
        listing_venue=venue,
        n_days=504,
        listing_max_volume_share=0.99 if volume else 0.5,
        close_match_share_by_venue={venue: 0.99 if close else 0.6},
        passes_volume=volume,
        passes_close=close,
    )


def _spread(n_per_venue: int, **flags: bool) -> tuple[NameEvaluation, ...]:
    return tuple(
        _name(f"{venue}-{i}", venue, **flags)
        for venue in ("NYSE", "ISLAND", "ARCA")
        for i in range(n_per_venue)
    )


def test_evaluate_study_passes_a_valid_study() -> None:
    result = evaluate_study(_spread(10, volume=True, close=True), _PREREG, "1d")
    assert result.timeframe == "1d"
    assert result.n_names_by_venue == {"NYSE": 10, "ISLAND": 10, "ARCA": 10}
    assert result.criterion_a_pass is True
    assert result.criterion_b_pass is True
    assert result.passed is True
    assert result.reasons == ()


def test_evaluate_study_fails_below_min_names() -> None:
    result = evaluate_study(_spread(9, volume=True, close=True), _PREREG, "1d")
    assert result.passed is False
    assert any("min_names" in reason for reason in result.reasons)


def test_evaluate_study_fails_below_min_per_venue() -> None:
    names = tuple(_name(f"NYSE-{i}", "NYSE", volume=True, close=True) for i in range(30))
    result = evaluate_study(names, _PREREG, "1d")
    assert result.passed is False
    assert any("min_per_venue" in reason for reason in result.reasons)
    assert any("ISLAND" in reason for reason in result.reasons)


def test_evaluate_study_judges_criteria_by_share_of_names() -> None:
    # 20 of 30 names pass the volume criterion (0.667 < 0.9); 28 of 30 pass b.
    names = tuple(
        _name(
            f"S-{i}",
            ("NYSE", "ISLAND", "ARCA")[i % 3],
            volume=i < 20,
            close=i < 28,
        )
        for i in range(30)
    )
    result = evaluate_study(names, _PREREG, "5m")
    assert result.timeframe == "5m"
    assert result.criterion_a_pass is False
    assert result.criterion_b_pass is True
    assert result.passed is False
    assert any("criterion_a" in reason for reason in result.reasons)


def test_preregistration_carries_the_registered_contract() -> None:
    assert _PREREG["version"] == 1
    assert _PREREG["selection"]["seed"] == 185017
    assert _PREREG["selection"]["min_names"] >= 30
    assert _PREREG["selection"]["listing_venues"] == ["NYSE", "ISLAND", "ARCA"]
    assert set(_PREREG["windows"]) == {"daily_sessions", "intraday_5m_sessions"}
    assert _PREREG["routes"] == ["SMART", "NYSE", "ARCA", "ISLAND", "AMEX", "BATS"]
    for key in ("criterion_a", "criterion_b", "verdict", "effect", "rationale"):
        assert _PREREG[key], f"missing preregistration key {key}"
