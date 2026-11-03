from types import SimpleNamespace

import pytest
from psycopg import sql

from scripts.ops.ops_feature_column_screen import (
    _query,
    applicable_columns,
    apr_value,
    classify,
    declared_memory,
    gate_failures,
    judge,
    registry_declarations,
    screen_rows,
    zero_is_state,
)


@pytest.mark.parametrize(
    ("non_null", "finite", "low", "high", "expected"),
    [
        (0, 0, None, None, "all_null"),
        (5, 0, None, None, "no_finite"),  # all NaN or infinite
        (5, 5, 0.0, 0.0, "constant"),
        (5, 3, 0.0, 0.0, "constant"),  # NaN warmup rows do not make a constant column live
        (5, 5, -1.0, 2.5, None),
    ],
)
def test_classify(non_null, finite, low, high, expected):
    assert classify(non_null, finite, low, high) == expected


def test_judge_canary_must_hold_its_value_on_every_row():
    assert judge("canary_constant", 5, 5, 1.0, 1.0) is None
    assert judge("canary_constant", 5, 5, 2.0, 2.0).startswith("not_declared_constant")
    assert judge("canary_constant", 5, 3, 1.0, 1.0).startswith("not_declared_constant")  # NaN rows
    assert judge("canary_constant", 0, 0, None, None) == "all_null"


def test_registry_accessors_tolerate_missing_declarations():
    columns = ("a", "b")
    # applicable_outputs is still forward-declared (item 2): a registry without it
    # falls back to all columns. zero_is_state landed with todo 584 4c as a Kernel
    # dataclass field, so every registry carries it; no missing-state to tolerate.
    bare = SimpleNamespace(kernels=(SimpleNamespace(outputs=("a",), zero_is_state=frozenset()),))
    assert applicable_columns(bare, columns, "1d") == {"a", "b"}
    assert zero_is_state(bare) == frozenset()
    declared = SimpleNamespace(
        applicable_outputs=lambda tf: {"a", "x"},
        kernels=(SimpleNamespace(zero_is_state=frozenset({"b"})),),
    )
    assert applicable_columns(declared, columns, "1d") == {"a"}
    assert zero_is_state(declared) == {"b"}


def test_declared_memory_maps_only_path_dependent_columns_to_none(monkeypatch):
    def is_path_dependent(column):
        if column == "unknown":
            raise KeyError(column)  # no kernel produces it: loud, not "no memory"
        return column == "hmm"

    monkeypatch.setattr(
        "scripts.ops.ops_feature_column_screen.feature_memory_bars", lambda c, cfg, reg: 7
    )
    registry = SimpleNamespace(is_path_dependent=is_path_dependent)
    assert declared_memory(registry, None, ("adx", "hmm")) == {"adx": 7, "hmm": None}
    with pytest.raises(KeyError):
        declared_memory(registry, None, ("unknown",))


def test_apr_value_raises_on_a_missing_key():
    assert apr_value(SimpleNamespace(get_sync=lambda k, d: 5), "k") == 5
    with pytest.raises(KeyError):
        apr_value(SimpleNamespace(get_sync=lambda k, d: None), "k")


def test_registry_declarations_report():
    bare = SimpleNamespace(kernels=(SimpleNamespace(),))
    assert registry_declarations(bare) == {"applicable_outputs": False, "zero_is_state": False}
    full = SimpleNamespace(
        applicable_outputs=lambda tf: (),
        kernels=(SimpleNamespace(zero_is_state=frozenset()),),
    )
    assert registry_declarations(full) == {"applicable_outputs": True, "zero_is_state": True}


def _row(tf, symbol, n_rows, *columns):
    return (tf, symbol, n_rows, *(v for column in columns for v in column))


# (non_null, finite, first finite row number, finite min, max, zeros after warmup, finite after)
LIVE = (1100, 1100, 11, -1.0, 1.0, 5, 1090)
DEAD = (1100, 1100, 11, 0.0, 0.0, 1090, 1090)
LATE = (1100, 1100, 301, -1.0, 1.0, 5, 800)  # first finite at index 300, memory 10
ZEROY = (1100, 1100, 11, 0.0, 1.0, 500, 1090)  # 46% exact zeros after warmup
EMPTY = (0, 0, None, None, None, 0, 0)


def _screen(rows, columns=("live", "x"), memory=None, applicable=None, zero_state=frozenset()):
    memory = memory or dict.fromkeys(columns, 10)
    return screen_rows(
        columns,
        rows,
        memory=memory,
        applicable={"1d": frozenset(columns) if applicable is None else applicable},
        zero_state=zero_state,
        min_rows=1000,
        min_name_rows=252,
        warmup_gap_max=5,
        zero_share_max=0.25,
    )


def test_g1_dead_column_fails_only_where_applicable():
    rows = [_row("1d", "A", 1200, LIVE, DEAD), _row("1d", "B", 1200, LIVE, DEAD)]
    report, _ = _screen(rows)
    assert report["1d"]["dead"] == {"x": {"constant": 2}}
    assert report["1d"]["G1"]["x"]["n_names"] == 2
    report, _ = _screen(rows, applicable=frozenset({"live"}))
    assert report["1d"]["dead"] == {"x": {"constant": 2}} and report["1d"]["G1"] == {}
    assert gate_failures(report) == {"G1": 0, "G2": 0, "G3": 0}


def test_g2_flags_a_late_first_finite_row_and_skips_path_dependent_columns():
    rows = [_row("1d", "A", 1200, LIVE, LATE)]
    report, _ = _screen(rows)
    assert report["1d"]["G2"] == {"x": {"n_names": 1, "examples": ["A"]}}
    assert gate_failures(report) == {"G1": 0, "G2": 1, "G3": 0}
    report, _ = _screen(rows, memory={"live": 10, "x": None})
    assert report["1d"]["G2"] == {}


def test_g3_flags_a_zero_fill_unless_zero_is_state():
    rows = [_row("1d", "A", 1200, LIVE, ZEROY)]
    assert list(_screen(rows)[0]["1d"]["G3"]) == ["x"]
    assert _screen(rows, zero_state=frozenset({"x"}))[0]["1d"]["G3"] == {}


def test_dead_uses_the_names_a_column_was_judged_on_and_unjudged_names_are_listed():
    # NEW has no more rows than the memory of x (1100 > 10, but 8 rows <= 10): x is not judged on it
    rows = [
        _row("1d", "A", 1200, LIVE, DEAD),
        _row("1d", "B", 1200, LIVE, DEAD),
        _row("1d", "NEW", 300, LIVE, EMPTY),
        _row("1d", "TINY", 8, EMPTY, EMPTY),
    ]
    report, _ = _screen(rows, memory={"live": 10, "x": 400})
    assert report["1d"]["dead"] == {"x": {"constant": 2}}  # NEW (300 <= 400) is not a judge of x
    assert report["1d"]["unjudged_names"] == ["TINY"] and report["1d"]["n_names_judged"] == 3


def test_short_timeframes_are_skipped():
    assert _screen([_row("1h", "A", 500, LIVE, LIVE)])[1] == {"1h": 500}


def test_query_renders_the_window_and_post_warmup_filters():
    text = _query(("adx",), {"adx": 40}, sql.SQL("")).as_string(None)
    assert "row_number() OVER (PARTITION BY symbol, tf ORDER BY bar_ts)" in text
    assert 'count(*) FILTER (WHERE "adx" = 0 AND rn > 40)' in text
