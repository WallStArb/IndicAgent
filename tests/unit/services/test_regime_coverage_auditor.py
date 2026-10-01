"""Unit tests for regime_coverage_auditor. CI-clean: no DB, no network."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parents[3]))

import json
from datetime import date

import pytest

import services.regime_coverage_auditor as auditor
from services.regime_coverage_auditor import (
    _fetch_coverage_gaps,
    evaluate_gaps,
    parse_known_exceptions,
)


def _mock_cursor(gap_rows: list[dict]) -> MagicMock:
    cur = MagicMock()
    cur.fetchall.return_value = gap_rows
    return cur


def test_no_gap_returns_empty_list():
    cur = _mock_cursor([])
    assert _fetch_coverage_gaps(cur) == []
    cur.execute.assert_called_once()


def test_gap_found_returns_symbol_list():
    cur = _mock_cursor(
        [
            {"symbol": "LQD", "total_rows": 100, "non_null_regime_rows": 0},
            {"symbol": "SPY", "total_rows": 200, "non_null_regime_rows": 0},
        ]
    )
    assert _fetch_coverage_gaps(cur) == ["LQD", "SPY"]


TODAY = date(2026, 10, 1)


def _entry(symbol="BIL", expires="2026-12-01", **extra):
    return {
        "symbol": symbol,
        "reason": "degenerate fit",
        "expires": expires,
        "todo": "341",
        **extra,
    }


def test_gap_covered_by_a_live_exception_does_not_fail():
    result = evaluate_gaps(["BIL"], parse_known_exceptions([_entry()]), TODAY)
    assert not result.failed
    assert [e.symbol for e in result.excepted] == ["BIL"]
    assert result.unregistered == [] and result.expired == []


def test_unregistered_gap_fails():
    result = evaluate_gaps(["BIL", "XYZ"], parse_known_exceptions([_entry()]), TODAY)
    assert result.failed
    assert result.unregistered == ["XYZ"]


def test_expired_exception_fails_but_the_expiry_day_itself_is_honored():
    exceptions = parse_known_exceptions([_entry("BIL", "2026-09-30"), _entry("EMLC", "2026-10-01")])
    result = evaluate_gaps(["BIL", "EMLC"], exceptions, TODAY)
    assert result.expired == ["BIL"]
    assert [e.symbol for e in result.excepted] == ["EMLC"]
    assert result.failed


def test_stale_exception_is_reported_and_does_not_fail():
    result = evaluate_gaps([], parse_known_exceptions([_entry()]), TODAY)
    assert not result.failed
    assert [e.symbol for e in result.stale_exceptions] == ["BIL"]


@pytest.mark.parametrize(
    "bad",
    [
        [{"reason": "r", "expires": "2026-12-01"}],
        [{"symbol": "BIL", "expires": "2026-12-01"}],
        [{"symbol": "BIL", "reason": "r"}],
        [{"symbol": "BIL", "reason": "r", "expires": "01/12/2026"}],
        [{"symbol": "BIL", "reason": "r", "expires": "2026-12-01"}] * 2,
        {"symbol": "BIL"},
        ["BIL"],
    ],
)
def test_malformed_exception_list_raises(bad):
    with pytest.raises(ValueError):
        parse_known_exceptions(bad)


def test_exception_list_parses_from_a_json_string_or_a_parsed_list():
    assert parse_known_exceptions(json.dumps([_entry()])) == parse_known_exceptions([_entry()])
    assert parse_known_exceptions("[]") == []


def _run_main(monkeypatch, gaps, raw_exceptions):
    class _Cfg:
        def get_sync(self, key, default=None):
            assert key == auditor._EXCEPTIONS_KEY
            return raw_exceptions

    class _Conn:
        def close(self):
            pass

        def cursor(self, **_kwargs):
            raise AssertionError("cursor is stubbed by _fetch_coverage_gaps")

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    conn = _Conn()
    conn.cursor = lambda **_kwargs: _Cursor()  # type: ignore[method-assign]
    monkeypatch.setattr(auditor, "Settings", lambda: object())
    monkeypatch.setattr(auditor, "_connect_db", lambda _settings: conn)
    monkeypatch.setattr(auditor, "load_config_service_sync", lambda _conn: _Cfg())
    monkeypatch.setattr(auditor, "_fetch_coverage_gaps", lambda _cur: gaps)
    monkeypatch.setattr(auditor, "init_otel_providers", lambda **_kw: None)
    monkeypatch.setattr(auditor, "flush_and_shutdown_metrics", lambda: None)
    statuses = []
    monkeypatch.setattr(
        auditor.JOB_COMPLETED_TOTAL, "add", lambda _n, attrs: statuses.append(attrs["status"])
    )
    with pytest.raises(SystemExit) as exit_info:
        auditor.main()
    return exit_info.value.code, statuses[-1]


def test_main_exits_zero_when_every_gap_is_excepted(monkeypatch):
    code, status = _run_main(monkeypatch, ["BIL"], json.dumps([_entry(expires="2999-01-01")]))
    assert (code, status) == (0, "success")


def test_main_exits_one_on_an_unregistered_gap(monkeypatch):
    code, status = _run_main(
        monkeypatch, ["BIL", "NEW"], json.dumps([_entry(expires="2999-01-01")])
    )
    assert (code, status) == (1, "gap_found")


def test_main_exits_one_with_failure_status_on_a_malformed_list(monkeypatch):
    code, status = _run_main(monkeypatch, [], json.dumps([{"symbol": "BIL"}]))
    assert (code, status) == (1, "failure")
