"""Unit tests for the D-32 rebuild precondition checker (186-25, consumed by 186-26).

Every check is a pure function over measured inputs: pass and fail cases per check, the
run_all aggregation that names every failure, and the two thin fetch helpers against fake
connections. No database, no filesystem beyond a tmp STATE.md.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from services import rebuild_preconditions as rp
from services.rebuild_preconditions import (
    CheckResult,
    RebuildPreconditionFailure,
    check_bar_coverage,
    check_dependencies_landed,
    check_derived_grid_landed,
    check_disk_guard,
    check_drops_landed,
    check_no_live_run,
    check_todo445_decision,
    fetch_coverage_inputs,
    fetch_landed_markers,
    run_all,
)

_GB = 10**9


def _covered_rows():
    span = (datetime(2006, 7, 7, tzinfo=UTC), datetime(2026, 9, 25, tzinfo=UTC))
    expected = {("SPY", tf): span for tf in ("5m", "15m", "1h", "1d")}
    rows = {k: rp.CoverageRow(count=1000, first=span[0], last=span[1]) for k in expected}
    return rows, expected


# ---------------------------------------------------------------------------
# check_bar_coverage
# ---------------------------------------------------------------------------


def test_bar_coverage_passes_and_lists_empty_history_spans_verbatim():
    rows, expected = _covered_rows()
    spans = [("TLT", "5m", "nothing before 2016-06-13 (IBKR venue move)")]
    result = check_bar_coverage(rows, expected, spans)
    assert result.ok
    assert "2016-06-13" in result.detail  # the span is listed, not assumed away


def test_bar_coverage_names_every_short_symbol_with_measured_vs_expected():
    rows, expected = _covered_rows()
    rows[("SPY", "5m")] = rp.CoverageRow(
        count=10, first=datetime(2016, 2, 4, tzinfo=UTC), last=expected[("SPY", "5m")][1]
    )
    del rows[("SPY", "1d")]
    result = check_bar_coverage(rows, expected, [("AAA", "5m", "reached request start 2006-09-29")])
    assert not result.ok
    assert "SPY|5m" in result.detail and "2016-02-04" in result.detail
    assert "SPY|1d" in result.detail and "no bars" in result.detail
    assert "reached request start 2006-09-29" in result.detail


# ---------------------------------------------------------------------------
# check_derived_grid_landed
# ---------------------------------------------------------------------------


def test_derived_grid_marker_passes_when_present_and_fails_when_absent():
    assert check_derived_grid_landed(True, "STATE.md: D2b landed on 2026-09-30").ok
    failed = check_derived_grid_landed(False, "no D2b bullet in STATE.md")
    assert not failed.ok
    assert "D2b" in failed.detail


# ---------------------------------------------------------------------------
# check_todo445_decision
# ---------------------------------------------------------------------------


def _todo445_decision():
    return {"decision": "keep_5m", "rebuild_timeframes": ["15m", "1h", "1d", "5m"]}


def test_todo445_decision_passes_when_it_agrees_with_the_configured_tfs():
    result = check_todo445_decision(_todo445_decision(), ["5m", "15m", "1h", "1d"])
    assert result.ok


def test_todo445_decision_fails_when_missing_or_disagreeing():
    for decision in (
        None,
        {},
        {"decision": "drop_5m", "rebuild_timeframes": ["15m", "1h", "1d"]},
        {**_todo445_decision(), "rebuild_timeframes": ["15m", "1h", "1d"]},
    ):
        result = check_todo445_decision(decision, ["5m", "15m", "1h", "1d"])
        assert not result.ok, decision


# ---------------------------------------------------------------------------
# check_dependencies_landed
# ---------------------------------------------------------------------------


def test_dependencies_pass_when_every_marker_is_true():
    markers = {name: True for name in rp.REQUIRED_DEPENDENCY_MARKERS}
    assert check_dependencies_landed(markers).ok


def test_dependencies_fail_naming_each_missing_marker():
    markers = {name: True for name in rp.REQUIRED_DEPENDENCY_MARKERS}
    markers["feature_vectors_v2_relation"] = False
    del markers["bulk_load_import"]
    result = check_dependencies_landed(markers)
    assert not result.ok
    assert "feature_vectors_v2_relation" in result.detail
    assert "bulk_load_import" in result.detail


def test_dependency_marker_names_are_pinned():
    assert set(rp.REQUIRED_DEPENDENCY_MARKERS) == {
        "bulk_load_import",
        "registry_regime_origin",
        "kernels_regime_module",
        "feature_vectors_v2_relation",
        "writer_module_import",
    }


# ---------------------------------------------------------------------------
# check_drops_landed
# ---------------------------------------------------------------------------


def test_drops_pass_when_no_old_relation_is_present():
    assert check_drops_landed(frozenset({"feature_vectors_v2", "market_data_ohlcv"})).ok


def test_drops_fail_naming_each_surviving_table():
    result = check_drops_landed(frozenset({"alpha_events", "forward_returns"}))
    assert not result.ok
    assert "alpha_events" in result.detail and "forward_returns" in result.detail


def test_the_drop_list_is_the_186_22_186_23_set():
    assert set(rp.DROPS_DUE_BEFORE_REBUILD) == {
        "ensemble_weights",
        "ensemble_alpha",
        "alpha_ensemble_ic",
        "alpha_events",
        "alpha_frames",
        "alpha_strategy_scores",
        "context_features",
        "feature_ic_scores_history",
        "construction_spreads",
        "ctx_events",
        "ctx_snapshots",
        "forward_returns",
    }


# ---------------------------------------------------------------------------
# check_disk_guard (R-09 arithmetic; the margin is the caller's, never a literal here)
# ---------------------------------------------------------------------------


def test_disk_guard_passes_when_free_covers_projected_working_and_margin():
    result = check_disk_guard(
        projected_compressed_bytes=400 * _GB,
        largest_chunk_working_set_bytes=100 * _GB,
        margin_bytes=50 * _GB,
        free_bytes=1000 * _GB,
        reserve_bytes=100 * _GB,
    )
    assert result.ok


def test_disk_guard_passes_at_exact_equality():
    result = check_disk_guard(
        projected_compressed_bytes=500 * _GB,
        largest_chunk_working_set_bytes=200 * _GB,
        margin_bytes=100 * _GB,
        free_bytes=900 * _GB,
        reserve_bytes=100 * _GB,
    )
    assert result.ok


def test_disk_guard_fails_with_the_figures_in_gb():
    result = check_disk_guard(
        projected_compressed_bytes=700 * _GB,
        largest_chunk_working_set_bytes=200 * _GB,
        margin_bytes=100 * _GB,
        free_bytes=900 * _GB,
        reserve_bytes=100 * _GB,
    )
    assert not result.ok
    assert "700" in result.detail and "200" in result.detail and "900" in result.detail


# ---------------------------------------------------------------------------
# check_no_live_run
# ---------------------------------------------------------------------------


def test_no_live_run_passes_on_a_quiet_host():
    assert check_no_live_run([], "").ok


def test_no_live_run_fails_on_a_matching_process_or_resumable_evidence():
    lines = ["bg 12345 python services/backfill_feature_factory.py --compute-only"]
    failed = check_no_live_run(lines, "")
    assert not failed.ok and "backfill_feature_factory" in failed.detail
    failed = check_no_live_run([], "ic_engine corpus run resumable at scratch/ic_run")
    assert not failed.ok and "resumable" in failed.detail
    # An unrelated process line does not trip it.
    assert check_no_live_run(["tail -f logs/app.log"], "").ok


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------


def _all_passing_inputs():
    rows, expected = _covered_rows()
    return {
        "coverage_rows": rows,
        "expected_spans": expected,
        "empty_history_spans": [],
        "grid_marker_present": True,
        "grid_marker_detail": "D2b landed 2026-09-30",
        "todo445_decision": _todo445_decision(),
        "configured_tfs": ["5m", "15m", "1h", "1d"],
        "dependency_markers": {name: True for name in rp.REQUIRED_DEPENDENCY_MARKERS},
        "present_relations": frozenset(),
        "disk": {
            "projected_compressed_bytes": 400 * _GB,
            "largest_chunk_working_set_bytes": 100 * _GB,
            "margin_bytes": 50 * _GB,
            "free_bytes": 1000 * _GB,
            "reserve_bytes": 100 * _GB,
        },
        "process_lines": [],
        "resumable_log_evidence": "",
    }


def test_run_all_returns_every_result_and_raises_nothing_when_clean():
    results = run_all(**_all_passing_inputs())
    names = [r.name for r in results]
    assert len(names) == 7 and len(set(names)) == 7
    assert all(r.ok for r in results)
    assert all(isinstance(r, CheckResult) for r in results)


def test_run_all_raises_naming_every_failed_check():
    inputs = _all_passing_inputs()
    rows, expected = _covered_rows()
    del rows[("SPY", "5m")]
    inputs["coverage_rows"] = rows
    inputs["grid_marker_present"] = False
    inputs["present_relations"] = frozenset({"alpha_events"})
    inputs["disk"]["free_bytes"] = 500 * _GB
    with pytest.raises(RebuildPreconditionFailure) as excinfo:
        run_all(**inputs)
    message = str(excinfo.value)
    for name in (
        "bar_coverage",
        "derived_grid_landed",
        "drops_landed",
        "disk_guard",
    ):
        assert name in message, name
    # The passing checks are recorded too, not silently skipped.
    assert "todo445_decision" in message and "no_live_run" in message


# ---------------------------------------------------------------------------
# The two thin fetch helpers, against fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.calls.append((sql, params))

    def fetchall(self):
        return self._conn.responses.pop(0)

    def fetchone(self):
        rows = self._conn.responses.pop(0)
        return rows[0] if rows else (None,)


class _FakeConn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def cursor(self):
        return _FakeCursor(self)


def test_fetch_coverage_inputs_reads_only_the_tradeable_view_and_sets_a_timeout():
    coverage = [
        ("SPY", "5m", 100, datetime(2006, 7, 7, tzinfo=UTC), datetime(2026, 9, 25, tzinfo=UTC)),
        ("SPY", "1d", 10, datetime(2006, 7, 7, tzinfo=UTC), datetime(2026, 9, 25, tzinfo=UTC)),
    ]
    empty_spans = [("TLT", "5m", "2006-09-29", "2016-06-13")]
    conn = _FakeConn([coverage, empty_spans])
    rows, spans = fetch_coverage_inputs(conn, ["5m", "1d"], ["SPY", "TLT"])
    assert ("SPY", "5m") in rows and ("SPY", "1d") in rows
    assert spans == [("TLT", "5m", "2006-09-29..2016-06-13")]
    sqls = [sql for sql, _params in conn.calls]
    assert sqls[0].startswith("SET statement_timeout")
    assert "market_data_ohlcv_tradeable" in sqls[1]
    assert "ohlcv_empty_history" in sqls[2]
    assert not any("market_data_ohlcv " in sql for sql in sqls)


def test_fetch_landed_markers_gathers_every_required_marker(tmp_path):
    state = tmp_path / "STATE.md"
    state.write_text("## Phase 185\n- D2b landed on 2026-09-30, 231 symbols derived\n")
    conn = _FakeConn([[("feature_vectors_v2",)]])
    markers = fetch_landed_markers(conn, state_path=state)
    assert set(markers) == set(rp.REQUIRED_DEPENDENCY_MARKERS) | {"grid_marker"}
    assert all(markers.values()), markers
    # The relation check is the passed connection's to answer, not a psql subprocess.
    assert any("to_regclass" in sql for sql, _ in conn.calls)


def test_fetch_landed_markers_reports_an_absent_grid_marker(tmp_path):
    state = tmp_path / "STATE.md"
    state.write_text("## Phase 185\n- nothing about the grid yet\n")
    conn = _FakeConn([[]])
    markers = fetch_landed_markers(conn, state_path=state)
    assert markers["grid_marker"] is False


def test_the_module_writes_nothing():
    source = Path(rp.__file__).read_text()
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "COPY "):
        lines = [
            line
            for line in source.splitlines()
            if forbidden in line and not line.lstrip().startswith("#")
        ]
        assert lines == [], (forbidden, lines)
