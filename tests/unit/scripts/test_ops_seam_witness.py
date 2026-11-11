"""The seam witness's pure core (todo 600 step 7, check a): level, never the junction step."""

from __future__ import annotations

import math
from datetime import date

from scripts.ops.bars.ops_seam_witness import LEVEL_TOL, judge, split_log_k

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
