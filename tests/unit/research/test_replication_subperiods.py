"""R-1 sub-period disclosure (ledger 2026-11-23b): no DB, no network, no real series."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import scripts.research.replication_subperiods as rs
from scripts.research.replication_subperiods import (
    Cell,
    ReplicationError,
    cell_stats,
    format_report,
    run_cells,
)
from src.intelligence.research.spec import parse_spec_text

ROOT = Path(__file__).resolve().parents[3]


def parse_loaded(text):
    """What load_spec_from_blob returns, for the one field the script reads."""
    return SimpleNamespace(model=parse_spec_text(text))


def _days(n: int, start: date = date(2010, 1, 4)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def test_cell_bounds_are_inclusive_and_exclude_outside_sessions():
    days = _days(10)
    series = [100.0] + [0.01, -0.01] * 4 + [100.0]  # outliers on both outer sessions
    cell = cell_stats(days, series, days[1], days[8], overlap=0)
    assert (cell.n_sessions, cell.n_finite, cell.n_nonfinite) == (8, 8, 0)
    assert (cell.first_session, cell.last_session) == (days[1], days[8])
    assert cell.mean_session_pnl == pytest.approx(0.0)


def test_mean_and_t_follow_the_stored_series():
    rng = np.random.default_rng(7)
    x = rng.normal(0.002, 0.01, 400)
    days = _days(400)
    cell = cell_stats(days, x, days[0], days[-1], overlap=4)
    assert cell.mean_session_pnl == pytest.approx(float(x.mean()))
    assert cell.t > 0 and 0 < cell.p < 0.5


def test_nonfinite_sessions_are_counted_and_never_read_as_zero():
    days = _days(6)
    series = [0.01, float("nan"), 0.03, 0.01, float("inf"), 0.03]
    cell = cell_stats(days, series, days[0], days[-1], overlap=0)
    assert cell.n_nonfinite == 2 and cell.n_finite == 4
    assert cell.mean_session_pnl == pytest.approx(0.02)  # a zero fill would read 0.0133


def test_cell_with_no_stored_session_raises_not_skips():
    days = _days(5)
    with pytest.raises(ReplicationError, match="no stored session"):
        cell_stats(days, [0.01] * 5, date(2030, 1, 1), date(2030, 12, 31), overlap=0)


def test_cell_with_too_few_finite_sessions_raises():
    days = _days(3)
    with pytest.raises(ReplicationError, match="finite sessions"):
        cell_stats(days, [0.01, float("nan"), float("nan")], days[0], days[-1], overlap=0)


def test_length_mismatch_raises():
    with pytest.raises(ReplicationError, match="lengths differ"):
        cell_stats(_days(3), [0.0, 0.0], date(2010, 1, 1), date(2011, 1, 1), overlap=0)


def test_run_cells_use_the_recorded_spec_sub_periods_and_horizon_overlap(monkeypatch):
    """The sub-periods come from the recorded spec blob (here the committed core spec), not from
    the caller: three cells, and the overlap is horizon - 1."""
    text = (ROOT / "research/specs/daily_residual_h5_core.yaml").read_text()
    monkeypatch.setattr(rs, "load_spec_from_blob", lambda root, rel, blob: parse_loaded(text))
    days = _days(7000, date(2007, 3, 1))
    rng = np.random.default_rng(3)
    row = {
        "run_id": "r",
        "spec_path": "research/specs/daily_residual_h5_core.yaml",
        "spec_blob": "b",
        "sessions": days,
        "d_s": rng.normal(0, 0.01, 7000),
    }
    seen = []
    real = rs.hac_total_test
    monkeypatch.setattr(rs, "hac_total_test", lambda *args: (seen.append(args[3]), real(*args))[1])
    cells = run_cells(row, ROOT)
    spec = parse_spec_text(text)
    assert seen == [spec.horizon - 1] * 3
    assert [(c.start.isoformat(), c.end.isoformat()) for c in cells] == [
        tuple(p) for p in spec.scoring.sub_periods
    ]
    assert len(cells) == 3


def test_report_labels_non_independence_and_flags_non_positive_cells():
    pos = Cell(date(2010, 1, 1), date(2011, 1, 1), 250, 250, 0, 1e-4, 1.5, 0.07)
    neg = Cell(date(2011, 1, 2), date(2012, 1, 1), 250, 249, 1, -2e-4, -0.5, 0.69)
    row = {
        "run_group": "c249e9bb-0000",
        "spec_hash": "096abd79ff",
        "concept": "member.x.reversal_21",
    }
    text = format_report("reversal_21", [(row, [pos, neg])])
    assert "NOT INDEPENDENT" in text and "charges no look" in text
    assert "NON-POSITIVE" in text and "cells 2, non-positive 1" in text


def test_cell_reports_the_stored_span_inside_a_cut_short_sub_period():
    days = _days(20)
    cell = cell_stats(days, [0.01, 0.02] * 10, date(2009, 1, 1), days[-1], overlap=0)
    assert (cell.first_session, cell.last_session) == (days[0], days[-1])
