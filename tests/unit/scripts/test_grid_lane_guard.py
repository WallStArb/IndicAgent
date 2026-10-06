"""Tests for scripts/ops/bars/ops_grid_lane_guard.py (phase 185 plan 12, task 1a).

The guard keeps the D2b grid rewrite (and the nightly's grid stage) off the
symbols a running historical-pipeline lane is writing at a grid timeframe:
running_lane_symbols() parses `ps -eo args` output for
infrastructure_run_historical_pipeline.py processes whose --timeframes
intersect {5m, 15m, 1h} (or that run the default full stack), and returns
their --symbols union plus whether any such process runs WITHOUT --symbols
(a dimension-wide lane the exclude file cannot scope, which must stop the
rewrite rather than narrow it). write_exclude_file() writes the file the
bar-derivation --exclude-symbols-file flag reads.

Pure parsing tests: ps output is injected as text, never executed.
"""

from __future__ import annotations

import pytest

from scripts.ops.bars.ops_grid_lane_guard import running_lane_symbols, write_exclude_file

_HTF_LANE = (
    "python -u scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py "
    "--dimension backfill --timeframes 1h,15m --real-bars-only --client-id 46 "
    "--symbols A,ABNB,ADBE"
)
_NIGHTLY_STACK = (
    "python -u scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py "
    "--lease-tier priority"
)
_1D_LANE = (
    "python -u scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py "
    "--dimension compute_1d --timeframes 1d --symbols C,CL"
)
_5M_LANE = (
    "python -u scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py "
    "--timeframes 5m --dimension compute"
)
_UNRELATED = "vim logs/backfill_ops/intraday_chain.sh"


class TestRunningLaneSymbols:
    def test_grid_lane_symbols_returned_and_other_processes_ignored(self):
        ps_args = "\n".join([_HTF_LANE, _1D_LANE, _UNRELATED])
        symbols, unscoped = running_lane_symbols(ps_args)
        assert symbols == frozenset({"A", "ABNB", "ADBE"})
        assert unscoped is False

    def test_lane_without_symbols_is_unscoped(self):
        """The nightly's default stack includes 1h/15m/5m, and it has no
        --symbols: no exclude file can scope it, so the rewrite must refuse."""
        symbols, unscoped = running_lane_symbols(_NIGHTLY_STACK)
        assert symbols == frozenset()
        assert unscoped is True

    def test_equals_form_flags_are_parsed(self):
        ps_args = "python infrastructure_run_historical_pipeline.py --timeframes=15m --symbols=X,Y"
        symbols, unscoped = running_lane_symbols(ps_args)
        assert symbols == frozenset({"X", "Y"})
        assert unscoped is False

    def test_default_timeframes_intersect_the_grid(self):
        """No --timeframes means the full default stack (1d,1h,15m,5m,1m), which
        intersects the grid; only its explicit --symbols scopes it."""
        symbols, unscoped = running_lane_symbols(
            "python infrastructure_run_historical_pipeline.py --client-id 46 --symbols Q"
        )
        assert symbols == frozenset({"Q"})
        assert unscoped is False

    def test_1d_only_lane_is_ignored(self):
        symbols, unscoped = running_lane_symbols(_1D_LANE)
        assert symbols == frozenset()
        assert unscoped is False

    def test_5m_lane_without_symbols_is_unscoped(self):
        """5m is a grid constituent too (the todo 449 second leg): an unscoped
        5m lane blocks the rewrite exactly like an unscoped 1h lane."""
        symbols, unscoped = running_lane_symbols(_5M_LANE)
        assert symbols == frozenset()
        assert unscoped is True

    def test_symbols_across_processes_union(self):
        ps_args = "\n".join([_HTF_LANE, _5M_LANE.replace("--timeframes 5m", "--timeframes 5m")])
        ps_args = ps_args.replace("--dimension compute", "--dimension compute --symbols D")
        symbols, _ = running_lane_symbols(ps_args)
        assert symbols == frozenset({"A", "ABNB", "ADBE", "D"})


class TestWriteExcludeFile:
    def test_writes_one_symbol_per_line_and_returns_count(self, tmp_path):
        path = tmp_path / "exclude.txt"
        n = write_exclude_file(path, ps_args="\n".join([_HTF_LANE, _1D_LANE]))
        assert n == 3
        symbols = {
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        assert symbols == {"A", "ABNB", "ADBE"}

    def test_refuses_a_lane_without_symbols(self, tmp_path):
        """A dimension-wide grid lane cannot be excluded file-by-file: refuse
        loudly so the caller stops (blocked, not silently narrowed)."""
        with pytest.raises(RuntimeError, match="without --symbols"):
            write_exclude_file(tmp_path / "exclude.txt", ps_args=_NIGHTLY_STACK)
        assert not (tmp_path / "exclude.txt").exists()

    def test_no_lane_writes_an_empty_file(self, tmp_path):
        """Zero grid lanes is the normal quiet state: an empty (comment-only)
        file excludes nothing and the rewrite may run."""
        path = tmp_path / "exclude.txt"
        n = write_exclude_file(path, ps_args="\n".join([_1D_LANE, _UNRELATED]))
        assert n == 0
        assert path.exists()
        symbols = [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert symbols == []
