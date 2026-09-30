"""Unit tests for the D1 bootstrap (scripts/ops/bars/ops_d1_bootstrap.py), fakes only."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.ops.bars import ops_d1_bootstrap as mod
from services.ohlcv_observation_writer import _observation_rows, _request_row

_NOW = datetime(2026, 9, 30, tzinfo=UTC)
_RUN = "11111111-1111-1111-1111-111111111111"


def _rows():
    return [
        (datetime(2020, 1, 2, tzinfo=UTC), 10.0, 11.0, 9.0, 10.5, 1000),
        (datetime(2020, 1, 3, tzinfo=UTC), 10.5, 12.0, 10.0, 11.0, 2000),
    ]


def test_legacy_records_map_to_request_and_observation_rows() -> None:
    request, bars = mod.legacy_records("AAA", _rows(), fetch_run_id=_RUN, now=_NOW)
    assert request.route == "LEGACY_IMPORT"
    assert request.outcome == "legacy_import"
    assert request.what_to_show == "TRADES"
    assert request.n_bars == 2
    assert request.window_start == _rows()[0][0]
    assert request.window_end == _rows()[1][0]
    req_row = _request_row(request, caller="d1-bootstrap", source="ibkr")
    assert req_row[5] == "LEGACY_IMPORT" and req_row[11] == "legacy_import"
    assert req_row[16] == "d1-bootstrap"
    obs = _observation_rows(request, bars, source="ibkr", fetched_at=_NOW)
    assert [row[3].isoformat() for row in obs] == ["2020-01-02", "2020-01-03"]
    assert obs[0][5] == 11.0 and obs[0][8] == 1000
    assert obs[0][10] == "LEGACY_IMPORT" and obs[0][11] == "TRADES"


def test_legacy_records_refuse_empty_symbol() -> None:
    with pytest.raises(ValueError):
        mod.legacy_records("AAA", [], fetch_run_id=_RUN, now=_NOW)


def test_order_puts_mrna_and_alms_first() -> None:
    assert mod.order_symbols(["ZZZ", "AAPL", "ALMS", "MRNA"]) == ["MRNA", "ALMS", "AAPL", "ZZZ"]


def test_resume_refetches_a_symbol_missing_either_series() -> None:
    outcomes = {
        "BOTH": {"TRADES": ["bars"], "ADJUSTED_LAST": ["no_data"]},
        "ONLY_TRADES": {"TRADES": ["bars"]},
        "FAILED_ADJ": {"TRADES": ["bars"], "ADJUSTED_LAST": ["failed", "timeout"]},
        "RETRIED": {"TRADES": ["bars"], "ADJUSTED_LAST": ["failed", "bars"]},
    }
    done = mod.symbols_done(outcomes)
    assert done == {"BOTH", "RETRIED"}
    todo = mod.pending_symbols(["BOTH", "ONLY_TRADES", "FAILED_ADJ", "RETRIED", "MRNA"], done)
    assert todo == ["MRNA", "FAILED_ADJ", "ONLY_TRADES"]
