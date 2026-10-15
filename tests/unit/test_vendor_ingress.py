"""Vendor ingress seam: registry resolution and artifact normalization."""

from __future__ import annotations

import pandas as pd
import pytest

from src.intelligence.bars.vendor_ingress import stamp_floor, vendor_ingress


def _write_parquet(directory, symbol: str, stamps: list[str]) -> None:
    frame = pd.DataFrame(
        {
            "t": stamps,
            "o": [1.0] * len(stamps),
            "h": [1.0] * len(stamps),
            "l": [1.0] * len(stamps),
            "c": [1.0] * len(stamps),
            "v": [100] * len(stamps),
        }
    )
    frame.to_parquet(directory / f"{symbol}_5Min.parquet")


def test_vendor_ingress_resolves_alpaca_5m() -> None:
    ingress = vendor_ingress("alpaca", "5m")
    assert ingress.source == "alpaca"
    assert ingress.timeframe == "5m"


def test_vendor_ingress_rejects_unknown_pairs() -> None:
    with pytest.raises(ValueError, match="no vendor ingress"):
        vendor_ingress("tradier", "5m")
    with pytest.raises(ValueError, match="no vendor ingress"):
        vendor_ingress("alpaca", "1d")


def test_read_artifacts_normalizes_to_canonical_frame(tmp_path) -> None:
    _write_parquet(tmp_path, "AAL", ["2026-10-09 13:30:00+00:00", "2026-10-09 13:35:00+00:00"])
    _write_parquet(tmp_path, "AAPL", ["2026-10-09 13:32:17+00:00"])

    artifacts = vendor_ingress("alpaca", "5m").read_artifacts(tmp_path)

    assert sorted(artifacts) == ["AAL", "AAPL"]
    aal = artifacts["AAL"]
    assert list(aal.columns) == ["t", "o", "h", "l", "c", "v"]
    assert str(aal["t"].dt.tz) == "UTC"
    # stamps floored to the 5m grid so they survive the session-grid filter
    assert list(aal["t"]) == list(
        pd.to_datetime(["2026-10-09 13:30:00+00:00", "2026-10-09 13:35:00+00:00"])
    )
    aapl = artifacts["AAPL"]
    assert list(aapl["t"]) == list(pd.to_datetime(["2026-10-09 13:30:00+00:00"]))


def test_read_artifacts_ignores_complete_markers(tmp_path) -> None:
    _write_parquet(tmp_path, "AAL", ["2026-10-09 13:30:00+00:00"])
    (tmp_path / "AAL_5Min.complete").write_text("{}")
    artifacts = vendor_ingress("alpaca", "5m").read_artifacts(tmp_path)
    assert sorted(artifacts) == ["AAL"]


def test_stamp_floor_matches_timeframe_vocabulary() -> None:
    assert stamp_floor("5m") == "5min"
    assert stamp_floor("1m") == "1min"
    with pytest.raises(KeyError):
        stamp_floor("1d")


def test_an_artifact_reports_its_recorded_fetch_time_not_the_load_time(tmp_path) -> None:
    # fourth review of 191-07, finding 1: a replayed artifact keeps its own serve time
    import os
    from datetime import UTC, datetime

    _write_parquet(tmp_path, "SPY", ["2026-10-09T13:30:00Z"])
    fetched = datetime(2026, 10, 9, 21, 5, tzinfo=UTC)
    os.utime(tmp_path / "SPY_5Min.parquet", (fetched.timestamp(), fetched.timestamp()))
    assert vendor_ingress("alpaca", "5m").answered_at(tmp_path, "SPY") == fetched


def test_the_pulls_answer_time_in_the_metadata_wins_over_a_moved_mtime(tmp_path) -> None:
    # review of 191-08, M2: a rewrite or copy moves the mtime; the recorded answer time stays
    import os
    from datetime import UTC, datetime

    from src.intelligence.bars.vendor_ingress import write_alpaca_artifact

    frame = pd.DataFrame(
        {"t": ["2026-10-09T19:55:00Z"], "o": [1.0], "h": [1.0], "l": [1.0], "c": [1.0], "v": [1]}
    )
    answered = datetime(2026, 10, 9, 21, 5, tzinfo=UTC)
    write_alpaca_artifact(frame, tmp_path / "SPY_5Min.parquet", answered)
    later = datetime(2026, 12, 1, tzinfo=UTC).timestamp()
    os.utime(tmp_path / "SPY_5Min.parquet", (later, later))
    assert vendor_ingress("alpaca", "5m").answered_at(tmp_path, "SPY") == answered
    read = vendor_ingress("alpaca", "5m").read_artifacts(tmp_path, None)["SPY"]
    assert len(read) == 1
    with pytest.raises(ValueError, match="timezone-aware"):
        write_alpaca_artifact(frame, tmp_path / "X_5Min.parquet", datetime(2026, 10, 9))


def test_an_implausible_answer_time_is_refused() -> None:
    from datetime import UTC, datetime, timedelta

    from src.intelligence.bars.vendor_ingress import check_answered_at

    frame = pd.DataFrame({"t": pd.to_datetime(["2026-10-09T19:55:00Z"], utc=True)})
    newest = datetime(2026, 10, 9, 19, 55, tzinfo=UTC)
    lag = timedelta(hours=120)
    check_answered_at(newest + timedelta(hours=1), frame, max_lag=lag, where="SPY")
    check_answered_at(newest, frame.iloc[0:0], max_lag=lag, where="SPY")  # empty passes
    with pytest.raises(ValueError, match="not after the newest bar"):
        check_answered_at(newest, frame, max_lag=lag, where="SPY")
    with pytest.raises(ValueError, match="rewritten or copied"):
        check_answered_at(newest + timedelta(days=30), frame, max_lag=lag, where="SPY")
