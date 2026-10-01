"""Unit tests for infrastructure_nightly_backfill's candidate-selection and
dispatch logic — the non-trivial pure-ish pieces; gap accounting itself
stays in infrastructure_run_historical_pipeline.py and isn't re-tested here.
Lease behavior (priority tier, wait bound, failed_lease_timeout mapping) is
covered by test_nightly_lease.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from structlog.testing import capture_logs

from scripts.infrastructure.backfill import infrastructure_nightly_backfill
from scripts.infrastructure.backfill.infrastructure_nightly_backfill import (
    _finish,
    _select_stalest,
)


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.executed_sql: str | None = None
        self.executed_params: tuple | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self.executed_sql = sql
        self.executed_params = params

    def fetchall(self) -> list[tuple]:
        return self._rows


_COMPUTE, _COHORT = (
    infrastructure_nightly_backfill._LEGS[0],
    infrastructure_nightly_backfill._LEGS[1],
)


def _run_select(leg, rows):
    cursor = _FakeCursor(rows)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return _select_stalest(conn, leg), cursor


class TestSelectStalest:
    def test_latest_bar_lookup_is_per_symbol(self):
        """Per-candidate LATERAL lookup: a leg costs its own size, not a whole-table scan."""
        _, cursor = _run_select(_COHORT, [])
        assert "LEFT JOIN LATERAL" in cursor.executed_sql
        assert "GROUP BY" not in cursor.executed_sql

    def test_returns_symbols_in_query_order(self):
        result, _ = _run_select(_COMPUTE, [("ZZZ",), ("AAA",)])
        assert result == ["ZZZ", "AAA"]

    @pytest.mark.parametrize("leg", [_COMPUTE, _COHORT], ids=lambda leg: leg.name)
    def test_no_hard_exclusion_filter_or_count_cap_in_query(self, leg):
        """Regression test for two bugs: (1) 2026-09-16, a symbol's row count crossing
        a fixed threshold must never make it permanently ineligible; (2) 2026-09-22
        (todo 382), a LIMIT on candidate selection throttles the wrong resource (see
        module docstring) -- every eligible symbol must be a candidate every night,
        dispatched all at once, staliest first."""
        _, cursor = _run_select(leg, [])
        sql = cursor.executed_sql or ""
        assert "completeness_threshold" not in sql
        assert "< %s" not in sql
        assert "LIMIT" not in sql
        assert "ORDER BY" in sql
        assert cursor.executed_params == (leg.ranking_tf,)

    def test_compute_leg_is_the_compute_universe_ranked_on_1h(self):
        """is_active alone would sweep up the D-09 pilot cohort and pull full-stack
        history for symbols kept 1d-only for exactly that cost reason."""
        _, cursor = _run_select(_COMPUTE, [])
        assert "i.is_active = true AND i.compute_eligible = true" in cursor.executed_sql
        assert _COMPUTE.ranking_tf == "1h"
        assert _COMPUTE.delegate_args == ()

    def test_cohort_leg_is_1d_only_symbols_fetched_at_1d(self):
        """174 review WR-02: the 1d-only cohort needs its own leg or its series stops."""
        _, cursor = _run_select(_COHORT, [])
        assert "i.compute_eligible_1d = true" in cursor.executed_sql
        assert "i.compute_eligible = false" in cursor.executed_sql
        assert _COHORT.ranking_tf == "1d"
        assert _COHORT.delegate_args == ("--dimension", "compute_1d", "--timeframes", "1d")


def _run_main(batches, returncodes, grid_returncode=0):
    mod = infrastructure_nightly_backfill
    by_leg = dict(zip((leg.name for leg in mod._LEGS), batches, strict=True))
    with (
        patch.object(mod, "setup_service_logging"),
        patch.object(mod, "Settings"),
        patch.object(mod, "connect_db"),
        patch.object(mod, "_select_stalest", side_effect=lambda _c, leg: by_leg[leg.name]),
        patch.object(mod, "_load_lease_wait_minutes", return_value=60),
        patch.object(mod, "_run_delegate", side_effect=returncodes) as mock_delegate,
        patch.object(mod, "_prepare_grid_stage") as mock_prepare,
        patch.object(mod, "_run_grid_stage", return_value=grid_returncode) as mock_grid,
        patch.object(mod, "emit_integrity_fact_sync"),
        patch.object(mod, "flush_and_shutdown_metrics"),
        patch.object(mod, "JOB_COMPLETED_TOTAL"),
    ):
        rc = mod.main()
    return rc, mock_delegate, mock_grid, mock_prepare


class TestMainDispatch:
    def test_each_leg_dispatches_with_its_own_args(self):
        rc, mock_delegate, _mock_grid, _mock_prepare = _run_main(
            [["AAA"], ["PIL1", "PIL2"]], [0, 0]
        )
        assert rc == 0
        lease_args = ("--lease-tier", "priority", "--lease-wait-minutes", "60")
        assert [c.args for c in mock_delegate.call_args_list] == [
            (["AAA"], lease_args),
            (
                ["PIL1", "PIL2"],
                ("--dimension", "compute_1d", "--timeframes", "1d") + lease_args,
            ),
        ]

    @pytest.mark.parametrize(("returncodes", "expected"), [([0, 3], 3), ([2, 0], 2)])
    def test_failure_in_either_leg_fails_the_job(self, returncodes, expected):
        rc, _delegate, _grid, _prepare = _run_main([["AAA"], ["PIL1"]], returncodes)
        assert rc == expected

    def test_empty_leg_is_skipped(self):
        rc, mock_delegate, _grid, _prepare = _run_main([["AAA"], []], [0])
        assert rc == 0
        assert mock_delegate.call_count == 1


class TestGridStage:
    """Plan 12: after the backfill legs (whose 1h/15m now land in the archive),
    the nightly derives the 15m/1h grid for every symbol whose 5m changed, with
    the lane guard's exclude file. No skip path: the stage also runs after a
    leg that ended failed_lease_timeout."""

    def test_grid_stage_runs_after_legs_even_after_lease_timeout(self):
        rc, _delegate, mock_grid, mock_prepare = _run_main([["AAA"], ["PIL1"]], [0, 3])
        assert mock_prepare.call_count == 1
        assert mock_grid.call_count == 1
        assert rc == 3  # the lease timeout still fails the job

    def test_grid_stage_failure_fails_the_job(self):
        rc, _delegate, _grid, _prepare = _run_main([["AAA"], []], [0], grid_returncode=2)
        assert rc == 2

    def test_grid_stage_refuses_on_an_unscoped_lane(self, capsys):
        mod = infrastructure_nightly_backfill
        with (
            patch.object(mod, "setup_service_logging"),
            patch.object(mod, "Settings"),
            patch.object(mod, "connect_db"),
            patch.object(mod, "_select_stalest", side_effect=lambda _c, leg: ["AAA"]),
            patch.object(mod, "_load_lease_wait_minutes", return_value=60),
            patch.object(mod, "_run_delegate", return_value=0),
            patch.object(
                mod, "_prepare_grid_stage", side_effect=RuntimeError("lane without --symbols")
            ),
            patch.object(mod, "flush_and_shutdown_metrics"),
            patch.object(mod, "JOB_COMPLETED_TOTAL"),
        ):
            rc = mod.main()
        assert rc == 1
        assert "lane without --symbols" in capsys.readouterr().out

    def test_grid_stage_invokes_bar_derivation_with_the_exclude_file(self, tmp_path):
        mod = infrastructure_nightly_backfill
        exclude = tmp_path / "exclude.txt"
        exclude.write_text("")
        with patch.object(mod.subprocess, "run", return_value=MagicMock(returncode=0)) as mock_run:
            rc = mod._run_grid_stage(exclude)
        assert rc == 0
        argv = mock_run.call_args.args[0]
        assert argv[0].endswith("python") or argv[0].endswith("python3")
        assert argv[1].endswith("services/bar_derivation.py")
        assert argv[2:] == [
            "--stage",
            "grid",
            "--changed-only",
            "--apply",
            "--exclude-symbols-file",
            str(exclude),
        ]

    def test_prepare_grid_stage_writes_the_lane_guard_file(self, tmp_path):
        """The nightly's exclude file comes from ops_grid_lane_guard, so a
        symbol a running lane is writing is never derived mid-lane."""
        mod = infrastructure_nightly_backfill
        with patch.object(mod, "_GRID_EXCLUDE_FILE", tmp_path / "exclude.txt"):
            path = mod._prepare_grid_stage()
        assert path.exists()  # comment-only file when no grid lane runs

    def test_default_timeframes_keep_1h_and_15m(self):
        """1h/15m stay in the default stack: their fetches are archive-bound
        raw observations now, feeding coverage and the parity record."""
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            _DEFAULT_TIMEFRAMES,
        )

        tfs = {t.strip() for t in _DEFAULT_TIMEFRAMES.split(",")}
        assert {"1h", "15m", "1d", "5m", "1m"} <= tfs


class TestFinishLogLevel:
    """todo 395 item 4: a failed run must log at error, not info, so a
    log-based check (or a future alert) can see it without a human first
    reading the nightly's stdout."""

    def _finish_events(self, status: str) -> list[dict]:
        with (
            patch.object(infrastructure_nightly_backfill, "flush_and_shutdown_metrics"),
            patch.object(infrastructure_nightly_backfill, "JOB_COMPLETED_TOTAL"),
            capture_logs() as cap_logs,
        ):
            _finish(status, f"message for {status}")
        return cap_logs

    def test_success_logs_at_info(self):
        events = self._finish_events("success")
        assert events == [{"event": "nightly_backfill.success", "log_level": "info"}]

    @pytest.mark.parametrize("status", ["failed", "failed_lease_timeout"])
    def test_non_success_logs_at_error(self, status):
        events = self._finish_events(status)
        assert events == [{"event": f"nightly_backfill.{status}", "log_level": "error"}]
