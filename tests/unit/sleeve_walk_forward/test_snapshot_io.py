"""Snapshot helpers that need no database."""

from datetime import datetime

import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.snapshot import (
    _labels_by_session,
    _write,
    session_calendar,
    verify_snapshot,
)

SESSIONS = np.array(["2020-01-02", "2020-01-03"], dtype="datetime64[D]")


def test_labels_by_session_places_each_group_label():
    rows = [("equity", datetime(2020, 1, 3), "hi"), ("rates", datetime(2020, 1, 2), "flat")]
    assert _labels_by_session(SESSIONS, rows, "equity").tolist() == ["", "hi"]


def test_duplicate_label_for_a_group_day_raises():
    rows = [("equity", datetime(2020, 1, 3), "hi"), ("equity", datetime(2020, 1, 3), "lo")]
    with pytest.raises(ValueError, match="duplicate"):
        _labels_by_session(SESSIONS, rows, "equity")


def test_verify_snapshot_detects_tampering(tmp_path):
    path = _write(tmp_path, {"a": np.arange(5.0), "b": np.ones(3)}, {"manifest": {}})
    verify_snapshot(path)
    np.save(path / "a.npy", np.arange(5.0) + 1)
    with pytest.raises(ValueError, match="hash"):
        verify_snapshot(path)


def _block(*days: str) -> dict[str, np.ndarray]:
    return {"bar_ts": np.array(days, dtype="datetime64[D]")}


def test_session_calendar_is_the_union_of_every_symbols_dates():
    # 2007-07-02 has no SPY row (its bar is a synthetic fill) but is a real session for others.
    spy = _block("2007-06-29", "2007-07-03")
    gld = _block("2007-06-29", "2007-07-02", "2007-07-03")
    days = session_calendar([spy, None, gld])
    assert (
        days.tolist()
        == np.array(["2007-06-29", "2007-07-02", "2007-07-03"], dtype="datetime64[D]").tolist()
    )


def test_session_calendar_rejects_weekend_rows():
    with pytest.raises(ValueError, match="weekend"):
        session_calendar([_block("2007-06-29", "2007-06-30")])
