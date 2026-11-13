"""The identity witness for gap-list spans (design 8c): pure tests, no database."""

from __future__ import annotations

import math
from datetime import date, timedelta

from scripts.ops.bars.ops_identity_witness import (
    AMBIGUOUS,
    LEVEL_UNEXPLAINED,
    MARKER,
    MISSING,
    PLACED,
    PREDECESSOR,
    RETURNS_DISAGREE,
    THIN,
    References,
    continuity,
    judge,
    span_decision,
)

DAYS = [date(2005, 1, 3) + timedelta(days=i) for i in range(300)]


def _walk(seed: int) -> dict[date, float]:
    price, out = 50.0, {}
    for i, day in enumerate(DAYS):
        price *= math.exp(0.01 * math.sin(seed * 7.1 + i * 1.3))
        out[day] = round(price, 2)
    return out


def test_the_same_tape_places_and_a_split_is_rescaled_first():
    ibkr = _walk(1)
    split_day = DAYS[150]
    massive = {d: c * (2.0 if d <= split_day else 1.0) for d, c in ibkr.items()}  # raw, unadjusted
    scales = {d: 2.0 if d <= split_day else 1.0 for d in massive}
    matched, pairs, agreeing, corr, median, iqr, decision = judge(massive, ibkr, scales)
    assert (matched, pairs, agreeing) == (300, 299, 299)
    assert corr > 0.999 and abs(median) < 1e-9 and decision == PLACED


def test_another_tape_disagrees_and_a_short_one_is_thin():
    assert judge(_walk(2), _walk(1), {})[-1] == RETURNS_DISAGREE
    short = dict(list(_walk(1).items())[:20])
    assert judge(short, short, {})[-1] == THIN  # 19 returns, under the 8a minimum of 20


def test_a_close_definition_difference_still_places_on_correlation():
    """The first calibration's failure: the same security, closes off by a few cents on many
    days (last trade against official close), fails 99 percent agreement but correlates."""
    ibkr = _walk(1)
    massive = {d: c + (0.03 if i % 3 == 0 else 0.0) for i, (d, c) in enumerate(ibkr.items())}
    matched, pairs, agreeing, corr, *_rest, decision = judge(massive, ibkr, {})
    assert agreeing < 0.99 * pairs and corr >= 0.9 and decision == PLACED


def test_split_sized_returns_leave_the_identity_correlation():
    from scripts.ops.bars.ops_identity_witness import identity_correlation, split_sized

    assert split_sized(math.log(4 / 3)) and split_sized(-math.log(2)) and not split_sized(0.2)
    base = [0.01 * math.sin(i) for i in range(40)]
    shocked = [*base[:20], -math.log(4 / 3), *base[21:]]
    assert identity_correlation(shocked, base) > 0.99


def test_a_stable_unexplained_offset_does_not_place():
    ibkr = _walk(1)
    massive = {d: c * 1.05 for d, c in ibkr.items()}  # a 5 percent level no split explains
    assert judge(massive, ibkr, {})[-1] == LEVEL_UNEXPLAINED


def test_continuity_reads_listing_then_markers():
    refs = References(
        list_date={"OLD": date(1990, 1, 1), "SPAC": date(2021, 6, 1), "REUSE": date(1990, 1, 1)},
        figi={"OLD": "F1", "REUSE": "F3"},
        events={"OLD": [(date(2003, 9, 10), "OLD")]},
        delisted={"REUSE": [("F9", date(2008, 1, 2))], "OLD": [("F1", date(2001, 1, 2))]},
    )
    span = (date(2003, 9, 10), date(2012, 1, 3))
    assert continuity(refs, "OLD", "before_first_event", *span, "OLD") is None
    assert continuity(refs, "SPAC", "before_first_event", *span, "SPAC") == PREDECESSOR
    assert continuity(refs, "NONE", "before_first_event", *span, "NONE") == MISSING
    assert continuity(refs, "REUSE", "before_first_event", *span, "REUSE") == MARKER
    assert continuity(refs, "OLD", "ticker_claimed_by_other_security", *span, "OLD") == MARKER


def test_a_span_places_on_exactly_one_candidate():
    assert span_decision([PLACED, THIN]) == PLACED
    assert span_decision([PLACED, PLACED]) == AMBIGUOUS
    assert span_decision([THIN, PREDECESSOR, RETURNS_DISAGREE]) == PREDECESSOR
    assert span_decision([]) == THIN
