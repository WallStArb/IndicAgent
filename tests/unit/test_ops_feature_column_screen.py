import pytest
from psycopg import sql

from scripts.ops.ops_feature_column_screen import _query, classify, judge, screen_rows


@pytest.mark.parametrize(
    ("non_null", "finite", "low", "high", "expected"),
    [
        (0, 0, None, None, "all_null"),
        (5, 0, None, None, "no_finite"),  # all NaN or infinite
        (5, 5, 0.0, 0.0, "constant"),
        (5, 3, 0.0, 0.0, "constant"),  # NaN warmup or inf rows do not make it live
        (5, 5, -1.0, 2.5, None),
    ],
)
def test_classify(non_null, finite, low, high, expected):
    assert classify(non_null, finite, low, high) == expected


def test_judge_declared_constant():
    assert judge("canary_constant", 5, 5, 1.0, 1.0) is None
    assert judge("canary_constant", 5, 5, 2.0, 2.0) == "not_declared_constant (2.0..2.0)"
    assert judge("canary_constant", 0, 0, None, None) == "all_null"


def _row(tf, symbol, n_rows, *columns):
    return (tf, symbol, n_rows, *(v for column in columns for v in column))


LIVE, FLAT, CANARY = (9, 9, -1.0, 1.0), (9, 9, 0.0, 0.0), (9, 9, 1.0, 1.0)


def test_screen_rows_judges_per_name():
    columns = ("live", "flat", "canary_constant")
    rows = [
        _row("1d", "A", 600, LIVE, FLAT, CANARY),
        _row("1d", "B", 600, LIVE, (9, 9, 5.0, 5.0), CANARY),  # constant at another level
        _row("1d", "THIN", 3, FLAT, FLAT, FLAT),  # too short to judge
        _row("1h", "A", 600, LIVE, LIVE, CANARY),
        _row("1h", "B", 600, FLAT, LIVE, (9, 9, 2.0, 2.0)),
        _row("5m", "A", 10, LIVE, LIVE, CANARY),
    ]
    report, skipped = screen_rows(columns, rows, min_rows=1000, min_name_rows=252)
    assert skipped == {"5m": 10}
    assert report["1d"]["n_names_judged"] == 2
    assert report["1d"]["dead"] == {"flat": {"constant": 2}}
    assert report["1d"]["partial"] == {}
    assert report["1h"]["dead"] == {}
    assert report["1h"]["partial"] == {
        "live": {"constant": 1},
        "canary_constant": {"not_declared_constant (2.0..2.0)": 1},
    }


def test_query_renders():
    text = _query(("adx",), sql.SQL("")).as_string(None)
    assert 'max("adx") FILTER' in text and "GROUP BY tf, symbol" in text
