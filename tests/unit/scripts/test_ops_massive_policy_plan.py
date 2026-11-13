"""The Massive switch plan builder without IBKR (todo 600 step 7): pure tests, no database."""

from __future__ import annotations

import json
from datetime import date

import pytest

from scripts.ops.bars.ops_massive_policy_plan import (
    GapRow,
    LiveRow,
    archive_end_of,
    build_plan,
    build_restore_plan,
    ibkr_rows,
    read_gap_list,
    read_snapshot,
    snapshot_rows,
    through_needed,
)
from scripts.ops.bars.ops_source_policy import parse_plan

_GAP = {"path": "data/ticker_entity_map/x/gap_list.csv", "sha256": "ab"}
_MANIFEST = {"path": "data/massive/manifest/manifest.jsonl", "sha256": "cd"}
_FP = {"through": "2026-11-10", "series": {"massive/sip_flat": {"rows": 1}}}
_END = date(2026, 11, 10)
_GAPS = [
    GapRow("AAL", "span", "before_first_event", date(2003, 9, 10), date(2013, 12, 9)),
    GapRow("A", "instrument", "event_chain_head_mismatch", None, None),
]


def _live():
    """Today's live 1d/5m shape: the IBKR default before 2016, Alpaca with the IBKR fallback after
    it, and one D-191-Q IBKR symbol row."""
    return [
        LiveRow("d-old", None, date(1990, 1, 1), date(2016, 1, 4), "ibkr", None, "seed", {}),
        LiveRow("d-new", None, date(2016, 1, 4), None, "alpaca", "ibkr", "seed", {}),
        LiveRow(
            "p-bhp", "BHP", date(2016, 1, 4), date(2022, 6, 2), "ibkr", None, "D-191-Q", {"c": 1}
        ),
    ]


def _plan(timeframe, live=None):
    plan = build_plan(
        timeframe=timeframe,
        live=live if live is not None else _live(),
        gaps=_GAPS,
        gap_list=_GAP,
        archive_end=_END,
        manifest=_MANIFEST,
    )
    if timeframe == "1d":
        plan["raw_fingerprint"] = _FP
    return plan


def _spans(plan):
    return [
        (r["valid_from"], r["valid_to"], r["primary"], r.get("fallback")) for r in plan["defaults"]
    ]


@pytest.mark.parametrize("timeframe", ["5m", "1d"])
def test_massive_serves_to_the_archive_end_then_alpaca_with_no_fallback(timeframe):
    plan = _plan(timeframe)
    parse_plan(plan)
    assert _spans(plan) == [
        ("1990-01-01", "2026-11-10", "massive", None),
        ("2026-11-10", None, "alpaca", None),
    ]
    assert plan["seam"] == "2026-11-10"
    assert plan["evidence"]["archive_end"] == "2026-11-10"


@pytest.mark.parametrize("timeframe", ["5m", "1d", "1m", "4h"])
def test_the_plan_leaves_no_ibkr_row_live(timeframe):
    plan = _plan(timeframe)
    assert ibkr_rows(plan) == []
    assert plan["symbol_rows"] == [] and plan["keep_symbol_rows"] == []
    assert plan["retire_default_ids"] == ["d-new", "d-old"]
    assert [(r["policy_id"], r["disposition"]) for r in plan["retire_symbol_rows"]] == [
        ("p-bhp", "superseded_by_default")
    ]


def test_ibkr_rows_finds_a_primary_or_a_fallback():
    plan = {
        "defaults": [{"primary": "alpaca", "fallback": "ibkr"}],
        "symbol_rows": [{"primary": "ibkr"}],
        "keep_symbol_rows": [],
    }
    assert len(ibkr_rows(plan)) == 2


@pytest.mark.parametrize("timeframe", ["1m", "4h"])
def test_1m_and_4h_get_one_massive_default_that_serves_nothing(timeframe):
    live = [LiveRow("d", None, date(1990, 1, 1), date(2026, 10, 15), "ibkr", None, "seed", {})]
    plan = _plan(timeframe, live)
    parse_plan(plan)
    assert _spans(plan) == [("1990-01-01", None, "massive", None)]
    assert plan["seam"] == "1990-01-01" and plan["retire_default_ids"] == ["d"]


def test_the_gap_list_is_evidence_only():
    plan = _plan("1d")
    assert plan["evidence"]["gap_list"] == _GAP
    assert [g["symbol"] for g in plan["evidence"]["gap_spans"]] == ["AAL", "A"]
    assert "before 2003-09-10" in plan["evidence"]["coverage"]


def test_through_needed_is_the_seam_with_no_symbol_row():
    assert through_needed(_plan("1d")) == _END


def test_derived_timeframes_and_an_empty_policy_refuse():
    with pytest.raises(ValueError, match="no Massive switch plan"):
        _plan("15m")
    with pytest.raises(ValueError, match="no live default"):
        _plan("5m", live=[])


def test_the_archive_end_is_the_first_session_after_the_manifest_s_last_day():
    lines = [
        {"dataset": "minute", "key": "us_stocks_sip/minute_aggs_v1/2003/09/2003-09-10.csv.gz"},
        {"dataset": "day", "key": "us_stocks_sip/day_aggs_v1/2026/11/2026-11-09.csv.gz"},
    ]
    data = "".join(json.dumps(r) + "\n" for r in lines).encode()
    assert archive_end_of(data) == date(2026, 11, 10)
    friday = data.replace(b"2026-11-09", b"2026-11-06")
    assert archive_end_of(friday) == date(2026, 11, 9)  # over the weekend
    with pytest.raises(ValueError, match="empty"):
        archive_end_of(b"")


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


def _switched_live(plan):
    """The live policy after the switch apply, with new ids."""
    return [
        LiveRow(
            f"s-d{i}",
            None,
            date.fromisoformat(d["valid_from"]),
            date.fromisoformat(d["valid_to"]) if d["valid_to"] else None,
            d["primary"],
            d.get("fallback"),
            "switch",
            {},
        )
        for i, d in enumerate(plan["defaults"])
    ]


def test_restore_puts_the_pre_switch_policy_back_and_round_trips_the_snapshot():
    before = _live()
    snapshot = read_snapshot(snapshot_rows(before))
    assert snapshot == before
    live = _switched_live(_plan("1d"))  # the switch retired BHP's row
    plan = build_restore_plan(timeframe="1d", snapshot=snapshot, live=live, source="snap.json")
    plan["raw_fingerprint"] = _FP
    parse_plan(plan)
    assert _spans(plan) == [
        ("1990-01-01", "2016-01-04", "ibkr", None),
        ("2016-01-04", None, "alpaca", "ibkr"),
    ]
    assert plan["seam"] == "2016-01-04"
    assert plan["retire_default_ids"] == ["s-d0", "s-d1"]
    assert plan["symbol_rows"] == [
        {
            "symbol": "BHP",
            "valid_from": "2016-01-04",
            "valid_to": "2022-06-02",
            "primary": "ibkr",
            "fallback": None,
            "evidence": {"c": 1, "restored_from": "p-bhp"},
        }
    ]
    assert plan["retire_symbol_rows"] == [] and plan["keep_symbol_rows"] == []


def test_restore_refuses_a_snapshot_without_an_open_default():
    closed = [LiveRow("d", None, date(1990, 1, 1), date(2016, 1, 4), "ibkr", None, "x", {})]
    with pytest.raises(ValueError, match="open-ended default"):
        build_restore_plan(timeframe="5m", snapshot=closed, live=_live(), source="s")
