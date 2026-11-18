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


def test_seen_mask_is_true_from_first_membership_and_never_before():
    member = np.array([[False, True], [True, False], [False, False]])
    seen = mem.seen_member_mask(member)
    assert seen.tolist() == [[False, True], [True, True], [True, True]]
    # a name whose first membership is after t is never in the set at t
    first = np.argmax(member, axis=0)
    for j in range(member.shape[1]):
        assert not seen[: first[j], j].any()


def test_seen_mask_does_not_move_when_a_later_membership_list_changes():
    base = np.array([[True, False, False], [True, True, False], [True, True, False]])
    longer = np.concatenate([base, [[True, True, True]]])
    assert np.array_equal(mem.seen_member_mask(longer)[:3], mem.seen_member_mask(base))


def test_apply_seen_prices_nans_rows_before_first_membership():
    seen = np.array([[False], [True]])
    open_, close = np.ones((4, 1)), np.ones((4, 1))
    o, c = mem.apply_seen_prices(open_, close, seen, 2)
    assert (
        np.isnan(o).ravel().tolist() == [True, True, False, False] == np.isnan(c).ravel().tolist()
    )


def test_cold_start_share_counts_member_days_inside_the_memory_of_entry():
    # A is a member throughout; B enters at session 2. Memory 2 sessions: B is cold at 2 and 3.
    member = np.array(
        [[True, False], [True, False], [True, True], [True, True], [True, True], [True, True]]
    )
    years = np.array([2020, 2020, 2020, 2020, 2021, 2021])
    share = mem.cold_start_share_by_year(member, years, 2)
    # A is cold at its first two member-days too: 2 + 2 cold of 4 + 2 member-days in 2020.
    assert share == {2020: 4 / 6, 2021: 0.0}


def test_cold_start_share_skips_years_without_members_and_refuses_bad_input():
    member = np.array([[False], [True]])
    assert mem.cold_start_share_by_year(member, np.array([2019, 2020]), 5) == {2020: 1.0}
    with pytest.raises(ValueError, match="at least 1"):
        mem.cold_start_share_by_year(member, np.array([2019, 2020]), 0)
    with pytest.raises(ValueError, match="years has shape"):
        mem.cold_start_share_by_year(member, np.array([2019]), 1)
