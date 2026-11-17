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


# --- a split row naming a raw series unadjusted rescales that series (CLBK share exchange) ---

from src.intelligence.bars.split_rescale import (  # noqa: E402
    SplitRow,
    routed_splits_known_at,
    split_row_routes,
    splits_known_at,
)

ALPACA = ("alpaca", "sip_rth")
CLBK_LAST_OLD = datetime(2026, 7, 20, 19, 55, tzinfo=UTC)  # 15:55 ET, last old-scale session
CLBK_FIRST_NEW = datetime(2026, 7, 21, 13, 30, tzinfo=UTC)
HORIZON = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
RECORDED = datetime(2026, 11, 17, 3, 0, tzinfo=UTC)


def _row(*, market_fact=False, routes=frozenset({ALPACA}), effective=date(2026, 7, 20)):
    return SplitRow(effective, 2.2, RECORDED, market_fact, routes)


def _alpaca(stamp, close=24.5, volume=1000):
    return _bar("CLBK", stamp, close, close, close, close, volume, kind="sip_rth", vendor="alpaca")


def _canonical(winners, rows, horizon=HORIZON):
    return canonicalize_winners(
        winners,
        {"CLBK": splits_known_at(rows, horizon)},
        {"CLBK": routed_splits_known_at(rows, horizon)},
    )


def test_a_route_named_row_rescales_the_named_series_through_its_effective_date_only():
    old, new = _canonical([_alpaca(CLBK_LAST_OLD), _alpaca(CLBK_FIRST_NEW, 11.08, 5000)], [_row()])
    assert (old.close, old.volume, old.kind, old.vendor) == (
        pytest.approx(24.5 / 2.2),
        2200,
        "sip_rth",
        "alpaca",
    )
    assert (new.close, new.volume) == (11.08, 5000)  # the next session is untouched


def test_the_boundary_session_is_the_last_old_scale_session():
    first_session_bar = datetime(2026, 7, 20, 13, 30, tzinfo=UTC)
    (bar,) = _canonical([_alpaca(first_session_bar)], [_row()])
    assert bar.close == pytest.approx(24.5 / 2.2)
    (after,) = _canonical([_alpaca(datetime(2026, 7, 21, 13, 30, tzinfo=UTC))], [_row()])
    assert after.close == 24.5


def test_a_series_the_row_does_not_name_keeps_its_scale():
    other = _bar(
        "CLBK", CLBK_LAST_OLD, 24.5, 24.5, 24.5, 24.5, 1000, kind="smart_trades", vendor="ibkr"
    )
    assert _canonical([other], [_row()]) == [other]


def test_a_row_without_routes_or_not_yet_known_changes_nothing():
    bar = _alpaca(CLBK_LAST_OLD)
    assert _canonical([bar], [_row(routes=frozenset())]) == [bar]
    unexecuted = _row(effective=date(2026, 12, 1))
    assert _canonical([bar], [unexecuted]) == [bar]
    assert routed_splits_known_at([_row()], datetime(2026, 11, 17, 2, 0, tzinfo=UTC)) == {}


def test_a_market_row_without_routes_still_rescales_only_massive():
    market = _row(market_fact=True, routes=frozenset())
    massive = _bar("CLBK", CLBK_LAST_OLD, 24.5, 24.5, 24.5, 24.5, 1000)
    alpaca = _alpaca(CLBK_LAST_OLD)
    out_massive, out_alpaca = _canonical([massive, alpaca], [market])
    assert (out_massive.kind, out_massive.close) == ("sip_flat_adj", pytest.approx(24.5 / 2.2))
    assert out_alpaca == alpaca


def test_a_second_run_over_the_same_raw_gives_the_same_rows():
    winners = [_alpaca(CLBK_LAST_OLD), _alpaca(CLBK_FIRST_NEW, 11.08, 5000)]
    assert _canonical(winners, [_row()]) == _canonical(winners, [_row()])


def test_route_parsing_reads_the_jsonb_list_or_its_text_and_refuses_a_bad_one():
    assert split_row_routes(None) == frozenset()
    assert split_row_routes('[{"vendor": "alpaca", "kind": "sip_rth"}]') == {ALPACA}
    assert split_row_routes([{"vendor": "alpaca", "kind": "sip_rth"}]) == {ALPACA}
    with pytest.raises(ValueError):
        split_row_routes([{"vendor": "alpaca"}])
    with pytest.raises(ValueError):
        split_row_routes({"vendor": "alpaca", "kind": "sip_rth"})
