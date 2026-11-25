"""E18 selection command helpers (phase 187 plan 06)."""

import numpy as np

from scripts.research import select_books
from scripts.research.select_books import (
    battery_refusals,
    horizon_sessions,
    selection_refusals,
    split_missing_series,
    universe_matrix,
)

FAMILY = open("research/specs/family1_h26.yaml").read()
FAMILY10 = open("research/specs/family10_volume_shock_h5.yaml").read()
BOOK = open("research/specs/book_v1.yaml").read()


def test_universe_aligns_sessions_and_never_fills():
    rows = [
        {
            "sessions": np.array(["2020-01-02", "2020-01-03"], dtype="datetime64[D]"),
            "d_s": [1.0, 2.0],
        },
        {
            "sessions": np.array(["2020-01-03", "2020-01-06"], dtype="datetime64[D]"),
            "d_s": [3.0, 4.0],
        },
    ]
    calendar, matrix = universe_matrix(rows)
    assert [str(d) for d in calendar] == ["2020-01-02", "2020-01-03", "2020-01-06"]
    assert np.array_equal(
        matrix, np.array([[1.0, np.nan], [2.0, 3.0], [np.nan, 4.0]]), equal_nan=True
    )


def test_family_horizon_in_sessions():
    assert horizon_sessions(FAMILY, None) == 1  # 26 fifteen-minute rows = one session


def test_book_horizon_reads_its_first_family():
    seen = []

    def family_text(path):
        seen.append(path)
        return open(path).read()

    assert horizon_sessions(BOOK, family_text) >= 1
    assert seen and seen[0].startswith("research/specs/")


APR = {"alpha.selection.stepm.fwer": 0.05, "alpha.selection.stepm.block_mean_sessions": 20}
GOOD = {
    "schema": "stepm_null_battery_v1",
    "complete": True,
    "failures": [],
    "stepm_sha256": "abc",
    "studentize": "draw",
    "fwer": 0.05,
    "block_mean": 20.0,
    "sessions": 4000,
}


def test_a_complete_passing_battery_on_this_code_attests():
    assert battery_refusals(GOOD, APR, "abc") == []


def test_battery_gates_refuse_every_weaker_record():
    assert battery_refusals(None, APR, "abc") == ["no StepM null-battery record (--battery)"]
    for change, word in (
        ({"complete": False}, "only some cells"),
        ({"failures": ["slot_effects"]}, "fails"),
        ({"stepm_sha256": "old"}, "different StepM code"),
        ({"studentize": "sample"}, "studentize"),
        ({"fwer": 0.1}, "fwer"),
        ({"block_mean": 10.0}, "block_mean"),
        ({"sessions": 1500}, "real panel length"),
    ):
        (reason,) = battery_refusals({**GOOD, **change}, APR, "abc")
        assert word in reason


def test_missing_series_and_other_vintages_are_not_a_result():
    assert selection_refusals([], [], []) == []
    reasons = selection_refusals([{"run_id": "r"}], ["2"], ["no battery"])
    assert len(reasons) == 3 and "1 charged runs have no series" in reasons[0]
    assert "other vintages" in reasons[1]


def _row(run_id, *, status="completed", sessions=("2024-01-02",), spec="h1", concept="m", **kw):
    row = {
        "run_id": run_id,
        "status": status,
        "mode": "real",
        "concept_id": concept,
        "spec_hash": spec,
        "sessions": sessions,
        "snapshot_hash": "s1",
        "decision_t": 1.0,
        "decision_p": 0.3,
        "gross_sharpe": 0.1,
        "span_start": "2014-12-29",
    }
    return row | kw


def _killed(run_id, **kw):
    nulls = dict.fromkeys(
        ("snapshot_hash", "decision_t", "decision_p", "gross_sharpe", "span_start")
    )
    return _row(run_id, status="failed", sessions=None, **(nulls | kw))


def test_a_killed_row_is_exempt_only_when_a_completed_real_row_of_its_spec_and_member_has_a_series():
    done, killed = _row("done"), _killed("killed")
    assert split_missing_series([killed, done]) == ([], [killed])
    assert split_missing_series([killed]) == ([killed], [])  # no twin yet: a gap
    for other in (_row("o", spec="h2"), _row("o", concept="n"), _row("o", mode="exploration")):
        assert split_missing_series([killed, other]) == ([killed], [])


def test_a_failed_row_that_recorded_any_outcome_or_is_not_failed_stays_a_gap():
    done = _row("done")
    gaps = [
        _killed("a", snapshot_hash="abc"),
        _killed("b", decision_t=2.1),  # computed a statistic, then died before its series
        _killed("c", mode="exploration"),
        _row("d", status="started", sessions=None, snapshot_hash=None),
    ]
    assert split_missing_series([*gaps, done]) == (gaps, [])


# --- the StepM read across the counted looks (todo 636), as a dry run on recorded synthetic inputs ---
# The vintage after the four family 10 runs: the completed rows each carry a series; the earlier
# killed rows (three daily residual, one family 9, four family 10) carry none and are exempt only
# while a completed real row of the same spec hash and concept has one. No database, no git: the
# loader and the spec-horizon reader are replaced, StepM and the gates are the shipped code.

import asyncio  # noqa: E402
import json  # noqa: E402

from scripts.research import select_books  # noqa: E402
from scripts.research.stepm_null_battery import REAL_SESSIONS, stepm_source_sha256  # noqa: E402

_SESSIONS = [str(d) for d in np.arange("2018-01-01", "2019-06-01", dtype="datetime64[D]")]
_APR = {
    "alpha.selection.stepm.fwer": 0.05,
    "alpha.selection.stepm.block_mean_sessions": 20.0,
    "alpha.selection.stepm.reps": 300,
    "alpha.selection.stepm.seed": 187,
    "alpha.research.vintage_id": "vintage_1",
}


def _series_row(i, spec, *, concept=None, status="completed", planted=0.0):
    rng = np.random.default_rng(100 + i)
    d_s = rng.standard_normal(len(_SESSIONS)) * 0.01 + planted
    return _row(
        f"run{i:02d}",
        spec=spec,
        concept=concept or f"c{i:02d}",
        status=status,
        sessions=_SESSIONS,
        d_s=d_s.tolist(),
        concept_name=concept or f"c{i:02d}",
        kind="evidence",
        spec_blob="{}",
        code_commit="c" * 40,
    )


def _vintage(*, family10_spec_edited=False):
    """16 completed series, 4 of them family 10 (concept ids f10a to f10d); 8 killed rows."""
    rows = [_series_row(i, f"spec{i // 2}") for i in range(12)]
    rows[0]["d_s"] = (np.asarray(rows[0]["d_s"]) + 0.02).tolist()  # one strong series
    rows += [_series_row(12 + k, "f10spec", concept=f"f10{c}") for k, c in enumerate("abcd")]
    killed = [_killed(f"k{k}", spec=f"spec{k // 2}", concept=f"c{k:02d}") for k in range(3)]
    killed.append(_killed("k3", spec="spec5", concept="c11"))
    for c in "abcd":
        spec = "f10spec-edited" if family10_spec_edited else "f10spec"
        killed.append(_killed(f"k10{c}", spec=spec, concept=f"f10{c}"))
    for r in killed:
        r |= {"concept_name": r["concept_id"], "kind": "evidence", "spec_blob": "{}"}
        r["code_commit"] = "c" * 40
    return rows + killed


def _read(tmp_path, monkeypatch, rows, *, diagnostic=False, stepm_sha=None):
    async def load(dsn, vintage):
        shaped = [{**r, "concept": r.get("concept_name", r["concept_id"])} for r in rows]
        return shaped, [], dict(_APR), "vintage_1"

    monkeypatch.setattr(select_books, "_load", load)
    # every recorded spec is read as family 10's real spec text (horizon 5), with no git call
    monkeypatch.setattr(select_books, "_git", lambda root, *args: FAMILY10)
    record = {
        "schema": "stepm_null_battery_v1",
        "complete": True,
        "sessions": REAL_SESSIONS,
        "failures": [],
        "stepm_sha256": stepm_sha or stepm_source_sha256(),
        "studentize": "draw",
        "fwer": 0.05,
        "block_mean": 20.0,
    }
    path = tmp_path / "battery.json"
    path.write_text(json.dumps(record))
    return asyncio.run(select_books.build_report("dsn", None, str(path), diagnostic=diagnostic))


def test_the_read_after_family10_is_a_result_with_16_series_and_8_exempt_rows(
    tmp_path, monkeypatch
):
    report = _read(tmp_path, monkeypatch, _vintage())
    assert report["result"] is True and report["refusals"] == []
    assert report["attempts"] == 16
    assert len(report["exempt_killed_rows"]) == 8 and report["missing_series"] == []
    assert report["max_horizon_sessions"] == 5 and report["reps"] == 300
    selected = {s["run_id"] for s in report["selection_set"]}
    assert selected == {"run00"}  # only the planted series survives the 16-series correction
    assert report["not_selected"] == 15


def test_editing_the_family10_specs_between_launch_and_relaunch_leaves_four_gaps(
    tmp_path, monkeypatch
):
    refused = _read(tmp_path, monkeypatch, _vintage(family10_spec_edited=True))
    assert refused["result"] is False
    assert any("4 charged runs have no series" in r for r in refused["refusals"])
    shown = _read(tmp_path, monkeypatch, _vintage(family10_spec_edited=True), diagnostic=True)
    assert shown["result"] is False and len(shown["missing_series"]) == 4
    assert "unattested_set" in shown and "selection_set" not in shown


def test_an_edit_to_stepm_since_the_attestation_refuses_the_read(tmp_path, monkeypatch):
    stale = _read(tmp_path, monkeypatch, _vintage(), stepm_sha="0" * 64)
    assert stale["result"] is False
    assert any("different StepM code" in r for r in stale["refusals"])


def test_a_family10_member_that_never_completed_is_a_gap_not_an_exemption(tmp_path, monkeypatch):
    rows = [r for r in _vintage() if r["run_id"] != "run15"]  # volume_shock_d never completed
    report = _read(tmp_path, monkeypatch, rows, diagnostic=True)
    assert [m["run_id"] for m in report["missing_series"]] == ["k10d"]


def test_a_sweep_attempt_reads_its_horizon_from_its_json_spec_not_from_git(tmp_path):
    blob = '{"version":"ic-sweep-cell-v1","horizon":5}'
    row = {"spec_blob": blob, "code_commit": "c" * 40, "sessions": [], "d_s": []}
    assert select_books._is_sweep_spec(blob) and not select_books._is_sweep_spec("a" * 40)
    assert select_books._sweep_horizon(blob) == 5
    # no git call is made for a sweep row: a root that is not a repository is never read
    horizons, _calendar, _matrix = select_books.attempt_universe(
        [
            {
                **row,
                "sessions": ["2020-01-02", "2020-01-03"],
                "d_s": [0.1, 0.2],
            }
        ],
        tmp_path,
    )
    assert horizons == [5]
