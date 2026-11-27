"""The seam witness's pure core (todo 600 step 7, check a): level, never the junction step."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import pytest

from scripts.ops.bars.ops_seam_witness import (
    LEVEL_TOL,
    _incoming_source,
    _series,
    judge,
    split_log_k,
)

SEAM = date(2016, 1, 4)


def test_both_spans_at_the_reference_level_match():
    row = judge("AAA", [0.0, 0.0002], [-0.0003, 0.0], [])
    assert row.verdict == "canonical_matches_massive"
    assert (row.n_before, row.n_after) == (2, 2)


def test_an_offset_span_that_equals_a_recorded_split_run_reconciles():
    # Alpaca after the seam sits 1/2 below the reference: one 2:1 split differs between them
    row = judge("AAA", [0.0] * 5, [-math.log(2.0)] * 5, [2.0, 3.0])
    assert row.verdict == "reconciled_split"
    assert row.factor == 0.5
    row = judge("AAA", [math.log(6.0)] * 5, [0.0] * 5, [2.0, 3.0])  # both splits, one run
    assert row.verdict == "reconciled_split" and row.factor == 6.0


def test_an_offset_no_split_explains_is_unexplained():
    assert judge("AAA", [0.0] * 5, [0.05] * 5, [2.0]).verdict == "unexplained"
    # a one-bar junction print does not move the median, so the level decides
    assert judge("AAA", [0.0] * 5, [0.5] + [0.0] * 4, []).verdict == "canonical_matches_massive"


def test_a_side_without_common_bars_is_one_sided():
    row = judge("AAA", [0.0], [], [])
    assert row.verdict == "one_sided" and row.log_k_after is None


def test_split_log_k_takes_the_sessions_nearest_the_seam_on_each_side():
    days = [date(2015, 12, d) for d in (28, 29, 30, 31)] + [date(2016, 1, d) for d in (4, 5, 6)]
    incoming = {d: 2.0 if d >= SEAM else 1.0 for d in days}
    reference = dict.fromkeys(days, 1.0)
    reference.pop(date(2015, 12, 31))  # a reference hole is not a common bar
    before, after = split_log_k(incoming, reference, {d: d for d in days}, SEAM, sessions=2)
    assert before == [0.0, 0.0]  # 12-29 and 12-30: the two common sessions nearest the seam
    assert after == [math.log(2.0)] * 2


def test_the_tolerance_is_design_8a_ten_basis_points():
    assert LEVEL_TOL == 0.001
    assert judge("AAA", [0.0], [0.0011], []).verdict == "unexplained"


def test_1d_sessions_follow_each_series_own_stamp_convention():
    # canonical and IBKR stamp 00:00 UTC; Massive and Alpaca stamp midnight New York (05:00 UTC in winter)
    utc_midnight = datetime(2016, 1, 4, 0, 0, tzinfo=UTC)
    ny_midnight = datetime(2016, 1, 4, 5, 0, tzinfo=UTC)
    for source, stamp in (
        (None, utc_midnight),
        (("ibkr", "smart_trades"), utc_midnight),
        (("massive", "sip_flat"), ny_midnight),
        (("alpaca", "sip_rth"), ny_midnight),
    ):
        values, days = _series([(stamp, 10.0)], "1d", source)
        assert values == {date(2016, 1, 4): 10.0} and days == {date(2016, 1, 4): date(2016, 1, 4)}


def test_5m_joins_by_stamp_and_dates_it_in_new_york():
    stamp = datetime(2016, 1, 4, 3, 0, tzinfo=UTC)  # 22:00 on Jan 3 in New York
    values, days = _series([(stamp, 10.0)], "5m", None)
    assert values == {stamp: 10.0} and days == {stamp: date(2016, 1, 3)}


def test_a_1d_series_the_rule_does_not_know_is_refused_not_dated_by_guess():
    with pytest.raises(ValueError, match="not a d2-v4 input series"):
        _series([(datetime(2016, 1, 4, tzinfo=UTC), 1.0)], "1d", ("yahoo", "daily"))


def test_incoming_names_the_series_and_refuses_an_unknown_1d_one_before_any_query():
    assert _incoming_source("canonical", "1d") is None
    assert _incoming_source("raw:alpaca/sip_rth", "1d") == ("alpaca", "sip_rth")
    assert _incoming_source("raw:alpaca/sip_rth_5m", "5m") == ("alpaca", "sip_rth_5m")
    for typo in ("raw:alpaca/sip_rht", "raw:ibkr/venue_nyse", "raw:alpaca/iex_rth"):
        with pytest.raises(ValueError, match="known stamp convention"):
            _incoming_source(typo, "1d")
    for malformed in ("raw:foo", "alpaca/sip_rth", "raw:a/b/c", "raw:/x"):
        with pytest.raises(ValueError, match="expected canonical or raw:VENDOR/KIND"):
            _incoming_source(malformed, "5m")
