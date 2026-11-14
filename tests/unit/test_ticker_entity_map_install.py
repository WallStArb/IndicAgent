"""The ticker-entity map writer's --install and --rollback runs (design 8c, 2026-11-14): pure tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from services.ticker_entity_map_writer import (
    DocPlacement,
    HistoryRow,
    InstallRefused,
    NewSpan,
    OldSpan,
    ReconcileInputs,
    WitnessRegion,
    canonical_json,
    check_install_target,
    content_sha256,
    install_evidence,
    manifest_sha256,
    massive_load_pids,
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


def _installed(files, plan, lineage=True):
    figi = {s.symbol: s.composite_figi for s in OLD}
    return [
        OldSpan(
            k[0], k[1], k[2], k[3], figi[k[0]], "raw",
            canonical_json({"map_install": {"map_digest": files.digest}} if lineage else {}),
        )
        for k in sorted(plan.new_keys)
    ]  # fmt: skip


def test_a_second_install_over_the_first_is_a_no_op(files):
    first = plan_install(files, OLD, UNTOUCHED)
    again = plan_install(files, _installed(files, first), UNTOUCHED)
    assert (again.status, again.retire, again.insert) == ("already_installed", (), ())


def test_live_rows_with_the_maps_dates_but_not_its_lineage_or_identity_are_not_a_no_op(files):
    first = plan_install(files, OLD, UNTOUCHED)
    with pytest.raises(InstallRefused, match="not this map"):
        plan_install(files, _installed(files, first, lineage=False), UNTOUCHED)
    wrong = [OldSpan(s.symbol, s.ticker, s.start, s.end, "OTHER", "raw", s.evidence)
             for s in _installed(files, first)]  # fmt: skip
    with pytest.raises(InstallRefused, match="not this map"):
        plan_install(files, wrong, UNTOUCHED)


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


LOST_1D = (
    b"symbol,session,file_ticker,class\nLUMN,2010-01-04,CTL,map_gap\nLUMN,2010-01-05,X,other\n"
)
LOST_5M = b"symbol,session,alt_ticker,class\n"
COVERAGE = json.dumps(EXPECTED).encode()
HIDDEN = ("CACI:2009-05-04:CACI",)


def _inputs(hidden=()):
    return ReconcileInputs(LOST_1D, LOST_5M, COVERAGE, tuple(sorted(hidden)))


def _build_pinned(tmp_path: Path, reconcile: ReconcileInputs) -> Path:
    result = plan_documentary_map(OLD, [], REGIONS, PLACEMENTS, "p" * 8)
    reconciliation = reconcile_coverage(result.spans, LOST, EXPECTED)
    name, files = render_documentary_map(
        OLD, result, {"x": 1, **reconcile.pins()}, reconciliation, "20261114"
    )
    write_map_files(tmp_path / name, files)
    return tmp_path / name


def test_the_manifest_pin_covers_every_file_and_the_directory_name_is_unchanged(tmp_path):
    path = _build_pinned(tmp_path, _inputs())
    files = read_map_dir(path)
    assert files.manifest_sha256 == manifest_sha256(files.raw)
    assert path.name == f"20261114_{files.diff['gap_list_sha256'][:12]}"
    files.require_pins(files.manifest_sha256, _inputs())
    with pytest.raises(InstallRefused, match="--install-spans-sha256"):
        files.require_pins("0" * 64, _inputs())


def test_spans_edited_together_with_their_recorded_hash_still_fail_the_pin(tmp_path):
    path = _build_pinned(tmp_path, _inputs())
    pin = read_map_dir(path).manifest_sha256
    spans = (path / "spans.csv").read_bytes().replace(b"CTL", b"CTX")
    (path / "spans.csv").write_bytes(spans)
    doc = json.loads((path / "map_diff.json").read_text())
    doc["spans_sha256"] = hashlib.sha256(spans).hexdigest()
    (path / "map_diff.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    edited = read_map_dir(path)  # the map is internally consistent again
    with pytest.raises(InstallRefused, match="--install-spans-sha256"):
        edited.require_pins(pin, _inputs())


@pytest.mark.parametrize("name", ["span_accounting.csv", "map_diff.json"])
def test_the_accounting_and_the_diff_are_pinned_too(tmp_path, name):
    path = _build_pinned(tmp_path, _inputs())
    pin = read_map_dir(path).manifest_sha256
    (path / name).write_bytes((path / name).read_bytes() + b" ")
    with pytest.raises(InstallRefused, match="--install-spans-sha256"):
        read_map_dir(path).require_pins(pin, _inputs())


def test_reconciliation_inputs_must_be_the_ones_the_map_recorded(tmp_path):
    files = read_map_dir(_build_pinned(tmp_path, _inputs()))
    pin = files.manifest_sha256
    files.require_pins(pin, _inputs())
    changed = ReconcileInputs(LOST_1D + b"LUMN,2010-01-06,CTL,map_gap\n", LOST_5M, COVERAGE, ())
    with pytest.raises(InstallRefused, match="lost_1d_sha256.*rebuild"):
        files.require_pins(pin, changed)
    with pytest.raises(InstallRefused, match="coverage_summary_sha256"):
        files.require_pins(pin, ReconcileInputs(LOST_1D, LOST_5M, COVERAGE + b" ", ()))
    with pytest.raises(InstallRefused, match="hidden_1d"):
        files.require_pins(pin, _inputs(HIDDEN))


def test_a_map_built_before_the_input_pins_refuses_with_a_rebuild_message(files):
    with pytest.raises(InstallRefused, match="rebuild the map"):
        files.require_pins(files.manifest_sha256, _inputs())


def test_the_inputs_are_read_once_as_bytes_and_hidden_rows_join_the_1d_rows(tmp_path):
    for name, data in (("a", LOST_1D), ("b", LOST_5M), ("c", COVERAGE)):
        (tmp_path / name).write_bytes(data)

    class Args:
        lost_1d, lost_5m, coverage_summary = (tmp_path / n for n in "abc")
        hidden_1d = ["Z:2015-08-17:Z", "CACI:2009-05-04:CACI"]

    got = ReconcileInputs.read(Args)  # type: ignore[arg-type]
    assert got.rows() == {
        "1d": [("LUMN", "2010-01-04", "CTL"), ("CACI", "2009-05-04", "CACI"),
               ("Z", "2015-08-17", "Z")],
        "5m": [],
    }  # fmt: skip
    assert got.pins()["hidden_1d"] == ["CACI:2009-05-04:CACI", "Z:2015-08-17:Z"]
    assert got.expected() == EXPECTED


def test_a_visible_massive_loader_process_is_found(tmp_path):
    script = tmp_path / "ops_massive_load.py"
    script.write_text("import time; time.sleep(30)")
    loader = subprocess.Popen([sys.executable, str(script)])
    bystander = subprocess.Popen(["sleep", "30", script.name])  # names the file, runs no loader
    try:
        found = massive_load_pids()
        assert loader.pid in found and bystander.pid not in found
    finally:
        for proc in (loader, bystander):
            proc.kill()
            proc.wait()
    assert loader.pid not in massive_load_pids()
