"""The Massive switch plan builder (todo 600 step 7): pure tests, no database."""

from __future__ import annotations

from datetime import date

import pytest

from scripts.ops.bars.ops_massive_policy_plan import (
    GapRow,
    LiveRow,
    build_plan,
    incumbent_rows,
    read_gap_list,
    through_needed,
)
from scripts.ops.bars.ops_source_policy import parse_plan

_GAP = {"path": "data/ticker_entity_map/x/gap_list.csv", "sha256": "ab"}
_FP = {"through": "2026-11-10", "series": {"ibkr/smart_trades": {"rows": 1}}}


def _defaults():
    return [
        LiveRow("d-old", None, date(1990, 1, 1), date(2016, 1, 4), "ibkr", None, "seed", {}),
        LiveRow("d-new", None, date(2016, 1, 4), None, "alpaca", "ibkr", "seed", {}),
    ]


def _ibkr_row(symbol, start, end, pid):
    return LiveRow(pid, symbol, start, end, "ibkr", None, "D-191-Q", {"class": "alpaca_differs"})


_GAPS = [
    GapRow("AAL", "span", "before_first_event", date(2003, 9, 10), date(2013, 12, 9)),
    GapRow("A", "instrument", "event_chain_head_mismatch", None, None),
    GapRow("ES", "instrument", "asset_class_outside_vendor", None, None),
    GapRow("LATE", "span", "before_first_event", date(2003, 9, 10), date(2019, 5, 1)),
    GapRow("LATE", "span", "ticker_claimed_by_other_security", date(2018, 1, 1), date(2020, 1, 1)),
]


def _plan(stage, timeframe, live):
    plan = build_plan(stage=stage, timeframe=timeframe, live=live, gaps=_GAPS, gap_list=_GAP)
    if timeframe == "1d":
        plan["raw_fingerprint"] = _FP
    return plan


def _rows(plan, symbol):
    return [
        (r["valid_from"], r["valid_to"], r["primary"])
        for r in plan["symbol_rows"]
        if r["symbol"] == symbol
    ]


@pytest.mark.parametrize("timeframe", ["5m", "1d"])
def test_stage1_defaults_put_massive_between_its_first_file_and_the_alpaca_seam(timeframe):
    plan = _plan(1, timeframe, _defaults())
    parse_plan(plan)
    assert plan["seam"] == "2003-09-10"
    assert [
        (d["valid_from"], d["valid_to"], d["primary"], d.get("fallback")) for d in plan["defaults"]
    ] == [
        ("1990-01-01", "2003-09-10", "ibkr", None),
        ("2003-09-10", "2016-01-04", "massive", None),
        ("2016-01-04", None, "alpaca", "ibkr"),
    ]
    assert plan["retire_default_ids"] == ["d-new", "d-old"]


def test_stage1_gap_names_keep_ibkr_inside_the_massive_span_only():
    plan = _plan(1, "5m", _defaults())
    assert _rows(plan, "AAL") == [("2003-09-10", "2013-12-09", "ibkr")]
    assert _rows(plan, "A") == [("2003-09-10", "2016-01-04", "ibkr")]
    assert _rows(plan, "LATE") == [("2003-09-10", "2016-01-04", "ibkr")]  # merged, clipped


def test_stage2_cuts_gap_spans_at_2016_and_keeps_ibkr_only_for_names_no_vendor_serves():
    plan = _plan(2, "5m", _defaults())
    parse_plan(plan)
    assert plan["seam"] == "2003-09-10"
    assert [(d["valid_from"], d["valid_to"], d["primary"]) for d in plan["defaults"]] == [
        ("1990-01-01", "2003-09-10", "ibkr"),
        ("2003-09-10", "2026-11-10", "massive"),
        ("2026-11-10", None, "alpaca"),
    ]
    assert all(d.get("fallback") is None for d in plan["defaults"])
    assert _rows(plan, "LATE") == [
        ("2003-09-10", "2016-01-04", "ibkr"),
        ("2016-01-04", "2020-01-01", "alpaca"),
    ]
    assert _rows(plan, "ES") == [
        ("2003-09-10", "2016-01-04", "ibkr"),
        ("2016-01-04", "2026-11-10", "ibkr"),
    ]


def test_stage1_keeps_every_live_symbol_row_beside_the_new_gap_rows():
    live = [
        *_defaults(),
        _ibkr_row("BHP", date(2016, 1, 4), date(2022, 6, 2), "p-bhp"),
        _ibkr_row("AAL", date(2016, 1, 4), date(2017, 2, 2), "p-aal"),
    ]
    plan = _plan(1, "1d", live)
    parse_plan(plan)
    assert [k["symbol"] for k in plan["keep_symbol_rows"]] == ["BHP", "AAL"]
    assert plan["retire_symbol_rows"] == []
    assert _rows(plan, "AAL") == [("2003-09-10", "2013-12-09", "ibkr")]


def test_a_kept_row_overlapping_a_new_row_of_its_name_is_refused():
    live = [*_defaults(), _ibkr_row("AAL", date(2010, 1, 4), date(2017, 2, 2), "p-aal")]
    with pytest.raises(ValueError, match="would overlap"):
        parse_plan(_plan(1, "1d", live))


def test_stage2_retires_every_live_symbol_row_and_names_each():
    live = [
        LiveRow("s1", None, date(1990, 1, 1), date(2003, 9, 10), "ibkr", None, "s1", {}),
        LiveRow("s2", None, date(2003, 9, 10), date(2016, 1, 4), "massive", None, "s1", {}),
        LiveRow("s3", None, date(2016, 1, 4), None, "alpaca", "ibkr", "s1", {}),
        _ibkr_row("BHP", date(2016, 1, 4), date(2022, 6, 2), "p-bhp"),
        _ibkr_row("AAL", date(2003, 9, 10), date(2013, 12, 9), "p-aal-gap"),
    ]
    plan = _plan(2, "1d", live)
    parse_plan(plan)
    assert plan["keep_symbol_rows"] == []
    assert {(r["symbol"], r["disposition"]) for r in plan["retire_symbol_rows"]} == {
        ("BHP", "superseded_by_default"),
        ("AAL", "replaced"),
    }
    assert plan["retire_default_ids"] == ["s1", "s2", "s3"]


def test_through_needed_is_the_latest_symbol_row_end():
    plan = build_plan(stage=1, timeframe="1d", live=_defaults(), gaps=_GAPS, gap_list=_GAP)
    assert through_needed(plan) == date(2016, 1, 4)
    stage2 = build_plan(stage=2, timeframe="1d", live=_defaults(), gaps=_GAPS, gap_list=_GAP)
    assert through_needed(stage2) == date(2026, 11, 10)


def test_stage1_refuses_an_unexpected_live_open_default():
    live = [LiveRow("d", None, date(1990, 1, 1), None, "ibkr", None, "seed", {})]
    with pytest.raises(ValueError, match="live open default"):
        build_plan(stage=1, timeframe="5m", live=live, gaps=(), gap_list=_GAP)


def test_a_gap_span_outside_the_massive_span_adds_nothing():
    gaps = [GapRow("OLD", "span", "x", date(1995, 1, 1), date(2003, 9, 10))]
    assert incumbent_rows(gaps, 1, date(2026, 11, 10), {}) == []


def test_read_gap_list_parses_both_scopes(tmp_path):
    path = tmp_path / "gap_list.csv"
    path.write_text(
        "symbol,scope,reason,valid_from,valid_to,detail\n"
        'A,instrument,event_chain_head_mismatch,,,"{}"\n'
        'AAL,span,before_first_event,2003-09-10,2013-12-09,"{}"\n'
    )
    assert read_gap_list(path) == [
        GapRow("A", "instrument", "event_chain_head_mismatch", None, None),
        GapRow("AAL", "span", "before_first_event", date(2003, 9, 10), date(2013, 12, 9)),
    ]
