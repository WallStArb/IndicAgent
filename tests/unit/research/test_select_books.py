"""E18 selection command helpers (phase 187 plan 06)."""

import numpy as np

from scripts.research.select_books import (
    battery_refusals,
    horizon_sessions,
    selection_refusals,
    universe_matrix,
)

FAMILY = open("research/specs/family1_h26.yaml").read()
BOOK = open("research/specs/book_v1.yaml").read()


def test_universe_aligns_sessions_and_never_fills():
    rows = [
        {
            "sessions": np.array(["2020-01-02", "2020-01-03"], dtype="datetime64[D]"),
            "d_s": [1.0, 2.0],
        },
        {
            "sessions": np.array(["2020-01-03", "2020-01-06"], dtype="datetime64[D]"),
            "d_s": [3.0, 4.0],
        },
    ]
    calendar, matrix = universe_matrix(rows)
    assert [str(d) for d in calendar] == ["2020-01-02", "2020-01-03", "2020-01-06"]
    assert np.array_equal(
        matrix, np.array([[1.0, np.nan], [2.0, 3.0], [np.nan, 4.0]]), equal_nan=True
    )


def test_family_horizon_in_sessions():
    assert horizon_sessions(FAMILY, None) == 1  # 26 fifteen-minute rows = one session


def test_book_horizon_reads_its_first_family():
    seen = []

    def family_text(path):
        seen.append(path)
        return open(path).read()

    assert horizon_sessions(BOOK, family_text) >= 1
    assert seen and seen[0].startswith("research/specs/")


APR = {"alpha.selection.stepm.fwer": 0.05, "alpha.selection.stepm.block_mean_sessions": 20}
GOOD = {
    "schema": "stepm_null_battery_v1",
    "complete": True,
    "failures": [],
    "stepm_sha256": "abc",
    "studentize": "draw",
    "fwer": 0.05,
    "block_mean": 20.0,
    "sessions": 4000,
}


def test_a_complete_passing_battery_on_this_code_attests():
    assert battery_refusals(GOOD, APR, "abc") == []


def test_battery_gates_refuse_every_weaker_record():
    assert battery_refusals(None, APR, "abc") == ["no StepM null-battery record (--battery)"]
    for change, word in (
        ({"complete": False}, "only some cells"),
        ({"failures": ["slot_effects"]}, "fails"),
        ({"stepm_sha256": "old"}, "different StepM code"),
        ({"studentize": "sample"}, "studentize"),
        ({"fwer": 0.1}, "fwer"),
        ({"block_mean": 10.0}, "block_mean"),
        ({"sessions": 1500}, "real panel length"),
    ):
        (reason,) = battery_refusals({**GOOD, **change}, APR, "abc")
        assert word in reason


def test_missing_series_and_other_vintages_are_not_a_result():
    assert selection_refusals([], [], []) == []
    reasons = selection_refusals([{"run_id": "r"}], ["2"], ["no battery"])
    assert len(reasons) == 3 and "1 charged runs have no series" in reasons[0]
    assert "other vintages" in reasons[1]
