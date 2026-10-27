"""E18 selection command helpers (phase 187 plan 06)."""

import numpy as np

from scripts.research.select_books import horizon_sessions, universe_matrix

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
