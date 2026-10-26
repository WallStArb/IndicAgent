"""Bar load engine no-drop semantics (todo 528 R1, phase 191 plan 05).

Raw is stored per source: the loader offers every row the vendor served to ohlcv_raw, regular
hours and extended hours alike, whatever any other source holds. Nothing is split, skipped or
dropped before the contract. Every offered row lands in ohlcv_raw last-wins (D-191-N: nothing is
refused or held); the LoadResult counts add up to the rows offered.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.infrastructure.backfill._intraday_persist import PersistResult
from services import bar_load
from services.bar_load import LoadPolicy, frame_to_raw_rows, load_frame, load_series
from services.ohlcv_ingress_contract import IngressResult

POLICY = LoadPolicy(vendor="alpaca", timeframe="5m", caller="test-load")


def _frame(rows: list[str]) -> pd.DataFrame:
    """ISO stamps -> canonical frame; 13:30/13:35 UTC are RTH slots, 12:00 is pre-market."""
    stamps = [pd.Timestamp(t, tz="UTC") for t in rows]
    return pd.DataFrame(
        {
            "t": stamps,
            "o": [1.0] * len(rows),
            "h": [1.0] * len(rows),
            "l": [1.0] * len(rows),
            "c": [1.0] * len(rows),
            "v": [100] * len(rows),
        }
    )


ANSWERED = pd.Timestamp("2026-10-09 21:00", tz="UTC").to_pydatetime()


def test_a_write_without_the_answer_time_raises(persisted) -> None:
    # fourth review of 191-07, finding 1: served_at is never the load time
    frame = _frame(["2026-10-09 13:30:00"])
    with pytest.raises(ValueError, match="answer time"):
        load_series(object(), POLICY, "SPY", frame, write=True)
    assert persisted.calls == []


@pytest.fixture
def persisted(monkeypatch):
    """persist_chunk_atomically replaced by a recorder; every row lands new."""
    state = type("State", (), {"calls": []})()

    def fake(conn, *, request_rows, raw_rows, coverage=None, caller, params=None, **kw):
        state.calls.append(
            {
                "rows": list(raw_rows),
                "coverage": coverage,
                "caller": caller,
                "answered_at": kw.get("answered_at"),
            }
        )
        return PersistResult(
            0,
            len(raw_rows),
            IngressResult(
                n_offered=len(raw_rows),
                n_new=len(raw_rows),
                n_changed=0,
                n_unchanged=0,
                selected_slots=0,
            ),
        )

    monkeypatch.setattr(bar_load, "persist_chunk_atomically", fake)
    return state


def test_frame_rows_carry_the_vendor_and_its_kind_and_keep_every_row() -> None:
    frame = _frame(["2026-10-09 12:00:00", "2026-10-09 13:30:00", "2026-10-09 13:35:00"])
    rows = frame_to_raw_rows(frame, "SPY", vendor="alpaca", timeframe="5m")
    assert [r.timestamp.hour for r in rows] == [12, 13, 13]
    assert {(r.vendor, r.kind, r.timeframe, r.symbol) for r in rows} == {
        ("alpaca", "sip_rth", "5m", "SPY")
    }
    assert rows[0].volume == 100 and isinstance(rows[0].volume, int)


def test_explicit_kind_names_the_served_basis_and_an_unserved_kind_raises() -> None:
    """The nightly's feed-derived kind override: an iex answer is written iex_rth, and the
    vendor-served check makes the sip_rth basis lie impossible."""
    frame = _frame(["2026-10-09 13:30:00"])
    rows = frame_to_raw_rows(frame, "SPY", vendor="alpaca", timeframe="5m", kind="iex_rth")
    assert {(r.vendor, r.kind) for r in rows} == {("alpaca", "iex_rth")}
    with pytest.raises(ValueError, match="does not serve kind 'sip_rth'"):
        frame_to_raw_rows(frame, "SPY", vendor="tradier", timeframe="1d", kind="sip_rth")


def test_policy_kind_reaches_the_raw_rows(persisted) -> None:
    policy_iex = LoadPolicy(vendor="alpaca", timeframe="5m", caller="test-load-iex", kind="iex_rth")
    frame = _frame(["2026-10-09 13:30:00"])
    result = load_series(object(), policy_iex, "SPY", frame, write=True, answered_at=ANSWERED)
    (call,) = persisted.calls
    assert {(r.vendor, r.kind) for r in call["rows"]} == {("alpaca", "iex_rth")}
    assert result.n_offered == 1


def test_five_minute_is_not_derivation_owned_and_the_grid_helpers_are_gone() -> None:
    from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES

    assert "5m" not in DERIVATION_OWNED_TIMEFRAMES
    for retired in ("session_grid", "grid_stamps_utc", "filter_frame_to_grid"):
        assert not hasattr(bar_load, retired)


def test_every_row_is_offered_regardless_of_session_grid_or_other_sources(persisted) -> None:
    frame = _frame(["2026-10-09 12:00:00", "2026-10-09 13:30:00", "2026-10-09 13:35:00"])
    result = load_series(object(), POLICY, "SPY", frame, write=True, answered_at=ANSWERED)
    (call,) = persisted.calls
    assert call["answered_at"] == ANSWERED  # the artifact's answer time is the serve time
    assert len(call["rows"]) == 3  # pre-market included; nothing consulted another source
    assert (result.n_offered, result.n_new) == (3, 3)


def test_dry_run_writes_nothing_and_plans_the_offered_count(persisted) -> None:
    frame = _frame(["2026-10-09 13:30:00", "2026-10-09 13:35:00"])
    result = load_series(object(), POLICY, "SPY", frame, write=False)
    assert persisted.calls == [] and result.n_offered == 2


def test_chunks_commit_separately_and_coverage_names_the_vendor(persisted) -> None:
    frame = _frame([f"2026-10-09 13:{m:02d}:00" for m in range(30, 50, 5)] * 1)
    progress: list[tuple[int, int]] = []
    result = load_series(
        object(),
        POLICY,
        "SPY",
        frame,
        write=True,
        answered_at=ANSWERED,
        chunk_rows=3,
        on_chunk=lambda a, b: progress.append((a, b)),
    )
    assert [len(c["rows"]) for c in persisted.calls] == [3, 1]
    assert progress == [(3, 4), (4, 4)] and result.n_offered == 4
    coverage = persisted.calls[0]["coverage"]
    assert (coverage.symbol, coverage.timeframe, coverage.provider) == ("SPY", "5m", "alpaca")


def test_load_frame_without_coverage_is_a_raw_only_capture(persisted) -> None:
    frame = _frame(["2026-10-09 00:00:00"])
    load_frame(
        object(),
        "SPY",
        frame,
        vendor="alpaca",
        timeframe="1d",
        caller="x-1d",
        write=True,
        answered_at=ANSWERED,
        coverage=False,
    )
    assert persisted.calls[0]["coverage"] is None and persisted.calls[0]["caller"] == "x-1d"


def test_the_derivation_owned_timeframe_fence_still_refuses_a_policy() -> None:
    with pytest.raises(ValueError, match="derivation-owned"):
        LoadPolicy(vendor="alpaca", timeframe="15m", caller="x")


def test_the_loader_defines_no_split_or_archive_helper() -> None:
    for retired in ("split_series", "archive_rows", "archive_frame_to_tuples", "drop_stored_rows"):
        assert not hasattr(bar_load, retired)
