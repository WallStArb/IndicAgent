"""The security type resolver: class mapping order, conflicts, untyped (todo 648)."""

from __future__ import annotations

import pytest

from src.intelligence.security_type import ETF_CLASS, resolve_security_type


def test_no_label_is_untyped_never_filled():
    assert resolve_security_type({}) == (None, False)
    assert resolve_security_type({"CS": 0}) == (None, False)


@pytest.mark.parametrize("label", ["CS", "ADRC", "ETF", "UNIT", "SP", "OTHER"])
def test_a_single_label_resolves_to_itself_without_conflict(label):
    assert resolve_security_type({label: 3}) == (label, False)


@pytest.mark.parametrize("label", sorted(ETF_CLASS - {"ETF"}))
def test_the_etf_class_is_one_type_and_not_a_conflict(label):
    assert resolve_security_type({label: 2, "ETF": 5}) == ("ETF", False)
    assert resolve_security_type({label: 4}) == ("ETF", False)


@pytest.mark.parametrize("excluding", ["ETN", "WARRANT", "RIGHT", "PFD", "ADRP"])
def test_excluding_labels_win_over_every_other_label(excluding):
    assert resolve_security_type({"CS": 90, "ETF": 90, "FUND": 9, excluding: 1}) == (
        excluding,
        True,
    )


def test_excluding_labels_resolve_in_the_registered_order():
    assert resolve_security_type({"PFD": 9, "ETN": 1, "RIGHT": 4})[0] == "ETN"
    assert resolve_security_type({"ADRP": 9, "PFD": 1})[0] == "PFD"
    assert resolve_security_type({"WARRANT": 1, "RIGHT": 9})[0] == "WARRANT"


def test_etf_class_beats_fund_beats_common_beats_unit():
    assert resolve_security_type({"ETF": 1, "FUND": 8, "CS": 20})[0] == "ETF"
    assert resolve_security_type({"FUND": 1, "CS": 20})[0] == "FUND"
    assert resolve_security_type({"CS": 1, "UNIT": 20})[0] == "CS"
    assert resolve_security_type({"UNIT": 5, "OTHER": 9})[0] == "UNIT"


def test_common_labels_are_decided_by_count_then_cs_first_on_a_tie():
    assert resolve_security_type({"CS": 3, "ADRC": 5}) == ("ADRC", False)
    assert resolve_security_type({"CS": 5, "ADRC": 5}) == ("CS", False)


def test_conflict_is_true_exactly_when_the_labels_span_classes():
    assert resolve_security_type({"CS": 1, "ADRC": 1})[1] is False
    assert resolve_security_type({"CS": 1, "UNIT": 1})[1] is True
    assert resolve_security_type({"ETF": 1, "INDEX": 1, "ETV": 1})[1] is False


def test_the_result_never_depends_on_label_order():
    forward = {"UNIT": 2, "OTHER": 2, "SP": 2}
    backward = dict(reversed(list(forward.items())))
    assert resolve_security_type(forward) == resolve_security_type(backward)
