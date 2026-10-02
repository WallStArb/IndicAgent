"""Unit tests for the D-28 data bar check CLI (plan 185-16).

Every condition is a pure predicate over query results (T-185-16-01: no
hard-coded pass, every verdict carries evidence counts). The database is never
touched: the CLI's gather step is exercised through a fake cursor that records
SQL and replays canned rows.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from scripts.ops.bars import ops_data_bar_check as mod

_FIXTURE = (
    __file__.rsplit("/tests/", 1)[0] + "/tests/fixtures/bars/corrupt_1d_dry_run_2026_09_26.txt"
)


# --- fixture parsing ---------------------------------------------------------------


def test_parse_dry_run_keys_takes_confirmed_and_market_event_1d_rows_only() -> None:
    text = """# header

## CONFIRMED_CORRUPT (2)

| symbol | tf | timestamp | open |
|---|---|---|---|
| AMAT | 1d | 2007-01-16T00:00:00Z | 19.5 |
| XY | 5m | 2007-01-16T14:30:00Z | 1.0 |

## AMBIGUOUS (1)

| symbol | tf | timestamp |
|---|---|---|
| NOPE | 1d | 2008-01-02T00:00:00Z |

## MARKET_EVENT (1)

| symbol | tf | timestamp |
|---|---|---|
| LEH | 1d | 2008-09-15T00:00:00Z |
"""
    keys = mod.parse_dry_run_keys(text)
    assert keys == (
        ("AMAT", "2007-01-16T00:00:00Z"),
        ("LEH", "2008-09-15T00:00:00Z"),
    )


def test_parse_dry_run_keys_on_the_recorded_fixture_finds_72_1d_keys() -> None:
    keys = mod.parse_dry_run_keys(open(_FIXTURE).read())
    assert len(keys) == 72
    assert ("AMAT", "2007-01-16T00:00:00Z") in keys
    assert all(len(symbol) > 0 for symbol, _ in keys)


# --- pure conditions ----------------------------------------------------------------


def test_scrub_condition_requires_fact_quarantined_keys_and_legacy_keys() -> None:
    ok = mod.scrub_condition(
        fact_passed=True, fixture_total=72, fixture_quarantined=72, legacy_quarantined=15
    )
    assert ok.ok

    no_fact = mod.scrub_condition(
        fact_passed=False, fixture_quarantined=72, fixture_total=72, legacy_quarantined=15
    )
    assert not no_fact.ok

    short = mod.scrub_condition(
        fact_passed=True, fixture_total=72, fixture_quarantined=71, legacy_quarantined=15
    )
    assert not short.ok

    no_legacy = mod.scrub_condition(
        fact_passed=True, fixture_total=72, fixture_quarantined=72, legacy_quarantined=14
    )
    assert not no_legacy.ok


def test_seam_condition_missing_fact_fails_and_actions_need_split_seam_coverage() -> None:
    assert not mod.seam_condition(
        fact_passed=False, actions=(), split_seam_bars={}, daily_batches=()
    ).ok

    ok_empty = mod.seam_condition(
        fact_passed=True, actions=(), split_seam_bars={}, daily_batches=()
    )
    assert ok_empty.ok

    action = ("FRHC", date(2012, 10, 31), datetime(2026, 9, 30, tzinfo=UTC))
    flagged = mod.seam_condition(
        fact_passed=True,
        actions=(action,),
        split_seam_bars={"FRHC": [date(2012, 10, 1), date(2012, 11, 1)]},
        daily_batches=(),
    )
    assert flagged.ok

    unflagged = mod.seam_condition(
        fact_passed=True, actions=(action,), split_seam_bars={}, daily_batches=()
    )
    assert not unflagged.ok

    rederived = mod.seam_condition(
        fact_passed=True,
        actions=(action,),
        split_seam_bars={},
        daily_batches=(datetime(2026, 10, 1, tzinfo=UTC),),
    )
    assert rederived.ok


def test_dispositions_condition_fails_on_any_unresolved_late_name() -> None:
    ok = mod.dispositions_condition({"AA": "reached_window_start", "AMD": "moved"})
    assert ok.ok
    bad = mod.dispositions_condition({"AA": "reached_window_start", "HOOD": "unresolved"})
    assert not bad.ok
    assert "HOOD" in bad.evidence


def test_premove_condition_fails_on_pre_move_bar_unless_venue_bars_allowed() -> None:
    assert mod.premove_condition(n_pre_move_bars=0, venue_bars_1d=False).ok
    assert not mod.premove_condition(n_pre_move_bars=3, venue_bars_1d=False).ok
    allowed = mod.premove_condition(n_pre_move_bars=3, venue_bars_1d=True)
    assert allowed.ok
    assert "venue_bars_1d" in allowed.evidence


def test_dividend_condition_requires_share_and_total_return_symbol() -> None:
    assert mod.dividend_condition(covered=925, eligible=931, total_return_importable=True).ok
    short = mod.dividend_condition(covered=900, eligible=931, total_return_importable=True)
    assert not short.ok
    no_fn = mod.dividend_condition(covered=925, eligible=931, total_return_importable=False)
    assert not no_fn.ok


def test_survivorship_condition_requires_all_six_apr_keys() -> None:
    full = {
        "alpha.survivorship.delisting_return.nasdaq",
        "alpha.survivorship.delisting_return.nyse_amex",
        "alpha.survivorship.hazard.nasdaq_annual",
        "alpha.survivorship.hazard.nyse_amex_annual",
        "alpha.survivorship.haircut.small_cap_annual",
        "alpha.survivorship.trading_days_per_year",
    }
    assert mod.survivorship_condition(full).ok
    assert not mod.survivorship_condition(full - {"alpha.survivorship.hazard.nasdaq_annual"}).ok


def test_is_active_condition_fails_on_any_soft_deleted_inventory_name() -> None:
    assert mod.is_active_condition(deactivated=0).ok
    failed = mod.is_active_condition(deactivated=1)
    assert not failed.ok


def test_summarize_exits_zero_only_when_every_condition_passes() -> None:
    ok_result = mod.CheckResult(condition="c", ok=True, evidence="e")
    fail_result = mod.CheckResult(condition="c", ok=False, evidence="e")
    assert mod.summarize([ok_result, ok_result]) == 0
    assert mod.summarize([ok_result, fail_result]) == 1


# --- CLI over a fake connection ------------------------------------------------------


class FakeCursor:
    """Replies are per-marker queues: consecutive queries on the same tables
    (the venue flag and the survivorship keys both read config_state) get
    consecutive replies in execution order."""

    def __init__(self, queues: dict[str, list[object]]) -> None:
        self._queues = queues
        self._next: object = None

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple | dict = ()) -> None:
        self._next = self._queues[_marker(sql)].pop(0)

    def fetchall(self):
        return self._next if isinstance(self._next, list) else []

    def fetchone(self):
        if isinstance(self._next, list):
            return self._next[0] if self._next else None
        return self._next


def _marker(sql: str) -> str:
    for key in (
        "integrity_monitor",
        "unnest",
        "legacy_price_sanity_status",
        "corporate_action",
        "split_seam",
        "bar_derivation_batch",
        "market_data_ohlcv_tradeable",
        "instruments",
        "config_state",
        "ohlcv_request",
        "dividend_event_coverage",
    ):
        if key in sql:
            return key
    raise AssertionError(f"unexpected SQL in fake: {sql}")


_SIX_KEYS = [
    ("alpha.survivorship.delisting_return.nasdaq",),
    ("alpha.survivorship.delisting_return.nyse_amex",),
    ("alpha.survivorship.hazard.nasdaq_annual",),
    ("alpha.survivorship.hazard.nyse_amex_annual",),
    ("alpha.survivorship.haircut.small_cap_annual",),
    ("alpha.survivorship.trading_days_per_year",),
]


def _replies() -> dict[str, list[object]]:
    return {
        "integrity_monitor": [(True,), (True,)],  # scrub fact, then seam fact
        "unnest": [(72,)],  # all fixture keys quarantined
        "legacy_price_sanity_status": [(15,)],
        "corporate_action": [[]],  # no seam-audit splits
        "split_seam": [[]],
        "bar_derivation_batch": [[]],  # no daily batches
        "market_data_ohlcv_tradeable": [(0,)],  # no pre-move bars visible
        "config_state": [("false",), list(_SIX_KEYS)],  # venue flag, then keys
        "instruments": [(925, 931, 0)],  # covered, eligible, deactivated
        "ohlcv_request": [[]],  # no stored requests
    }


class FakeConn:
    def __init__(self, replies: dict[str, list[object]]) -> None:
        self._queues = {marker: list(items) for marker, items in replies.items()}

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._queues)


def test_main_prints_one_line_per_condition_and_exits_1_on_fail(monkeypatch, capsys) -> None:
    conn = FakeConn(_replies())
    monkeypatch.setattr(mod, "_connect", lambda: _fake_ctx(conn))
    monkeypatch.setattr(mod, "_late_names", lambda conn: {"AMD": date(2015, 10, 1)})
    monkeypatch.setattr(mod, "_load_apr", lambda conn: {})
    monkeypatch.setattr(mod, "_total_return_importable", lambda: True)
    monkeypatch.setattr(mod, "_FIXTURE_PATH", Path(_FIXTURE))

    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert excinfo.value.code == 1
    lines = [line for line in capsys.readouterr().out.splitlines() if line[:4] in ("PASS", "FAIL")]
    assert len(lines) == 7  # one line per D-28 condition
    fails = [line for line in lines if line.startswith("FAIL")]
    # The only failing condition: no stored requests, so AMD stays unresolved.
    assert len(fails) == 1
    assert "unresolved" in fails[0]


def test_main_exits_0_when_every_condition_holds(monkeypatch, capsys) -> None:
    conn = FakeConn(_replies())
    monkeypatch.setattr(mod, "_connect", lambda: _fake_ctx(conn))
    monkeypatch.setattr(mod, "_late_names", lambda conn: {})
    monkeypatch.setattr(mod, "_load_apr", lambda conn: {})
    monkeypatch.setattr(mod, "_total_return_importable", lambda: True)
    monkeypatch.setattr(mod, "_FIXTURE_PATH", Path(_FIXTURE))

    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out


class _FakeCtx:
    def __init__(self, conn) -> None:
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc) -> None:
        return None


def _fake_ctx(conn) -> _FakeCtx:
    return _FakeCtx(conn)
