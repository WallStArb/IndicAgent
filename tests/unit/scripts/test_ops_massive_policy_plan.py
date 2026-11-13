"""The Massive switch plan builder (todo 600 step 7): pure tests, no database."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date

import pytest

from scripts.ops.bars import ops_massive_policy_plan as mod
from scripts.ops.bars.ops_massive_policy_plan import (
    GapRow,
    LiveRow,
    LoadChecks,
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
ERAS = tuple(range(2003, 2027))
#: every era ok on both timeframes: the plan the builder made before the 8a input existed
_OK = LoadChecks(
    ERAS,
    {(e, tf): mod.MASSIVE for e in ERAS for tf in mod.TIMEFRAMES},
    frozenset(),
    {"stopped": [], "sole_source_exception": []},
)


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
    plan = build_plan(
        stage=stage, timeframe=timeframe, live=live, gaps=_GAPS, gap_list=_GAP, checks=_OK
    )
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
    plan = build_plan(
        stage=1, timeframe="1d", live=_defaults(), gaps=_GAPS, gap_list=_GAP, checks=_OK
    )
    assert through_needed(plan) == date(2016, 1, 4)
    stage2 = build_plan(
        stage=2, timeframe="1d", live=_defaults(), gaps=_GAPS, gap_list=_GAP, checks=_OK
    )
    assert through_needed(stage2) == date(2026, 11, 10)


def test_stage1_refuses_an_unexpected_live_open_default():
    live = [LiveRow("d", None, date(1990, 1, 1), None, "ibkr", None, "seed", {})]
    with pytest.raises(ValueError, match="live open default"):
        build_plan(stage=1, timeframe="5m", live=live, gaps=(), gap_list=_GAP, checks=_OK)


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
MANIFEST_LINES = [
    {"dataset": "minute", "key": "us_stocks_sip/minute_aggs_v1/2003/09/2003-09-10.csv.gz"},
    {"dataset": "day", "key": "us_stocks_sip/day_aggs_v1/2026/11/2026-11-09.csv.gz"},
]


def _out_dir(tmp_path, *, verdicts=None, stops=None, status="complete", eras=None, calibrated=None):
    """A synthetic 8a out dir and its manifest: every era ok on both timeframes unless
    ``verdicts`` says {(era, tf): (verdict, reason)}; ``stops`` are the stopped (era, tf), stop
    verdicts by default. Returns (out dir, manifest path)."""
    verdicts = dict(verdicts or {})
    for key in stops or []:
        verdicts.setdefault(key, ("stop", "x"))
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in MANIFEST_LINES))
    eras = list(eras if eras is not None else ERAS)
    stop_view = {f"{e}/{tf}": "x" for (e, tf) in (stops or [])}
    era_verdicts = {
        f"{e}/{tf}": verdicts.get((e, tf), ("ok", ""))[0] for e in ERAS for tf in ("1d", "5m")
    }
    summary = {
        "status": status,
        "stages_requested": ["A", "B", "C"],
        "eras": eras,
        "inputs": {"manifest.jsonl": hashlib.sha256(manifest.read_bytes()).hexdigest()},
        "partition": {"status": "complete"},
        "stage_c": {
            "eras": eras,
            "era_verdicts": era_verdicts,
            "stop_eras_all_sources": stop_view,
        },
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    (tmp_path / "stageC_stop_eras.json").write_text(json.dumps(stop_view))
    with (tmp_path / "stageC_era_tables.csv").open("w", newline="") as handle:
        w = csv.DictWriter(handle, ["era", "timeframe", "verdict", "reasons", "calibrated_on"])
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
    return tmp_path, manifest


def _checks(tmp_path, **kw):
    return mod.read_load_checks(*_out_dir(tmp_path, **kw))


def _plan_with(tmp_path, timeframe, stage=1, **kw):
    return build_plan(
        stage=stage,
        timeframe=timeframe,
        live=_defaults(),
        gaps=[],
        gap_list={},
        checks=_checks(tmp_path, **kw),
    )


def _spans(plan):
    return [(r["valid_from"], r["valid_to"], r["primary"]) for r in plan["defaults"]]


def _edges(plan):
    return [
        (e["seam"], e["from_source"], e["to_source"], e["incoming"]) for e in plan["seam_edges"]
    ]


def test_an_all_ok_run_reproduces_the_single_massive_span(tmp_path):
    plan = _plan_with(tmp_path, "5m")
    assert _spans(plan) == [
        ("1990-01-01", "2003-09-10", "ibkr"),
        ("2003-09-10", "2016-01-04", "massive"),
        ("2016-01-04", None, "alpaca"),
    ]
    pins = plan["evidence"]["load_checks"]
    assert (
        pins["summary.json"]["sha256"]
        == hashlib.sha256((tmp_path / "summary.json").read_bytes()).hexdigest()
    )
    assert pins["manifest"]["sha256"] and plan["evidence"]["sole_source_exception"] == []


def test_today_s_three_hand_witness_rows_come_out_of_the_incoming_rule(tmp_path):
    """Runbook D2 before the loop: 2016-01-04 1d and 5m on canonical, 2003-09-10 1d on IBKR raw;
    Part E: the archive end on Alpaca raw."""
    one_d, five_m = _plan_with(tmp_path, "1d"), _plan_with(tmp_path, "5m")
    assert _edges(one_d) == [
        ("2003-09-10", "ibkr", "massive", "raw:ibkr/smart_trades"),
        ("2016-01-04", "massive", "alpaca", "canonical"),
    ]
    assert ("2016-01-04", "massive", "alpaca", "canonical") in _edges(five_m)
    stage2 = _plan_with(tmp_path, "1d", stage=2)
    assert ("2026-11-10", "massive", "alpaca", "raw:alpaca/sip_rth") in _edges(stage2)


def test_a_stop_at_the_first_era_keeps_the_incumbent_from_the_archive_start(tmp_path):
    plan = _plan_with(tmp_path, "1d", stops=[(2003, "1d")])
    assert _spans(plan)[:3] == [
        ("1990-01-01", "2003-09-10", "ibkr"),
        ("2003-09-10", "2004-01-01", "ibkr"),
        ("2004-01-01", "2016-01-04", "massive"),
    ]
    assert plan["seam"] == "2003-09-10"  # still a boundary of the new defaults
    assert _edges(plan)[0] == ("2004-01-01", "ibkr", "massive", "canonical")


def test_a_stop_at_the_last_era_of_the_span_keeps_the_incumbent_to_the_seam(tmp_path):
    plan = _plan_with(tmp_path, "1d", stops=[(2015, "1d")])
    assert _spans(plan)[1:] == [
        ("2003-09-10", "2015-01-01", "massive"),
        ("2015-01-01", "2016-01-04", "ibkr"),
        ("2016-01-04", None, "alpaca"),
    ]


def test_the_2008_to_2013_1d_stop_is_one_ibkr_span_with_two_canonical_edges(tmp_path):
    """The first full run's shape (runbook A2): 1d 2008 to 2013 stopped, 5m untouched."""
    stops = [(e, "1d") for e in range(2008, 2014)]
    one_d = _plan_with(tmp_path, "1d", stops=stops)
    assert _spans(one_d)[1:4] == [
        ("2003-09-10", "2008-01-01", "massive"),
        ("2008-01-01", "2014-01-01", "ibkr"),
        ("2014-01-01", "2016-01-04", "massive"),
    ]
    assert _edges(one_d)[1:3] == [
        ("2008-01-01", "massive", "ibkr", "canonical"),
        ("2014-01-01", "ibkr", "massive", "canonical"),
    ]
    assert len(one_d["defaults"]) == len(one_d["seam_edges"]) + 1 == 5
    five_m = _plan_with(tmp_path, "5m", stops=stops)
    assert _spans(five_m)[1] == ("2003-09-10", "2016-01-04", "massive")
    assert len(five_m["defaults"]) == 3


def test_the_source_table_maps_unresolved_close_definition_to_massive_and_the_rest_to_incumbent():
    s = mod.source_of
    assert s("1d", "unresolved", ["close_definition_witnessed"]) == "massive"
    assert s("1d", "unresolved", ["close_convention"]) == "incumbent"
    assert s("5m", "no_detector", ["no_judged_names"]) == "massive"
    assert s("5m", "unresolved", ["thin_era"]) == "massive"
    assert s("5m", "ok_convention", []) == "massive"
    for verdict, reasons in (
        ("unresolved", ["something_new"]),
        ("stop", ["x"]),
        ("unresolved", ["thin_era", "price_level"]),  # a benign reason never hides another
    ):
        with pytest.raises(ValueError, match="no source rule"):
            s("5m", verdict, reasons)  # a stop is the stop set's, never the table's


def test_unresolved_1d_eras_split_by_reason(tmp_path):
    v = {
        (2005, "1d"): ("unresolved", "close_definition_witnessed"),
        (2009, "1d"): ("unresolved", "close_convention"),
    }
    plan = _plan_with(tmp_path, "1d", verdicts=v)
    assert _spans(plan)[1:4] == [
        ("2003-09-10", "2009-01-01", "massive"),
        ("2009-01-01", "2010-01-01", "ibkr"),
        ("2010-01-01", "2016-01-04", "massive"),
    ]


def test_stage2_a_stopped_2016_era_starts_at_the_seam_with_no_non_session_span(tmp_path):
    plan = _plan_with(tmp_path, "1d", stage=2, stops=[(2016, "1d")])
    assert _spans(plan)[1:4] == [
        ("2003-09-10", "2016-01-04", "massive"),
        ("2016-01-04", "2017-01-01", "alpaca"),
        ("2017-01-01", "2026-11-10", "massive"),
    ]
    assert [e[0] for e in _edges(plan)] == ["2003-09-10", "2016-01-04", "2017-01-01", "2026-11-10"]


def test_stage2_a_stop_straddling_2016_is_cut_at_the_seam(tmp_path):
    plan = _plan_with(tmp_path, "1d", stage=2, stops=[(2015, "1d"), (2016, "1d")])
    assert _spans(plan)[2:4] == [
        ("2015-01-01", "2016-01-04", "ibkr"),
        ("2016-01-04", "2017-01-01", "alpaca"),
    ]


def test_stage1_ignores_a_2016_stop(tmp_path):
    plan = _plan_with(tmp_path, "1d", stops=[(2016, "1d")])
    assert _spans(plan)[1] == ("2003-09-10", "2016-01-04", "massive")


def test_a_stopped_pre_2016_5m_era_is_a_listed_sole_source_exception(tmp_path):
    plan = _plan_with(tmp_path, "5m", stops=[(2008, "5m"), (2020, "5m")])
    assert ("2008-01-01", "2009-01-01", "ibkr") in _spans(plan)
    assert plan["evidence"]["sole_source_exception"] == ["2008/5m"]
    parse_plan(plan)
    one_d = _plan_with(tmp_path, "1d", stops=[(2008, "5m")])
    assert one_d["evidence"]["sole_source_exception"] == []


def test_a_partial_or_self_calibrated_or_short_run_refuses(tmp_path):
    with pytest.raises(ValueError, match="need complete"):
        _checks(tmp_path, status="partial")
    with pytest.raises(ValueError, match="self-calibrated"):
        _checks(tmp_path, calibrated="self")
    with pytest.raises(ValueError, match="not the archive's"):
        _checks(tmp_path, eras=list(range(2003, 2026)))


def test_the_eras_come_from_the_manifest_the_run_hashed(tmp_path):
    out, manifest = _out_dir(tmp_path)
    manifest.write_text(manifest.read_text() + json.dumps(MANIFEST_LINES[0]) + "\n")
    with pytest.raises(ValueError, match="another manifest"):
        mod.read_load_checks(out, manifest)
    out, manifest = _out_dir(tmp_path)
    for wrong in (date(2026, 11, 9), date(2026, 12, 1)):  # before it, or past Massive's data
        with pytest.raises(ValueError, match="not the first session"):
            mod.read_load_checks(out, manifest, wrong)
    assert mod.manifest_last_day(
        "".join(json.dumps(r) + "\n" for r in MANIFEST_LINES).encode()
    ) == date(2026, 11, 9)


def test_the_era_table_and_the_stop_file_must_match_the_summary(tmp_path):
    out, manifest = _out_dir(tmp_path, stops=[(2010, "1d")])
    (out / "stageC_stop_eras.json").write_text(json.dumps({}))
    with pytest.raises(ValueError, match="differs from the summary's stops"):
        mod.read_load_checks(out, manifest)
    out, manifest = _out_dir(tmp_path)
    table = (out / "stageC_era_tables.csv").read_text()
    (out / "stageC_era_tables.csv").write_text(table.replace("2010,1d,ok", "2010,1d,stop"))
    with pytest.raises(ValueError, match="verdict differs"):
        mod.read_load_checks(out, manifest)
    lines = table.splitlines()
    (out / "stageC_era_tables.csv").write_text("\n".join([*lines, lines[1]]) + "\n")
    with pytest.raises(ValueError, match="duplicate row"):
        mod.read_load_checks(out, manifest)


def test_a_stop_verdict_missing_from_the_stop_file_refuses(tmp_path):
    out, manifest = _out_dir(tmp_path, verdicts={(2010, "5m"): ("stop", "x")})
    with pytest.raises(ValueError, match="not in the stop file"):
        mod.read_load_checks(out, manifest)


def test_an_unknown_timeframe_key_or_an_era_outside_the_archive_refuses(tmp_path):
    out, manifest = _out_dir(tmp_path)
    summary = json.loads((out / "summary.json").read_text())
    for view, match in (({"2010/15m": "x"}, "known timeframe"), ({"1999/1d": "x"}, "exactly")):
        summary["stage_c"]["stop_eras_all_sources"] = view
        (out / "summary.json").write_text(json.dumps(summary))
        (out / "stageC_stop_eras.json").write_text(json.dumps(view))
        with pytest.raises(ValueError, match=match):
            mod.read_load_checks(out, manifest)


@pytest.mark.parametrize(
    "stops",
    [
        [],
        [(2003, "1d")],
        [(e, "1d") for e in range(2008, 2014)],
        [(2015, "1d")],
        [(2016, "1d")],
        [(2026, "1d")],
    ],
)
@pytest.mark.parametrize("stage", [1, 2])
def test_the_default_count_follows_from_the_seam_edges(tmp_path, stage, stops):
    """Runbook C1: defaults = edges + 1, plus one when the 2003 era is stopped."""
    plan = _plan_with(tmp_path, "1d", stage=stage, stops=stops)
    head_stopped = (2003, "1d") in stops
    assert len(plan["defaults"]) == len(plan["seam_edges"]) + 1 + head_stopped
    parse_plan({**plan, "raw_fingerprint": _FP})


def test_stage2_a_stopped_last_era_runs_on_into_the_open_alpaca_tail(tmp_path):
    plan = _plan_with(tmp_path, "1d", stage=2, stops=[(2026, "1d")])
    assert _spans(plan)[1:] == [
        ("2003-09-10", "2026-01-01", "massive"),
        ("2026-01-01", None, "alpaca"),
    ]
    assert _edges(plan)[-1] == ("2026-01-01", "massive", "alpaca", "canonical")


def test_a_stage_a_or_b_systemic_stop_refuses_the_plan(tmp_path):
    out, manifest = _out_dir(tmp_path)
    summary = json.loads((out / "summary.json").read_text())
    summary["systemic_verdicts"] = {"stage_c.price": "stop", "stage_a.units": "stop"}
    (out / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match=r"systemic stop \['stage_a.units'\]"):
        mod.read_load_checks(out, manifest)
