"""Held and refused counts are reported, never hidden behind APPLIED (review finding 4, 191-05)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pandas as pd

from scripts.ops.bars import ops_bar_load, ops_bar_nightly
from services import bar_load
from services.bar_load import LoadResult, load_status
from services.ohlcv_ingress_contract import IngressResult, RefusedSeries


def _refused(n: int) -> IngressResult:
    series = RefusedSeries("SPY", "5m", "alpaca", "sip_rth", 0.03, 0.02, n, n, "refused", n_held=n)
    return IngressResult(n, 0, 0, 0, True, 0, refused_series=(series,), n_held=n)


def test_load_result_counts_refused_series_across_chunks():
    result = LoadResult().plus(_refused(5)).plus(_refused(3))
    assert (result.n_held, result.n_refused_series, result.refused) == (8, 2, True)
    clean = LoadResult().plus(IngressResult(4, 4, 0, 0, False, 0))
    assert (clean.n_held, clean.n_refused_series, clean.refused) == (0, 0, False)


def test_load_status_is_applied_only_when_nothing_was_held():
    assert load_status(apply=False, held=3) == "PLANNED"
    assert load_status(apply=True, held=0) == "APPLIED"
    held = load_status(apply=True, held=3)
    assert held != "APPLIED" and "HELD" in held


def test_nightly_summary_counts_refused_and_held_and_does_not_print_applied(monkeypatch):
    def fake_series(conn, policy, symbol, frame, *, params, write):
        return LoadResult().plus(_refused(len(frame)))

    def fake_frame(conn, symbol, frame, **kw):
        return LoadResult(n_offered=len(frame), n_new=len(frame))

    monkeypatch.setattr(ops_bar_nightly, "load_series", fake_series)
    monkeypatch.setattr(ops_bar_nightly, "load_frame", fake_frame)

    page = SimpleNamespace(
        bars=[
            SimpleNamespace(
                timestamp=pd.Timestamp("2026-10-09 13:30", tz="UTC"),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )
        ]
    )

    class Leaf:
        async def connect(self):
            pass

        async def close(self):
            pass

        async def fetch_ohlcv(self, request, budget):
            return page

    sink = SimpleNamespace(flush=lambda: 0)
    policy = bar_load.LoadPolicy(vendor="alpaca", timeframe="5m", caller="x")
    summary = asyncio.run(
        ops_bar_nightly._run(Leaf(), None, sink, policy, None, ["SPY"], None, None, True)
    )
    assert summary["refused"] == 1 and summary["held"] == 1 and summary["errors"] == 0
    line = ops_bar_nightly.summary_line(summary, apply=True)
    assert "APPLIED" not in line and "1 held" in line and "1 refused" in line
    assert ops_bar_nightly.exit_code(summary) == 1
    clean = {"authored": 4, "raw_1d": 4, "errors": 0, "refused": 0, "held": 0, "unselected": 0}
    assert ops_bar_nightly.summary_line(clean, apply=True).startswith("APPLIED")
    assert ops_bar_nightly.exit_code(clean) == 0


def test_ops_bar_load_uses_the_shared_status():
    assert ops_bar_load.load_status is load_status


def test_unselected_slots_are_reported_and_fail_the_night():
    ingress = IngressResult(4, 4, 0, 0, False, 1, n_unselected=3)
    result = LoadResult().plus(ingress).plus(ingress)
    assert result.n_unselected == 6
    status = load_status(apply=True, held=0, unselected=6)
    assert status != "APPLIED" and "UNSELECTED" in status
    assert load_status(apply=True, held=2, unselected=6).startswith("HELD")
    assert load_status(apply=False, held=0, unselected=6) == "PLANNED"
    summary = {"authored": 4, "raw_1d": 0, "errors": 0, "refused": 0, "held": 0, "unselected": 6}
    assert "6 unselected" in ops_bar_nightly.summary_line(summary, apply=True)
    assert ops_bar_nightly.exit_code(summary) == 1
