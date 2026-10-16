"""The daily-rule equivalence check's comparison arithmetic (phase 191 plan 08). Pure, no DB."""

from __future__ import annotations

from datetime import date

from scripts.ops.bars.ops_d2_raw_equivalence import (
    TAG_AFTER_END,
    TAG_LABEL,
    TAG_RULE_ONLY,
    TAG_STORED_ONLY,
    TAG_VALUE,
    compare,
    series_digest,
    unexplained,
)

_D1, _D2, _D3, _D4 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)


def _bar(close: float, vendor: str = "ibkr", kind: str = "named", volume: int | None = 100):
    return (close, close, close, close, volume, vendor, kind)


def test_equal_series_have_equal_digests_and_no_tags():
    series = {_D1: _bar(1.0), _D2: _bar(2.0)}
    result = compare("X", dict(series), dict(series))
    assert result.equal and result.tags == {} and result.as_dict()["equal_in_span"]


def test_the_digest_sees_the_identity_pair_and_a_null_volume():
    other = _bar(1.0, vendor="tradier", kind="consolidated")
    assert series_digest({_D1: _bar(1.0)}) != series_digest({_D1: other})
    assert series_digest({_D1: _bar(1.0)}) != series_digest({_D1: _bar(1.0, volume=None)})


def test_dates_after_the_stored_end_are_their_own_tag_and_keep_the_span_equal():
    stored = {_D1: _bar(1.0), _D2: _bar(2.0)}
    rule = {**stored, _D3: _bar(3.0)}
    result = compare("X", rule, stored)
    assert not result.equal and result.tags == {TAG_AFTER_END: 1}
    assert result.as_dict()["equal_in_span"] and result.examples == []


def test_every_kind_of_difference_is_tagged():
    stored = {
        _D1: _bar(1.0),
        _D2: _bar(2.0),
        _D3: _bar(3.0, vendor="tradier", kind="consolidated"),
    }
    rule = {_D2: _bar(2.5), _D3: _bar(3.0), _D4: _bar(4.0)}
    stored[_D4 + (_D4 - _D3)] = _bar(5.0)  # a later stored date makes _D4 inside the span
    result = compare("X", rule, stored)
    assert result.tags == {TAG_STORED_ONLY: 2, TAG_VALUE: 1, TAG_LABEL: 1, TAG_RULE_ONLY: 1}
    assert not result.as_dict()["equal_in_span"]


def test_the_allow_list_explains_by_class_or_by_symbol():
    row = compare("X", {_D1: _bar(1.0), _D2: _bar(2.0), _D3: _bar(3.0)}, {_D2: _bar(2.0)})
    data = row.as_dict()
    assert data["tags"] == {TAG_RULE_ONLY: 1, TAG_AFTER_END: 1}
    assert unexplained(data, {}) == sorted([TAG_AFTER_END, TAG_RULE_ONLY])
    classes = {"classes": {TAG_AFTER_END: "cutover"}}
    assert unexplained(data, classes) == [TAG_RULE_ONLY]
    per_symbol = {**classes, "symbols": {"X": {"tags": [TAG_RULE_ONLY], "reason": "r"}}}
    assert unexplained(data, per_symbol) == []
    assert unexplained(data, {**classes, "symbols": {"Y": {"tags": [TAG_RULE_ONLY]}}}) == [
        TAG_RULE_ONLY
    ]


def test_a_rule_error_is_never_explained_by_tags():
    data = {"symbol": "X", "equal": False, "error": "LookupError: no policy", "tags": {}}
    assert unexplained(data, {"classes": {TAG_VALUE: "x"}}) == ["error"]
