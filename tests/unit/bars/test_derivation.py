"""Tests for src/intelligence/bars/derivation.py (phase 185 plan 17, task 1).

Pure rule, no DB: derive_daily picks, per (symbol, bar date), the canonical 1d
bar from D1 TRADES observations. Direct-oracle convention: every expected
value below is written by hand from the D-06/D-21 rule text, never computed by
calling the implementation under test.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.intelligence.bars.derivation import (
    RULE_VERSION,
    CanonicalBar,
    Observation,
    SplitRecord,
    derive_daily,
)

# 2024-06-10 split recorded 2024-06-11 (plan behavior block).
_SPLIT_EFFECTIVE = date(2024, 6, 10)
_SPLIT_RECORDED = datetime(2024, 6, 11, 12, 0, tzinfo=UTC)
SPLIT = SplitRecord(effective_date=_SPLIT_EFFECTIVE, recorded_at=_SPLIT_RECORDED, factor=2.0)


def _obs(
    request_id: str,
    bar_date: date,
    *,
    close: float,
    route: str = "SMART",
    fetched_at: datetime | None = None,
    legacy: bool = False,
    volume: int | None = 100,
    open_: float = 1.0,
    high: float | None = None,
    low: float | None = None,
    what_to_show: str = "TRADES",
) -> Observation:
    return Observation(
        request_id=request_id,
        route=route,
        bar_date=bar_date,
        open=open_,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=volume,
        fetched_at=fetched_at or datetime(2026, 9, 30, tzinfo=UTC),
        legacy=legacy,
        what_to_show=what_to_show,
    )


def _bar_dates(bars: list[CanonicalBar]) -> list[date]:
    return [b.bar_date for b in bars]


class TestFetchPrecedence:
    def test_two_smart_observations_the_later_fetch_wins(self):
        day = date(2024, 6, 20)
        bars = derive_daily(
            [
                _obs("older", day, close=10.0, fetched_at=datetime(2024, 6, 1, tzinfo=UTC)),
                _obs("newer", day, close=11.0, fetched_at=datetime(2024, 6, 12, tzinfo=UTC)),
            ],
            [],
            venue_bars_enabled=False,
        )
        assert len(bars) == 1
        assert bars[0].close == 11.0
        assert bars[0].request_ids == ("newer",)

    def test_legacy_alone_is_used(self):
        day = date(2020, 1, 2)
        bars = derive_daily(
            [_obs("leg", day, close=5.0, route="LEGACY_IMPORT", legacy=True)],
            [],
            venue_bars_enabled=False,
        )
        assert len(bars) == 1
        assert bars[0].close == 5.0
        assert bars[0].source == "ibkr_named"
        assert bars[0].request_ids == ("leg",)

    def test_legacy_loses_to_any_real_observation(self):
        day = date(2020, 1, 2)
        bars = derive_daily(
            [
                _obs("leg", day, close=5.0, route="LEGACY_IMPORT", legacy=True),
                _obs("smart", day, close=6.0),
            ],
            [],
            venue_bars_enabled=False,
        )
        assert bars[0].close == 6.0
        assert bars[0].request_ids == ("smart",)


class TestSplitRule:
    def test_pre_split_date_only_prefetch_observation_old_value_flagged(self):
        day = date(2024, 6, 3)  # before the effective date
        bars = derive_daily(
            [_obs("pre", day, close=10.0, fetched_at=datetime(2024, 6, 1, tzinfo=UTC))],
            [SPLIT],
            venue_bars_enabled=False,
        )
        assert len(bars) == 1
        assert bars[0].close == 10.0
        assert bars[0].flags == ("pre_split_unrefetched",)

    def test_pre_split_date_with_post_recorded_fetch_new_value_no_flag(self):
        day = date(2024, 6, 3)
        bars = derive_daily(
            [_obs("post", day, close=20.0, fetched_at=datetime(2024, 6, 12, tzinfo=UTC))],
            [SPLIT],
            venue_bars_enabled=False,
        )
        assert bars[0].close == 20.0
        assert bars[0].flags == ()

    def test_post_recorded_fetch_beats_stale_fetch_for_pre_split_date(self):
        day = date(2024, 6, 3)
        bars = derive_daily(
            [
                _obs("stale", day, close=10.0, fetched_at=datetime(2024, 6, 1, tzinfo=UTC)),
                _obs("fresh", day, close=20.0, fetched_at=datetime(2024, 6, 12, tzinfo=UTC)),
            ],
            [SPLIT],
            venue_bars_enabled=False,
        )
        assert bars[0].close == 20.0
        assert bars[0].flags == ()
        assert bars[0].request_ids == ("fresh",)

    def test_date_on_or_after_effective_date_never_flagged(self):
        day = _SPLIT_EFFECTIVE
        bars = derive_daily(
            [_obs("on", day, close=10.0, fetched_at=datetime(2024, 6, 1, tzinfo=UTC))],
            [SPLIT],
            venue_bars_enabled=False,
        )
        assert bars[0].flags == ()

    def test_legacy_always_counts_as_pre_split_even_when_imported_late(self):
        day = date(2024, 6, 3)
        bars = derive_daily(
            [
                _obs(
                    "leg",
                    day,
                    close=10.0,
                    route="LEGACY_IMPORT",
                    legacy=True,
                    fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
                )
            ],
            [SPLIT],
            venue_bars_enabled=False,
        )
        assert bars[0].close == 10.0
        assert bars[0].flags == ("pre_split_unrefetched",)

    def test_two_splits_the_latest_recorded_at_sets_the_threshold(self):
        day = date(2023, 1, 3)
        earlier = SplitRecord(
            effective_date=date(2023, 6, 1),
            recorded_at=datetime(2023, 6, 2, tzinfo=UTC),
            factor=2.0,
        )
        later = SPLIT
        # Fetched after the earlier split but before the later one: stale.
        fetched = datetime(2024, 1, 15, tzinfo=UTC)
        bars = derive_daily(
            [_obs("mid", day, close=7.0, fetched_at=fetched)],
            [earlier, later],
            venue_bars_enabled=False,
        )
        assert bars[0].flags == ("pre_split_unrefetched",)
        # The same observation fetched after both recordings is current.
        bars = derive_daily(
            [_obs("late", day, close=7.0, fetched_at=datetime(2024, 6, 12, tzinfo=UTC))],
            [earlier, later],
            venue_bars_enabled=False,
        )
        assert bars[0].flags == ()


class TestVenueRule:
    def test_venue_ignored_when_disabled(self):
        head = date(2015, 1, 5)
        before = date(2014, 12, 30)
        bars = derive_daily(
            [
                _obs("smart", head, close=9.0),
                _obs("v", before, close=4.0, route="NYSE"),
            ],
            [],
            venue_bars_enabled=False,
        )
        assert _bar_dates(bars) == [head]

    def test_venue_used_when_enabled_max_volume_venue_wins(self):
        head = date(2015, 1, 5)
        bars = derive_daily(
            [
                _obs("smart", head, close=9.0),
                _obs("ny1", date(2014, 12, 29), close=4.0, route="NYSE", volume=500),
                _obs("ny2", date(2014, 12, 30), close=4.1, route="NYSE", volume=500),
                _obs("ar1", date(2014, 12, 30), close=8.0, route="ARCA", volume=10),
            ],
            [],
            venue_bars_enabled=True,
        )
        by_date = {b.bar_date: b for b in bars}
        assert by_date[date(2014, 12, 30)].source == "ibkr_venue"
        assert by_date[date(2014, 12, 30)].request_ids == ("ny2",)
        assert date(2014, 12, 29) in by_date
        # ARCA (the low-volume venue) never contributes a bar.
        assert {b.request_ids[0] for b in bars} == {"smart", "ny1", "ny2"}

    def test_venue_volume_tie_breaks_to_first_route_alphabetically(self):
        head = date(2015, 1, 5)
        bars = derive_daily(
            [
                _obs("smart", head, close=9.0),
                _obs("bats9", date(2014, 12, 30), close=4.0, route="BATS", volume=100),
                _obs("arca9", date(2014, 12, 30), close=4.0, route="ARCA", volume=100),
            ],
            [],
            venue_bars_enabled=True,
        )
        by_date = {b.bar_date: b for b in bars}
        assert by_date[date(2014, 12, 30)].request_ids == ("arca9",)

    def test_venue_on_or_after_smart_head_never_used(self):
        head = date(2015, 1, 5)
        bars = derive_daily(
            [
                _obs("smart", head, close=9.0),
                _obs("v_after", date(2015, 6, 1), close=4.0, route="NYSE"),
            ],
            [],
            venue_bars_enabled=True,
        )
        assert _bar_dates(bars) == [head]

    def test_venue_volume_none_counts_as_zero_not_max(self):
        head = date(2015, 1, 5)
        bars = derive_daily(
            [
                _obs("smart", head, close=9.0),
                _obs("noner", date(2014, 12, 30), close=4.0, route="NYSE", volume=None),
                _obs("tiny", date(2014, 12, 30), close=4.0, route="ARCA", volume=1),
            ],
            [],
            venue_bars_enabled=True,
        )
        by_date = {b.bar_date: b for b in bars}
        assert by_date[date(2014, 12, 30)].request_ids == ("tiny",)


class TestOutputContract:
    def test_sorted_by_date_and_deterministic_under_shuffle(self):
        observations = [
            _obs(
                f"s{i}", date(2024, 6, 1) + __import__("datetime").timedelta(days=i), close=10.0 + i
            )
            for i in range(10)
        ]
        expected = derive_daily(observations, [], venue_bars_enabled=False)
        rng = random.Random(17)
        for _ in range(5):
            shuffled = observations[:]
            rng.shuffle(shuffled)
            assert derive_daily(shuffled, [], venue_bars_enabled=False) == expected
        assert _bar_dates(expected) == sorted(_bar_dates(expected))

    def test_request_ids_name_the_chosen_observation(self):
        day = date(2024, 6, 20)
        bars = derive_daily(
            [
                _obs("a", day, close=1.0, fetched_at=datetime(2024, 6, 1, tzinfo=UTC)),
                _obs("b", day, close=2.0, fetched_at=datetime(2024, 6, 2, tzinfo=UTC)),
            ],
            [],
            venue_bars_enabled=False,
        )
        assert bars[0].request_ids == ("b",)

    def test_missing_volume_is_flagged_not_silent(self):
        day = date(2024, 6, 20)
        bars = derive_daily([_obs("nv", day, close=3.0, volume=None)], [], venue_bars_enabled=False)
        assert bars[0].volume is None
        assert "no_provider_volume" in bars[0].flags

    def test_adjusted_last_raises_value_error(self):
        day = date(2024, 6, 20)
        with pytest.raises(ValueError, match="ADJUSTED_LAST"):
            derive_daily(
                [_obs("adj", day, close=3.0, what_to_show="ADJUSTED_LAST")],
                [],
                venue_bars_enabled=False,
            )

    def test_rule_version_is_d2_v1(self):
        assert RULE_VERSION == "d2-v1"

    def test_empty_input_returns_empty_list(self):
        assert derive_daily([], [], venue_bars_enabled=True) == []


class TestCanonicalBarDefaults:
    def test_frozen_dataclasses_reject_mutation(self):
        bar = CanonicalBar(
            bar_date=date(2024, 1, 2),
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=10,
            source="ibkr_named",
            request_ids=("r",),
            flags=(),
        )
        with pytest.raises(Exception):
            bar.close = Decimal("2")  # type: ignore[misc]
