from types import SimpleNamespace

import pytest
from psycopg import sql

from scripts.ops.ops_feature_column_screen import (
    APR_KEYS,
    _clock_query,
    _query,
    applicable_columns,
    apr_value,
    classify,
    context_columns,
    declared_memory,
    fill_audit_exempt,
    gate_failures,
    judge,
    null_share_gate,
    registry_declarations,
    screen_rows,
    uncovered_dividend_clock,
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


def test_declared_memory_is_the_first_storable_row_per_tf_for_every_column(monkeypatch):
    def stored(registry, column, config, tf):
        if column == "unknown":
            raise KeyError(column)  # no kernel produces it: loud, never a default
        return {"adx": 30, "hmm": {"5m": 1539, "1d": 639}[tf]}[column]

    monkeypatch.setattr("scripts.ops.ops_feature_column_screen.stored_first_row", stored)
    registry = SimpleNamespace(applicable_outputs=lambda tf: {"adx", "hmm", "unknown"})
    assert declared_memory(registry, None, ("adx", "hmm"), ["5m", "1d"]) == {
        "5m": {"adx": 30, "hmm": 1539},
        "1d": {"adx": 30, "hmm": 639},
    }
    with pytest.raises(KeyError):
        declared_memory(registry, None, ("unknown",), ["5m"])
    # a column not applicable on a tf is never judged there, so it needs no warmup there
    registry.applicable_outputs = lambda tf: {"adx"}
    assert declared_memory(registry, None, ("unknown",), ["5m"]) == {"5m": {"unknown": 0}}


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


def _screen(rows, columns=("live", "x"), memory=None, applicable=None, fill_exempt=frozenset()):
    memory = {"1d": memory or dict.fromkeys(columns, 10)}
    return screen_rows(
        columns,
        rows,
        memory=memory,
        applicable={"1d": frozenset(columns) if applicable is None else applicable},
        fill_exempt=fill_exempt,
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


def test_g2_flags_a_late_first_finite_row_against_the_declared_warmup():
    rows = [_row("1d", "A", 1200, LIVE, LATE)]
    report, _ = _screen(rows)
    assert report["1d"]["G2"] == {"x": {"n_names": 1, "examples": ["A"]}}
    assert gate_failures(report) == {"G1": 0, "G2": 1, "G3": 0}
    # a path-dependent column declares its anchor warmup and is judged from it like any other
    report, _ = _screen(rows, memory={"live": 10, "x": 298})
    assert report["1d"]["G2"] == {}


def test_g3_flags_a_zero_fill_unless_zero_is_state():
    rows = [_row("1d", "A", 1200, LIVE, ZEROY)]
    assert list(_screen(rows)[0]["1d"]["G3"]) == ["x"]
    assert _screen(rows, fill_exempt=frozenset({"x"}))[0]["1d"]["G3"] == {}


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
    text = _query(("adx",), {"1d": {"adx": 40}}, sql.SQL("")).as_string(None)
    assert "row_number() OVER (PARTITION BY symbol, tf ORDER BY bar_ts)" in text
    assert 'count(*) FILTER (WHERE "adx" = 0 AND rn > 40)' in text
    # a warmup that differs by tf is a CASE over tf
    text = _query(("hmm",), {"1d": {"hmm": 639}, "5m": {"hmm": 1539}}, sql.SQL("")).as_string(None)
    assert "rn > CASE tf WHEN '1d' THEN 639 WHEN '5m' THEN 1539 ELSE 0 END" in text


# ---------------------------------------------------------------------------
# G6: the post-warmup NULL share (186-31, the deleted verifier's null-rate check restored)
# ---------------------------------------------------------------------------


def _years(n_years: int, null_years: int) -> tuple:
    """One name, 252 rows a year after a 10-bar warmup, NULL on `null_years` of the years."""
    n = 10 + 252 * n_years
    finite_post = 252 * (n_years - null_years)
    return (n, (n, n, 11, -1.0, 1.0, 0, finite_post))


def _null_gate(rows, columns=("x",), memory=None, applicable=None, objects=(), max_null=0.05):
    tfs = {r[0] for r in rows}
    per_tf = memory or dict.fromkeys(columns, 10)
    return null_share_gate(
        columns,
        rows,
        memory={tf: per_tf for tf in tfs},
        applicable={tf: frozenset(columns) if applicable is None else applicable for tf in tfs},
        object_columns=frozenset(objects),
        max_null_fraction=max_null,
        min_name_rows=252,
    )


def test_g6_fails_a_column_null_for_4_of_10_years_on_every_name():
    n, cell = _years(10, 4)
    rows = [_row("1h", s, n, cell) for s in ("A", "B", "C")]
    gate = _null_gate(rows)["1h"]
    assert list(gate["failing"]) == ["x"] and gate["worst"] == {"x": 0.4}


def test_g6_passes_a_full_column_and_counts_only_rows_past_the_warmup():
    n, cell = _years(10, 0)
    gate = _null_gate([_row("1h", "A", n, cell)])["1h"]
    assert gate["failing"] == {} and gate["worst"] == {"x": 0.0}


def test_g6_skips_not_applicable_columns():
    n, cell = _years(10, 10)
    gate = _null_gate(
        [_row("1h", "A", n, cell, cell)], columns=("x", "y"), applicable=frozenset({"y"})
    )["1h"]
    assert list(gate["failing"]) == ["y"] and "x" not in gate["worst"]


def _post(n: int, warmup: int, finite_post: int) -> tuple:
    """A column whose rows past its declared warmup hold `finite_post` finite values."""
    return (finite_post, finite_post, warmup + 1, -1.0, 1.0, 0, finite_post)


def test_g6_fails_a_40_percent_null_hmm_column_past_its_declared_warmup():
    """An HMM column declares its first refit boundary as its warmup (registry warmup_bars);
    40% NULL past it fails."""
    n, warmup = 2539, 1539
    cell = _post(n, warmup, 600)  # 1000 rows past the warmup, 600 finite
    rows = [_row("5m", s, n, cell) for s in ("A", "B")]
    gate = _null_gate(rows, columns=("hmm_regime_prob",), memory={"hmm_regime_prob": warmup})
    assert list(gate["5m"]["failing"]) == ["hmm_regime_prob"]
    assert gate["5m"]["worst"] == {"hmm_regime_prob": 0.4}


def test_g6_fails_a_path_dependent_column_null_in_a_block_inside_its_span():
    n, warmup = 2030, 30  # adx: 2000 rows past its declared warmup, a 300-row hole among them
    gate = _null_gate(
        [_row("5m", "A", n, _post(n, warmup, 1700))], columns=("adx",), memory={"adx": warmup}
    )["5m"]
    assert "adx" in gate["failing"] and gate["worst"]["adx"] == pytest.approx(0.15)
    full = _null_gate(
        [_row("5m", "A", n, _post(n, warmup, 2000))], columns=("adx",), memory={"adx": warmup}
    )["5m"]
    assert full["failing"] == {}


def test_g6_an_applicable_column_that_cannot_be_measured_fails():
    n, cell = _years(1, 0)  # 262 rows, warmup 300: no name has a row past it
    gate = _null_gate([_row("1h", "A", n, cell)], memory={"x": 300})["1h"]
    assert gate["failing"]["x"].startswith("cannot be measured")


def test_g6_object_dependent_columns_fail_only_when_entirely_null():
    n, partial = _years(10, 6)
    _, empty = _years(10, 10)
    cols = ("sr_support_dist",)
    assert (
        _null_gate([_row("1h", "A", n, partial)], columns=cols, objects=cols)["1h"]["failing"] == {}
    )
    gate = _null_gate([_row("1h", "A", n, empty)], columns=cols, objects=cols)["1h"]
    assert gate["failing"]["sr_support_dist"].startswith("entirely NULL")
    # not declared object dependent: the same 60% hole fails the share
    assert (
        "sr_support_dist"
        in _null_gate([_row("1h", "A", n, partial)], columns=cols)["1h"]["failing"]
    )


def test_the_screen_lists_its_apr_keys():
    assert "infra.corpus_rerun.max_null_fraction" in APR_KEYS
    assert "threshold.pilot_gate.warmup_gap_bars" in APR_KEYS


# ---------------------------------------------------------------------------
# G3 skips by declared kernel property, never by column name (todo 652)
# ---------------------------------------------------------------------------


def _kernel(outputs, **flags):
    base = {"zero_is_state": frozenset(), "acausal_control": False}
    return SimpleNamespace(outputs=tuple(outputs), **{**base, **flags})


def test_fill_audit_exempt_follows_the_declared_kernel_properties():
    kernels = (
        _kernel(("a_state", "a_other"), zero_is_state=frozenset({"a_state"})),
        _kernel(("a_control",), acausal_control=True),
        _kernel(("an_object", "a_plain")),
    )
    registry = SimpleNamespace(kernels=kernels, object_dependent_outputs=lambda: ("an_object",))
    # an object-dependent column is still audited: a 0.0 can stand in for an absent object
    assert fill_audit_exempt(registry) == {"a_state", "a_control"}
    bare = SimpleNamespace(
        kernels=(_kernel(("a_state", "a_control")),), object_dependent_outputs=lambda: ()
    )
    assert fill_audit_exempt(bare) == frozenset()


def test_fill_audit_exempt_on_the_real_registry():
    from src.intelligence.features.contract.registry import default_registry

    exempt = fill_audit_exempt(default_registry())
    assert {"opex_flag", "canary_acausal_placebo", "body_ratio"} <= exempt
    assert {"swing_pattern", "struct_accel_bias", "reclaim_velocity"}.isdisjoint(exempt)
    assert "hmm_churn" not in exempt  # parked until its segment status is verifiable


# ---------------------------------------------------------------------------
# The context clock: an input that does not exist yet is not a warmup gap or a null (todo 652)
# ---------------------------------------------------------------------------


def test_the_context_clock_moves_a_late_first_row_inside_the_warmup():
    rows = [_row("1d", "A", 1200, LIVE, LATE)]
    assert _screen(rows)[0]["1d"]["G2"] != {}
    memory = {"1d": dict.fromkeys(("live", "x"), 10)}
    base = {
        "columns": ("live", "x"),
        "memory": memory,
        "applicable": {"1d": frozenset(("live", "x"))},
        "fill_exempt": frozenset(),
        "min_rows": 1000,
        "min_name_rows": 252,
        "warmup_gap_max": 5,
        "zero_share_max": 0.25,
    }
    # the input begins 298 rows in: LATE (first finite at index 300) is then 2 rows after it
    report, _ = screen_rows(rows=rows, clock={("1d", "A"): {"x": 298}}, **base)
    assert report["1d"]["G2"] == {}
    # another name that is NaN well after the clock still fails
    late_again = (1100, 1100, 700, -1.0, 1.0, 5, 800)
    rows = [_row("1d", "A", 1200, LIVE, LATE), _row("1d", "B", 1200, LIVE, late_again)]
    clock = {("1d", "A"): {"x": 298}, ("1d", "B"): {"x": 0}}
    report, _ = screen_rows(rows=rows, clock=clock, **base)
    assert report["1d"]["G2"]["x"]["examples"] == ["B"]


def test_the_context_clock_counts_only_rows_after_the_input_begins_in_g6():
    n = 10 + 252 * 10
    # 901 rows of a 2,530-row name are before the input; every later row is finite
    cell = (n, (n, n - 901, 902, -1.0, 1.0, 0, n - 901))
    rows = [("1d", "A", cell[0], *cell[1])]
    memory = {"1d": {"x": 10}}
    kw = {
        "memory": memory,
        "applicable": {"1d": frozenset({"x"})},
        "object_columns": frozenset(),
        "max_null_fraction": 0.05,
        "min_name_rows": 252,
    }
    assert null_share_gate(("x",), rows, **kw)["1d"]["failing"] != {}
    clocked = null_share_gate(("x",), rows, clock={("1d", "A"): {"x": 901}}, **kw)
    assert clocked["1d"]["failing"] == {}


def test_the_clock_query_reads_the_first_finite_date_from_the_screened_rows():
    text = _clock_query(("vix_z",), sql.SQL(" WHERE symbol = ANY(%s)")).as_string(None)
    assert "AS NOT MATERIALIZED" in text
    assert "min(bar_ts) FILTER (WHERE \"vix_z\" > '-Infinity' AND \"vix_z\" < 'Infinity')" in text
    assert 'count(*) FILTER (WHERE f.bar_ts < avail."first_vix_z")' in text
    assert "WHERE symbol = ANY(%s)" in text


def test_only_the_symbol_independent_record_columns_get_a_clock():
    assert context_columns(("vix_z", "equity_beta_z", "rsi", "hyg_lqd_ret_z")) == (
        "vix_z",
        "hyg_lqd_ret_z",
    )


def test_a_name_without_dividend_coverage_is_not_judged_on_the_dividend_column():
    rows = [_row("1d", "A", 1200, LIVE, DEAD), _row("1d", "B", 1200, LIVE, DEAD)]
    clock = uncovered_dividend_clock(rows, covered={"A"})
    assert clock == {("1d", "B"): {"dividend_yield": 1200}}
    base = {
        "columns": ("live", "dividend_yield"),
        "memory": {"1d": {"live": 10, "dividend_yield": 0}},
        "applicable": {"1d": frozenset(("live", "dividend_yield"))},
        "fill_exempt": frozenset(),
        "min_rows": 1000,
        "min_name_rows": 252,
        "warmup_gap_max": 5,
        "zero_share_max": 0.25,
    }
    # both names are constant (a 0.0 column) on the dividend column; only the covered one fails
    report, _ = screen_rows(rows=rows, clock=clock, **base)
    assert report["1d"]["G1"]["dividend_yield"]["examples"] == ["A"]
