"""Unit tests for infrastructure_nightly_backfill's candidate-selection and
collision-guard logic — the only two non-trivial pure-ish pieces; gap accounting itself
stays in infrastructure_run_historical_pipeline.py and isn't re-tested here."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.infrastructure.backfill import infrastructure_nightly_backfill
from scripts.infrastructure.backfill.infrastructure_nightly_backfill import (
    _is_another_backfill_running,
    _select_stalest,
)


class TestIsAnotherBackfillRunning:
    def test_true_when_pgrep_finds_a_pid(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="123456\n")
            assert _is_another_backfill_running() is True

    def test_false_when_pgrep_finds_nothing(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="")
            assert _is_another_backfill_running() is False


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


class TestMainDispatch:
    def _run_main(self, batches, returncodes):
        mod = infrastructure_nightly_backfill
        by_leg = dict(zip((leg.name for leg in mod._LEGS), batches, strict=True))
        with (
            patch.object(mod, "setup_service_logging"),
            patch.object(mod, "Settings"),
            patch.object(mod, "_is_another_backfill_running", return_value=False),
            patch.object(mod, "connect_db"),
            patch.object(mod, "_select_stalest", side_effect=lambda _c, leg: by_leg[leg.name]),
            patch.object(mod, "_run_delegate", side_effect=returncodes) as mock_delegate,
            patch.object(mod, "flush_and_shutdown_metrics"),
            patch.object(mod, "JOB_COMPLETED_TOTAL"),
        ):
            rc = mod.main()
        return rc, mock_delegate

    def test_each_leg_dispatches_with_its_own_args(self):
        rc, mock_delegate = self._run_main([["AAA"], ["PIL1", "PIL2"]], [0, 0])
        assert rc == 0
        assert [c.args for c in mock_delegate.call_args_list] == [
            (["AAA"], ()),
            (["PIL1", "PIL2"], ("--dimension", "compute_1d", "--timeframes", "1d")),
        ]

    @pytest.mark.parametrize(("returncodes", "expected"), [([0, 3], 3), ([2, 0], 2)])
    def test_failure_in_either_leg_fails_the_job(self, returncodes, expected):
        rc, _ = self._run_main([["AAA"], ["PIL1"]], returncodes)
        assert rc == expected

    def test_empty_leg_is_skipped(self):
        rc, mock_delegate = self._run_main([["AAA"], []], [0])
        assert rc == 0
        assert mock_delegate.call_count == 1
