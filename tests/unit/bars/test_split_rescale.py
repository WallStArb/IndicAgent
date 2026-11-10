"""Split rescale canary: expected series computed by hand, independent of any data state."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.intelligence.bars.selection import Candidate
from src.intelligence.bars.split_rescale import (
    SplitFactor,
    canonicalize_winners,
    rescale_volume,
    scales_for_sessions,
)


def _bar(symbol, stamp, o, h, low, c, v, kind="sip_flat_agg", vendor="massive"):
    return Candidate(stamp, symbol, "5m", vendor, kind, o, h, low, c, v)


# NVDA 10:1 forward split, effective_date 2024-06-07 (the last session on the old scale):
# 15:55 ET on 2024-06-07 is 19:55Z, the first bar on the new scale is 09:30 ET on 2024-06-10.
NVDA_SPLIT = [SplitFactor(date(2024, 6, 7), 10.0)]
LAST_OLD = datetime(2024, 6, 7, 19, 55, tzinfo=UTC)
FIRST_NEW = datetime(2024, 6, 10, 13, 30, tzinfo=UTC)


def test_nvda_ten_for_one_canary_matches_the_hand_computed_series():
    winners = [
        _bar("NVDA", LAST_OLD, 1200.0, 1210.0, 1190.0, 1205.0, 1000),
        _bar("NVDA", FIRST_NEW, 121.0, 122.0, 120.0, 121.5, 5000),
    ]
    old, new = canonicalize_winners(winners, {"NVDA": NVDA_SPLIT})
    # old scale: prices / 10, volume * 10
    assert (old.open, old.high, old.low, old.close, old.volume) == (
        120.0,
        121.0,
        119.0,
        120.5,
        10000,
    )
    # first bar on the new scale is untouched except for its kind
    assert (new.open, new.high, new.low, new.close, new.volume) == (
        121.0,
        122.0,
        120.0,
        121.5,
        5000,
    )
    assert (old.kind, new.kind) == ("sip_flat_adj", "sip_flat_adj")
    assert (old.vendor, old.symbol, old.timestamp) == ("massive", "NVDA", LAST_OLD)


def test_reverse_split_multiplies_prices_and_rounds_volume_half_up():
    split = [SplitFactor(date(2024, 1, 5), 0.1)]  # 1:10 reverse
    (bar,) = canonicalize_winners(
        [_bar("X", datetime(2024, 1, 5, 15, 0, tzinfo=UTC), 2.0, 2.5, 1.5, 2.25, 15)],
        {"X": split},
    )
    assert (bar.open, bar.close) == (2.0 / 0.1, 2.25 / 0.1)
    assert bar.volume == 2  # 15 * 0.1 = 1.5 rounds half up


def test_two_splits_multiply_in_effective_date_order_and_divide_once():
    splits = [SplitFactor(date(2024, 6, 7), 10.0), SplitFactor(date(2022, 7, 15), 20.0)]
    scales = scales_for_sessions(
        [date(2022, 7, 15), date(2022, 7, 18), date(2024, 6, 7), date(2024, 6, 10)], splits
    )
    assert scales == {
        date(2022, 7, 15): 20.0 * 10.0,  # on or before both
        date(2022, 7, 18): 10.0,  # between them
        date(2024, 6, 7): 10.0,
        date(2024, 6, 10): 1.0,  # after both
    }


def test_session_date_is_the_new_york_date_of_the_stamp():
    # 2024-06-08 01:00Z is still the 2024-06-07 session evening in New York
    late = datetime(2024, 6, 8, 1, 0, tzinfo=UTC)
    (bar,) = canonicalize_winners(
        [_bar("NVDA", late, 1000.0, 1000.0, 1000.0, 1000.0, 10)], {"NVDA": NVDA_SPLIT}
    )
    assert bar.close == 100.0


def test_other_winners_and_unsplit_symbols_pass_through():
    ibkr = _bar("AAPL", LAST_OLD, 1.0, 2.0, 0.5, 1.5, 7, kind="named", vendor="ibkr")
    plain = _bar("MSFT", LAST_OLD, 10.0, 11.0, 9.0, 10.5, 3)
    out = canonicalize_winners([ibkr, plain], {"NVDA": NVDA_SPLIT})
    assert out[0] == ibkr
    assert (out[1].close, out[1].volume, out[1].kind) == (10.5, 3, "sip_flat_adj")


def test_null_volume_stays_null_and_rounding_helper():
    assert rescale_volume(None, 10.0) is None
    assert rescale_volume(3, 0.5) == 2  # 1.5 -> 2
    assert rescale_volume(5, 0.5) == 3  # 2.5 -> 3 (half up, not half even)


def test_splits_are_applied_whatever_their_order_in_the_input():
    forward = scales_for_sessions(
        [date(2022, 1, 1)],
        [SplitFactor(date(2022, 7, 15), 20.0), SplitFactor(date(2024, 6, 7), 10.0)],
    )
    backward = scales_for_sessions(
        [date(2022, 1, 1)],
        [SplitFactor(date(2024, 6, 7), 10.0), SplitFactor(date(2022, 7, 15), 20.0)],
    )
    assert forward == backward == {date(2022, 1, 1): pytest.approx(200.0)}
