"""Point-in-time membership mask (todo 609 I1)."""

import datetime as dt

import numpy as np
import pytest

from src.intelligence.research import membership as mem

D = dt.date


def _days(*isos):
    return np.array(isos, dtype="datetime64[D]")


LEDGER = {
    D(2024, 1, 31): frozenset({"A", "B"}),
    D(2024, 2, 29): frozenset({"B", "C"}),
}


def test_session_reads_the_latest_built_month_end_strictly_before_it():
    sessions = _days("2024-01-31", "2024-02-01", "2024-02-29", "2024-03-01")
    mask = mem.member_mask(sessions, ["A", "B", "C"], LEDGER)
    assert mask.tolist() == [
        [False, False, False],  # on the first as_of: not yet effective
        [True, True, False],  # first session after 2024-01-31 uses it
        [True, True, False],  # a decision made on 02-29's close is not in its own cross-section
        [False, True, True],
    ]


def test_session_before_the_first_as_of_is_all_false():
    assert not mem.member_mask(_days("2023-12-29"), ["A"], LEDGER).any()


def test_session_past_the_month_after_the_ledger_raises():
    ok = mem.member_mask(_days("2024-03-29"), ["A"], LEDGER)
    assert ok.shape == (1, 1)
    with pytest.raises(ValueError, match="built through 2024-02-29"):
        mem.member_mask(_days("2024-04-01"), ["A"], LEDGER)


def test_empty_ledger_raises():
    with pytest.raises(ValueError, match="empty"):
        mem.member_mask(_days("2024-02-01"), ["A"], {})


def test_a_built_empty_month_is_no_member_not_an_error():
    ledger = {D(2024, 1, 31): frozenset(), D(2024, 2, 29): frozenset({"A"})}
    mask = mem.member_mask(_days("2024-02-01", "2024-03-01"), ["A"], ledger)
    assert mask.ravel().tolist() == [False, True]


def test_symbols_outside_the_panel_are_ignored():
    mask = mem.member_mask(_days("2024-02-01"), ["B"], LEDGER)
    assert mask.tolist() == [[True]]


def test_core_is_members_at_ninety_percent_of_month_ends():
    ledger = {
        D(2024, m, 28): frozenset({"ALWAYS"} | ({"SOMETIMES"} if m <= 5 else set()))
        for m in range(1, 11)
    }
    assert mem.core_symbols(ledger) == frozenset({"ALWAYS"})
    ledger[D(2024, 11, 28)] = frozenset({"ALWAYS", "SOMETIMES"})
    assert "SOMETIMES" not in mem.core_symbols(ledger)
    assert mem.core_symbols({D(2024, 1, 31): frozenset({"A"})}) == frozenset({"A"})


def test_apply_member_mask_nans_non_members_and_leaves_members_untouched():
    member = np.array([[True, False], [False, True]])
    array = np.arange(8, dtype=float).reshape(4, 2)  # 2 bars per session
    out = mem.apply_member_mask(array, member, 2)
    assert np.isnan(out).tolist() == [[False, True], [False, True], [True, False], [True, False]]
    assert out[0, 0] == 0.0 and out[3, 1] == 7.0
    assert not np.shares_memory(out, array)


def test_apply_member_mask_refuses_a_misfit():
    with pytest.raises(ValueError, match="does not fit"):
        mem.apply_member_mask(np.zeros((3, 2)), np.ones((2, 2), dtype=bool), 2)
