"""The spread_leg audit's pure checks (todo 678): no database."""

from scripts.ops.ops_spread_leg_audit import pairs_of, spread_leg_problems

SYMBOLS = frozenset({"SPY", "IPO", "EZU", "FXE", "UUP"})


def test_pairs_accept_a_symbol_a_list_or_nothing():
    assert pairs_of({"pair": "UUP"}) == ["UUP"]
    assert pairs_of({"pair": ["IPO", "EZU"]}) == ["IPO", "EZU"]
    assert pairs_of({}) == [] and pairs_of(None) == []


def test_a_clean_set_with_a_hub_has_no_problems():
    rows = {
        "SPY": {"pair": ["IPO", "EZU"]},
        "IPO": {"pair": "SPY"},
        "EZU": {"pair": "SPY"},
        "FXE": {"pair": "UUP"},
        "UUP": {"pair": "FXE"},
    }
    assert spread_leg_problems(list(rows.items()), SYMBOLS) == []


def test_each_defect_is_named():
    rows = {
        "FXE": {"pair": "UUP"},  # UUP has no row
        "SPY": {"pair": ["IPO", "ZZZ"]},  # IPO does not name SPY back; ZZZ is not an instrument
        "IPO": {"pair": "EZU"},
        "EZU": {"note": "no pair"},
    }
    problems = spread_leg_problems(list(rows.items()), SYMBOLS)
    assert "FXE->UUP: partner has no spread_leg row" in problems
    assert "SPY->IPO: IPO does not name SPY back" in problems
    assert "SPY->ZZZ: no such instrument" in problems
    assert "EZU: no evidence pair" in problems


def test_a_symbol_with_two_current_rows_is_a_problem_not_collapsed():
    rows = [("FXE", {"pair": "UUP"}), ("UUP", {"pair": "FXE"}), ("UUP", {"pair": "SPY"})]
    assert "UUP: 2 current spread_leg rows" in spread_leg_problems(rows, SYMBOLS)
