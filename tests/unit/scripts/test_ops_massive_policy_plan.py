"""The Massive switch plan builder (todo 600 step 7): pure tests, no database."""

from __future__ import annotations

from datetime import date

import pytest

from scripts.ops.bars.ops_massive_policy_plan import (
    GapRow,
    LiveRow,
    build_plan,
    build_restore_plan,
    incumbent_rows,
    read_gap_list,
    read_snapshot,
    snapshot_rows,
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


# --- the reverse plan (rollback; review 2026-11-11, finding 2) ---------------------------------


def _stage1_live(stage1_plan):
    """The live policy after the stage 1 apply, with new ids."""
    rows = [
        LiveRow(
            f"s1-d{i}",
            None,
            date.fromisoformat(d["valid_from"]),
            date.fromisoformat(d["valid_to"]) if d["valid_to"] else None,
            d["primary"],
            d.get("fallback"),
            "stage 1",
            {},
        )
        for i, d in enumerate(stage1_plan["defaults"])
    ]
    rows += [
        LiveRow(
            f"s1-r{i}",
            r["symbol"],
            date.fromisoformat(r["valid_from"]),
            date.fromisoformat(r["valid_to"]),
            r["primary"],
            None,
            "stage 1",
            r["evidence"],
        )
        for i, r in enumerate(stage1_plan["symbol_rows"])
    ]
    return rows


def test_restore_puts_the_pre_switch_policy_back_and_round_trips_the_snapshot():
    before = [*_defaults(), _ibkr_row("BHP", date(2016, 1, 4), date(2022, 6, 2), "p-bhp")]
    snapshot = read_snapshot(snapshot_rows(before))
    assert snapshot == before
    stage1 = _plan(1, "1d", before)
    live = [*_stage1_live(stage1), before[2]]  # BHP was kept by stage 1
    plan = build_restore_plan(timeframe="1d", snapshot=snapshot, live=live, source="snap.json")
    plan["raw_fingerprint"] = _FP
    parsed = parse_plan(plan)
    assert [
        (d["valid_from"], d["valid_to"], d["primary"], d["fallback"]) for d in plan["defaults"]
    ] == [
        ("1990-01-01", "2016-01-04", "ibkr", None),
        ("2016-01-04", None, "alpaca", "ibkr"),
    ]
    assert plan["seam"] == "2016-01-04"
    assert plan["retire_default_ids"] == ["s1-d0", "s1-d1", "s1-d2"]
    assert [k["policy_id"] for k in plan["keep_symbol_rows"]] == ["p-bhp"]
    assert {r["disposition"] for r in plan["retire_symbol_rows"]} == {"superseded_by_default"}
    assert len(plan["retire_symbol_rows"]) == len(stage1["symbol_rows"])
    assert plan["symbol_rows"] == [] and parsed.symbol_rows == ()


def test_restore_reinserts_a_snapshot_row_the_switch_retired():
    before = [*_defaults(), _ibkr_row("BHP", date(2016, 1, 4), date(2022, 6, 2), "p-bhp")]
    live = _stage1_live(_plan(1, "5m", _defaults()))  # BHP's row gone (stage 2 shape)
    plan = build_restore_plan(timeframe="5m", snapshot=before, live=live, source="s")
    parse_plan(plan)
    bhp = [r for r in plan["symbol_rows"] if r["symbol"] == "BHP"]
    assert bhp == [
        {
            "symbol": "BHP",
            "valid_from": "2016-01-04",
            "valid_to": "2022-06-02",
            "primary": "ibkr",
            "fallback": None,
            "evidence": {"class": "alpaca_differs", "restored_from": "p-bhp"},
        }
    ]


def test_restore_refuses_a_snapshot_without_an_open_default():
    closed = [LiveRow("d", None, date(1990, 1, 1), date(2016, 1, 4), "ibkr", None, "x", {})]
    with pytest.raises(ValueError, match="open-ended default"):
        build_restore_plan(timeframe="5m", snapshot=closed, live=_defaults(), source="s")


# ---- the 8a input (runbook A2 amendment 2026-11-13) ---------------------------------------------
import csv as _csv  # noqa: E402
import json as _json  # noqa: E402

from scripts.ops.bars import ops_massive_policy_plan as _mod  # noqa: E402

ERAS = list(range(2003, 2027))


def _out_dir(tmp_path, *, verdicts=None, stops=None, status="complete", eras=None, calibrated=None):
    """A synthetic 8a out dir: every era ok on both timeframes unless ``verdicts`` says
    {(era, tf): (verdict, reason)}; ``stops`` are the (era, tf) in the stop file."""
    verdicts = verdicts or {}
    (tmp_path / "summary.json").write_text(
        _json.dumps(
            {
                "status": status,
                "stages_requested": ["A", "B", "C"],
                "eras": eras if eras is not None else ERAS,
                "partition": {"status": "complete"},
            }
        )
    )
    (tmp_path / "stageC_stop_eras.json").write_text(
        _json.dumps({f"{e}/{tf}": "x" for (e, tf) in (stops or [])})
    )
    with (tmp_path / "stageC_era_tables.csv").open("w", newline="") as handle:
        w = _csv.DictWriter(handle, ["era", "timeframe", "verdict", "reasons", "calibrated_on"])
        w.writeheader()
        for era in ERAS:
            for tf in ("1d", "5m"):
                verdict, reason = verdicts.get((era, tf), ("ok", ""))
                w.writerow(
                    {
                        "era": era,
                        "timeframe": tf,
                        "verdict": verdict,
                        "reasons": reason,
                        "calibrated_on": calibrated or "2014,2015",
                    }
                )
    return tmp_path


def _defaults_of(tmp_path, timeframe, stage=1, **kw):
    checks = _mod.read_load_checks(_out_dir(tmp_path, **kw))
    live = _defaults()
    plan = _mod.build_plan(
        stage=stage, timeframe=timeframe, live=live, gaps=[], gap_list={}, checks=checks
    )
    return plan


def _spans(plan):
    return [(r["valid_from"], r["valid_to"], r["primary"]) for r in plan["defaults"]]


def test_an_all_ok_run_reproduces_the_single_massive_span(tmp_path):
    plan = _defaults_of(tmp_path, "5m")
    assert [s for s in _spans(plan) if s[2] == "massive"] == [
        ("2003-09-10", "2016-01-04", "massive")
    ]
    assert plan["evidence"]["load_checks"]["summary.json"]["sha256"]


def test_a_stop_at_the_first_era_keeps_the_incumbent_from_the_archive_start(tmp_path):
    plan = _defaults_of(
        tmp_path, "1d", verdicts={(2003, "1d"): ("stop", "x")}, stops=[(2003, "1d")]
    )
    assert _spans(plan)[:3] == [
        ("1990-01-01", "2003-09-10", "ibkr"),
        ("2003-09-10", "2004-01-01", "ibkr"),
        ("2004-01-01", "2016-01-04", "massive"),
    ]
    assert plan["seam"] == "2003-09-10"  # still a boundary of the new defaults


def test_a_stop_at_the_last_era_of_the_span_keeps_the_incumbent_to_the_seam(tmp_path):
    plan = _defaults_of(
        tmp_path, "1d", verdicts={(2015, "1d"): ("stop", "x")}, stops=[(2015, "1d")]
    )
    assert ("2015-01-01", "2016-01-04", "ibkr") in _spans(plan)
    assert ("2003-09-10", "2015-01-01", "massive") in _spans(plan)


def test_two_adjacent_stopped_eras_merge_into_one_incumbent_span(tmp_path):
    stops = [(2008, "1d"), (2009, "1d"), (2010, "1d")]
    plan = _defaults_of(tmp_path, "1d", verdicts={k: ("stop", "x") for k in stops}, stops=stops)
    assert ("2008-01-01", "2011-01-01", "ibkr") in _spans(plan)
    edges = [(e["seam"], e["from_source"], e["to_source"]) for e in plan["seam_edges"]]
    assert ("2008-01-01", "massive", "ibkr") in edges and ("2011-01-01", "ibkr", "massive") in edges


def test_a_stopped_1d_era_leaves_5m_massive(tmp_path):
    kw = dict(verdicts={(2010, "1d"): ("stop", "x")}, stops=[(2010, "1d")])
    one_d = _defaults_of(tmp_path, "1d", **kw)
    five_m = _defaults_of(tmp_path, "5m", **kw)
    assert ("2010-01-01", "2011-01-01", "ibkr") in _spans(one_d)
    assert [s for s in _spans(five_m) if s[2] != "massive"][0][2] == "ibkr"  # head and tail only
    assert ("2003-09-10", "2016-01-04", "massive") in _spans(five_m)


def test_the_source_table_maps_unresolved_close_definition_to_massive_and_the_rest_to_incumbent():
    s = _mod.source_of
    assert s("1d", "unresolved", ["close_definition_witnessed"]) == "massive"
    assert s("1d", "unresolved", ["close_convention"]) == "incumbent"
    assert s("5m", "no_detector", ["no_judged_names"]) == "massive"
    assert s("5m", "unresolved", ["thin_era"]) == "massive"
    assert s("1d", "stop", ["x"]) == "incumbent" and s("5m", "ok_convention", []) == "massive"
    with pytest.raises(ValueError, match="no source rule"):
        s("5m", "unresolved", ["something_new"])


def test_unresolved_1d_eras_split_by_reason(tmp_path):
    v = {
        (2005, "1d"): ("unresolved", "close_definition_witnessed"),
        (2009, "1d"): ("unresolved", "close_convention"),
    }
    plan = _defaults_of(tmp_path, "1d", verdicts=v)
    assert ("2009-01-01", "2010-01-01", "ibkr") in _spans(plan)
    assert not any(s[0] <= "2005-06-01" < s[1] and s[2] == "ibkr" for s in _spans(plan)[1:])


def test_stage2_stopped_eras_after_2016_keep_alpaca_and_one_straddling_span_is_cut(tmp_path):
    stops = [(2015, "1d"), (2016, "1d")]
    plan = _defaults_of(
        tmp_path, "1d", stage=2, verdicts={k: ("stop", "x") for k in stops}, stops=stops
    )
    got = _spans(plan)
    assert ("2015-01-01", "2016-01-04", "ibkr") in got and (
        "2016-01-04",
        "2017-01-01",
        "alpaca",
    ) in got


def test_a_partial_or_self_calibrated_or_short_run_refuses(tmp_path):
    with pytest.raises(ValueError, match="need complete"):
        _mod.read_load_checks(_out_dir(tmp_path, status="partial"))
    with pytest.raises(ValueError, match="self-calibrated"):
        _mod.read_load_checks(_out_dir(tmp_path, calibrated="self"))
    with pytest.raises(ValueError, match="not the full"):
        _mod.read_load_checks(_out_dir(tmp_path, eras=[2010, 2011]))


def test_an_unknown_timeframe_key_or_an_era_outside_the_archive_refuses(tmp_path):
    d = _out_dir(tmp_path)
    (d / "stageC_stop_eras.json").write_text(_json.dumps({"2010/15m": "x"}))
    with pytest.raises(ValueError, match="known timeframe"):
        _mod.read_load_checks(d)
    (d / "stageC_stop_eras.json").write_text(_json.dumps({"1999/1d": "x"}))
    with pytest.raises(ValueError, match="outside the archive"):
        _mod.read_load_checks(d)


def test_the_plan_validates_through_the_writers_parse_plan_and_lists_its_edges(tmp_path):
    stops = [(2008, "5m")]
    plan = _defaults_of(tmp_path, "5m", verdicts={(2008, "5m"): ("stop", "x")}, stops=stops)
    parse_plan(plan)
    assert {e["seam"] for e in plan["seam_edges"]} >= {"2008-01-01", "2009-01-01"}


def test_the_three_non_session_days_of_2016_are_no_era_of_their_own(tmp_path):
    plan = _defaults_of(
        tmp_path, "1d", verdicts={(2016, "1d"): ("stop", "x")}, stops=[(2016, "1d")]
    )
    assert ("2003-09-10", "2016-01-04", "massive") in _spans(plan)  # stage 1 ignores a 2016 stop
