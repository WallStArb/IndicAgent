"""Massive serve time from the downloader manifest record, and the one-file-per-call rule."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.intelligence.bars.vendor_ingress import (
    massive_answered_at,
    massive_day_file,
    vendor_ingress,
)

REL = "minute_aggs_v1/2024/06/2024-06-11.csv.gz"


def _setup(tmp_path: Path, **overrides):
    day_file = tmp_path / REL
    day_file.parent.mkdir(parents=True)
    day_file.write_bytes(b"")
    record = {
        "path": REL,
        "etag": "abc",
        "last_modified": "2026-03-30T19:05:52.379Z",
        "downloaded_at": "2026-11-10T12:00:00+00:00",
        **overrides,
    }
    manifest = tmp_path / "manifest.jsonl"
    older = {**record, "etag": "old", "last_modified": "2026-03-01T00:00:00.000Z"}
    manifest.write_text(json.dumps(older) + "\n" + json.dumps(record) + "\n")  # latest wins
    return day_file, manifest


def test_answered_at_is_the_latest_record_last_modified(tmp_path):
    day_file, manifest = _setup(tmp_path)
    assert massive_answered_at(day_file, "AAPL", manifest) == datetime(
        2026, 3, 30, 19, 5, 52, 379000, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"etag": ""}, "no etag"),
        ({"last_modified": None}, "no etag or last_modified"),
        ({"last_modified": "2024-06-11T19:00:00.000Z"}, "not after the session"),  # before 20:00Z
        ({"last_modified": "2026-12-01T00:00:00.000Z"}, "after the download"),
    ],
)
def test_a_bad_record_fails_loudly(tmp_path, override, message):
    day_file, manifest = _setup(tmp_path, **override)
    with pytest.raises(ValueError, match=message):
        massive_answered_at(day_file, "AAPL", manifest)


def test_a_file_with_no_manifest_record_fails(tmp_path):
    day_file, manifest = _setup(tmp_path)
    manifest.write_text("")
    with pytest.raises(ValueError, match="no manifest record"):
        massive_answered_at(day_file, "AAPL", manifest)


def test_one_day_file_per_call(tmp_path):
    day_file, _ = _setup(tmp_path)
    assert massive_day_file(day_file) == day_file
    assert massive_day_file(tmp_path / "minute_aggs_v1") == day_file
    (day_file.parent / "2024-06-12.csv.gz").write_bytes(b"")
    with pytest.raises(ValueError, match="one day file per call"):
        massive_day_file(tmp_path / "minute_aggs_v1")


def test_ingress_rows_skip_the_alpaca_lag_bound():
    for timeframe, kind in (("5m", "sip_flat_agg"), ("1d", "sip_flat")):
        row = vendor_ingress("massive", timeframe)
        assert (row.kind, row.check_lag) == (kind, False)
    assert vendor_ingress("alpaca", "5m").check_lag is True
