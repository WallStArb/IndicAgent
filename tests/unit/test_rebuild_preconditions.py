"""Unit tests for the D-32 rebuild precondition checker (186-25, consumed by 186-26).

Every check is a pure function over measured inputs: pass and fail cases per check, the
run_all aggregation that names every failure, and the two thin fetch helpers against fake
connections. No database, no filesystem beyond a tmp STATE.md.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from services import rebuild_preconditions as rp
from services.rebuild_preconditions import (
    CheckResult,
    RebuildPreconditionFailure,
    check_bar_coverage,
    check_data_layer_final_landed,
    check_dependencies_landed,
    check_derived_grid_landed,
    check_disk_guard,
    check_drops_landed,
    check_no_live_run,
    check_todo445_decision,
    fetch_bar_verdict_inputs,
    fetch_coverage_inputs,
    fetch_d2_inputs,
    fetch_final_landed_markers,
    fetch_landed_markers,
    run_all,
)
from src.intelligence.bars.verdict_gate import VerdictScan

_GB = 10**9


_AT1 = datetime(2026, 10, 7, 13, 28, tzinfo=UTC)
_AT2 = datetime(2026, 10, 7, 13, 40, tzinfo=UTC)


def _clean_scan(n=3):
    return VerdictScan({}, n, _AT1, _AT2)


# ---------------------------------------------------------------------------
# check_bar_coverage (reads the intraday verdicts since 185-41)
# ---------------------------------------------------------------------------


def test_bar_coverage_passes_and_lists_empty_history_spans_verbatim():
    spans = [("TLT", "5m", "nothing before 2016-06-13 (IBKR venue move)")]
    result = check_bar_coverage(_clean_scan(), spans)
    assert result.ok
    assert "2016-06-13" in result.detail  # the span is listed, not assumed away
    assert "2026-10-07 13:28" in result.detail and "2026-10-07 13:40" in result.detail


def test_bar_coverage_names_every_failing_symbol_timeframe_and_check():
    scan = VerdictScan(
        {
            "SPY": ["5m:slot_coverage failed", "15m:grid_parity missing"],
            "QQQ": ["1h:stray_vendor_rows failed", "5m:digest_fresh stale (verdict 31.0h old)"],
        },
        3,
        _AT1,
        _AT2,
    )
    result = check_bar_coverage(scan, [("AAA", "5m", "reached request start 2006-09-29")])
    assert not result.ok
    assert "SPY" in result.detail and "5m:slot_coverage failed" in result.detail
    assert "15m:grid_parity missing" in result.detail
    assert "QQQ" in result.detail and "1h:stray_vendor_rows failed" in result.detail
    assert "stale" in result.detail
    assert "2 of 3 symbols" in result.detail
    assert "reached request start 2006-09-29" in result.detail


def test_bar_coverage_fails_when_no_symbol_was_judged():
    result = check_bar_coverage(VerdictScan({}, 0, None, None), [])
    assert not result.ok and "no symbols" in result.detail


def test_bar_coverage_truncates_a_long_failure_list():
    failures = {f"S{i:02d}": ["5m:slot_coverage failed"] for i in range(25)}
    result = check_bar_coverage(VerdictScan(failures, 30, _AT1, _AT2), [])
    assert "25 of 30 symbols" in result.detail and "..." in result.detail


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


def test_fetch_process_lines_drops_this_process_but_keeps_every_other(monkeypatch):
    """A launcher importing the writer module would self-match
    LIVE_RUN_PROCESS_PATTERN; the own-pid line must be filtered, every other line kept,
    and a whitespace-only line dropped without crashing."""
    from types import SimpleNamespace

    own = str(os.getpid())
    stdout = "\n".join(
        [
            "  PID COMMAND",
            f"{own} python services/backfill_feature_factory.py --compute-only",
            " 999 python services/ic_engine.py --corpus",
            "1234 tail -f logs/app.log",
            "   ",
        ]
    )
    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=stdout))
    # The ps header carries no pattern and is kept; only the own-pid and blank lines drop.
    assert rp.fetch_process_lines() == [
        "  PID COMMAND",
        " 999 python services/ic_engine.py --corpus",
        "1234 tail -f logs/app.log",
    ]


def test_no_live_run_fails_on_a_matching_process_or_resumable_evidence():
    lines = ["bg 12345 python services/backfill_feature_factory.py --compute-only"]
    failed = check_no_live_run(lines, "")
    assert not failed.ok and "backfill_feature_factory" in failed.detail
    failed = check_no_live_run([], "ic_engine corpus run resumable at scratch/ic_run")
    assert not failed.ok and "resumable" in failed.detail
    # An unrelated process line does not trip it.
    assert check_no_live_run(["tail -f logs/app.log"], "").ok


def test_d2_landed_passes_with_an_evidence_line_citing_the_verdict_range():
    result = rp.check_d2_landed(_clean_scan(1502))
    assert result.ok
    assert "1502" in result.detail
    assert "2026-10-07 13:28" in result.detail and "2026-10-07 13:40" in result.detail


def test_d2_landed_fails_naming_failing_missing_and_stale_verdicts():
    scan = VerdictScan(
        {
            "ZZZ": ["1d:canonical_recompute failed"],
            "AAA": [
                "1d:digest_fresh missing",
                "1d:lineage_missing stale (newer load at 2026-10-07 14:00Z)",
            ],
        },
        1502,
        _AT1,
        _AT2,
    )
    result = rp.check_d2_landed(scan)
    assert not result.ok
    assert "2 of 1502 symbols" in result.detail
    assert "ZZZ" in result.detail and "1d:canonical_recompute failed" in result.detail
    assert "AAA" in result.detail and "1d:digest_fresh missing" in result.detail
    assert "newer load" in result.detail


def test_d2_landed_fails_when_no_symbol_was_judged():
    assert not rp.check_d2_landed(VerdictScan({}, 0, None, None)).ok


def test_d2_landed_truncates_a_long_symbol_list():
    failures = {f"S{i:02d}": ["1d:session_coverage failed"] for i in range(25)}
    result = rp.check_d2_landed(VerdictScan(failures, 30, _AT1, _AT2))
    assert "25 of 30 symbols" in result.detail and "..." in result.detail


# ---------------------------------------------------------------------------
# check_data_layer_final_landed
# ---------------------------------------------------------------------------


def test_final_landed_passes_when_every_summary_exists():
    markers = {name: True for name in rp.REQUIRED_FINAL_LANDED_SUMMARIES}
    assert check_data_layer_final_landed(markers).ok


def test_final_landed_names_each_missing_summary():
    assert rp.REQUIRED_FINAL_LANDED_SUMMARIES == frozenset(
        {
            "185-42-SUMMARY.md",
            "185-43-SUMMARY.md",
            "185-45-SUMMARY.md",
            "185-47-SUMMARY.md",
            "185-48-SUMMARY.md",
            "189-11-SUMMARY.md",
        }
    )
    markers = {name: True for name in rp.REQUIRED_FINAL_LANDED_SUMMARIES}
    markers["185-43-SUMMARY.md"] = False
    del markers["189-11-SUMMARY.md"]
    result = check_data_layer_final_landed(markers)
    assert not result.ok
    assert "185-43-SUMMARY.md" in result.detail and "189-11-SUMMARY.md" in result.detail
    assert "185-42" not in result.detail


def test_fetch_final_landed_markers_reads_presence_in_the_phase_directories(tmp_path):
    p185 = tmp_path / ".planning" / "phases" / "185-daily-data-foundation"
    p189 = tmp_path / ".planning" / "phases" / "189-ibkr-history-fetch"
    p185.mkdir(parents=True)
    p189.mkdir(parents=True)
    (p185 / "185-42-SUMMARY.md").write_text("x")
    (p185 / "185-45-SUMMARY.md").write_text("x")
    (p189 / "189-11-SUMMARY.md").write_text("x")
    (p185 / "185-47-SUMMARY.md").write_text("x")
    (p185 / "185-43-PLAN.md").write_text("a plan is not a landing")
    markers = fetch_final_landed_markers(tmp_path)
    assert markers == {
        "185-42-SUMMARY.md": True,
        "185-43-SUMMARY.md": False,
        "185-45-SUMMARY.md": True,
        "185-47-SUMMARY.md": True,
        "185-48-SUMMARY.md": False,
        "189-11-SUMMARY.md": True,
    }


def test_final_landed_fails_naming_the_swap_plans_while_absent():
    markers = {name: True for name in rp.REQUIRED_FINAL_LANDED_SUMMARIES}
    markers["185-47-SUMMARY.md"] = False
    markers["185-48-SUMMARY.md"] = False
    result = check_data_layer_final_landed(markers)
    assert not result.ok
    assert "185-47-SUMMARY.md" in result.detail and "185-48-SUMMARY.md" in result.detail


def test_rebuild_extra_checks_include_freshness_1d():
    assert rp.REBUILD_EXTRA_CHECKS == frozenset({"stray_vendor_rows", "freshness_1d"})


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------


def _all_passing_inputs():
    return {
        "bar_scan": _clean_scan(),
        "empty_history_spans": [],
        "grid_marker_present": True,
        "grid_marker_detail": "D2b landed 2026-09-30",
        "d2_scan": _clean_scan(1502),
        "final_landed_markers": {name: True for name in rp.REQUIRED_FINAL_LANDED_SUMMARIES},
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
    assert len(names) == 9 and len(set(names)) == 9
    assert all(r.ok for r in results)
    assert all(isinstance(r, CheckResult) for r in results)


def test_run_all_raises_naming_every_failed_check():
    inputs = _all_passing_inputs()
    inputs["bar_scan"] = VerdictScan({"SPY": ["5m:slot_coverage failed"]}, 3, _AT1, _AT2)
    inputs["grid_marker_present"] = False
    inputs["d2_scan"] = VerdictScan({"SPY": ["1d:digest_fresh failed"]}, 3, _AT1, _AT2)
    inputs["final_landed_markers"] = {"185-42-SUMMARY.md": False}
    inputs["present_relations"] = frozenset({"alpha_events"})
    inputs["disk"]["free_bytes"] = 500 * _GB
    with pytest.raises(RebuildPreconditionFailure) as excinfo:
        run_all(**inputs)
    message = str(excinfo.value)
    for name in (
        "bar_coverage",
        "derived_grid_landed",
        "d2_landed",
        "data_layer_final_landed",
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
    # The live table's columns (a first_bar/last_bar guess failed on the real schema, 185-41).
    assert "empty_from" in sqls[2] and "empty_through" in sqls[2]
    assert not any("market_data_ohlcv " in sql for sql in sqls)


class _VerdictConn:
    """Answers the gate's reads: APR age, latest verdicts, latest changing loads."""

    def __init__(self, verdicts, loads=()):
        self.verdicts = verdicts
        self.loads = loads
        self.calls = []
        self._last = ""

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._last = sql

    def fetchone(self):
        return ("30",)

    def fetchall(self):
        if "integrity_monitor" in self._last:
            return list(self.verdicts)
        if "ohlcv_load" in self._last:
            return list(self.loads)
        return []


def _verdicts(symbol, tf, checks, at, passed=True):
    return [(f"{symbol}|{tf}", check, passed, at) for check in sorted(checks)]


def test_fetch_d2_inputs_gates_the_1d_verdicts_of_the_symbols():
    from src.intelligence.bars.verdict_gate import REQUIRED_CHECKS

    at = datetime.now(UTC)
    conn = _VerdictConn(
        _verdicts("SPY", "1d", REQUIRED_CHECKS["1d"] | {"freshness_1d"}, at)
        + _verdicts("BAD", "1d", REQUIRED_CHECKS["1d"], at, passed=False)
        + _verdicts("OLD", "1d", REQUIRED_CHECKS["1d"], at)
        + _verdicts("OLD", "1d", {"freshness_1d"}, at, passed=False)
    )
    scan = fetch_d2_inputs(conn, ["SPY", "BAD", "OLD", "NEW1"])
    assert scan.n_symbols == 4
    assert set(scan.failures) == {"BAD", "OLD", "NEW1"}
    # a stale name fails the 1d rebuild gate on freshness_1d alone, and is named
    assert scan.failures["OLD"] == ["1d:freshness_1d failed"]
    assert scan.failures["NEW1"][0].endswith("missing")
    assert scan.first_evaluated_at == scan.last_evaluated_at == at
    sqls = [sql for sql, _ in conn.calls]
    assert not any("canonical_bar_lineage" in sql or "rule_version" in sql for sql in sqls)
    verdict_params = next(p for sql, p in conn.calls if "integrity_monitor" in sql)
    assert verdict_params["subjects"] == ["SPY|1d", "BAD|1d", "OLD|1d", "NEW1|1d"]


def test_fetch_d2_inputs_fails_a_verdict_older_than_the_latest_load():
    from src.intelligence.bars.verdict_gate import REQUIRED_CHECKS

    at = datetime.now(UTC) - timedelta(hours=2)
    conn = _VerdictConn(
        _verdicts("SPY", "1d", REQUIRED_CHECKS["1d"], at),
        loads=[("SPY", "1d", at + timedelta(hours=1))],
    )
    assert set(fetch_d2_inputs(conn, ["SPY"]).failures) == {"SPY"}


def test_fetch_bar_verdict_inputs_requires_intraday_checks_plus_stray_vendor_rows():
    from src.intelligence.bars.verdict_gate import REQUIRED_CHECKS

    at = datetime.now(UTC)
    rows = (
        _verdicts("SPY", "5m", REQUIRED_CHECKS["5m"], at)
        + _verdicts("SPY", "15m", REQUIRED_CHECKS["15m"], at)
        + _verdicts("SPY", "1h", REQUIRED_CHECKS["1h"], at)
    )
    scan = fetch_bar_verdict_inputs(_VerdictConn(rows), ["SPY"], ["5m", "15m", "1h", "1d"])
    assert scan.failures == {
        "SPY": ["15m:stray_vendor_rows missing", "1h:stray_vendor_rows missing"]
    }


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
