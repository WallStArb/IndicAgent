"""One memory function for feature members and the S0 warmup prefix (184 RESEARCH Pattern 4)."""

import pytest

from src.intelligence.research.book import book_memory
from src.intelligence.research.combiner import EqualWeight
from src.intelligence.research.horizon import HorizonRule
from src.intelligence.research.member_memory import (
    MemberMemory,
    feature_member_memory,
    feature_member_memory_rows,
    feature_member_memory_sessions,
    warmup_prefix_sessions,
)
from src.intelligence.research.timing import e17_memory


def _kw(**over):
    kw = dict(
        source_memory_bars=251,
        source_bars_per_session=1,
        max_age_rows=1,
        smoothing_half_life=None,
        slot_history_sessions=1,
        book_bars_per_session=1,
    )
    kw.update(over)
    return kw


def test_daily_feature_on_daily_book():
    assert feature_member_memory_sessions(**_kw()) == 253
    assert feature_member_memory_rows(**_kw()) == 253


def test_hourly_feature_on_daily_book():
    kw = _kw(source_memory_bars=20, source_bars_per_session=7, max_age_rows=2)
    assert feature_member_memory_sessions(**kw) == 5  # ceil(22 / 7) = 4, plus slot history 1
    assert feature_member_memory_rows(**kw) == 5


def test_daily_feature_on_hourly_book():
    kw = _kw(book_bars_per_session=7)
    assert feature_member_memory_sessions(**kw) == 253
    assert feature_member_memory_rows(**kw) == 253 * 7


def test_smoothing_adds_its_memory():
    assert feature_member_memory_sessions(**_kw(smoothing_half_life=63)) == 253 + 838
    assert feature_member_memory_sessions(**_kw(smoothing_half_life=5)) == 253 + 67


def test_smoothing_refused_off_the_daily_book_clock():
    with pytest.raises(ValueError, match="daily book clock"):
        feature_member_memory_sessions(**_kw(smoothing_half_life=21, book_bars_per_session=7))


def test_off_menu_smoothing_refused():
    with pytest.raises(ValueError, match="half-life"):
        feature_member_memory_sessions(**_kw(smoothing_half_life=10))


def test_warmup_prefix_is_the_max():
    assert warmup_prefix_sessions([253, 5, 1091]) == 1091
    assert warmup_prefix_sessions([]) == 0
    with pytest.raises(ValueError):
        warmup_prefix_sessions([5, -1])


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_memory_bars", -1),
        ("source_memory_bars", 2.0),
        ("max_age_rows", -2),
        ("slot_history_sessions", 1.5),
        ("source_bars_per_session", 0),
        ("book_bars_per_session", 0),
        ("max_age_rows", True),
    ],
)
def test_bad_inputs_raise(field, value):
    with pytest.raises(ValueError, match=field):
        feature_member_memory_sessions(**_kw(**{field: value}))


def test_member_memory_object():
    mem = feature_member_memory(**_kw(smoothing_half_life=21, slot_history_sessions=3))
    assert isinstance(mem, MemberMemory)
    assert (mem.source_memory_bars, mem.max_age_rows) == (251, 1)
    assert (mem.smoothing_sessions, mem.slot_history_sessions) == (280, 3)
    assert mem.sessions == 252 + 280 + 3
    assert mem.rows == mem.sessions
    assert mem.transform_rows == 280 + 3
    # the thin accessors read the same object
    kw = _kw(smoothing_half_life=21, slot_history_sessions=3)
    assert feature_member_memory_sessions(**kw) == mem.sessions
    assert feature_member_memory_rows(**kw) == mem.rows
    with pytest.raises(AttributeError):
        mem.sessions = 1  # frozen


def test_member_memory_object_transform_rows_on_intraday_book():
    mem = feature_member_memory(**_kw(slot_history_sessions=4, book_bars_per_session=7))
    assert mem.transform_rows == 4 * 7
    assert mem.rows == (252 + 4) * 7


@pytest.mark.parametrize("horizon", [1, 5, 20])
def test_e17_memory_over_member_memory_on_daily_panel(horizon):
    """L is timing.e17_memory over the member-memory sessions (184-03 amendment); smoothing
    lands in slot history, and the daily target adds its reach only through e17_memory."""
    members = [
        feature_member_memory(**_kw(smoothing_half_life=5)),
        feature_member_memory(**_kw(source_memory_bars=20, source_bars_per_session=7)),
    ]
    sessions = [m.sessions for m in members]
    mem = book_memory(
        sessions, [m.rows for m in members], horizon, EqualWeight((1.0, 1.0)), HorizonRule(1.0), 1
    )
    assert mem.sessions == e17_memory(max(sessions), horizon, 1)
    assert mem.sessions == max(sessions) + horizon


def test_e17_memory_over_member_memory_on_intraday_panel():
    member = feature_member_memory(**_kw(book_bars_per_session=26))
    mem = book_memory(
        [member.sessions], [member.rows], 26, EqualWeight((1.0,)), HorizonRule(1.0), 26
    )
    assert mem.sessions == e17_memory(member.sessions, 26, 26) == member.sessions
