"""Snapshot helpers that need no database."""

from datetime import datetime

import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.snapshot import (
    _labels_by_session,
    _write,
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
