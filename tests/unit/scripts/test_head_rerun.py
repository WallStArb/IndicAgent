"""Unit tests for the D-27 step 2 head re-run (scripts/ops/bars/ops_head_rerun.py)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from scripts.ops.bars import ops_head_rerun as mod
from scripts.ops.bars._campaign import CampaignRefused
from scripts.ops.bars.ops_head_rerun import HeadRequest, classify_head, pending_symbols

_VENUES = ("NYSE", "ARCA", "ISLAND", "AMEX", "BATS")
_WS = date(2006, 10, 5)
_WE = date(2016, 2, 2)
_T0 = datetime(2026, 9, 29, tzinfo=UTC)


def _req(route: str, outcome: str, first_bar: date | None = None, day: int = 0) -> HeadRequest:
    return HeadRequest(
        route=route,
        outcome=outcome,
        window_start=_WS,
        window_end=_WE,
        first_bar=first_bar,
        answered_at=_T0.replace(day=1 + day),
    )


def test_moved_when_venue_bars_predate_smart_head() -> None:
    reqs = [_req("SMART", "no_data"), _req("NYSE", "bars", date(2009, 3, 2))]
    reqs += [_req(v, "no_data") for v in _VENUES if v != "NYSE"]
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "moved"


def test_verified_empty_when_smart_and_every_venue_no_data() -> None:
    reqs = [_req("SMART", "no_data")] + [_req(v, "no_data") for v in _VENUES]
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "verified_empty"


def test_venue_timeout_is_unresolved_not_empty() -> None:
    reqs = [_req("SMART", "no_data"), _req("NYSE", "timeout")]
    reqs += [_req(v, "no_data") for v in _VENUES if v != "NYSE"]
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "unresolved"


def test_missing_venue_is_unresolved() -> None:
    reqs = [_req("SMART", "no_data")] + [_req(v, "no_data") for v in _VENUES[:-1]]
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "unresolved"


def test_no_requests_is_unresolved() -> None:
    assert classify_head([], date(2015, 1, 2), _VENUES) == "unresolved"


def test_reached_window_start() -> None:
    reqs = [_req("SMART", "bars", date(2006, 10, 5))]
    assert classify_head(reqs, date(2006, 10, 5), _VENUES) == "reached_window_start"


def test_latest_answer_per_route_wins() -> None:
    reqs = [_req("SMART", "no_data")]
    reqs += [_req(v, "no_data") for v in _VENUES]
    reqs.append(_req("NYSE", "timeout", day=-0))  # same time: ambiguous, ties keep failure
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "unresolved"
    reqs.append(_req("NYSE", "no_data", day=3))  # later clean answer resolves it
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "verified_empty"


def test_pending_skips_resolved_unless_force() -> None:
    dispositions = {
        "A": "moved",
        "B": "verified_empty",
        "C": "unresolved",
        "D": "reached_window_start",
    }
    assert pending_symbols(["A", "B", "C", "D", "E"], dispositions, force=False) == ["C", "E"]
    assert pending_symbols(["A", "B", "C"], dispositions, force=True) == ["A", "B", "C"]


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.executed: list[tuple[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeConn:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.cur = _FakeCursor(rows)

    def cursor(self) -> _FakeCursor:
        return self.cur


def _row(route: str, outcome: str, first_bar: date | None, source: str) -> tuple[Any, ...]:
    ws = datetime(2006, 10, 5, tzinfo=UTC)
    we = datetime(2016, 2, 2, tzinfo=UTC)
    return ("XYZ", route, outcome, ws, we, first_bar, _T0, source, None)


def test_load_requests_excludes_tradier_answers() -> None:
    """185-28: a TRADIER bars answer before the SMART head is not a venue move. Only IBKR
    routes reach classify_head, so the name is not 'moved' on Tradier's account."""
    rows = [_row("SMART", "no_data", None, "ibkr")]
    rows += [_row(v, "no_data", None, "ibkr") for v in _VENUES]
    rows.append(_row("TRADIER", "bars", date(2000, 1, 3), "tradier"))
    loaded = mod._load_requests(_FakeConn(rows), ["XYZ"])
    assert {r.route for r in loaded["XYZ"]} == {"SMART", *_VENUES}
    assert classify_head(loaded["XYZ"], date(2015, 1, 2), _VENUES) == "verified_empty"


def test_load_requests_excludes_any_non_ibkr_source() -> None:
    rows = [
        _row("NYSE", "bars", date(2009, 3, 2), "tradier"),
        _row("SMART", "no_data", None, "ibkr"),
    ]
    loaded = mod._load_requests(_FakeConn(rows), ["XYZ"])
    assert [r.route for r in loaded["XYZ"]] == ["SMART"]
    assert classify_head(loaded["XYZ"], date(2015, 1, 2), _VENUES) != "moved"


def test_refuses_when_preflight_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(**_: Any) -> None:
        raise CampaignRefused("client id outside lanes")

    monkeypatch.setattr(mod, "preflight", _refuse)
    with pytest.raises(SystemExit) as excinfo:
        mod.run_with_refusal(lambda: mod.preflight(client_id=49, apr={}))
    assert excinfo.value.code == 3


def _primary_req(route: str, outcome: str, primary: str) -> HeadRequest:
    return HeadRequest(
        route=route,
        outcome=outcome,
        window_start=_WS,
        window_end=_WE,
        first_bar=None,
        answered_at=_T0,
        primary_exchange=primary,
    )


@pytest.mark.parametrize(("primary", "skipped"), [("NYSE", "NYSE"), ("NASDAQ", "ISLAND")])
def test_primary_venue_not_required_for_verified_empty(primary: str, skipped: str) -> None:
    """185-28: the provider never asks the current primary venue (SMART already routes
    there, ibkr._fetch_pre_move_history), and the empty-history reconcile does not require
    it either. SMART plus every other venue answering no_data is verified_empty."""
    reqs = [_primary_req("SMART", "no_data", primary)]
    reqs += [_primary_req(v, "no_data", primary) for v in _VENUES if v != skipped]
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "verified_empty"


def test_non_primary_venue_still_required() -> None:
    reqs = [_primary_req("SMART", "no_data", "NYSE")]
    reqs += [_primary_req(v, "no_data", "NYSE") for v in _VENUES if v not in ("NYSE", "ARCA")]
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "unresolved"


def test_smart_bars_from_the_head_answer_the_oldest_window() -> None:
    """185-28: a full-depth 1d SMART request answers the head with bars from the listing on,
    so the span before the head is implied by that answer, not a SMART no_data window (the
    rule reconcile_empty_history confirms empty spans by). With every non-primary venue
    no_data, the head is verified_empty."""
    head = date(2014, 3, 20)
    smart = HeadRequest("SMART", "bars", _WS, _WE, head, _T0, "NASDAQ")
    reqs = [smart] + [_primary_req(v, "no_data", "NASDAQ") for v in _VENUES if v != "ISLAND"]
    assert classify_head(reqs, head, _VENUES) == "verified_empty"


def test_smart_bars_before_the_stored_head_stay_unresolved() -> None:
    """SMART served bars before the stored head (e.g. zero-volume prints the tradeable view
    hides): the head is not shown empty, so the name stays unresolved."""
    smart = HeadRequest("SMART", "bars", _WS, _WE, date(2006, 10, 12), _T0, "NASDAQ")
    reqs = [smart] + [_primary_req(v, "no_data", "NASDAQ") for v in _VENUES if v != "ISLAND"]
    assert classify_head(reqs, date(2007, 5, 11), _VENUES) == "unresolved"


# --- 185-34: a failed ISLAND answer on a non-Nasdaq name (APR switch) ----------------


def _island_failed(primary: str | None, outcome: str = "failed") -> list[HeadRequest]:
    """SMART no_data, ISLAND answering `outcome`, every other non-primary venue no_data."""
    reqs = [_primary_req("SMART", "no_data", primary), _primary_req("ISLAND", outcome, primary)]
    reqs += [_primary_req(v, "no_data", primary) for v in _VENUES if v not in ("ISLAND", primary)]
    return reqs


def test_island_failed_on_a_non_nasdaq_name_is_unlisted_when_the_switch_is_on() -> None:
    """IDR, SGHC, UUUU, BMNR, CPS, FUBO, QXO, SD (185-28): ISLAND answers `failed` on every
    attempt for NYSE/AMEX names. With infra.ibkr.venue_fallback.island_failed_unlisted on,
    that answer counts as no listing at Nasdaq for the head (owner-pending rule)."""
    reqs = _island_failed("NYSE")
    head = date(2015, 1, 2)
    assert classify_head(reqs, head, _VENUES) == "unresolved"
    assert classify_head(reqs, head, _VENUES, island_failed_unlisted=True) == "verified_empty"


@pytest.mark.parametrize("outcome", ["timeout", "throttled"])
def test_island_rule_covers_failed_only(outcome: str) -> None:
    reqs = _island_failed("AMEX", outcome)
    assert (
        classify_head(reqs, date(2015, 1, 2), _VENUES, island_failed_unlisted=True) == "unresolved"
    )


def test_island_rule_needs_a_recorded_primary() -> None:
    """No primary recorded: nothing shows the name is not a Nasdaq listing (fail closed)."""
    reqs = _island_failed(None)
    assert (
        classify_head(reqs, date(2015, 1, 2), _VENUES, island_failed_unlisted=True) == "unresolved"
    )


def test_island_rule_does_not_cover_other_venues() -> None:
    reqs = [_primary_req("SMART", "no_data", "NYSE"), _primary_req("ISLAND", "no_data", "NYSE")]
    reqs.append(_primary_req("AMEX", "failed", "NYSE"))
    reqs += [_primary_req(v, "no_data", "NYSE") for v in ("ARCA", "BATS")]
    assert (
        classify_head(reqs, date(2015, 1, 2), _VENUES, island_failed_unlisted=True) == "unresolved"
    )


@pytest.mark.parametrize(
    ("value", "expected"), [("true", True), ("false", False), (None, False), ("TRUE", True)]
)
def test_island_switch_reads_the_apr_key_and_a_missing_key_is_off(
    value: str | None, expected: bool
) -> None:
    apr = {} if value is None else {"infra.ibkr.venue_fallback.island_failed_unlisted": value}
    assert mod.island_failed_unlisted(apr) is expected


def test_load_apr_reads_the_island_switch() -> None:
    conn = _FakeConn([])
    mod._load_apr(conn)
    _, params = conn.cur.executed[0]
    assert "infra.ibkr.venue_fallback.island_failed_unlisted" in params[0]


# --- the fetcher subprocess (plan 189-08) -------------------------------------------


class _FakeProc:
    def __init__(self, lines: list[str], rc: int) -> None:
        self.stdout = iter(lines)
        self._rc = rc

    def wait(self) -> int:
        return self._rc


def test_fetcher_command_asks_named_1d_series_on_the_campaign_client() -> None:
    argv = mod.fetcher_command(["AAA", "BBB"])
    assert argv[1].endswith("scripts/infrastructure/backfill/ibkr_history_fetcher.py")
    pairs = dict(zip(argv[2::2], argv[3::2], strict=False))
    assert pairs["--symbols"] == "AAA,BBB"
    assert pairs["--timeframes"] == "1d"
    assert pairs["--dimension"] == "compute_1d"
    assert pairs["--client-id"] == str(mod._CLIENT_ID) == "49"
    assert "--full-scan" in argv
    assert not any("lease" in part for part in argv)


def test_run_chunk_parses_fetch_run_ids_and_passes_the_exit_code() -> None:
    run_id = "0f3b2c1a-1111-4222-8333-444455556666"
    lines = [f"  fetch_run_id: {run_id}\n", "run summary: {}\n"]
    rc, ids = mod._run_chunk(["AAA"], popen=lambda *a, **k: _FakeProc(lines, 0))
    assert (rc, ids) == (0, [run_id])


def test_run_chunk_maps_the_lock_held_line_to_the_lock_held_exit() -> None:
    """The fetcher exits 0 when its lock is held elsewhere; the exact LOCK_HELD_MESSAGE line
    must stop the campaign cleanly, never read as a clean chunk."""
    from scripts.infrastructure.backfill._fetcher_lock import LOCK_HELD_MESSAGE

    lines = [LOCK_HELD_MESSAGE + "\n"]
    rc, ids = mod._run_chunk(["AAA"], popen=lambda *a, **k: _FakeProc(lines, 0))
    assert (rc, ids) == (mod._LOCK_HELD_EXIT, [])
    assert mod._LOCK_HELD_EXIT == 3
