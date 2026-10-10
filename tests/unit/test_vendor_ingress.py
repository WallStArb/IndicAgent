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
