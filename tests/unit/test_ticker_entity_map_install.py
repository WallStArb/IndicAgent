"""The ticker-entity map writer's --install and --rollback runs (design 8c, 2026-11-14): pure tests."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from services.ticker_entity_map_writer import (
    DocPlacement,
    HistoryRow,
    InstallRefused,
    NewSpan,
    OldSpan,
    WitnessRegion,
    canonical_json,
    check_install_target,
    content_sha256,
    install_evidence,
    plan_documentary_map,
    plan_install,
    plan_rollback,
    read_map_dir,
    reconcile_coverage,
    render_documentary_map,
    require_reconciled,
    retire_reason,
    verify_balance,
    verify_install_reconciliation,
    write_map_files,
)

D = date.fromisoformat
OPEN = date.max
UNTOUCHED = ["RGA"]


def _old(symbol, ticker, start, end=None, figi="BBG1"):
    return OldSpan(symbol, ticker, D(start), D(end) if end else OPEN, figi, "raw", "{}")


OLD = [
    _old("LUMN", "LUMN", "2003-09-10", "2021-01-22"),
    _old("LUMN", "LUMN", "2021-01-22"),
    _old("ZZZ", "ZZZ", "2010-01-04", None, "BBG5"),
    _old("RGA", "RGA", "2003-09-10", "2008-11-26", "BBG4"),
]
REGIONS = [WitnessRegion("LUMN", D("2003-09-10"), D("2020-09-18"), "placed", 4286)]
PLACEMENTS = [
    DocPlacement("LUMN", "CTL", D("2003-09-10"), D("2020-09-18"), 4286, "before_first_event",
                 "cik_and_share_class_figi_same", "agrees", "")  # fmt: skip
]
LOST = {"1d": [("LUMN", "2010-01-04", "CTL")], "5m": []}
EXPECTED = {
    "1d": {"map_gap_rows": 1, "covered": 1},
    "5m": {"map_gap_rows": 0, "covered": 0},
}


def _build(tmp_path: Path, expected=EXPECTED) -> Path:
    result = plan_documentary_map(OLD, [], REGIONS, PLACEMENTS, "p" * 8)
    reconciliation = reconcile_coverage(result.spans, LOST, expected)
    name, files = render_documentary_map(OLD, result, {"x": 1}, reconciliation, "20261114")
    write_map_files(tmp_path / name, files)
    return tmp_path / name


@pytest.fixture
def files(tmp_path):
    return read_map_dir(_build(tmp_path))


def test_the_plan_retires_what_the_map_cut_and_inserts_what_it_adds(files):
    plan = plan_install(files, OLD, UNTOUCHED)
    assert plan.status == "install"
    assert [(k[0], k[2], d) for k, d in plan.retire] == [("LUMN", D("2003-09-10"), "clipped")]
    assert sorted((s.ticker, s.origin) for s in plan.insert) == [
        ("CTL", "placement"),
        ("LUMN", "clipped"),
    ]
    assert (plan.live_before, len(plan.retire), len(plan.insert), plan.live_after) == (4, 1, 2, 5)
    assert plan.live_before - len(plan.retire) + len(plan.insert) == plan.live_after
    assert plan.touched_symbols == {"LUMN"}


def test_live_spans_that_drifted_from_the_pinned_ones_refuse(files):
    with pytest.raises(InstallRefused, match="table moved since the map was built"):
        plan_install(files, [*OLD, _old("NEW", "NEW", "2020-01-02")], UNTOUCHED)
    with pytest.raises(InstallRefused, match="table moved"):
        plan_install(files, OLD[:-1], UNTOUCHED)


def test_a_plan_touching_a_name_that_must_stay_refuses(files):
    with pytest.raises(InstallRefused, match="must stay as they are"):
        plan_install(files, OLD, ["LUMN"])


def test_a_second_install_over_the_first_is_a_no_op(files):
    first = plan_install(files, OLD, UNTOUCHED)
    after = [OldSpan(k[0], k[1], k[2], k[3], "BBG1", "raw", "{}") for k in sorted(first.new_keys)]
    again = plan_install(files, after, UNTOUCHED)
    assert (again.status, again.retire, again.insert) == ("already_installed", (), ())


def test_a_row_balance_that_does_not_match_the_map_refuses(files):
    plan = plan_install(files, OLD, UNTOUCHED)
    verify_balance(plan, plan.new_keys)
    with pytest.raises(InstallRefused, match="row balance"):
        verify_balance(plan, list(plan.new_keys)[:-1])
    extra = [*plan.new_keys, ("X", "X", D("2020-01-02"), OPEN)]
    with pytest.raises(InstallRefused, match="1 extra"):
        verify_balance(plan, extra)


def test_a_map_whose_files_disagree_with_their_own_hashes_refuses(tmp_path):
    path = _build(tmp_path)
    (path / "spans.csv").write_bytes((path / "spans.csv").read_bytes() + b"\r\n")
    with pytest.raises(InstallRefused, match="spans_sha256"):
        read_map_dir(path)
    (tmp_path / "b").mkdir()
    other = _build(tmp_path / "b")
    (other / "extra.txt").write_text("x")
    with pytest.raises(InstallRefused, match="not part of a map version"):
        read_map_dir(other)


def test_a_span_diff_that_does_not_match_the_accounting_refuses(tmp_path):
    path = _build(tmp_path)
    doc = json.loads((path / "map_diff.json").read_text())
    doc["diff"]["span_rows_added"] += 1
    (path / "map_diff.json").write_text(json.dumps(doc))
    with pytest.raises(InstallRefused, match="does not reconcile"):
        plan_install(read_map_dir(path), OLD, UNTOUCHED)


def test_coverage_that_does_not_reconcile_refuses_the_install(tmp_path):
    bad = {"1d": {"map_gap_rows": 1, "covered": 0}, "5m": EXPECTED["5m"]}
    files = read_map_dir(_build(tmp_path, bad))
    assert files.diff["reconciliation"]["1d"]["reconciles"] is False
    with pytest.raises(InstallRefused, match="does not reconcile"):
        verify_install_reconciliation(files, LOST, bad)
    with pytest.raises(InstallRefused, match="does not reconcile"):
        require_reconciled(files.diff["reconciliation"])


def test_the_install_recomputes_the_reconciliation_rather_than_trusting_the_file(tmp_path):
    files = read_map_dir(_build(tmp_path))
    assert verify_install_reconciliation(files, LOST, EXPECTED)["1d"]["reconciles"]
    # the file says it reconciles; the lost rows handed in now do not agree with its spans
    lost = {"1d": [*LOST["1d"], ("LUMN", "2010-01-05", "OTHER")], "5m": []}
    expected = {"1d": {"map_gap_rows": 2, "covered": 2}, "5m": EXPECTED["5m"]}
    with pytest.raises(InstallRefused, match="does not reconcile"):
        verify_install_reconciliation(files, lost, expected)
    with pytest.raises(InstallRefused, match="not the one the map holds"):
        verify_install_reconciliation(
            files, {"1d": [], "5m": []}, {k: {"map_gap_rows": 0, "covered": 0} for k in LOST}
        )
    with pytest.raises(InstallRefused, match="no coverage reconciliation"):
        require_reconciled(None)


def test_install_evidence_adds_the_lineage_once():
    span = NewSpan("LUMN", "CTL", D("2003-09-10"), D("2020-09-18"), "placement", "B", "", '{"a":1}')
    out = json.loads(install_evidence(span, {"install_id": "i"}))
    assert out == {"a": 1, "map_install": {"install_id": "i", "origin": "placement"}}
    again = NewSpan("L", "C", D("2003-09-10"), OPEN, "clipped", "B", "r", canonical_json(out))
    with pytest.raises(InstallRefused, match="already holds"):
        install_evidence(again, {"install_id": "j"})


def test_the_install_directory_is_copied_once_and_never_over_other_content(tmp_path):
    raw = {"a.csv": b"1", "b.csv": b"2"}
    target = tmp_path / "20261114_abc"
    assert check_install_target(target, raw) is False
    write_map_files(target, raw)
    assert check_install_target(target, raw) is True
    (target / "a.csv").write_bytes(b"other")
    with pytest.raises(InstallRefused, match="other than this map"):
        check_install_target(target, raw)


def test_the_content_hash_ignores_row_order_and_ids():
    def row(sym, ev="{}"):
        return {"symbol": sym, "ticker": sym, "valid_from": D("2020-01-02"), "valid_to": None,
                "security_identifier_id": "s", "reference_raw_id": "r", "evidence": json.loads(ev),
                "ticker_event_id": sym + "-id"}  # fmt: skip

    a, b = row("A"), row("B")
    assert content_sha256([a, b]) == content_sha256([{**b, "ticker_event_id": "zz"}, a])
    assert content_sha256([a, b]) != content_sha256([a, row("B", '{"k":1}')])


def _history(install_id="i1", n_retired=1, n_inserted=2, later_retired=False):
    lineage = {"install_id": install_id, "map_digest": "d", "map_dir": "20261114_d",
               "pre_install_sha256": "pre", "rows_retired": n_retired,
               "rows_inserted": n_inserted}  # fmt: skip
    rows = [
        HistoryRow(
            f"old{i}",
            "sid",
            "LUMN",
            "LUMN",
            D("2003-09-10"),
            D("2021-01-22"),
            "raw",
            {},
            retire_reason(install_id, "d", "clipped"),
        )
        for i in range(n_retired)
    ]
    rows += [
        HistoryRow(f"new{i}", "sid", "LUMN", f"T{i}", D("2003-09-10"), None, "raw",
                   {"map_install": {**lineage, "origin": "clipped"}},
                   "ticker_map_rollback x" if later_retired and i == 0 else None)
        for i in range(n_inserted)
    ]  # fmt: skip
    return rows


def test_a_rollback_retires_the_inserted_rows_and_restores_copies_of_the_retired_ones():
    plan = plan_rollback("i1", _history())
    assert plan.retire_ids == ("new0", "new1")
    assert [r.ticker_event_id for r in plan.restore] == ["old0"]
    assert (plan.pre_install_sha256, plan.map_dir) == ("pre", "20261114_d")


def test_a_rollback_refuses_an_install_that_is_gone_rolled_back_or_built_upon():
    with pytest.raises(InstallRefused, match="no rows were inserted"):
        plan_rollback("nope", _history())
    with pytest.raises(InstallRefused, match="already rolled back, or a later change"):
        plan_rollback("i1", _history(later_retired=True))
    # rolled back already: the originals are retired by the install, the inserted rows are not live
    rolled = [r for r in _history() if r.ticker_event_id.startswith("old")]
    rolled += [
        HistoryRow(r.ticker_event_id, r.security_identifier_id, r.symbol, r.ticker, r.start, r.end,
                   r.reference_raw_id, r.evidence, "ticker_map_rollback i1: restores")
        for r in _history() if r.ticker_event_id.startswith("new")
    ]  # fmt: skip
    with pytest.raises(InstallRefused, match="already rolled back, or a later change"):
        plan_rollback("i1", rolled)
    with pytest.raises(InstallRefused, match="already rolled back"):
        plan_rollback("i1", _history(n_retired=1)[1:] + _history()[1:2])
