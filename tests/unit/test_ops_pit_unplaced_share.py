"""The unplaced share of liquid rows (todo 609): coverage by span, floor, type, share."""

from __future__ import annotations

from datetime import date

from scripts.ops.bars.ops_pit_unplaced_share import covered, report_rows, tally

D = date


def test_a_day_is_covered_inside_a_half_open_span_and_open_spans_run_on():
    spans = {"AAA": [(D(2010, 1, 1), D(2010, 6, 1))], "BBB": [(D(2010, 1, 1), None)]}
    assert covered(spans, "AAA", D(2010, 1, 1)) and covered(spans, "AAA", D(2010, 5, 31))
    assert not covered(spans, "AAA", D(2010, 6, 1)) and not covered(spans, "AAA", D(2009, 12, 31))
    assert covered(spans, "BBB", D(2030, 1, 1)) and not covered(spans, "CCC", D(2010, 1, 1))


def test_only_rows_at_or_above_the_floor_count_and_the_share_is_unplaced_over_total():
    spans = {"AAA": [(D(2010, 1, 1), None)]}
    types = {("AAA", 2010, 3): "CS", ("ZZZ", 2010, 3): "ETF"}
    days = [
        (D(2010, 3, 1), [("AAA", 2_000_000.0), ("ZZZ", 5_000_000.0), ("AAA", 999_999.0)]),
        (D(2010, 3, 2), [("ZZZ", 1_000_000.0), ("QQQ", 3_000_000.0)]),
    ]
    rows = {(r["year"], r["type"]): r for r in report_rows(tally(days, spans, types))}
    assert rows[(2010, "CS")]["rows_meeting_floor"] == 1 and rows[(2010, "CS")]["unplaced"] == 0
    assert rows[(2010, "ETF")]["unplaced_share"] == 1.0 and rows[(2010, "ETF")]["unplaced"] == 2
    assert rows[(2010, "none")]["rows_meeting_floor"] == 1
