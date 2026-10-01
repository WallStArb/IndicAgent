"""Unit tests for regime_coverage_auditor. CI-clean: no DB, no network."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parents[3]))

import json
from datetime import UTC, date, datetime, timedelta

import pytest

import services.regime_coverage_auditor as auditor
from services.regime_coverage_auditor import (
    KIND_PERMANENT,
    KIND_REBUILD,
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
        "kind": KIND_REBUILD,
        "reason": "degenerate fit",
        "expires": expires,
        "clears_on": "186-26 rebuild",
        "todo": "341",
        **extra,
    }


def _permanent(symbol="XYZ", **extra):
    return {"symbol": symbol, "kind": KIND_PERMANENT, "reason": "flat price, no variance", **extra}


def test_gap_covered_by_a_live_exception_does_not_fail():
    result = evaluate_gaps(["BIL"], parse_known_exceptions([_entry()]), TODAY)
    assert not result.failed
    assert [e.symbol for e in result.excepted] == ["BIL"]
    assert result.unregistered == [] and result.expired == []


def test_unregistered_gap_fails():
    result = evaluate_gaps(["BIL", "ABC"], parse_known_exceptions([_entry()]), TODAY)
    assert result.failed
    assert result.unregistered == ["ABC"]


def test_expired_exception_fails_but_the_expiry_day_itself_is_honored():
    exceptions = parse_known_exceptions([_entry("BIL", "2026-09-30"), _entry("EMLC", "2026-10-01")])
    result = evaluate_gaps(["BIL", "EMLC"], exceptions, TODAY)
    assert result.expired == ["BIL"]
    assert [e.symbol for e in result.excepted] == ["EMLC"]
    assert result.failed


def test_a_permanent_exception_never_expires():
    exceptions = parse_known_exceptions([_permanent()])
    assert exceptions[0].expires is None and exceptions[0].kind == KIND_PERMANENT
    result = evaluate_gaps(["XYZ"], exceptions, date(2099, 1, 1))
    assert not result.failed and [e.symbol for e in result.excepted] == ["XYZ"]


def test_stale_exception_is_reported_and_does_not_fail():
    result = evaluate_gaps([], parse_known_exceptions([_entry()]), TODAY)
    assert not result.failed
    assert [e.symbol for e in result.stale_exceptions] == ["BIL"]


def test_fields_are_parsed():
    (entry,) = parse_known_exceptions([_entry()])
    assert (entry.kind, entry.clears_on, entry.expires, entry.todo) == (
        KIND_REBUILD,
        "186-26 rebuild",
        date(2026, 12, 1),
        "341",
    )


@pytest.mark.parametrize(
    "bad",
    [
        [{**_entry(), "symbol": ""}],
        [{k: v for k, v in _entry().items() if k != "symbol"}],
        [{k: v for k, v in _entry().items() if k != "reason"}],
        [{k: v for k, v in _entry().items() if k != "kind"}],
        [{**_entry(), "kind": "forever"}],
        [{k: v for k, v in _entry().items() if k != "expires"}],  # rebuild_pending needs expires
        [{k: v for k, v in _entry().items() if k != "clears_on"}],  # and the trigger it clears on
        [_entry(expires="01/12/2026")],
        [{k: v for k, v in _permanent().items() if k != "reason"}],
        [_permanent(expires="2026-12-01")],  # permanent has no expiry
        [_entry(), _entry()],
        {"symbol": "BIL"},
        ["BIL"],
    ],
)
def test_malformed_exception_list_raises(bad):
    with pytest.raises(ValueError):
        parse_known_exceptions(bad)


def test_permanent_exceptions_are_capped():
    entries = [_permanent("AAA"), _permanent("BBB"), _permanent("CCC")]
    assert len(parse_known_exceptions(entries, max_permanent=3)) == 3
    with pytest.raises(ValueError, match="permanent"):
        parse_known_exceptions(entries, max_permanent=2)


def test_exception_list_parses_from_a_json_string_or_a_parsed_list():
    assert parse_known_exceptions(json.dumps([_entry()])) == parse_known_exceptions([_entry()])
    assert parse_known_exceptions("[]") == []


class _Gauges:
    def __init__(self, monkeypatch):
        self.live = []
        self.days = []
        monkeypatch.setattr(
            auditor._EXCEPTIONS_LIVE, "set", lambda value, *a, **k: self.live.append(value)
        )
        monkeypatch.setattr(
            auditor._DAYS_TO_EARLIEST_EXPIRY, "set", lambda value, *a, **k: self.days.append(value)
        )


def _run_main(monkeypatch, gaps, raw_exceptions, max_permanent=5):
    class _Cfg:
        def get_sync(self, key, default=None):
            if key == auditor._EXCEPTIONS_KEY:
                return raw_exceptions
            assert key == auditor._MAX_PERMANENT_KEY
            return max_permanent

    class _Conn:
        def close(self):
            pass

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


def test_main_exits_one_with_failure_status_when_the_permanent_cap_is_exceeded(monkeypatch):
    raw = json.dumps([_permanent("AAA"), _permanent("BBB")])
    assert _run_main(monkeypatch, [], raw, max_permanent=1) == (1, "failure")


def test_main_emits_the_live_count_and_days_to_the_earliest_expiry(monkeypatch):
    gauges = _Gauges(monkeypatch)
    today = datetime.now(UTC).date()
    raw = json.dumps(
        [
            _entry("BIL", (today + timedelta(days=40)).isoformat()),
            _entry("EMLC", (today + timedelta(days=12)).isoformat()),
            _entry("OLD", (today - timedelta(days=1)).isoformat()),  # expired: not live
            _permanent("XYZ"),
        ]
    )
    _run_main(monkeypatch, ["BIL"], raw)
    assert gauges.live == [3]  # BIL, EMLC and the permanent entry; the expired one is not live
    assert gauges.days == [12]


def test_main_sets_no_days_gauge_when_nothing_expires(monkeypatch):
    gauges = _Gauges(monkeypatch)
    _run_main(monkeypatch, [], json.dumps([_permanent()]))
    assert gauges.live == [1] and gauges.days == []


def test_main_lists_the_permanent_exceptions_every_run(monkeypatch):
    events = []
    monkeypatch.setattr(
        auditor._logger, "info", lambda event, **kw: events.append((event, kw)), raising=False
    )
    _run_main(monkeypatch, [], json.dumps([_permanent("XYZ")]))
    listed = [kw for event, kw in events if event == "regime_coverage_auditor.permanent_exceptions"]
    assert listed and listed[0]["symbols"] == ["XYZ"]
