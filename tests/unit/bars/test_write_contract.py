"""The write contract's pure core (plan 185-31; data layer integrity design section 4).

classify compares incoming rows with stored rows by exact value; revision_ratio and should_refuse
decide whether a write revises too much of what is stored to apply without a look.
"""

from __future__ import annotations

import pytest

from src.intelligence.bars.write_contract import (
    BarValues,
    WriteDelta,
    classify,
    revision_ratio,
    should_refuse,
)

_ROW: BarValues = (10.0, 10.5, 9.5, 10.25, 1000, "derived_5m")


def _with(row: BarValues, **changes: object) -> BarValues:
    fields = ["open", "high", "low", "close", "volume", "source"]
    values = list(row)
    for name, value in changes.items():
        values[fields.index(name)] = value
    return tuple(values)  # type: ignore[return-value]


def _delta(n_changed: int = 0, n_removed: int = 0) -> WriteDelta:
    return WriteDelta(
        new={},
        changed={("15m", i): (_ROW, _ROW) for i in range(n_changed)},
        unchanged=0,
        removed={("1h", i): _ROW for i in range(n_removed)},
    )


def test_identical_rows_are_unchanged_only():
    stored = {("15m", 1): _ROW, ("15m", 2): _ROW}
    delta = classify(dict(stored), stored, removal_scope=set(stored))
    assert delta == WriteDelta(new={}, changed={}, unchanged=2, removed={})


def test_one_differing_close_is_one_change_carrying_new_and_old():
    stored = {("15m", 1): _ROW, ("15m", 2): _ROW}
    revised = _with(_ROW, close=10.26)
    delta = classify({("15m", 1): revised, ("15m", 2): _ROW}, stored)
    assert delta.changed == {("15m", 1): (revised, _ROW)}
    assert delta.unchanged == 1 and not delta.new and not delta.removed


def test_a_source_only_difference_is_a_change():
    stored = {("15m", 1): _with(_ROW, source="ibkr_named")}
    delta = classify({("15m", 1): _ROW}, stored)
    assert list(delta.changed) == [("15m", 1)]


def test_an_absent_stored_key_is_new():
    delta = classify({("15m", 1): _ROW, ("15m", 2): _ROW}, {("15m", 1): _ROW})
    assert delta.new == {("15m", 2): _ROW}
    assert delta.unchanged == 1


def test_a_stored_key_absent_from_incoming_is_removed_only_inside_the_scope():
    stored = {("15m", 1): _ROW, ("15m", 2): _ROW, ("1h", 1): _ROW}
    incoming = {("15m", 1): _ROW}
    assert classify(incoming, stored).removed == {}
    scoped = classify(incoming, stored, removal_scope={("15m", 2)})
    assert scoped.removed == {("15m", 2): _ROW}
    assert classify(incoming, stored, removal_scope=set(stored)).removed == {
        ("15m", 2): _ROW,
        ("1h", 1): _ROW,
    }


def test_none_equals_none_and_differs_from_a_number():
    missing_volume = _with(_ROW, volume=None)
    assert classify({1: missing_volume}, {1: missing_volume}).unchanged == 1
    assert list(classify({1: missing_volume}, {1: _ROW}).changed) == [1]
    assert list(classify({1: _ROW}, {1: missing_volume}).changed) == [1]


def test_floats_compare_exactly_without_tolerance():
    nudged = _with(_ROW, open=10.0 + 1e-12)
    assert list(classify({1: nudged}, {1: _ROW}).changed) == [1]


def test_nan_is_refused_loudly_never_compared():
    with pytest.raises(ValueError, match="NaN"):
        classify({1: _with(_ROW, high=float("nan"))}, {1: _ROW})
    with pytest.raises(ValueError, match="NaN"):
        classify({1: _ROW}, {1: _with(_ROW, low=float("nan"))})


def test_revision_ratio_counts_changed_and_removed_over_stored():
    assert revision_ratio(_delta(n_changed=3, n_removed=2), 100) == pytest.approx(0.05)
    assert revision_ratio(_delta(n_changed=3), 0) == 0.0


@pytest.mark.parametrize(
    ("n_changed", "n_stored", "waived", "expected"),
    [
        (1, 1_000, False, False),  # 0.1% revised: written and recorded
        (30, 1_000, False, True),  # 3% revised: a finding
        (2, 78, False, False),  # a 5m tail window: fewer stored rows than min_stored
        (30, 1_000, True, False),  # a recorded corporate action waives it
        (0, 0, False, False),  # nothing stored yet
    ],
)
def test_should_refuse(n_changed, n_stored, waived, expected):
    delta = _delta(n_changed=n_changed)
    assert should_refuse(delta, n_stored, 0.02, min_stored=500, waived=waived) is expected, (
        n_changed,
        n_stored,
        waived,
    )


def test_removed_rows_count_toward_refusal():
    assert should_refuse(_delta(n_removed=30), 1_000, 0.02, min_stored=500, waived=False)
