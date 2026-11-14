"""The ticker-entity map writer's --documentary mode (design 8c, 2026-11-14): pure tests."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from services.ticker_entity_map_writer import (
    DocPlacement,
    GapRow,
    NewSpan,
    OldSpan,
    WitnessRegion,
    check_pinned_map,
    plan_documentary_map,
    read_doc_placements,
    reconcile_coverage,
    refuse_install_path,
    render_documentary_map,
    write_map_files,
)

D = date.fromisoformat
OPEN = date.max
PSHA = "p" * 8


def _old(symbol, ticker, start, end=None, figi="BBG1"):
    return OldSpan(symbol, ticker, D(start), D(end) if end else OPEN, figi, "raw", "{}")


def _region(symbol, start, end, decision="placed", sessions=0):
    return WitnessRegion(symbol, D(start), D(end), decision, sessions)


def _place(symbol, ticker, start, end, sessions):
    return DocPlacement(symbol, ticker, D(start), D(end), sessions, "before_first_event",
                        "cik_and_share_class_figi_same", "agrees", "")  # fmt: skip


def _held(result, symbol):
    return sorted((s.ticker, s.start.isoformat(), _iso(s.end)) for s in result.spans
                  if s.symbol == symbol)  # fmt: skip


def _iso(d):
    return "" if d == OPEN else d.isoformat()


OLD = [
    _old("LUMN", "LUMN", "2003-09-10", "2021-01-22"),
    _old("LUMN", "LUMN", "2021-01-22"),
    _old("QQQ", "QQQ", "2003-09-10", "2018-06-04", "BBG2"),
    _old("QQQ", "QQQ", "2018-06-04", None, "BBG2"),
    _old("PIPR", "PIPR", "2003-12-19", "2026-03-24", "BBG3"),
    _old("RGA", "RGA", "2003-09-10", "2008-11-26", "BBG4"),
    _old("ZZZ", "ZZZ", "2010-01-04", None, "BBG5"),
]
REGIONS = [
    _region("LUMN", "2003-09-10", "2020-09-18", "placed", 4286),
    _region("QQQ", "2004-12-01", "2011-03-23", "placed", 1588),
    _region("PIPR", "2003-12-19", "2020-01-06", "placed_partial", 8),
    _region("RGA", "2008-09-15", "2008-11-26", "ambiguous_sessions", 0),
]
PLACEMENTS = [
    _place("LUMN", "CTL", "2003-09-10", "2020-09-18", 4286),
    _place("QQQ", "QQQQ", "2004-12-01", "2011-03-23", 1588),
    _place("PIPR", "PJCw", "2003-12-19", "2004-01-01", 8),
]
GAPS = [
    GapRow("A", "instrument", "event_chain_head_mismatch", None, None, "{}"),
    GapRow("QQQ", "span", "before_first_event", D("2003-09-10"), D("2004-12-02"), "{}"),
]


def _plan(old=OLD, gaps=GAPS, regions=REGIONS, placements=PLACEMENTS):
    return plan_documentary_map(old, gaps, regions, placements, PSHA)


def test_a_rename_splits_the_span_at_the_ticker_tape():
    result = _plan()
    # LUMN: CTL to the day before LUMN's own tape (2020-09-17 is the last CTL session)
    assert _held(result, "LUMN") == [
        ("CTL", "2003-09-10", "2020-09-18"),
        ("LUMN", "2020-09-18", "2021-01-22"),
        ("LUMN", "2021-01-22", ""),
    ]
    # QQQ: the trust is QQQ before 2004-12-01, QQQQ 2004-12-01 to 2011-03-22, QQQ again after
    assert _held(result, "QQQ") == [
        ("QQQ", "2003-09-10", "2004-12-01"),
        ("QQQ", "2011-03-23", "2018-06-04"),
        ("QQQ", "2018-06-04", ""),
        ("QQQQ", "2004-12-01", "2011-03-23"),
    ]
    assert not any(
        s.symbol == "QQQ" and s.ticker == "QQQ" and s.start < D("2011-03-22") < s.end
        for s in result.spans
    )


def test_unplaced_rows_stay_unplaced_and_a_partial_span_lists_what_it_cut():
    result = _plan()
    assert _held(result, "RGA") == [("RGA", "2003-09-10", "2008-11-26")]  # left as it was
    assert _held(result, "PIPR") == [("PIPR", "2020-01-06", "2026-03-24"), ("PJCw", "2003-12-19", "2004-01-01")]  # fmt: skip
    listed = [g for g in result.gaps if g.reason == "identity_unplaced"]
    assert [(g.symbol, g.start, g.end) for g in listed] == [
        ("PIPR", D("2004-01-01"), D("2020-01-06"))
    ]
    assert _held(result, "ZZZ") == [("ZZZ", "2010-01-04", "")]


def test_a_gap_row_is_cut_by_a_placement_and_instrument_rows_pass_through():
    result = _plan()
    rows = {(g.symbol, g.start, g.end) for g in result.gaps}
    assert ("A", None, None) in rows
    assert ("QQQ", None, None) not in rows  # 2003-09-10..2004-12-02 minus the QQQQ placement
    assert ("QQQ", D("2003-09-10"), D("2004-12-01")) in rows


def test_every_input_span_gap_row_and_placement_is_accounted():
    result = _plan()
    kinds = [r["kind"] for r in result.accounting]
    assert kinds.count("span") == len(OLD)
    assert kinds.count("placement") == len(PLACEMENTS)
    assert sum(
        r["kind"] == "gap" and r["disposition"] != "added" for r in result.accounting
    ) == len(GAPS)
    by = {(r["symbol"], r["valid_from"]): r["disposition"] for r in result.accounting
          if r["kind"] == "span"}  # fmt: skip
    assert by[("QQQ", "2003-09-10")] == "split"
    assert by[("LUMN", "2003-09-10")] == "clipped"
    assert by[("ZZZ", "2010-01-04")] == "kept"


def test_an_old_span_inside_a_placed_witness_span_is_removed_with_its_reason():
    old = [_old("AAA", "AAB", "2005-01-03", "2005-02-01"), _old("AAA", "AAA", "2005-02-01")]
    result = _plan(old, [], [_region("AAA", "2005-01-03", "2005-02-01", "placed", 20)],
                   [_place("AAA", "AAA", "2005-01-03", "2005-02-01", 20)])  # fmt: skip
    removed = [r for r in result.accounting if r["disposition"] == "removed"]
    assert [(r["symbol"], r["ticker"]) for r in removed] == [("AAA", "AAB")]
    assert removed[0]["reason"]


def test_the_plan_is_deterministic_and_idempotent_on_its_own_output():
    first = _plan()
    again = _plan()
    assert first == again
    as_old = [OldSpan(s.symbol, s.ticker, s.start, s.end, s.composite_figi, s.reference_raw_id,
                      s.evidence) for s in first.spans]  # fmt: skip
    second = plan_documentary_map(as_old, first.gaps, REGIONS, PLACEMENTS, PSHA)
    assert _keys(second.spans) == _keys(first.spans)
    assert second.gaps == first.gaps


def _keys(spans: list[NewSpan]):
    return [(s.symbol, s.ticker, s.start, s.end) for s in spans]


def test_render_is_bit_identical_sorted_and_has_no_clock():
    old = sorted(OLD, key=lambda s: (s.symbol, s.start, s.ticker))
    name1, files1 = render_documentary_map(old, _plan(), {"k": "v"}, None, "20261114")
    name2, files2 = render_documentary_map(old, _plan(), {"k": "v"}, None, "20261114")
    assert (name1, files1) == (name2, files2)
    assert name1 == f"20261114_{hashlib.sha256(files1['gap_list.csv']).hexdigest()[:12]}"
    lines = files1["spans.csv"].decode().splitlines()[1:]
    assert lines == sorted(
        lines, key=lambda line: (line.split(",")[0], line.split(",")[2], line.split(",")[1])
    )
    diff = json.loads(files1["map_diff.json"])["diff"]
    assert diff["sessions_newly_covered"] == 4286 + 1588 + 8
    assert diff["old_spans_by_disposition"]["split"] == 1


def test_a_placement_outside_every_witness_span_or_in_an_unplaced_one_refuses():
    with pytest.raises(ValueError, match="not one"):
        _plan(placements=[*PLACEMENTS, _place("LUMN", "CTL", "2021-02-01", "2021-02-03", 1)])
    with pytest.raises(ValueError, match="ambiguous_sessions"):
        _plan(placements=[*PLACEMENTS, _place("RGA", "RGA", "2008-09-15", "2008-09-16", 1)])
    with pytest.raises(ValueError, match="sessions"):
        _plan(placements=[PLACEMENTS[0], PLACEMENTS[1], _place("PIPR", "PJCw", "2003-12-19", "2004-01-01", 9)])  # fmt: skip
    with pytest.raises(ValueError, match="with 0 placements"):
        _plan(placements=PLACEMENTS[:2])


def test_a_ticker_held_by_another_name_over_a_placement_refuses():
    rival = [*OLD, _old("OTH", "CTL", "2010-01-04", "2011-01-03", "BBG9")]
    with pytest.raises(RuntimeError, match="ticker CTL held by"):
        _plan(old=rival)


def test_a_placement_for_a_name_without_a_composite_figi_refuses():
    with pytest.raises(ValueError, match="no composite FIGI"):
        _plan(old=[s for s in OLD if s.symbol != "QQQ"])


def test_a_placements_file_with_another_sha_or_another_pinned_map_refuses():
    data = b"symbol,file_ticker,start,end,sessions,reason,documentary_identity,corroboration,lead_read\n"
    with pytest.raises(ValueError, match="not the pinned"):
        read_doc_placements(data, "0" * 64)
    assert read_doc_placements(data, hashlib.sha256(data).hexdigest()) == []
    gap = b"symbol,scope\r\nA,instrument\r\n"
    digest = hashlib.sha256(gap).hexdigest()[:12]
    check_pinned_map(f"20261113_{digest}", gap, digest)
    with pytest.raises(ValueError, match="pinned to map digest"):
        check_pinned_map(f"20261113_{digest}", gap, "000000000000")
    with pytest.raises(ValueError, match="holds a gap list"):
        check_pinned_map("20261113_000000000000", gap, digest)


def test_the_output_never_lands_under_the_live_map_root(tmp_path: Path):
    root = tmp_path / "data" / "ticker_entity_map"
    with pytest.raises(ValueError, match="scratch"):
        refuse_install_path(root / "20261114_x", root)
    refuse_install_path(tmp_path / "scratch", root)
    write_map_files(tmp_path / "scratch" / "m", {"a.csv": b"1"})
    write_map_files(tmp_path / "scratch" / "m", {"a.csv": b"1"})  # same bytes: fine
    with pytest.raises(RuntimeError, match="other bytes"):
        write_map_files(tmp_path / "scratch" / "m", {"a.csv": b"2"})


def test_reconciliation_counts_rows_held_by_a_new_span_of_the_name_and_ticker():
    spans = _plan().spans
    rows = {"1d": [("LUMN", "2010-01-04", "CTL"), ("LUMN", "2010-01-04", "LUMN")], "5m": []}
    out = reconcile_coverage(spans, rows, {"1d": {"map_gap_rows": 2, "covered": 1},
                                           "5m": {"map_gap_rows": 0, "covered": 0}})  # fmt: skip
    assert out["1d"]["covered"] == 1 and out["1d"]["reconciles"] and out["5m"]["reconciles"]
    bad = reconcile_coverage(spans, rows, {"1d": {"map_gap_rows": 2, "covered": 2},
                                           "5m": {"map_gap_rows": 0, "covered": 0}})  # fmt: skip
    assert not bad["1d"]["reconciles"]


def test_a_name_wide_undated_gap_row_does_not_hide_a_partial_spans_lost_coverage():
    wide = GapRow("PIPR", "instrument", "event_chain_head_mismatch", None, None, "{}")
    result = _plan(gaps=[*GAPS, wide])
    listed = [(g.symbol, g.start, g.end) for g in result.gaps if g.reason == "identity_unplaced"]
    assert listed == [("PIPR", D("2004-01-01"), D("2020-01-06"))]


def test_a_dated_gap_row_over_the_cut_still_records_it_and_one_elsewhere_does_not():
    over = GapRow("PIPR", "span", "before_first_event", D("2004-01-01"), D("2010-01-04"), "{}")
    elsewhere = GapRow("PIPR", "span", "after_last_event", D("2025-01-01"), D("2026-01-01"), "{}")
    result = _plan(gaps=[*GAPS, over, elsewhere])
    listed = [(g.start, g.end) for g in result.gaps if g.reason == "identity_unplaced"]
    assert listed == [(D("2010-01-04"), D("2020-01-06"))]  # the dated row already covers the rest
