from __future__ import annotations

import asyncio
import dataclasses

import numpy as np
import pytest

from src.intelligence.measure import targets
from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import (
    build_target_panels,
    check_horizon,
    chunk_targets,
    stack_targets,
)
from src.intelligence.research import panel as panel_mod
from src.intelligence.research.panel import forward_returns
from tests.unit.measure.conftest import SLOTS, make_panel


def _split(panel, sizes):
    out, start = [], 0
    for size in sizes:
        idx = slice(start, start + size)
        out.append(
            dataclasses.replace(
                panel,
                symbols=panel.symbols[idx],
                open=panel.open[:, idx],
                close=panel.close[:, idx],
                volume=panel.volume[:, idx],
            )
        )
        start += size
    return out


def test_chunk_targets_daily_is_the_kernel(daily_panel_fx):
    got = chunk_targets(daily_panel_fx, 2)
    want = forward_returns(daily_panel_fx.open, 2, session=None)
    assert np.array_equal(got, want, equal_nan=True)


def test_chunk_targets_intraday_never_crosses_a_session(intraday_panel_fx):
    p = intraday_panel_fx
    got = chunk_targets(p, 3)
    want = forward_returns(p.open, 3, session=p.session)
    assert np.array_equal(got, want, equal_nan=True)
    session = p.session
    for t in np.flatnonzero(np.isfinite(got).any(axis=1)):
        assert session[t + 1] == session[t + 1 + 3]
    # entry and exit straddling the session boundary are NaN; a signal on the session's last
    # bar enters at the next session's first open and stays inside that session
    assert np.isnan(got[SLOTS - 2]).all() and np.isnan(got[SLOTS - 3]).all()
    assert np.isfinite(got[SLOTS - 1]).all()


def test_check_horizon():
    with pytest.raises(ValueError, match="1d clock"):
        check_horizon("15m", SLOTS, SLOTS)
    check_horizon("15m", SLOTS, SLOTS - 1)
    with pytest.raises(ValueError):
        check_horizon("15m", SLOTS, 0)
    with pytest.raises(ValueError):
        check_horizon("1d", 1, 0)
    check_horizon("1d", 1, 40)


@pytest.mark.parametrize("kind", ["daily", "intraday"])
def test_chunked_equals_unchunked(kind, daily_panel_fx, intraday_panel_fx):
    panel = daily_panel_fx if kind == "daily" else intraday_panel_fx
    stack = stack_targets(_split(panel, [5, 5, 2]), 2, "2027-01-01")
    assert stack.symbols == panel.symbols
    assert np.array_equal(stack.targets, chunk_targets(panel, 2), equal_nan=True)


def test_interior_gap_in_a_chunk_raises(daily_panel_fx):
    a, b = _split(daily_panel_fx, [6, 6])
    keep = np.ones(len(b.timestamps), dtype=bool)
    keep[10] = False
    gappy = dataclasses.replace(
        b,
        timestamps=b.timestamps[keep],
        valid=b.valid[keep],
        open=b.open[keep],
        close=b.close[keep],
        volume=b.volume[keep],
    )
    with pytest.raises(ValueError, match=b.symbols[0]):
        stack_targets([a, gappy], 1, "2027-01-01")


def test_late_start_chunk_is_accepted(symbols):
    full = make_panel(symbols[:5], 30, 1)
    late = make_panel(symbols[5:8], 30, 1, seed=1)
    cut = 8
    late = dataclasses.replace(
        late,
        timestamps=late.timestamps[cut:],
        valid=late.valid[cut:],
        open=late.open[cut:],
        close=late.close[cut:],
        volume=late.volume[cut:],
    )
    stack = stack_targets([full, late], 1, "2027-01-01")
    assert np.isnan(stack.targets[:cut, 5:]).all()
    assert np.isfinite(stack.targets[cut:-2, 5:]).all()


def test_mixed_clock_raises(daily_panel_fx, intraday_panel_fx):
    with pytest.raises(ValueError, match="clock"):
        stack_targets([daily_panel_fx, intraday_panel_fx], 1, "2027-01-01")


def test_duplicate_symbol_across_chunks_raises(daily_panel_fx):
    a = _split(daily_panel_fx, [5])[0]
    with pytest.raises(ValueError, match="more than one"):
        stack_targets([a, a], 1, "2027-01-01")


def test_max_target_end_is_before_end_exclusive(symbols):
    panel = make_panel(symbols, 20, 1, start="2026-01-05")
    end = str(panel.timestamps[-1] + np.timedelta64(1, "D"))  # first day past the panel
    stack = stack_targets([panel], 3, end)
    assert stack.max_target_end() < stack.end_exclusive
    assert stack.max_target_end() == panel.timestamps[-1]


def test_build_target_panels_chunks_and_guards(monkeypatch, tmp_path, params, symbols):
    calls = []

    async def fake_build_panel(dsn, out_dir, *, symbols, tf, start, end_exclusive, **kw):
        calls.append((list(symbols), tf, start, end_exclusive))
        return panel_mod.save(make_panel(tuple(symbols), 5, 1), out_dir)

    monkeypatch.setattr(targets.snapshot, "build_panel", fake_build_panel)
    oos = "2026-06-01T00:00:00+00:00"
    shuffled = list(reversed(symbols))
    paths = asyncio.run(
        build_target_panels("dsn", tmp_path, shuffled, "1d", "2026-01-01", oos, oos, params)
    )
    assert len(paths) == 3
    assert [c[0] for c in calls] == [
        sorted(symbols)[0:5],
        sorted(symbols)[5:10],
        sorted(symbols)[10:],
    ]
    assert all(c[3] == oos for c in calls)

    calls.clear()
    with pytest.raises(ValueError, match="later than oos_start"):
        asyncio.run(
            build_target_panels(
                "dsn",
                tmp_path,
                shuffled,
                "1d",
                "2026-01-01",
                "2026-06-02T00:00:00+00:00",
                oos,
                params,
            )
        )
    assert calls == []


def test_params_validation(params):
    with pytest.raises(ValueError):
        dataclasses.replace(params, min_stride=0)
    with pytest.raises(ValueError):
        dataclasses.replace(params, fdr_alpha=1.0)
    assert isinstance(params, MeasureParams)
